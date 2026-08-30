from stockrank.summaries import sector_momentum_leaders


def test_sector_momentum_leaders_use_medians_and_minimum_samples():
    results = [
        {"sector": sector, "metrics": {"momentum_3m": value}}
        for sector, value in (
            ("Energy", 0.10),
            ("Energy", 0.20),
            ("Energy", 0.90),
            ("Health Care", 0.12),
            ("Health Care", 0.13),
            ("Health Care", 0.14),
            ("Financials", -0.01),
            ("Financials", 0.00),
            ("Financials", 0.01),
            ("Utilities", 0.50),
            ("Utilities", 0.60),
        )
    ]

    leaders = sector_momentum_leaders(results, minimum_members=3, limit=3)

    assert [row["sector"] for row in leaders] == ["Energy", "Health Care", "Financials"]
    assert leaders[0] == {
        "sector": "Energy",
        "median_return_3m": 0.20,
        "member_count": 3,
    }


def test_sector_momentum_leaders_are_deterministic_for_ties():
    results = [
        {"sector": sector, "metrics": {"momentum_3m": value}}
        for sector in ("Utilities", "Energy")
        for value in (0.10, 0.20, 0.30)
    ]

    leaders = sector_momentum_leaders(results, minimum_members=3, limit=2)

    assert [row["sector"] for row in leaders] == ["Energy", "Utilities"]
