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
EXPECTED_SCHEMA_FINGERPRINT = "bb28cd4797c869a02240ede38d56accb4a49fc546427f6459dfe48f3571f6670"


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


def test_fresh_schema_matches_frozen_version_10_inventory(tmp_path):
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
