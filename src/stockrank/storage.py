from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from stockrank.models import AnalysisRun, FundamentalSnapshot, PriceBar, ScoredSecurity

SCHEMA_VERSION = 1


class Storage:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cache_status (
                    cache_key TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT
                );
                CREATE TABLE IF NOT EXISTS price_bars (
                    ticker TEXT NOT NULL,
                    price_date TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL NOT NULL,
                    adjusted_close REAL NOT NULL,
                    volume INTEGER,
                    source TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    PRIMARY KEY (ticker, price_date, source)
                );
                CREATE INDEX IF NOT EXISTS idx_price_bars_ticker_date
                    ON price_bars(ticker, price_date);
                CREATE TABLE IF NOT EXISTS fundamental_cache (
                    ticker TEXT NOT NULL,
                    source TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (ticker, source)
                );
                CREATE TABLE IF NOT EXISTS analysis_runs (
                    run_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    as_of TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    universe_name TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    warnings_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run_results (
                    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
                    ticker TEXT NOT NULL,
                    rank INTEGER,
                    company TEXT NOT NULL,
                    sector TEXT NOT NULL,
                    latest_price REAL,
                    price_as_of TEXT,
                    overall_score REAL,
                    overall_coverage REAL NOT NULL,
                    recommendation TEXT NOT NULL,
                    eligible INTEGER NOT NULL,
                    component_scores_json TEXT NOT NULL,
                    component_coverage_json TEXT NOT NULL,
                    metric_scores_json TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    warnings_json TEXT NOT NULL,
                    PRIMARY KEY (run_id, ticker)
                );
                CREATE INDEX IF NOT EXISTS idx_run_results_rank
                    ON run_results(run_id, rank);
                CREATE TABLE IF NOT EXISTS research_notes (
                    run_id TEXT PRIMARY KEY REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
                    imported_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run_market_context (
                    run_id TEXT PRIMARY KEY REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
                    payload_json TEXT NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO schema_metadata(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    def cache_is_fresh(self, cache_key: str, now: datetime | None = None) -> bool:
        now = now or datetime.now(UTC)
        with self.connect() as connection:
            row = connection.execute(
                "SELECT expires_at, status FROM cache_status WHERE cache_key = ?", (cache_key,)
            ).fetchone()
        return bool(
            row and row["status"] == "ok" and datetime.fromisoformat(row["expires_at"]) > now
        )

    def set_cache_status(
        self, cache_key: str, source: str, ttl_hours: float, status: str, detail: str = ""
    ) -> None:
        now = datetime.now(UTC)
        expires = now + timedelta(hours=ttl_hours)
        with self.connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO cache_status
                (cache_key, source, fetched_at, expires_at, status, detail)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (cache_key, source, now.isoformat(), expires.isoformat(), status, detail[:2000]),
            )

    def upsert_price_bars(self, bars: Iterable[PriceBar]) -> int:
        rows = [
            (
                bar.ticker,
                bar.date.isoformat(),
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.adjusted_close,
                bar.volume,
                bar.source,
                bar.fetched_at.isoformat(),
            )
            for bar in bars
        ]
        if not rows:
            return 0
        with self.connect() as connection:
            connection.executemany(
                """INSERT OR REPLACE INTO price_bars
                (ticker, price_date, open, high, low, close, adjusted_close, volume,
                 source, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
        return len(rows)

    def get_price_bars(self, ticker: str, source: str | None = None) -> list[PriceBar]:
        query = "SELECT * FROM price_bars WHERE ticker = ?"
        args: list[Any] = [ticker]
        if source:
            query += " AND source = ?"
            args.append(source)
        query += " ORDER BY price_date"
        with self.connect() as connection:
            rows = connection.execute(query, args).fetchall()
        return [
            PriceBar(
                ticker=row["ticker"],
                date=date.fromisoformat(row["price_date"]),
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                adjusted_close=row["adjusted_close"],
                volume=row["volume"],
                source=row["source"],
                fetched_at=datetime.fromisoformat(row["fetched_at"]),
            )
            for row in rows
        ]

    def put_fundamental(self, value: FundamentalSnapshot, ttl_hours: float) -> None:
        expires = value.fetched_at + timedelta(hours=ttl_hours)
        with self.connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO fundamental_cache
                (ticker, source, fetched_at, expires_at, payload_json) VALUES (?, ?, ?, ?, ?)""",
                (
                    value.ticker,
                    value.source,
                    value.fetched_at.isoformat(),
                    expires.isoformat(),
                    json.dumps(value.to_dict(), sort_keys=True),
                ),
            )

    def get_fundamental(
        self, ticker: str, source: str, fresh_only: bool = False
    ) -> FundamentalSnapshot | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM fundamental_cache WHERE ticker = ? AND source = ?",
                (ticker, source),
            ).fetchone()
        if not row:
            return None
        if fresh_only and datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC):
            return None
        return FundamentalSnapshot.from_dict(json.loads(row["payload_json"]))

    def create_run(self, run: AnalysisRun) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO analysis_runs
                (run_id, started_at, completed_at, as_of, provider, universe_name,
                 model_version, config_json, status, warnings_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run.run_id,
                    run.started_at.isoformat(),
                    run.completed_at.isoformat() if run.completed_at else None,
                    run.as_of,
                    run.provider,
                    run.universe_name,
                    run.model_version,
                    json.dumps(run.config_snapshot, sort_keys=True),
                    run.status,
                    json.dumps(run.warnings),
                ),
            )

    def finish_run(self, run_id: str, status: str, warnings: list[str]) -> None:
        with self.connect() as connection:
            connection.execute(
                """UPDATE analysis_runs SET completed_at = ?, status = ?, warnings_json = ?
                WHERE run_id = ?""",
                (datetime.now(UTC).isoformat(), status, json.dumps(warnings), run_id),
            )

    def save_results(self, run_id: str, results: Iterable[ScoredSecurity]) -> None:
        rows = []
        for value in results:
            rows.append(
                (
                    run_id,
                    value.ticker,
                    value.rank,
                    value.company,
                    value.sector,
                    value.latest_price,
                    value.price_as_of,
                    value.overall_score,
                    value.overall_coverage,
                    value.recommendation,
                    int(value.eligible),
                    json.dumps(value.component_scores, sort_keys=True),
                    json.dumps(value.component_coverage, sort_keys=True),
                    json.dumps(value.metric_scores, sort_keys=True),
                    json.dumps(value.metrics, sort_keys=True),
                    json.dumps(value.warnings),
                )
            )
        with self.connect() as connection:
            connection.executemany(
                """INSERT INTO run_results
                (run_id, ticker, rank, company, sector, latest_price, price_as_of,
                 overall_score, overall_coverage, recommendation, eligible,
                 component_scores_json, component_coverage_json, metric_scores_json,
                 metrics_json, warnings_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )

    def latest_run(self) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM analysis_runs ORDER BY started_at DESC LIMIT 1"
            ).fetchone()

    def previous_run(self, run_id: str) -> sqlite3.Row | None:
        with self.connect() as connection:
            current = connection.execute(
                "SELECT started_at FROM analysis_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if not current:
                return None
            return connection.execute(
                """SELECT * FROM analysis_runs WHERE started_at < ? AND status = 'completed'
                ORDER BY started_at DESC LIMIT 1""",
                (current["started_at"],),
            ).fetchone()

    def get_results(self, run_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM run_results WHERE run_id = ?
                ORDER BY CASE WHEN rank IS NULL THEN 1 ELSE 0 END, rank, ticker""",
                (run_id,),
            ).fetchall()
        output = []
        json_fields = (
            "component_scores_json",
            "component_coverage_json",
            "metric_scores_json",
            "metrics_json",
            "warnings_json",
        )
        for row in rows:
            value = dict(row)
            for field in json_fields:
                value[field.removesuffix("_json")] = json.loads(value.pop(field))
            value["eligible"] = bool(value["eligible"])
            output.append(value)
        return output

    def import_research(self, run_id: str, payload: dict[str, Any]) -> None:
        with self.connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM analysis_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if not exists:
                raise ValueError(f"Unknown run_id: {run_id}")
            connection.execute(
                """INSERT OR REPLACE INTO research_notes(run_id, imported_at, payload_json)
                VALUES (?, ?, ?)""",
                (run_id, datetime.now(UTC).isoformat(), json.dumps(payload, sort_keys=True)),
            )

    def get_research(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM research_notes WHERE run_id = ?", (run_id,)
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def save_market_context(self, run_id: str, payload: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO run_market_context(run_id, payload_json) VALUES (?, ?)",
                (run_id, json.dumps(payload, sort_keys=True)),
            )

    def get_market_context(self, run_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM run_market_context WHERE run_id = ?", (run_id,)
            ).fetchone()
        return json.loads(row["payload_json"]) if row else {}

    def counts(self) -> dict[str, int]:
        tables = (
            "price_bars",
            "fundamental_cache",
            "analysis_runs",
            "run_results",
            "research_notes",
        )
        with self.connect() as connection:
            return {
                table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in tables
            }

    def cleanup_database(self, price_retention_days: int, apply: bool = False) -> dict[str, int]:
        cutoff = (datetime.now(UTC).date() - timedelta(days=price_retention_days)).isoformat()
        now = datetime.now(UTC).isoformat()
        with self.connect() as connection:
            preview = {
                "old_price_bars": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM price_bars WHERE price_date < ?", (cutoff,)
                    ).fetchone()[0]
                ),
                "expired_fundamentals": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM fundamental_cache WHERE expires_at < ?", (now,)
                    ).fetchone()[0]
                ),
                "expired_cache_status": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM cache_status WHERE expires_at < ?", (now,)
                    ).fetchone()[0]
                ),
            }
            if apply:
                connection.execute("DELETE FROM price_bars WHERE price_date < ?", (cutoff,))
                connection.execute("DELETE FROM fundamental_cache WHERE expires_at < ?", (now,))
                connection.execute("DELETE FROM cache_status WHERE expires_at < ?", (now,))
        return preview
