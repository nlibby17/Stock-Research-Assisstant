from datetime import UTC, date, datetime, timedelta

import pytest

from stockrank.metrics import apply_sector_conventions, calculate_metrics
from stockrank.models import FundamentalSnapshot, PriceBar


def test_metrics_calculate_returns_risk_and_fundamental_ratios():
    fetched = datetime.now(UTC)
    bars = [
        PriceBar(
            ticker="TEST",
            date=date(2025, 1, 1) + timedelta(days=index),
            open=100 + index,
            high=101 + index,
            low=99 + index,
            close=100 + index,
            adjusted_close=100 + index,
            volume=1_000_000,
            source="test",
            fetched_at=fetched,
        )
        for index in range(300)
    ]
    fundamentals = FundamentalSnapshot(
        ticker="TEST",
        source="test",
        fetched_at=fetched,
        market_cap=10_000,
        total_revenue=2_000,
        free_cash_flow=200,
        revenue_growth=0.2,
    )
    metrics, warnings = calculate_metrics(bars, fundamentals)
    assert metrics["latest_price"] == 399
    assert metrics["momentum_12m"] == pytest.approx(399 / 147 - 1)
    assert metrics["free_cash_flow_margin"] == pytest.approx(0.1)
    assert metrics["free_cash_flow_yield"] == pytest.approx(0.02)
    assert metrics["max_drawdown_1y"] == 0
    assert not warnings


def test_metrics_preserve_missing_fundamentals():
    metrics, warnings = calculate_metrics([], None)
    assert metrics["market_cap"] is None
    assert metrics["latest_price"] is None
    assert "Fundamental summary unavailable" in warnings


def test_financial_sector_excludes_noncomparable_industrial_ratios():
    metrics = {
        "gross_margin": 0.0,
        "debt_to_equity": 250.0,
        "current_ratio": 1.2,
        "free_cash_flow_margin": 0.3,
        "free_cash_flow_yield": 0.1,
        "return_on_equity": 0.18,
    }
    normalized, warnings = apply_sector_conventions(metrics, "Financials")
    assert normalized["gross_margin"] is None
    assert normalized["debt_to_equity"] is None
    assert normalized["return_on_equity"] == 0.18
    assert warnings
