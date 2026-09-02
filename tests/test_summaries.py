from stockrank.summaries import (
    market_context_leadership_order,
    sector_member_tickers,
    sector_momentum_leaders,
)


def test_market_context_leadership_order_uses_three_month_then_one_month_return():
    context = {
        "SPY": {"momentum_3m": 0.08, "momentum_1m": 0.01},
        "QQQ": {"momentum_3m": 0.12, "momentum_1m": -0.02},
        "XLK": {"momentum_3m": 0.08, "momentum_1m": 0.03},
        "IWM": {"momentum_3m": None, "momentum_1m": 0.04},
        "XLF": {"momentum_3m": float("nan"), "momentum_1m": 0.05},
    }

    ordered = market_context_leadership_order(context)

    assert [ticker for ticker, _ in ordered] == ["QQQ", "XLK", "SPY", "XLF", "IWM"]
    assert list(context) == ["SPY", "QQQ", "XLK", "IWM", "XLF"]


def test_sector_momentum_leaders_use_medians_and_minimum_samples():
    results = [
        {"ticker": ticker, "sector": sector, "metrics": {"momentum_3m": value}}
        for ticker, sector, value in (
            ("XOM", "Energy", 0.10),
            ("CVX", "Energy", 0.20),
            ("COP", "Energy", 0.90),
            ("UNH", "Health Care", 0.12),
            ("LLY", "Health Care", 0.13),
            ("ABBV", "Health Care", 0.14),
            ("JPM", "Financials", -0.01),
            ("BAC", "Financials", 0.00),
            ("GS", "Financials", 0.01),
            ("NEE", "Utilities", 0.50),
            ("DUK", "Utilities", 0.60),
        )
    ]

    leaders = sector_momentum_leaders(results, minimum_members=3, limit=3)

    assert [row["sector"] for row in leaders] == ["Energy", "Health Care", "Financials"]
    assert leaders[0] == {
        "sector": "Energy",
        "median_return_3m": 0.20,
        "member_count": 3,
        "tickers": ["COP", "CVX", "XOM"],
    }


def test_sector_momentum_leaders_are_deterministic_for_ties():
    results = [
        {
            "ticker": f"{sector[:2]}{index}",
            "sector": sector,
            "metrics": {"momentum_3m": value},
        }
        for sector in ("Utilities", "Energy")
        for index, value in enumerate((0.10, 0.20, 0.30), start=1)
    ]

    leaders = sector_momentum_leaders(results, minimum_members=3, limit=2)

    assert [row["sector"] for row in leaders] == ["Energy", "Utilities"]


def test_sector_member_tickers_exclude_missing_momentum_and_sort():
    results = [
        {"ticker": "XOM", "sector": "Energy", "metrics": {"momentum_3m": 0.1}},
        {"ticker": "COP", "sector": "Energy", "metrics": {"momentum_3m": 0.2}},
        {"ticker": "CVX", "sector": "Energy", "metrics": {"momentum_3m": None}},
        {"ticker": "JPM", "sector": "Financials", "metrics": {"momentum_3m": 0.3}},
    ]

    assert sector_member_tickers(results, "Energy") == ["COP", "XOM"]
