from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from stockrank.models import (
    AnalysisRun,
    FundamentalSnapshot,
    PriceBar,
    ProviderComparisonRun,
    ProviderHealth,
    ProviderMetricComparison,
    ScoredSecurity,
    SecCompanyFact,
    SecCompanyFactsRefreshState,
    SecFiling,
    SecFinancialMetric,
    SecFinancialSnapshot,
)
from stockrank.reproducibility import validate_run_manifest

SCHEMA_VERSION = 9
PROVIDER_EVIDENCE_MAX_LINK_AGE_HOURS = 6


class Storage:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

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
                    warnings_json TEXT NOT NULL,
                    manifest_json TEXT,
                    reproducibility_status TEXT NOT NULL DEFAULT 'legacy_limited',
                    reproducibility_reasons_json TEXT NOT NULL DEFAULT
                        '["Formal run reproducibility manifest was not recorded"]'
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
                CREATE TABLE IF NOT EXISTS sec_company_fact_observations (
                    observation_key TEXT PRIMARY KEY,
                    fact_key TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    payload_fingerprint TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    observation_status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    UNIQUE (fact_key, payload_fingerprint)
                );
                CREATE INDEX IF NOT EXISTS idx_sec_fact_observations_fact
                    ON sec_company_fact_observations(fact_key, observed_at);
                CREATE TABLE IF NOT EXISTS sec_companyfacts_refresh_state (
                    ticker TEXT PRIMARY KEY,
                    identity_fingerprint TEXT NOT NULL,
                    filing_fingerprint TEXT NOT NULL,
                    config_fingerprint TEXT NOT NULL,
                    last_successful_refresh_at TEXT NOT NULL,
                    latest_filing_at TEXT,
                    unmatched_accessions INTEGER NOT NULL,
                    last_refresh_reason TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sec_financial_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    ticker TEXT NOT NULL,
                    company_name TEXT NOT NULL,
                    sector TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    built_at TEXT NOT NULL,
                    formula_version TEXT NOT NULL,
                    formula_manifest_json TEXT,
                    status TEXT NOT NULL,
                    warnings_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sec_financial_snapshots_ticker_asof
                    ON sec_financial_snapshots(ticker, as_of DESC, built_at DESC);
                CREATE TABLE IF NOT EXISTS sec_financial_metrics (
                    snapshot_id TEXT NOT NULL REFERENCES sec_financial_snapshots(snapshot_id)
                        ON DELETE CASCADE,
                    metric_name TEXT NOT NULL,
                    period_kind TEXT NOT NULL,
                    value_text TEXT,
                    unit TEXT NOT NULL,
                    start_date TEXT,
                    end_date TEXT,
                    fiscal_year INTEGER,
                    fiscal_period TEXT,
                    quality TEXT NOT NULL,
                    formula TEXT NOT NULL,
                    reason TEXT,
                    lineage_json TEXT NOT NULL,
                    PRIMARY KEY (snapshot_id, metric_name, period_kind)
                );
                CREATE INDEX IF NOT EXISTS idx_sec_financial_metrics_name_period
                    ON sec_financial_metrics(metric_name, period_kind);
                CREATE TABLE IF NOT EXISTS provider_comparison_runs (
                    comparison_run_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    config_version TEXT NOT NULL,
                    universe_name TEXT NOT NULL,
                    scope_count INTEGER NOT NULL,
                    universe_size INTEGER NOT NULL,
                    full_universe INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    warnings_json TEXT NOT NULL,
                    analysis_run_id TEXT,
                    evidence_date TEXT,
                    evidence_qualified INTEGER NOT NULL DEFAULT 0,
                    evidence_reason TEXT NOT NULL DEFAULT 'No production-run evidence was recorded'
                );
                CREATE INDEX IF NOT EXISTS idx_provider_comparison_runs_asof
                    ON provider_comparison_runs(as_of DESC, completed_at DESC);
                CREATE TABLE IF NOT EXISTS provider_metric_comparisons (
                    comparison_run_id TEXT NOT NULL
                        REFERENCES provider_comparison_runs(comparison_run_id) ON DELETE CASCADE,
                    ticker TEXT NOT NULL,
                    sector TEXT NOT NULL,
                    metric_name TEXT NOT NULL,
                    yahoo_field TEXT NOT NULL,
                    yahoo_value_text TEXT,
                    yahoo_fetched_at TEXT,
                    yahoo_age_hours_text TEXT,
                    sec_metric_name TEXT,
                    sec_period_kind TEXT,
                    sec_value_text TEXT,
                    sec_unit TEXT,
                    sec_start_date TEXT,
                    sec_end_date TEXT,
                    sec_quality TEXT,
                    sec_snapshot_id TEXT,
                    sec_period_age_days INTEGER,
                    comparison_basis TEXT NOT NULL,
                    period_alignment TEXT NOT NULL,
                    classification TEXT NOT NULL,
                    absolute_difference_text TEXT,
                    relative_difference_text TEXT,
                    strict_absolute_tolerance_text TEXT NOT NULL,
                    strict_relative_tolerance_text TEXT NOT NULL,
                    material_absolute_tolerance_text TEXT NOT NULL,
                    material_relative_tolerance_text TEXT NOT NULL,
                    fallback_candidate TEXT,
                    reason TEXT NOT NULL,
                    PRIMARY KEY (comparison_run_id, ticker, metric_name)
                );
                CREATE INDEX IF NOT EXISTS idx_provider_metric_comparisons_class
                    ON provider_metric_comparisons(comparison_run_id, classification);
                CREATE INDEX IF NOT EXISTS idx_provider_metric_comparisons_metric
                    ON provider_metric_comparisons(metric_name, classification);
                """
            )
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(provider_comparison_runs)"
                ).fetchall()
            }
            added_evidence_columns = "evidence_date" not in columns
            if "analysis_run_id" not in columns:
                connection.execute(
                    "ALTER TABLE provider_comparison_runs ADD COLUMN analysis_run_id TEXT"
                )
            if "evidence_date" not in columns:
                connection.execute(
                    "ALTER TABLE provider_comparison_runs ADD COLUMN evidence_date TEXT"
                )
            if "evidence_qualified" not in columns:
                connection.execute(
                    """ALTER TABLE provider_comparison_runs
                    ADD COLUMN evidence_qualified INTEGER NOT NULL DEFAULT 0"""
                )
            if "evidence_reason" not in columns:
                connection.execute(
                    """ALTER TABLE provider_comparison_runs
                    ADD COLUMN evidence_reason TEXT NOT NULL
                    DEFAULT 'Legacy comparison run; production evidence was not verified'"""
                )
            if added_evidence_columns:
                self._backfill_provider_comparison_evidence(connection)
            analysis_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(analysis_runs)").fetchall()
            }
            if "manifest_json" not in analysis_columns:
                connection.execute("ALTER TABLE analysis_runs ADD COLUMN manifest_json TEXT")
            if "reproducibility_status" not in analysis_columns:
                connection.execute(
                    """ALTER TABLE analysis_runs ADD COLUMN reproducibility_status TEXT
                    NOT NULL DEFAULT 'legacy_limited'"""
                )
            if "reproducibility_reasons_json" not in analysis_columns:
                connection.execute(
                    """ALTER TABLE analysis_runs ADD COLUMN reproducibility_reasons_json TEXT
                    NOT NULL DEFAULT
                    '["Formal run reproducibility manifest was not recorded"]'"""
                )
            snapshot_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(sec_financial_snapshots)"
                ).fetchall()
            }
            if "formula_manifest_json" not in snapshot_columns:
                connection.execute(
                    "ALTER TABLE sec_financial_snapshots ADD COLUMN formula_manifest_json TEXT"
                )
            observation_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(sec_company_fact_observations)"
                ).fetchall()
            }
            if "observation_status" not in observation_columns:
                connection.execute(
                    """ALTER TABLE sec_company_fact_observations
                    ADD COLUMN observation_status TEXT NOT NULL DEFAULT 'legacy_seed'"""
                )
            if "ticker" not in observation_columns:
                connection.execute(
                    """ALTER TABLE sec_company_fact_observations
                    ADD COLUMN ticker TEXT NOT NULL DEFAULT ''"""
                )
                connection.execute(
                    """UPDATE sec_company_fact_observations
                    SET ticker = json_extract(payload_json, '$.ticker')
                    WHERE ticker = ''"""
                )
            connection.execute(
                """CREATE INDEX IF NOT EXISTS idx_sec_fact_observations_ticker
                ON sec_company_fact_observations(ticker, observed_at)"""
            )
            self._backfill_sec_fact_observations(connection)
            connection.execute(
                "INSERT OR REPLACE INTO schema_metadata(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    @staticmethod
    def _backfill_provider_comparison_evidence(connection: sqlite3.Connection) -> None:
        """Link only legacy comparisons that immediately followed a matching full run."""
        comparisons = connection.execute(
            """SELECT comparison_run_id, started_at, universe_name, universe_size
            FROM provider_comparison_runs
            WHERE full_universe = 1 AND status = 'complete'"""
        ).fetchall()
        for comparison in comparisons:
            started_at = datetime.fromisoformat(comparison["started_at"])
            analysis = connection.execute(
                """SELECT * FROM analysis_runs
                WHERE status = 'completed' AND provider = 'yfinance'
                  AND universe_name = ? AND completed_at <= ?
                ORDER BY completed_at DESC LIMIT 1""",
                (comparison["universe_name"], comparison["started_at"]),
            ).fetchone()
            if not analysis or not analysis["completed_at"]:
                continue
            analysis_warnings = json.loads(analysis["warnings_json"])
            if any(warning.startswith("Price refresh failed") for warning in analysis_warnings):
                continue
            completed_at = datetime.fromisoformat(analysis["completed_at"])
            if started_at - completed_at > timedelta(hours=PROVIDER_EVIDENCE_MAX_LINK_AGE_HOURS):
                continue
            coverage = connection.execute(
                """SELECT COUNT(*) AS result_count,
                    COUNT(price_as_of) AS priced_count,
                    COUNT(DISTINCT price_as_of) AS date_count,
                    MIN(price_as_of) AS evidence_date
                FROM run_results WHERE run_id = ?""",
                (analysis["run_id"],),
            ).fetchone()
            expected = int(comparison["universe_size"])
            evidence_date = coverage["evidence_date"]
            if (
                int(coverage["result_count"]) != expected
                or int(coverage["priced_count"]) != expected
                or int(coverage["date_count"]) != 1
                or evidence_date != analysis["as_of"]
            ):
                continue
            connection.execute(
                """UPDATE provider_comparison_runs
                SET analysis_run_id = ?, evidence_date = ?, evidence_qualified = 1,
                    evidence_reason = ? WHERE comparison_run_id = ?""",
                (
                    analysis["run_id"],
                    evidence_date,
                    "Migrated: linked to a complete full-universe production run",
                    comparison["comparison_run_id"],
                ),
            )

    @staticmethod
    def _sec_fact_payload(fact: SecCompanyFact) -> dict[str, Any]:
        return {
            "concept_priority": fact.concept_priority,
            "period_type": fact.period_type,
            "value": str(fact.value),
            "fiscal_year": fact.fiscal_year,
            "fiscal_period": fact.fiscal_period,
            "form": fact.form,
            "filed_date": fact.filed_date.isoformat(),
            "frame": fact.frame,
            "accepted_at": fact.accepted_at.isoformat() if fact.accepted_at else None,
            "availability_date": fact.availability_date.isoformat(),
            "availability_precision": fact.availability_precision,
        }

    @staticmethod
    def _sec_fact_payload_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "concept_priority": int(row["concept_priority"]),
            "period_type": row["period_type"],
            "value": row["value_text"],
            "fiscal_year": row["fiscal_year"],
            "fiscal_period": row["fiscal_period"],
            "form": row["form"],
            "filed_date": row["filed_date"],
            "frame": row["frame"],
            "accepted_at": row["accepted_at"],
            "availability_date": row["availability_date"],
            "availability_precision": row["availability_precision"],
        }

    @staticmethod
    def _sec_fact_observation_record(
        fact_key: str,
        ticker: str,
        observed_at: str,
        payload: dict[str, Any],
        *,
        first_seen_at: str,
        last_seen_at: str,
        observation_status: str,
    ) -> tuple[str, str, str, str, str, str, str, str, str]:
        payload_fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        observation_key = hashlib.sha256(
            f"{fact_key}\x1f{payload_fingerprint}".encode()
        ).hexdigest()
        return (
            observation_key,
            fact_key,
            ticker,
            payload_fingerprint,
            observed_at,
            observation_status,
            json.dumps(payload, sort_keys=True),
            first_seen_at,
            last_seen_at,
        )

    @classmethod
    def _backfill_sec_fact_observations(cls, connection: sqlite3.Connection) -> None:
        """Preserve the normalized state found when an older database is upgraded."""
        rows = connection.execute(
            """SELECT facts.* FROM sec_company_facts AS facts
            WHERE NOT EXISTS (
                SELECT 1 FROM sec_company_fact_observations AS observations
                WHERE observations.fact_key = facts.fact_key
            )"""
        ).fetchall()
        records = [
            cls._sec_fact_observation_record(
                row["fact_key"],
                row["ticker"],
                row["fetched_at"],
                cls._sec_fact_payload_from_row(row),
                first_seen_at=row["first_seen_at"],
                last_seen_at=row["last_seen_at"],
                observation_status="legacy_seed",
            )
            for row in rows
        ]
        connection.executemany(
            """INSERT OR IGNORE INTO sec_company_fact_observations
            (observation_key, fact_key, ticker, payload_fingerprint, observed_at,
             observation_status, payload_json, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            records,
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
        manifest_status, manifest_reasons = validate_run_manifest(run.reproducibility_manifest)
        if run.reproducibility_status == "recorded" and manifest_status != "recorded":
            raise ValueError("Run claims reproducibility but its manifest is incomplete or invalid")
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO analysis_runs
                (run_id, started_at, completed_at, as_of, provider, universe_name,
                 model_version, config_json, status, warnings_json, manifest_json,
                 reproducibility_status, reproducibility_reasons_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    (
                        json.dumps(run.reproducibility_manifest, sort_keys=True)
                        if run.reproducibility_manifest
                        else None
                    ),
                    manifest_status,
                    json.dumps(manifest_reasons),
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

    @staticmethod
    def _stored_manifest(row: sqlite3.Row) -> dict[str, Any] | None:
        raw = row["manifest_json"]
        return json.loads(raw) if raw else None

    @staticmethod
    def _manifest_universe_members(manifest: dict[str, Any]) -> dict[str, tuple[str, str]]:
        members = manifest.get("universe_members", [])
        if not isinstance(members, list):
            return {}
        return {
            str(member.get("ticker")): (
                str(member.get("company")),
                str(member.get("sector")),
            )
            for member in members
            if isinstance(member, dict)
            and member.get("ticker")
            and member.get("company")
            and member.get("sector")
        }

    def run_comparison_eligibility(
        self, run_id: str, candidate_run_id: str
    ) -> tuple[bool, tuple[str, ...]]:
        """Apply the stored calculation contract before allowing a historical comparison."""
        with self.connect() as connection:
            current = connection.execute(
                "SELECT * FROM analysis_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            candidate = connection.execute(
                "SELECT * FROM analysis_runs WHERE run_id = ?", (candidate_run_id,)
            ).fetchone()
            if not current or not candidate:
                missing = run_id if not current else candidate_run_id
                return False, (f"Unknown analysis run: {missing}",)

            reasons: list[str] = []
            if current["status"] != "completed":
                reasons.append("Current run is not complete")
            if candidate["status"] != "completed":
                reasons.append("Candidate run is not complete")
            if candidate["started_at"] >= current["started_at"]:
                reasons.append("Candidate run is not earlier than the current run")
            if candidate["as_of"] >= current["as_of"]:
                reasons.append("Runs do not represent different ordered market-data dates")

            current_manifest = self._stored_manifest(current)
            candidate_manifest = self._stored_manifest(candidate)
            for label, manifest in (
                ("Current", current_manifest),
                ("Candidate", candidate_manifest),
            ):
                status, manifest_reasons = validate_run_manifest(manifest)
                if status != "recorded":
                    reasons.extend(f"{label} run: {reason}" for reason in manifest_reasons)

            if current_manifest and candidate_manifest:
                current_contract = current_manifest.get("calculation_contract_fingerprint")
                candidate_contract = candidate_manifest.get("calculation_contract_fingerprint")
                if current_contract != candidate_contract:
                    reasons.append("Calculation contracts differ")
                for label, row, manifest in (
                    ("Current", current, current_manifest),
                    ("Candidate", candidate, candidate_manifest),
                ):
                    expected = self._manifest_universe_members(manifest)
                    observed = {
                        value["ticker"]: (value["company"], value["sector"])
                        for value in connection.execute(
                            "SELECT ticker, company, sector FROM run_results WHERE run_id = ?",
                            (row["run_id"],),
                        ).fetchall()
                    }
                    if not expected:
                        reasons.append(f"{label} run has no recorded universe membership")
                    elif observed != expected:
                        reasons.append(
                            f"{label} run result membership does not match its manifest"
                        )
            return not reasons, tuple(dict.fromkeys(reasons))

    def previous_comparable_run_assessment(
        self, run_id: str
    ) -> tuple[sqlite3.Row | None, tuple[str, ...]]:
        """Return the nearest eligible prior run, or why available history is limited."""
        with self.connect() as connection:
            current = connection.execute(
                "SELECT started_at FROM analysis_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if not current:
                return None, (f"Unknown analysis run: {run_id}",)
            candidates = connection.execute(
                """SELECT * FROM analysis_runs
                WHERE started_at < ? AND status = 'completed'
                ORDER BY started_at DESC""",
                (current["started_at"],),
            ).fetchall()
        nearest_reasons: tuple[str, ...] = ()
        for index, candidate in enumerate(candidates):
            eligible, reasons = self.run_comparison_eligibility(run_id, candidate["run_id"])
            if eligible:
                return candidate, ()
            if index == 0:
                nearest_reasons = reasons
        if not candidates:
            nearest_reasons = ("No earlier completed run is stored",)
        return None, nearest_reasons

    def previous_comparable_run(self, run_id: str) -> sqlite3.Row | None:
        """Return the nearest prior run with a complete matching calculation contract."""
        run, _ = self.previous_comparable_run_assessment(run_id)
        return run

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
        query += " ORDER BY COALESCE(accepted_at, filing_date) DESC, accession_number DESC"
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
        observation_rows = [
            self._sec_fact_observation_record(
                self._sec_fact_key(fact),
                fact.ticker,
                fact.fetched_at.isoformat(),
                self._sec_fact_payload(fact),
                first_seen_at=now,
                last_seen_at=now,
                observation_status="observed",
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
                connection.executemany(
                    """INSERT INTO sec_company_fact_observations
                    (observation_key, fact_key, ticker, payload_fingerprint, observed_at,
                     observation_status, payload_json, first_seen_at, last_seen_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(fact_key, payload_fingerprint) DO UPDATE SET
                        last_seen_at = excluded.last_seen_at""",
                    observation_rows,
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

    def get_sec_company_fact_observations(
        self, *, ticker: str | None = None, fact_key: str | None = None
    ) -> list[dict[str, Any]]:
        """Return immutable normalized SEC fact vintages for audit and reconstruction."""
        query = "SELECT * FROM sec_company_fact_observations"
        clauses: list[str] = []
        args: list[Any] = []
        if fact_key is not None:
            clauses.append("fact_key = ?")
            args.append(fact_key)
        if ticker is not None:
            clauses.append("ticker = ?")
            args.append(ticker)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY observed_at, observation_key"
        with self.connect() as connection:
            rows = connection.execute(query, args).fetchall()
        return [
            {
                "observation_key": row["observation_key"],
                "fact_key": row["fact_key"],
                "payload_fingerprint": row["payload_fingerprint"],
                "observed_at": row["observed_at"],
                "observation_status": row["observation_status"],
                "first_seen_at": row["first_seen_at"],
                "last_seen_at": row["last_seen_at"],
                "payload": json.loads(row["payload_json"]),
            }
            for row in rows
        ]

    def get_sec_companyfacts_refresh_state(
        self, ticker: str
    ) -> SecCompanyFactsRefreshState | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM sec_companyfacts_refresh_state WHERE ticker = ?", (ticker,)
            ).fetchone()
        if row is None:
            return None
        return SecCompanyFactsRefreshState(
            ticker=row["ticker"],
            identity_fingerprint=row["identity_fingerprint"],
            filing_fingerprint=row["filing_fingerprint"],
            config_fingerprint=row["config_fingerprint"],
            last_successful_refresh_at=datetime.fromisoformat(
                row["last_successful_refresh_at"]
            ),
            latest_filing_at=(
                datetime.fromisoformat(row["latest_filing_at"])
                if row["latest_filing_at"]
                else None
            ),
            unmatched_accessions=int(row["unmatched_accessions"]),
            last_refresh_reason=row["last_refresh_reason"],
        )

    def save_sec_companyfacts_refresh_state(
        self, state: SecCompanyFactsRefreshState
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO sec_companyfacts_refresh_state
                (ticker, identity_fingerprint, filing_fingerprint, config_fingerprint,
                 last_successful_refresh_at, latest_filing_at, unmatched_accessions,
                 last_refresh_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    identity_fingerprint = excluded.identity_fingerprint,
                    filing_fingerprint = excluded.filing_fingerprint,
                    config_fingerprint = excluded.config_fingerprint,
                    last_successful_refresh_at = excluded.last_successful_refresh_at,
                    latest_filing_at = excluded.latest_filing_at,
                    unmatched_accessions = excluded.unmatched_accessions,
                    last_refresh_reason = excluded.last_refresh_reason""",
                (
                    state.ticker,
                    state.identity_fingerprint,
                    state.filing_fingerprint,
                    state.config_fingerprint,
                    state.last_successful_refresh_at.isoformat(),
                    state.latest_filing_at.isoformat() if state.latest_filing_at else None,
                    state.unmatched_accessions,
                    state.last_refresh_reason,
                ),
            )

    def save_sec_financial_snapshot(self, snapshot: SecFinancialSnapshot) -> int:
        metric_keys = {(metric.metric_name, metric.period_kind) for metric in snapshot.metrics}
        if len(metric_keys) != len(snapshot.metrics):
            raise ValueError("Financial snapshot contains duplicate metric/period rows")
        with self.connect() as connection:
            try:
                connection.execute(
                    """INSERT INTO sec_financial_snapshots
                    (snapshot_id, ticker, company_name, sector, as_of, built_at,
                     formula_version, formula_manifest_json, status, warnings_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        snapshot.snapshot_id,
                        snapshot.ticker,
                        snapshot.company_name,
                        snapshot.sector,
                        snapshot.as_of.isoformat(),
                        snapshot.built_at.isoformat(),
                        snapshot.formula_version,
                        (
                            json.dumps(snapshot.formula_manifest, sort_keys=True)
                            if snapshot.formula_manifest
                            else None
                        ),
                        snapshot.status,
                        json.dumps(snapshot.warnings),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    f"Financial snapshot already exists: {snapshot.snapshot_id}"
                ) from exc
            connection.executemany(
                """INSERT INTO sec_financial_metrics
                (snapshot_id, metric_name, period_kind, value_text, unit, start_date,
                 end_date, fiscal_year, fiscal_period, quality, formula, reason,
                 lineage_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        snapshot.snapshot_id,
                        metric.metric_name,
                        metric.period_kind,
                        str(metric.value) if metric.value is not None else None,
                        metric.unit,
                        metric.start_date.isoformat() if metric.start_date else None,
                        metric.end_date.isoformat() if metric.end_date else None,
                        metric.fiscal_year,
                        metric.fiscal_period,
                        metric.quality,
                        metric.formula,
                        metric.reason,
                        json.dumps(metric.lineage, sort_keys=True),
                    )
                    for metric in snapshot.metrics
                ],
            )
        return len(snapshot.metrics)

    def get_sec_financial_snapshot(self, snapshot_id: str) -> SecFinancialSnapshot | None:
        with self.connect() as connection:
            snapshot_row = connection.execute(
                "SELECT * FROM sec_financial_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
            if not snapshot_row:
                return None
            metric_rows = connection.execute(
                """SELECT * FROM sec_financial_metrics WHERE snapshot_id = ?
                ORDER BY metric_name, period_kind""",
                (snapshot_id,),
            ).fetchall()
        return SecFinancialSnapshot(
            snapshot_id=snapshot_row["snapshot_id"],
            ticker=snapshot_row["ticker"],
            company_name=snapshot_row["company_name"],
            sector=snapshot_row["sector"],
            as_of=datetime.fromisoformat(snapshot_row["as_of"]),
            built_at=datetime.fromisoformat(snapshot_row["built_at"]),
            formula_version=snapshot_row["formula_version"],
            status=snapshot_row["status"],
            warnings=tuple(json.loads(snapshot_row["warnings_json"])),
            metrics=tuple(
                SecFinancialMetric(
                    metric_name=row["metric_name"],
                    period_kind=row["period_kind"],
                    value=Decimal(row["value_text"]) if row["value_text"] else None,
                    unit=row["unit"],
                    start_date=(
                        date.fromisoformat(row["start_date"]) if row["start_date"] else None
                    ),
                    end_date=(date.fromisoformat(row["end_date"]) if row["end_date"] else None),
                    fiscal_year=(
                        int(row["fiscal_year"]) if row["fiscal_year"] is not None else None
                    ),
                    fiscal_period=row["fiscal_period"],
                    quality=row["quality"],
                    formula=row["formula"],
                    reason=row["reason"],
                    lineage=tuple(json.loads(row["lineage_json"])),
                )
                for row in metric_rows
            ),
            formula_manifest=(
                json.loads(snapshot_row["formula_manifest_json"])
                if snapshot_row["formula_manifest_json"]
                else None
            ),
        )

    def latest_sec_financial_snapshot(
        self, ticker: str, *, available_at: datetime | None = None
    ) -> SecFinancialSnapshot | None:
        query = "SELECT snapshot_id FROM sec_financial_snapshots WHERE ticker = ?"
        args: list[Any] = [ticker]
        if available_at is not None:
            if available_at.tzinfo is None:
                raise ValueError("Financial snapshot cutoff must include a timezone")
            query += " AND as_of <= ?"
            args.append(available_at.isoformat())
        query += " ORDER BY as_of DESC, built_at DESC LIMIT 1"
        with self.connect() as connection:
            row = connection.execute(query, args).fetchone()
        return self.get_sec_financial_snapshot(row["snapshot_id"]) if row else None

    def save_provider_comparison_run(
        self,
        run: ProviderComparisonRun,
        comparisons: Iterable[ProviderMetricComparison],
    ) -> int:
        values = list(comparisons)
        keys = {(value.ticker, value.metric_name) for value in values}
        if len(keys) != len(values):
            raise ValueError("Provider comparison run contains duplicate ticker/metric rows")
        if any(value.comparison_run_id != run.comparison_run_id for value in values):
            raise ValueError("Provider comparison rows do not match their run")
        with self.connect() as connection:
            try:
                connection.execute(
                    """INSERT INTO provider_comparison_runs
                    (comparison_run_id, started_at, completed_at, as_of,
                     config_version, universe_name, scope_count, universe_size,
                     full_universe, status, warnings_json, analysis_run_id,
                     evidence_date, evidence_qualified, evidence_reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run.comparison_run_id,
                        run.started_at.isoformat(),
                        run.completed_at.isoformat(),
                        run.as_of.isoformat(),
                        run.config_version,
                        run.universe_name,
                        run.scope_count,
                        run.universe_size,
                        int(run.full_universe),
                        run.status,
                        json.dumps(run.warnings),
                        run.analysis_run_id,
                        run.evidence_date.isoformat() if run.evidence_date else None,
                        int(run.evidence_qualified),
                        run.evidence_reason,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    f"Provider comparison run already exists: {run.comparison_run_id}"
                ) from exc
            connection.executemany(
                """INSERT INTO provider_metric_comparisons
                (comparison_run_id, ticker, sector, metric_name, yahoo_field,
                 yahoo_value_text, yahoo_fetched_at, yahoo_age_hours_text,
                 sec_metric_name, sec_period_kind, sec_value_text, sec_unit,
                 sec_start_date, sec_end_date, sec_quality, sec_snapshot_id,
                 sec_period_age_days, comparison_basis, period_alignment,
                 classification, absolute_difference_text, relative_difference_text,
                 strict_absolute_tolerance_text, strict_relative_tolerance_text,
                 material_absolute_tolerance_text, material_relative_tolerance_text,
                 fallback_candidate, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        value.comparison_run_id,
                        value.ticker,
                        value.sector,
                        value.metric_name,
                        value.yahoo_field,
                        str(value.yahoo_value) if value.yahoo_value is not None else None,
                        value.yahoo_fetched_at.isoformat() if value.yahoo_fetched_at else None,
                        str(value.yahoo_age_hours) if value.yahoo_age_hours is not None else None,
                        value.sec_metric_name,
                        value.sec_period_kind,
                        str(value.sec_value) if value.sec_value is not None else None,
                        value.sec_unit,
                        value.sec_start_date.isoformat() if value.sec_start_date else None,
                        value.sec_end_date.isoformat() if value.sec_end_date else None,
                        value.sec_quality,
                        value.sec_snapshot_id,
                        value.sec_period_age_days,
                        value.comparison_basis,
                        value.period_alignment,
                        value.classification,
                        (
                            str(value.absolute_difference)
                            if value.absolute_difference is not None
                            else None
                        ),
                        (
                            str(value.relative_difference)
                            if value.relative_difference is not None
                            else None
                        ),
                        str(value.strict_absolute_tolerance),
                        str(value.strict_relative_tolerance),
                        str(value.material_absolute_tolerance),
                        str(value.material_relative_tolerance),
                        value.fallback_candidate,
                        value.reason,
                    )
                    for value in values
                ],
            )
        return len(values)

    def latest_provider_comparison_run(
        self,
        *,
        full_universe_only: bool = False,
        config_version: str | None = None,
        universe_name: str | None = None,
    ) -> ProviderComparisonRun | None:
        query = "SELECT * FROM provider_comparison_runs"
        conditions = []
        args: list[Any] = []
        if full_universe_only:
            conditions.append("full_universe = 1 AND status = 'complete'")
        if config_version is not None:
            conditions.append("config_version = ?")
            args.append(config_version)
        if universe_name is not None:
            conditions.append("universe_name = ?")
            args.append(universe_name)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY as_of DESC, completed_at DESC LIMIT 1"
        with self.connect() as connection:
            row = connection.execute(query, args).fetchone()
        if not row:
            return None
        return ProviderComparisonRun(
            comparison_run_id=row["comparison_run_id"],
            started_at=datetime.fromisoformat(row["started_at"]),
            completed_at=datetime.fromisoformat(row["completed_at"]),
            as_of=datetime.fromisoformat(row["as_of"]),
            config_version=row["config_version"],
            universe_name=row["universe_name"],
            scope_count=int(row["scope_count"]),
            universe_size=int(row["universe_size"]),
            full_universe=bool(row["full_universe"]),
            status=row["status"],
            warnings=tuple(json.loads(row["warnings_json"])),
            analysis_run_id=row["analysis_run_id"],
            evidence_date=(
                date.fromisoformat(row["evidence_date"]) if row["evidence_date"] else None
            ),
            evidence_qualified=bool(row["evidence_qualified"]),
            evidence_reason=row["evidence_reason"],
        )

    def get_provider_metric_comparisons(
        self, comparison_run_id: str
    ) -> list[ProviderMetricComparison]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM provider_metric_comparisons
                WHERE comparison_run_id = ? ORDER BY metric_name, ticker""",
                (comparison_run_id,),
            ).fetchall()
        return [
            ProviderMetricComparison(
                comparison_run_id=row["comparison_run_id"],
                ticker=row["ticker"],
                sector=row["sector"],
                metric_name=row["metric_name"],
                yahoo_field=row["yahoo_field"],
                yahoo_value=(Decimal(row["yahoo_value_text"]) if row["yahoo_value_text"] else None),
                yahoo_fetched_at=(
                    datetime.fromisoformat(row["yahoo_fetched_at"])
                    if row["yahoo_fetched_at"]
                    else None
                ),
                yahoo_age_hours=(
                    Decimal(row["yahoo_age_hours_text"]) if row["yahoo_age_hours_text"] else None
                ),
                sec_metric_name=row["sec_metric_name"],
                sec_period_kind=row["sec_period_kind"],
                sec_value=(Decimal(row["sec_value_text"]) if row["sec_value_text"] else None),
                sec_unit=row["sec_unit"],
                sec_start_date=(
                    date.fromisoformat(row["sec_start_date"]) if row["sec_start_date"] else None
                ),
                sec_end_date=(
                    date.fromisoformat(row["sec_end_date"]) if row["sec_end_date"] else None
                ),
                sec_quality=row["sec_quality"],
                sec_snapshot_id=row["sec_snapshot_id"],
                sec_period_age_days=(
                    int(row["sec_period_age_days"])
                    if row["sec_period_age_days"] is not None
                    else None
                ),
                comparison_basis=row["comparison_basis"],
                period_alignment=row["period_alignment"],
                classification=row["classification"],
                absolute_difference=(
                    Decimal(row["absolute_difference_text"])
                    if row["absolute_difference_text"]
                    else None
                ),
                relative_difference=(
                    Decimal(row["relative_difference_text"])
                    if row["relative_difference_text"]
                    else None
                ),
                strict_absolute_tolerance=Decimal(row["strict_absolute_tolerance_text"]),
                strict_relative_tolerance=Decimal(row["strict_relative_tolerance_text"]),
                material_absolute_tolerance=Decimal(row["material_absolute_tolerance_text"]),
                material_relative_tolerance=Decimal(row["material_relative_tolerance_text"]),
                fallback_candidate=row["fallback_candidate"],
                reason=row["reason"],
            )
            for row in rows
        ]

    def provider_comparison_full_universe_dates(
        self,
        config_version: str,
        timezone_name: str = "UTC",
        universe_name: str | None = None,
    ) -> int:
        query = """SELECT evidence_date
                FROM provider_comparison_runs
                WHERE config_version = ? AND full_universe = 1 AND status = 'complete'
                  AND evidence_qualified = 1 AND evidence_date IS NOT NULL"""
        args: list[Any] = [config_version]
        if universe_name is not None:
            query += " AND universe_name = ?"
            args.append(universe_name)
        with self.connect() as connection:
            rows = connection.execute(query, args).fetchall()
        return len({row["evidence_date"] for row in rows})

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
            "sec_company_fact_observations",
            "sec_financial_snapshots",
            "sec_financial_metrics",
            "provider_comparison_runs",
            "provider_metric_comparisons",
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
