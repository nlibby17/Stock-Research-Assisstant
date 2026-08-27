from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from stockrank.models import (
    AnalysisRun,
    FundamentalSnapshot,
    PriceBar,
    ProviderHealth,
    ScoredSecurity,
    SecCompanyFact,
    SecFiling,
)

SCHEMA_VERSION = 4


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
                CREATE TABLE IF NOT EXISTS provider_health (
                    provider TEXT PRIMARY KEY,
                    checked_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    latency_ms REAL NOT NULL,
                    cache_hit INTEGER NOT NULL,
                    detail TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sec_filings (
                    cik TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    company_name TEXT NOT NULL,
                    accession_number TEXT NOT NULL,
                    form TEXT NOT NULL,
                    base_form TEXT NOT NULL,
                    is_amendment INTEGER NOT NULL,
                    filing_date TEXT NOT NULL,
                    report_date TEXT,
                    acceptance_datetime TEXT,
                    accepted_at TEXT,
                    availability_date TEXT NOT NULL,
                    availability_precision TEXT NOT NULL,
                    primary_document TEXT,
                    filing_index_url TEXT NOT NULL,
                    primary_document_url TEXT,
                    source_url TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    active INTEGER NOT NULL,
                    PRIMARY KEY (cik, accession_number)
                );
                CREATE INDEX IF NOT EXISTS idx_sec_filings_ticker_date
                    ON sec_filings(ticker, filing_date);
                CREATE INDEX IF NOT EXISTS idx_sec_filings_form_period
                    ON sec_filings(ticker, base_form, report_date);
                CREATE TABLE IF NOT EXISTS sec_company_facts (
                    fact_key TEXT PRIMARY KEY,
                    cik TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    company_name TEXT NOT NULL,
                    canonical_name TEXT NOT NULL,
                    taxonomy TEXT NOT NULL,
                    concept TEXT NOT NULL,
                    concept_priority INTEGER NOT NULL,
                    label TEXT NOT NULL,
                    description TEXT NOT NULL,
                    period_type TEXT NOT NULL,
                    unit TEXT NOT NULL,
                    value_text TEXT NOT NULL,
                    start_date TEXT,
                    end_date TEXT NOT NULL,
                    accession_number TEXT NOT NULL,
                    fiscal_year INTEGER,
                    fiscal_period TEXT,
                    form TEXT NOT NULL,
                    filed_date TEXT NOT NULL,
                    frame TEXT,
                    accepted_at TEXT,
                    availability_date TEXT NOT NULL,
                    availability_precision TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    active INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sec_company_facts_ticker_concept_end
                    ON sec_company_facts(ticker, canonical_name, end_date);
                CREATE INDEX IF NOT EXISTS idx_sec_company_facts_accession
                    ON sec_company_facts(cik, accession_number);
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

    def record_provider_health(self, health: ProviderHealth) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO provider_health
                (provider, checked_at, status, endpoint, latency_ms, cache_hit, detail)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    health.provider,
                    health.checked_at.isoformat(),
                    health.status,
                    health.endpoint,
                    health.latency_ms,
                    int(health.cache_hit),
                    health.detail[:2000],
                ),
            )

    def get_provider_health(self, provider: str) -> ProviderHealth | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM provider_health WHERE provider = ?", (provider,)
            ).fetchone()
        if not row:
            return None
        return ProviderHealth(
            provider=row["provider"],
            checked_at=datetime.fromisoformat(row["checked_at"]),
            status=row["status"],
            endpoint=row["endpoint"],
            latency_ms=float(row["latency_ms"]),
            cache_hit=bool(row["cache_hit"]),
            detail=row["detail"],
        )

    def replace_sec_filings(
        self,
        *,
        ticker: str,
        ciks: Iterable[str],
        since_date: date,
        filings: Iterable[SecFiling],
    ) -> int:
        values = list(filings)
        valid_ciks = set(ciks)
        if not valid_ciks:
            raise ValueError("SEC filing sync target must contain at least one CIK")
        if any(filing.cik not in valid_ciks or filing.ticker != ticker for filing in values):
            raise ValueError("SEC filing batch does not match its ticker/CIK sync target")
        now = datetime.now(UTC).isoformat()
        rows = [
            (
                filing.cik,
                filing.ticker,
                filing.company_name,
                filing.accession_number,
                filing.form,
                filing.base_form,
                int(filing.is_amendment),
                filing.filing_date.isoformat(),
                filing.report_date.isoformat() if filing.report_date else None,
                filing.acceptance_datetime,
                filing.accepted_at.isoformat() if filing.accepted_at else None,
                filing.availability_date.isoformat(),
                filing.availability_precision,
                filing.primary_document,
                filing.filing_index_url,
                filing.primary_document_url,
                filing.source_url,
                filing.fetched_at.isoformat(),
                now,
                now,
                1,
            )
            for filing in values
        ]
        with self.connect() as connection:
            connection.execute(
                """UPDATE sec_filings SET active = 0, last_seen_at = ?
                WHERE ticker = ? AND filing_date >= ?""",
                (now, ticker, since_date.isoformat()),
            )
            if rows:
                connection.executemany(
                    """INSERT INTO sec_filings
                    (cik, ticker, company_name, accession_number, form, base_form,
                     is_amendment, filing_date, report_date, acceptance_datetime,
                     accepted_at, availability_date, availability_precision,
                     primary_document, filing_index_url, primary_document_url,
                     source_url, fetched_at, first_seen_at, last_seen_at, active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(cik, accession_number) DO UPDATE SET
                        ticker = excluded.ticker,
                        company_name = excluded.company_name,
                        form = excluded.form,
                        base_form = excluded.base_form,
                        is_amendment = excluded.is_amendment,
                        filing_date = excluded.filing_date,
                        report_date = excluded.report_date,
                        acceptance_datetime = excluded.acceptance_datetime,
                        accepted_at = excluded.accepted_at,
                        availability_date = excluded.availability_date,
                        availability_precision = excluded.availability_precision,
                        primary_document = excluded.primary_document,
                        filing_index_url = excluded.filing_index_url,
                        primary_document_url = excluded.primary_document_url,
                        source_url = excluded.source_url,
                        fetched_at = excluded.fetched_at,
                        last_seen_at = excluded.last_seen_at,
                        active = 1""",
                    rows,
                )
        return len(rows)

    def get_sec_filings(
        self,
        ticker: str,
        *,
        active_only: bool = True,
        since_date: date | None = None,
    ) -> list[SecFiling]:
        query = "SELECT * FROM sec_filings WHERE ticker = ?"
        args: list[Any] = [ticker]
        if active_only:
            query += " AND active = 1"
        if since_date:
            query += " AND filing_date >= ?"
            args.append(since_date.isoformat())
        query += (
            " ORDER BY COALESCE(accepted_at, filing_date) DESC, accession_number DESC"
        )
        with self.connect() as connection:
            rows = connection.execute(query, args).fetchall()
        return [
            SecFiling(
                cik=row["cik"],
                ticker=row["ticker"],
                company_name=row["company_name"],
                accession_number=row["accession_number"],
                form=row["form"],
                base_form=row["base_form"],
                is_amendment=bool(row["is_amendment"]),
                filing_date=date.fromisoformat(row["filing_date"]),
                report_date=(
                    date.fromisoformat(row["report_date"]) if row["report_date"] else None
                ),
                acceptance_datetime=row["acceptance_datetime"],
                accepted_at=(
                    datetime.fromisoformat(row["accepted_at"]) if row["accepted_at"] else None
                ),
                availability_date=date.fromisoformat(row["availability_date"]),
                availability_precision=row["availability_precision"],
                primary_document=row["primary_document"],
                filing_index_url=row["filing_index_url"],
                primary_document_url=row["primary_document_url"],
                source_url=row["source_url"],
                fetched_at=datetime.fromisoformat(row["fetched_at"]),
            )
            for row in rows
        ]

    @staticmethod
    def _sec_fact_key(fact: SecCompanyFact) -> str:
        identity = "\x1f".join(
            (
                fact.cik,
                fact.canonical_name,
                fact.taxonomy,
                fact.concept,
                fact.unit,
                fact.start_date.isoformat() if fact.start_date else "",
                fact.end_date.isoformat(),
                fact.accession_number,
            )
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def replace_sec_company_facts(
        self,
        *,
        ticker: str,
        ciks: Iterable[str],
        since_date: date,
        facts: Iterable[SecCompanyFact],
    ) -> int:
        values = list(facts)
        valid_ciks = set(ciks)
        if not valid_ciks:
            raise ValueError("SEC Company Facts sync target must contain at least one CIK")
        if any(fact.cik not in valid_ciks or fact.ticker != ticker for fact in values):
            raise ValueError("SEC Company Facts batch does not match its ticker/CIK target")
        now = datetime.now(UTC).isoformat()
        rows = [
            (
                self._sec_fact_key(fact),
                fact.cik,
                fact.ticker,
                fact.company_name,
                fact.canonical_name,
                fact.taxonomy,
                fact.concept,
                fact.concept_priority,
                fact.label,
                fact.description,
                fact.period_type,
                fact.unit,
                str(fact.value),
                fact.start_date.isoformat() if fact.start_date else None,
                fact.end_date.isoformat(),
                fact.accession_number,
                fact.fiscal_year,
                fact.fiscal_period,
                fact.form,
                fact.filed_date.isoformat(),
                fact.frame,
                fact.accepted_at.isoformat() if fact.accepted_at else None,
                fact.availability_date.isoformat(),
                fact.availability_precision,
                fact.source_url,
                fact.fetched_at.isoformat(),
                now,
                now,
                1,
            )
            for fact in values
        ]
        with self.connect() as connection:
            connection.execute(
                """UPDATE sec_company_facts SET active = 0, last_seen_at = ?
                WHERE ticker = ? AND filed_date >= ?""",
                (now, ticker, since_date.isoformat()),
            )
            if rows:
                connection.executemany(
                    """INSERT INTO sec_company_facts
                    (fact_key, cik, ticker, company_name, canonical_name, taxonomy,
                     concept, concept_priority, label, description, period_type,
                     unit, value_text, start_date, end_date, accession_number,
                     fiscal_year, fiscal_period, form, filed_date, frame, accepted_at,
                     availability_date, availability_precision, source_url,
                     fetched_at, first_seen_at, last_seen_at, active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(fact_key) DO UPDATE SET
                        ticker = excluded.ticker,
                        company_name = excluded.company_name,
                        concept_priority = excluded.concept_priority,
                        label = excluded.label,
                        description = excluded.description,
                        period_type = excluded.period_type,
                        value_text = excluded.value_text,
                        fiscal_year = excluded.fiscal_year,
                        fiscal_period = excluded.fiscal_period,
                        form = excluded.form,
                        filed_date = excluded.filed_date,
                        frame = excluded.frame,
                        accepted_at = excluded.accepted_at,
                        availability_date = excluded.availability_date,
                        availability_precision = excluded.availability_precision,
                        source_url = excluded.source_url,
                        fetched_at = excluded.fetched_at,
                        last_seen_at = excluded.last_seen_at,
                        active = 1""",
                    rows,
                )
        return len(rows)

    def get_sec_company_facts(
        self,
        ticker: str,
        *,
        canonical_name: str | None = None,
        active_only: bool = True,
        since_date: date | None = None,
    ) -> list[SecCompanyFact]:
        query = "SELECT * FROM sec_company_facts WHERE ticker = ?"
        args: list[Any] = [ticker]
        if canonical_name:
            query += " AND canonical_name = ?"
            args.append(canonical_name)
        if active_only:
            query += " AND active = 1"
        if since_date:
            query += " AND filed_date >= ?"
            args.append(since_date.isoformat())
        query += " ORDER BY end_date DESC, filed_date DESC, accession_number DESC"
        with self.connect() as connection:
            rows = connection.execute(query, args).fetchall()
        return [
            SecCompanyFact(
                cik=row["cik"],
                ticker=row["ticker"],
                company_name=row["company_name"],
                canonical_name=row["canonical_name"],
                taxonomy=row["taxonomy"],
                concept=row["concept"],
                concept_priority=int(row["concept_priority"]),
                label=row["label"],
                description=row["description"],
                period_type=row["period_type"],
                unit=row["unit"],
                value=Decimal(row["value_text"]),
                start_date=date.fromisoformat(row["start_date"]) if row["start_date"] else None,
                end_date=date.fromisoformat(row["end_date"]),
                accession_number=row["accession_number"],
                fiscal_year=int(row["fiscal_year"]) if row["fiscal_year"] is not None else None,
                fiscal_period=row["fiscal_period"],
                form=row["form"],
                filed_date=date.fromisoformat(row["filed_date"]),
                frame=row["frame"],
                accepted_at=(
                    datetime.fromisoformat(row["accepted_at"]) if row["accepted_at"] else None
                ),
                availability_date=date.fromisoformat(row["availability_date"]),
                availability_precision=row["availability_precision"],
                source_url=row["source_url"],
                fetched_at=datetime.fromisoformat(row["fetched_at"]),
            )
            for row in rows
        ]

    def counts(self) -> dict[str, int]:
        tables = (
            "price_bars",
            "fundamental_cache",
            "analysis_runs",
            "run_results",
            "research_notes",
            "provider_health",
            "sec_filings",
            "sec_company_facts",
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
