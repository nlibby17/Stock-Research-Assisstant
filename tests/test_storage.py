from datetime import UTC, date, datetime

from stockrank.models import FundamentalSnapshot, PriceBar, ProviderHealth, SecFiling
from stockrank.storage import Storage


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
