import hashlib
import sqlite3

import pytest

from stockrank.storage import SCHEMA_VERSION, Storage

EXPECTED_SCHEMA_OBJECTS = (
    "idx_price_bars_ticker_date",
    "idx_provider_comparison_runs_asof",
    "idx_provider_metric_comparisons_class",
    "idx_provider_metric_comparisons_metric",
    "idx_run_results_rank",
    "idx_sec_company_facts_accession",
    "idx_sec_company_facts_ticker_concept_end",
    "idx_sec_fact_observations_fact",
    "idx_sec_fact_observations_ticker",
    "idx_sec_filings_form_period",
    "idx_sec_filings_ticker_date",
    "idx_sec_financial_metrics_name_period",
    "idx_sec_financial_snapshots_ticker_asof",
    "analysis_runs",
    "cache_status",
    "fundamental_cache",
    "price_bars",
    "provider_comparison_runs",
    "provider_health",
    "provider_metric_comparisons",
    "research_notes",
    "run_market_context",
    "run_results",
    "schema_metadata",
    "sec_company_fact_observations",
    "sec_company_facts",
    "sec_companyfacts_refresh_state",
    "sec_filings",
    "sec_financial_metrics",
    "sec_financial_snapshots",
)
EXPECTED_SCHEMA_FINGERPRINT = "38f78cefb2e3b4087a799beca91cd7f8d8db8773911975fa2902acd0b906471c"


def _schema_inventory(path) -> tuple[tuple[str, ...], str]:
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            """SELECT type, name, tbl_name, sql
            FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%'
            ORDER BY type, name"""
        ).fetchall()
    normalized = "\n".join(
        "|".join("" if value is None else " ".join(str(value).split()) for value in row)
        for row in rows
    )
    return (
        tuple(str(row[1]) for row in rows),
        hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
    )


def _logical_dump(path) -> tuple[str, ...]:
    with sqlite3.connect(path) as connection:
        return tuple(connection.iterdump())


def test_fresh_schema_matches_frozen_current_inventory(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")

    storage.initialize()

    names, fingerprint = _schema_inventory(storage.path)
    assert names == EXPECTED_SCHEMA_OBJECTS
    assert fingerprint == EXPECTED_SCHEMA_FINGERPRINT
    with sqlite3.connect(storage.path) as connection:
        version = connection.execute(
            "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
        ).fetchone()
    assert version == (str(SCHEMA_VERSION),)


def test_version_10_migration_is_backed_up_ordered_and_preserves_legacy_rows(tmp_path):
    path = tmp_path / "version10.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE schema_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT INTO schema_metadata(key, value) VALUES('schema_version', '10');
            CREATE TABLE provider_comparison_runs (
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
                evidence_reason TEXT NOT NULL
            );
            INSERT INTO provider_comparison_runs VALUES (
                'legacy-shadow', '2026-08-31T12:00:00+00:00',
                '2026-08-31T12:01:00+00:00', '2026-08-31T12:00:00+00:00',
                'provider-shadow-v1.0.1', 'legacy-universe', 2, 2, 1, 'complete',
                '[]', 'analysis-legacy', '2026-08-30', 1,
                'Qualified before formula-contract enforcement'
            );
            CREATE TABLE analysis_runs (
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
                reproducibility_reasons_json TEXT NOT NULL DEFAULT '[]'
            );
            INSERT INTO analysis_runs VALUES (
                'ranking-run', '2026-08-31T11:00:00+00:00',
                '2026-08-31T11:01:00+00:00', '2026-08-30', 'yfinance',
                'legacy-universe', 'ranking-v1', '{}', 'completed', '[]', NULL,
                'legacy_limited', '[]'
            );
            CREATE TABLE run_results (
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
            INSERT INTO run_results VALUES (
                'ranking-run', 'AAA', 1, 'AAA Company', 'Technology', 100.0,
                '2026-08-30', 88.0, 1.0, 'Top tier', 1, '[]', '{}', '{}', '{}',
                '{}', '[]'
            );
            CREATE TABLE preserved_v10_state (value TEXT NOT NULL);
            INSERT INTO preserved_v10_state VALUES ('preserve me');
            """
        )
    before = _logical_dump(path)

    storage = Storage(path)
    storage.initialize()

    backups = list(tmp_path.glob("version10.sqlite3.pre-v11*.bak"))
    assert len(backups) == 1
    assert _logical_dump(backups[0]) == before
    with sqlite3.connect(path) as connection:
        version = connection.execute(
            "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
        ).fetchone()
        legacy = connection.execute(
            """SELECT comparison_run_id, analysis_run_id, evidence_date,
            evidence_qualified, evidence_reason, formula_contracts_json
            FROM provider_comparison_runs WHERE comparison_run_id = 'legacy-shadow'"""
        ).fetchone()
        preserved = connection.execute("SELECT value FROM preserved_v10_state").fetchone()
        ranking = connection.execute(
            """SELECT ticker, rank, latest_price, price_as_of, overall_score,
            recommendation, eligible FROM run_results WHERE run_id = 'ranking-run'"""
        ).fetchone()
    assert version == ("11",)
    assert legacy == (
        "legacy-shadow",
        "analysis-legacy",
        "2026-08-30",
        0,
        "Legacy comparison run; SEC formula contract was not recorded",
        "[]",
    )
    assert preserved == ("preserve me",)
    assert ranking == ("AAA", 1, 100.0, "2026-08-30", 88.0, "Top tier", 1)
    assert storage.provider_comparison_full_universe_dates("provider-shadow-v1.0.1") == 0

    migrated = _logical_dump(path)
    storage.initialize()
    assert _logical_dump(path) == migrated
    assert list(tmp_path.glob("version10.sqlite3.pre-v11*.bak")) == backups


def test_repeated_schema_initialization_is_logically_idempotent(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    before_schema = _schema_inventory(storage.path)
    before_dump = _logical_dump(storage.path)

    storage.initialize()

    assert _schema_inventory(storage.path) == before_schema
    assert _logical_dump(storage.path) == before_dump


def test_future_schema_version_is_refused_without_mutation(tmp_path):
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            f"""
            CREATE TABLE schema_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT INTO schema_metadata(key, value)
            VALUES('schema_version', '{SCHEMA_VERSION + 1}');
            CREATE TABLE future_only (value TEXT NOT NULL);
            INSERT INTO future_only(value) VALUES('preserve me');
            """
        )
    before = _logical_dump(path)

    with pytest.raises(
        ValueError,
        match=rf"schema version {SCHEMA_VERSION + 1} is newer than supported version {SCHEMA_VERSION}",
    ):
        Storage(path).initialize()

    assert _logical_dump(path) == before
