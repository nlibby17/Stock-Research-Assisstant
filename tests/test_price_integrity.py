from datetime import UTC, date, datetime, timedelta

from stockrank.metrics import calculate_metrics
from stockrank.models import PriceBar
from stockrank.price_integrity import assess_price_series, build_reference_sessions


def _bar(ticker: str, session: date, price: float) -> PriceBar:
    return PriceBar(
        ticker=ticker,
        date=session,
        open=price,
        high=price,
        low=price,
        close=price,
        adjusted_close=price,
        volume=1_000_000,
        source="test",
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _weekdays(start: date, count: int, *, excluded: set[date] | None = None) -> list[date]:
    output: list[date] = []
    current = start
    while len(output) < count:
        if current.weekday() < 5 and current not in (excluded or set()):
            output.append(current)
        current += timedelta(days=1)
    return output


def test_reference_calendar_uses_cross_security_consensus():
    sessions = _weekdays(date(2025, 1, 2), 30)
    series = {
        "A": [_bar("A", session, 100) for session in sessions],
        "B": [_bar("B", session, 100) for session in sessions],
        "C": [_bar("C", session, 100) for session in sessions],
        "D": [_bar("D", session, 100) for session in sessions if session != sessions[-5]],
    }

    assert build_reference_sessions(series) == tuple(sessions)


def test_market_holiday_absent_from_reference_is_not_a_gap():
    holiday = date(2025, 12, 25)
    sessions = _weekdays(date(2025, 12, 1), 30, excluded={holiday})
    bars = [_bar("TEST", session, 100) for session in sessions]

    integrity = assess_price_series(bars, sessions)

    assert holiday not in sessions
    assert integrity.status == "complete"
    assert not integrity.missing_sessions


def test_recent_missing_session_invalidates_affected_session_metrics():
    sessions = _weekdays(date(2024, 1, 2), 300)
    missing = sessions[-10]
    bars = [
        _bar("TEST", session, 100 + index)
        for index, session in enumerate(sessions)
        if session != missing
    ]

    integrity = assess_price_series(bars, sessions)
    metrics, warnings = calculate_metrics(bars, None, reference_sessions=sessions)

    assert integrity.status == "gapped"
    assert integrity.missing_sessions == (missing,)
    assert metrics["latest_price"] is not None
    assert metrics["momentum_1m"] is None
    assert metrics["momentum_3m"] is None
    assert metrics["momentum_6m"] is None
    assert metrics["momentum_12m"] is None
    assert metrics["volatility_3m"] is None
    assert metrics["average_dollar_volume_20d"] is None
    assert metrics["price_to_sma_200"] is None
    assert metrics["max_drawdown_1y"] is None
    assert any("Missing 1 expected trading session" in warning for warning in warnings)
    assert any("Session gaps made these metrics unavailable" in warning for warning in warnings)


def test_gap_outside_a_short_window_does_not_invalidate_that_metric():
    sessions = _weekdays(date(2024, 1, 2), 300)
    missing = sessions[-100]
    bars = [
        _bar("TEST", session, 100 + index)
        for index, session in enumerate(sessions)
        if session != missing
    ]

    metrics, _ = calculate_metrics(bars, None, reference_sessions=sessions)

    assert metrics["momentum_1m"] is not None
    assert metrics["momentum_3m"] is not None
    assert metrics["volatility_3m"] is not None
    assert metrics["average_dollar_volume_20d"] is not None
    assert metrics["momentum_6m"] is None
    assert metrics["momentum_12m"] is None
    assert metrics["price_to_sma_200"] is None
    assert metrics["max_drawdown_1y"] is None
