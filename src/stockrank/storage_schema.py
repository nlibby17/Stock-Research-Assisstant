from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 11
SUPPORTED_MIGRATION_BASELINE = 10
PROVIDER_EVIDENCE_MAX_LINK_AGE_HOURS = 6
LEGACY_FORMULA_CONTRACT_REASON = "Legacy comparison run; SEC formula contract was not recorded"


def read_schema_version(connection: sqlite3.Connection) -> int | None:
    """Read the published application schema version when one exists."""
    metadata_exists = connection.execute(
        """SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name = 'schema_metadata'"""
    ).fetchone()
    if not metadata_exists:
        return None
    row = connection.execute(
        "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


def backup_database_before_migration(
    connection: sqlite3.Connection,
    database_path: Path,
    *,
    target_version: int,
) -> Path:
    """Create a recoverable SQLite backup before changing a supported schema."""
    base = database_path.with_name(f"{database_path.name}.pre-v{target_version}.bak")
    backup_path = base
    suffix = 2
    while backup_path.exists():
        backup_path = base.with_name(f"{base.stem}-{suffix}{base.suffix}")
        suffix += 1
    with sqlite3.connect(backup_path) as backup_connection:
        connection.backup(backup_connection)
    return backup_path


def build_sec_fact_observation_record(
    fact_key: str,
    ticker: str,
    observed_at: str,
    payload: dict[str, Any],
    *,
    first_seen_at: str,
    last_seen_at: str,
    observation_status: str,
) -> tuple[str, str, str, str, str, str, str, str, str]:
    """Build the persisted record shared by live writes and legacy seeding."""
    payload_fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    observation_key = hashlib.sha256(f"{fact_key}\x1f{payload_fingerprint}".encode()).hexdigest()
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


def initialize_schema(connection: sqlite3.Connection) -> None:
    """Create the current schema or upgrade from the supported version-10 baseline."""
    stored_version = read_schema_version(connection)
    if stored_version is not None and stored_version > SCHEMA_VERSION:
        raise ValueError(
            f"Database schema version {stored_version} is newer than supported version "
            f"{SCHEMA_VERSION}; update the application before opening this database"
        )

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
            eligibility_reasons_json TEXT NOT NULL DEFAULT '[]',
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
            evidence_reason TEXT NOT NULL DEFAULT 'No production-run evidence was recorded',
            formula_contracts_json TEXT NOT NULL DEFAULT '[]'
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
    if stored_version is not None and stored_version >= SUPPORTED_MIGRATION_BASELINE:
        _apply_ordered_migrations(connection, stored_version)
    _apply_compatibility_repairs(connection)
    connection.execute(
        "INSERT OR REPLACE INTO schema_metadata(key, value) VALUES('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )


def _migrate_10_to_11(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(provider_comparison_runs)").fetchall()
    }
    if "formula_contracts_json" not in columns:
        connection.execute(
            """ALTER TABLE provider_comparison_runs
            ADD COLUMN formula_contracts_json TEXT NOT NULL DEFAULT '[]'"""
        )
    connection.execute(
        """UPDATE provider_comparison_runs
        SET evidence_qualified = 0, evidence_reason = ?, formula_contracts_json = '[]'""",
        (LEGACY_FORMULA_CONTRACT_REASON,),
    )


ORDERED_MIGRATIONS = ((10, 11, _migrate_10_to_11),)


def _apply_ordered_migrations(connection: sqlite3.Connection, stored_version: int) -> None:
    current_version = stored_version
    while current_version < SCHEMA_VERSION:
        step = next(
            (migration for migration in ORDERED_MIGRATIONS if migration[0] == current_version),
            None,
        )
        if step is None:
            raise ValueError(
                f"No supported schema migration from version {current_version} "
                f"to version {SCHEMA_VERSION}"
            )
        _, target_version, migrate = step
        migrate(connection)
        current_version = target_version


def _apply_compatibility_repairs(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(provider_comparison_runs)").fetchall()
    }
    added_evidence_columns = "evidence_date" not in columns
    if "analysis_run_id" not in columns:
        connection.execute("ALTER TABLE provider_comparison_runs ADD COLUMN analysis_run_id TEXT")
    if "evidence_date" not in columns:
        connection.execute("ALTER TABLE provider_comparison_runs ADD COLUMN evidence_date TEXT")
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
        _backfill_provider_comparison_evidence(connection)
    if "formula_contracts_json" not in columns:
        connection.execute(
            """ALTER TABLE provider_comparison_runs
            ADD COLUMN formula_contracts_json TEXT NOT NULL DEFAULT '[]'"""
        )
        connection.execute(
            """UPDATE provider_comparison_runs
            SET evidence_qualified = 0, evidence_reason = ?""",
            (LEGACY_FORMULA_CONTRACT_REASON,),
        )

    analysis_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(analysis_runs)").fetchall()
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

    result_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(run_results)").fetchall()
    }
    if "eligibility_reasons_json" not in result_columns:
        connection.execute(
            """ALTER TABLE run_results ADD COLUMN eligibility_reasons_json TEXT
            NOT NULL DEFAULT '[]'"""
        )

    snapshot_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(sec_financial_snapshots)").fetchall()
    }
    if "formula_manifest_json" not in snapshot_columns:
        connection.execute(
            "ALTER TABLE sec_financial_snapshots ADD COLUMN formula_manifest_json TEXT"
        )

    observation_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(sec_company_fact_observations)").fetchall()
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
    _backfill_sec_fact_observations(connection)


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


def _backfill_sec_fact_observations(connection: sqlite3.Connection) -> None:
    """Preserve the normalized state found when an older database is upgraded."""
    rows = connection.execute(
        """SELECT facts.* FROM sec_company_facts AS facts
        WHERE NOT EXISTS (
            SELECT 1 FROM sec_company_fact_observations AS observations
            WHERE observations.fact_key = facts.fact_key
        )"""
    ).fetchall()
    records = [
        build_sec_fact_observation_record(
            row["fact_key"],
            row["ticker"],
            row["fetched_at"],
            _sec_fact_payload_from_row(row),
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
