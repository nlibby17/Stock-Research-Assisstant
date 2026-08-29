import sqlite3
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from stockrank.models import (
    AnalysisRun,
    FundamentalSnapshot,
    PriceBar,
    ProviderHealth,
    SecCompanyFact,
    SecCompanyFactsRefreshState,
    SecFiling,
)
from stockrank.storage import Storage


def test_storage_context_closes_database_connection(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")

    with storage.connect() as connection:
        assert connection.execute("SELECT 1").fetchone()[0] == 1

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")


def test_previous_comparable_run_skips_other_models_and_universes(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    values = (
        ("matching", "2026-01-01", "universe-a", "model-a"),
        ("other-model", "2026-01-02", "universe-a", "model-b"),
        ("other-universe", "2026-01-03", "universe-b", "model-a"),
        ("current", "2026-01-04", "universe-a", "model-a"),
    )
    for run_id, as_of, universe_name, model_version in values:
        storage.create_run(
            AnalysisRun(
                run_id=run_id,
                started_at=datetime.fromisoformat(f"{as_of}T12:00:00+00:00"),
                completed_at=datetime.fromisoformat(f"{as_of}T12:01:00+00:00"),
                as_of=as_of,
                provider="test",
                universe_name=universe_name,
                model_version=model_version,
                config_snapshot={},
                status="completed",
            )
        )

    previous = storage.previous_comparable_run("current")

    assert previous is not None
    assert previous["run_id"] == "matching"


def test_normalized_cache_roundtrip(tmp_path):
    storage = Storage(tmp_path / "runtime" / "test.sqlite3")
    storage.initialize()
    fetched = datetime.now(UTC)
    bar = PriceBar("A", date(2026, 1, 2), 9, 11, 8, 10, 10, 100, "test", fetched)
    assert storage.upsert_price_bars([bar]) == 1
    assert storage.upsert_price_bars([bar]) == 1
    loaded = storage.get_price_bars("A", "test")
    assert len(loaded) == 1
    assert loaded[0].close == 10

    fundamental = FundamentalSnapshot(ticker="A", source="test", fetched_at=fetched, market_cap=123)
    storage.put_fundamental(fundamental, ttl_hours=2)
    assert storage.get_fundamental("A", "test", fresh_only=True).market_cap == 123


def test_cleanup_is_dry_run_by_default(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    old = PriceBar("A", date(2000, 1, 1), 9, 11, 8, 10, 10, 100, "test", datetime.now(UTC))
    storage.upsert_price_bars([old])
    preview = storage.cleanup_database(550, apply=False)
    assert preview["old_price_bars"] == 1
    assert len(storage.get_price_bars("A")) == 1
    storage.cleanup_database(550, apply=True)
    assert not storage.get_price_bars("A")


def test_provider_health_roundtrip(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    health = ProviderHealth(
        provider="sec-edgar",
        checked_at=datetime.now(UTC),
        status="healthy",
        endpoint="https://www.sec.gov/files/company_tickers_exchange.json",
        latency_ms=125.5,
        cache_hit=False,
        detail="identity_records=2; universe_matches=2/2",
    )
    storage.record_provider_health(health)
    loaded = storage.get_provider_health("sec-edgar")
    assert loaded is not None
    assert loaded.status == "healthy"
    assert loaded.latency_ms == 125.5
    assert loaded.cache_hit is False


def make_filing(accession_number: str, filing_date: date) -> SecFiling:
    return SecFiling(
        cik="0001045810",
        ticker="NVDA",
        company_name="NVIDIA CORP",
        accession_number=accession_number,
        form="10-Q",
        base_form="10-Q",
        is_amendment=False,
        filing_date=filing_date,
        report_date=filing_date,
        acceptance_datetime=f"{filing_date.isoformat()}T16:00:00Z",
        accepted_at=datetime.combine(filing_date, datetime.min.time(), tzinfo=UTC),
        availability_date=filing_date,
        availability_precision="timestamp",
        primary_document="filing.htm",
        filing_index_url="https://www.sec.gov/index.html",
        primary_document_url="https://www.sec.gov/filing.htm",
        source_url="https://data.sec.gov/submissions/CIK0001045810.json",
        fetched_at=datetime.now(UTC),
    )


def test_sec_filing_sync_roundtrip_and_deactivates_removed_rows(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    first = make_filing("0001045810-26-000001", date(2026, 1, 1))
    second = make_filing("0001045810-26-000002", date(2026, 4, 1))
    assert (
        storage.replace_sec_filings(
            ticker="NVDA",
            ciks=["0001045810"],
            since_date=date(2026, 1, 1),
            filings=[first, second],
        )
        == 2
    )
    assert len(storage.get_sec_filings("NVDA")) == 2
    storage.replace_sec_filings(
        ticker="NVDA",
        ciks=["0001045810"],
        since_date=date(2026, 1, 1),
        filings=[second],
    )
    assert [value.accession_number for value in storage.get_sec_filings("NVDA")] == [
        second.accession_number
    ]
    assert len(storage.get_sec_filings("NVDA", active_only=False)) == 2


def make_company_fact(accession_number: str, value: str) -> SecCompanyFact:
    filed = date(2026, 2, 20)
    return SecCompanyFact(
        cik="0001045810",
        ticker="NVDA",
        company_name="NVIDIA CORP",
        canonical_name="revenue",
        taxonomy="us-gaap",
        concept="Revenues",
        concept_priority=1,
        label="Revenue",
        description="Revenue from customers.",
        period_type="duration",
        unit="USD",
        value=Decimal(value),
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        accession_number=accession_number,
        fiscal_year=2025,
        fiscal_period="FY",
        form="10-K",
        filed_date=filed,
        frame="CY2025",
        accepted_at=datetime(2026, 2, 20, 21, 0, tzinfo=UTC),
        availability_date=filed,
        availability_precision="timestamp",
        source_url="https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json",
        fetched_at=datetime.now(UTC),
    )


def test_sec_company_fact_roundtrip_updates_values_and_deactivates_removed_rows(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    first = make_company_fact("0001045810-26-000001", "100.25")
    second = make_company_fact("0001045810-26-000002", "110")
    assert (
        storage.replace_sec_company_facts(
            ticker="NVDA",
            ciks=["0001045810"],
            since_date=date(2026, 1, 1),
            facts=[first, second],
        )
        == 2
    )
    loaded = storage.get_sec_company_facts("NVDA", canonical_name="revenue")
    assert {fact.value for fact in loaded} == {Decimal("100.25"), Decimal(110)}

    corrected = make_company_fact(first.accession_number, "101.5")
    storage.replace_sec_company_facts(
        ticker="NVDA",
        ciks=["0001045810"],
        since_date=date(2026, 1, 1),
        facts=[corrected],
    )
    active = storage.get_sec_company_facts("NVDA")
    assert len(active) == 1
    assert active[0].value == Decimal("101.5")
    assert len(storage.get_sec_company_facts("NVDA", active_only=False)) == 2


def test_sec_companyfacts_refresh_state_roundtrip(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    refreshed_at = datetime(2026, 8, 29, 14, 0, tzinfo=UTC)
    value = SecCompanyFactsRefreshState(
        ticker="NVDA",
        identity_fingerprint="identity-v1",
        filing_fingerprint="filings-v1",
        config_fingerprint="config-v1",
        last_successful_refresh_at=refreshed_at,
        latest_filing_at=refreshed_at - timedelta(days=1),
        unmatched_accessions=2,
        last_refresh_reason="new or changed SEC filing",
    )
    storage.save_sec_companyfacts_refresh_state(value)
    assert storage.get_sec_companyfacts_refresh_state("NVDA") == value
    assert storage.get_sec_companyfacts_refresh_state("AAPL") is None
