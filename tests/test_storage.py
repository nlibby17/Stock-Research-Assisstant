from datetime import UTC, date, datetime

from stockrank.models import FundamentalSnapshot, PriceBar
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
