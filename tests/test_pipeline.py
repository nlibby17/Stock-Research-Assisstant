import copy
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from stockrank.config import Settings, load_settings
from stockrank.data.base import MarketDataProvider
from stockrank.models import FundamentalSnapshot, PriceBar, Security
from stockrank.pipeline import _analysis_status, run_analysis
from stockrank.storage import Storage


def test_versioned_universe_has_50_unique_stocks_and_all_sectors():
    settings = load_settings(Path.cwd())
    assert settings.raw["universe"]["name"] == "us_diversified_50_v1"
    assert len(settings.universe) == 50
    assert len({security.ticker for security in settings.universe}) == 50
    assert len({security.sector for security in settings.universe}) == 11
    assert settings.raw["universe"]["maintenance_mode"] == "manual_curated"


def test_analysis_status_requires_price_coverage_for_the_full_universe():
    assert _analysis_status(50, 50) == "completed"
    assert _analysis_status(49, 50) == "partial"
    assert _analysis_status(0, 50) == "failed"
    assert _analysis_status(50, 50, price_dates_consistent=False) == "partial"


def test_demo_pipeline_end_to_end(tmp_path):
    loaded = load_settings(Path.cwd())
    raw = copy.deepcopy(loaded.raw)
    raw["provider"]["price_history_days"] = 420
    raw["app"]["runtime_dir"] = "runtime"
    settings = Settings(root=tmp_path, raw=raw, universe=loaded.universe[:8])
    run_id, report_path, warnings = run_analysis(settings, demo=True)
    assert report_path.exists()
    text = report_path.read_text(encoding="utf-8")
    assert run_id in text
    assert "demo-synthetic" in text
    assert "SYNTHETIC" in " ".join(warnings).upper()
    storage = Storage(settings.database_path)
    run = storage.latest_run()
    assert run["status"] == "completed"
    assert len(storage.get_results(run_id)) == 8
    assert (settings.runtime_dir / "reports" / "research_template.json").exists()


class _ControlledProvider(MarketDataProvider):
    name = "yfinance"
    freshness_label = "Controlled test provider"

    def __init__(self, *, mixed_dates: bool = False, missing_ticker: str | None = None):
        self.mixed_dates = mixed_dates
        self.missing_ticker = missing_ticker

    @staticmethod
    def _recent_completed_weekday() -> date:
        value = datetime.now(UTC).date() - timedelta(days=1)
        while value.weekday() >= 5:
            value -= timedelta(days=1)
        return value

    def fetch_prices(self, securities, start, end):
        latest = self._recent_completed_weekday()
        fetched_at = datetime.now(UTC)
        output = {}
        for security in securities:
            if security.ticker == self.missing_ticker:
                continue
            ticker_latest = (
                latest - timedelta(days=1)
                if self.mixed_dates and security.ticker == "B"
                else latest
            )
            bars = []
            current = ticker_latest - timedelta(days=420)
            while current <= ticker_latest:
                if current.weekday() < 5:
                    bars.append(
                        PriceBar(
                            ticker=security.ticker,
                            date=current,
                            open=100,
                            high=101,
                            low=99,
                            close=100,
                            adjusted_close=100,
                            volume=1_000_000,
                            source=self.name,
                            fetched_at=fetched_at,
                        )
                    )
                current += timedelta(days=1)
            output[security.ticker] = bars
        return output, []

    def fetch_fundamental(self, security):
        return None, [f"{security.ticker}: controlled fundamental failure"]


def _controlled_settings(tmp_path: Path) -> Settings:
    loaded = load_settings(Path.cwd())
    raw = copy.deepcopy(loaded.raw)
    raw["app"]["runtime_dir"] = "runtime"
    return Settings(
        root=tmp_path,
        raw=raw,
        universe=(
            Security("A", "Alpha", "Industrials"),
            Security("B", "Beta", "Industrials"),
        ),
    )


def test_pipeline_rejects_overage_fundamentals_and_records_freshness(tmp_path, monkeypatch):
    settings = _controlled_settings(tmp_path)
    storage = Storage(settings.database_path)
    storage.initialize()
    old = datetime.now(UTC) - timedelta(hours=200)
    for ticker in ("A", "B"):
        storage.put_fundamental(
            FundamentalSnapshot(
                ticker=ticker,
                source="yfinance",
                fetched_at=old,
                market_cap=1_000_000,
            ),
            ttl_hours=24,
        )
    monkeypatch.setattr(
        "stockrank.pipeline.provider_for", lambda settings, demo=False: _ControlledProvider()
    )

    run_id, _, warnings = run_analysis(settings)

    run = storage.latest_run()
    results = storage.get_results(run_id)
    runtime = json.loads(run["config_json"])["runtime"]["data_freshness"]
    assert run["status"] == "completed"
    assert all(result["metrics"]["market_cap"] is None for result in results)
    assert runtime["fundamentals"]["A"]["status"] == "rejected_stale"
    assert runtime["prices"]["A"]["status"] == "usable"
    assert any("above the 168-hour limit" in warning for warning in warnings)


def test_pipeline_marks_mixed_completed_price_dates_partial(tmp_path, monkeypatch):
    settings = _controlled_settings(tmp_path)
    monkeypatch.setattr(
        "stockrank.pipeline.provider_for",
        lambda settings, demo=False: _ControlledProvider(mixed_dates=True),
    )

    run_id, _, warnings = run_analysis(settings)

    storage = Storage(settings.database_path)
    run = storage.latest_run()
    assert run["run_id"] == run_id
    assert run["status"] == "partial"
    assert any("mixed completed price dates" in warning for warning in warnings)


def test_partial_price_response_is_not_cached_as_a_success(tmp_path, monkeypatch):
    settings = _controlled_settings(tmp_path)
    monkeypatch.setattr(
        "stockrank.pipeline.provider_for",
        lambda settings, demo=False: _ControlledProvider(missing_ticker="B"),
    )

    run_id, _, warnings = run_analysis(settings)

    storage = Storage(settings.database_path)
    run = storage.latest_run()
    with storage.connect() as connection:
        cache = connection.execute("SELECT status FROM cache_status").fetchone()
    assert run["run_id"] == run_id
    assert run["status"] == "partial"
    assert cache["status"] == "partial"
    assert any("cached bars will be checked for: B" in warning for warning in warnings)


def test_recent_stale_fundamental_is_used_only_as_labelled_fallback(tmp_path, monkeypatch):
    settings = _controlled_settings(tmp_path)
    storage = Storage(settings.database_path)
    storage.initialize()
    recent = datetime.now(UTC) - timedelta(hours=48)
    for ticker in ("A", "B"):
        storage.put_fundamental(
            FundamentalSnapshot(
                ticker=ticker,
                source="yfinance",
                fetched_at=recent,
                market_cap=1_000_000,
            ),
            ttl_hours=24,
        )
    monkeypatch.setattr(
        "stockrank.pipeline.provider_for", lambda settings, demo=False: _ControlledProvider()
    )

    run_id, _, warnings = run_analysis(settings)

    run = storage.latest_run()
    results = storage.get_results(run_id)
    runtime = json.loads(run["config_json"])["runtime"]["data_freshness"]
    assert all(result["metrics"]["market_cap"] == 1_000_000 for result in results)
    assert runtime["fundamentals"]["A"]["status"] == "stale_fallback"
    assert any("using stale fundamentals" in warning for warning in warnings)
