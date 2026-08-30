from datetime import UTC, date, datetime

from stockrank.freshness import assess_price_bars
from stockrank.models import PriceBar


def _bar(price_date: date, fetched_at: datetime, price: float = 100.0) -> PriceBar:
    return PriceBar(
        ticker="TEST",
        date=price_date,
        open=price,
        high=price,
        low=price,
        close=price,
        adjusted_close=price,
        volume=1_000_000,
        source="test",
        fetched_at=fetched_at,
    )


def test_in_progress_current_session_bar_is_never_treated_as_a_close():
    now = datetime.fromisoformat("2026-08-31T19:30:00+00:00")  # 3:30 p.m. New York
    prior = _bar(date(2026, 8, 28), now)
    in_progress = _bar(date(2026, 8, 31), now)

    result = assess_price_bars(
        [prior, in_progress],
        now=now,
        timezone_name="America/New_York",
        completion_buffer_minutes=15,
        maximum_age_hours=120,
    )

    assert result.status == "usable"
    assert result.latest_date == "2026-08-28"
    assert result.incomplete_bar_count == 1
    assert [bar.date for bar in result.usable_bars] == [date(2026, 8, 28)]


def test_current_session_bar_fetched_after_completion_buffer_is_usable():
    fetched = datetime.fromisoformat("2026-08-31T20:20:00+00:00")
    result = assess_price_bars(
        [_bar(date(2026, 8, 31), fetched)],
        now=fetched,
        timezone_name="America/New_York",
        completion_buffer_minutes=15,
        maximum_age_hours=120,
    )

    assert result.status == "usable"
    assert result.latest_date == "2026-08-31"
    assert result.incomplete_bar_count == 0


def test_old_or_invalid_prices_are_not_scoring_inputs():
    now = datetime.fromisoformat("2026-08-31T14:00:00+00:00")
    stale = _bar(date(2026, 8, 20), datetime(2026, 8, 20, 21, tzinfo=UTC))
    invalid = _bar(date(2026, 8, 28), datetime(2026, 8, 28, 21, tzinfo=UTC), price=0)

    result = assess_price_bars(
        [stale, invalid],
        now=now,
        timezone_name="America/New_York",
        completion_buffer_minutes=15,
        maximum_age_hours=120,
    )

    assert result.status == "stale"
    assert not result.usable_bars
    assert result.latest_date == "2026-08-20"
    assert result.invalid_bar_count == 1
    assert any("above the 120-hour limit" in warning for warning in result.warnings)
