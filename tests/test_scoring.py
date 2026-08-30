import copy
from pathlib import Path

from stockrank.config import Settings, load_settings
from stockrank.models import Security
from stockrank.scoring import (
    candidate_eligibility_reasons,
    percentile_scores,
    recommendation,
    score_universe,
)


def test_percentiles_respect_direction_and_ties():
    higher = percentile_scores({"A": 1.0, "B": 2.0, "C": 2.0}, "higher")
    assert higher["A"] == 0
    assert higher["B"] == higher["C"] == 75
    lower = percentile_scores({"A": 1.0, "B": 2.0, "C": None}, "lower")
    assert lower["A"] == 100
    assert lower["B"] == 0
    assert lower["C"] is None


def test_invalid_nonpositive_valuation_is_missing():
    values = percentile_scores({"A": -5.0, "B": 10.0}, "lower_positive")
    assert values["A"] is None
    assert values["B"] == 50


def test_candidate_liquidity_reasons_are_explicit_and_configurable():
    assert candidate_eligibility_reasons(
        {"latest_price": 0.75, "average_dollar_volume_20d": 250_000.0},
        minimum_latest_price=1.0,
        minimum_average_dollar_volume_20d=1_000_000.0,
    ) == [
        "latest price 0.75 is below the 1.00 minimum",
        "20-day average dollar volume 250,000 is below the 1,000,000 minimum",
    ]
    assert not candidate_eligibility_reasons(
        {"latest_price": 5.0, "average_dollar_volume_20d": 2_000_000.0},
        minimum_latest_price=1.0,
        minimum_average_dollar_volume_20d=1_000_000.0,
    )


def test_percentiles_are_withheld_below_the_peer_minimum():
    values = percentile_scores(
        {"A": 1.0, "B": 2.0, "C": None},
        "higher",
        minimum_peer_count=3,
    )
    assert values == {"A": None, "B": None, "C": None}


def test_missing_aware_score_reports_coverage():
    loaded = load_settings(Path.cwd())
    raw = copy.deepcopy(loaded.raw)
    raw["scoring"]["validity"]["minimum_metric_peer_count"] = 2
    settings = Settings(
        root=loaded.root,
        raw=raw,
        universe=(Security("A", "Alpha", "Tech"), Security("B", "Beta", "Tech")),
    )
    blank = {metric: None for component in settings.metric_weights.values() for metric in component}
    a_metrics = dict(blank, revenue_growth=0.2, momentum_1m=0.1, latest_price=10)
    b_metrics = dict(blank, revenue_growth=0.1, momentum_1m=-0.1, latest_price=9)
    results = score_universe(
        settings,
        {
            "A": {"metrics": a_metrics, "price_as_of": "2026-01-01"},
            "B": {"metrics": b_metrics, "price_as_of": "2026-01-01"},
        },
    )
    assert results[0].ticker == "A"
    assert results[0].overall_coverage < 0.60
    assert not results[0].eligible
    assert results[0].component_scores["valuation"] is None


def test_score_warns_when_a_present_metric_has_too_few_peers():
    loaded = load_settings(Path.cwd())
    raw = copy.deepcopy(loaded.raw)
    raw["scoring"]["validity"]["minimum_metric_peer_count"] = 3
    settings = Settings(
        root=loaded.root,
        raw=raw,
        universe=(Security("A", "Alpha", "Tech"), Security("B", "Beta", "Tech")),
    )
    blank = {metric: None for component in settings.metric_weights.values() for metric in component}
    results = score_universe(
        settings,
        {
            "A": {"metrics": dict(blank, revenue_growth=0.2), "price_as_of": "2026-01-01"},
            "B": {"metrics": dict(blank, revenue_growth=0.1), "price_as_of": "2026-01-01"},
        },
    )

    assert all(result.metric_scores["revenue_growth"] is None for result in results)
    assert all(result.overall_coverage == 0 for result in results)
    assert all("revenue_growth (2)" in " ".join(result.warnings) for result in results)


def test_recommendation_is_coverage_aware_and_explicitly_relative():
    assert recommendation(None, 0.0, 0.6) == "Insufficient data"
    assert recommendation(90.0, 0.59, 0.6) == "Insufficient coverage"
    assert recommendation(75.0, 0.6, 0.6) == "High relative score"
    assert recommendation(65.0, 0.6, 0.6) == "Above-average relative score"
    assert recommendation(55.0, 0.6, 0.6) == "Relative watchlist"
    assert recommendation(54.9, 1.0, 0.6) == "Lower relative score"


def test_missing_metric_is_not_penalized_but_reduces_visible_coverage():
    loaded = load_settings(Path.cwd())
    raw = copy.deepcopy(loaded.raw)
    raw["scoring"]["validity"]["minimum_metric_peer_count"] = 2
    settings = Settings(
        root=loaded.root,
        raw=raw,
        universe=(
            Security("A", "Alpha", "Tech"),
            Security("B", "Beta", "Tech"),
            Security("C", "Gamma", "Tech"),
        ),
    )
    blank = {metric: None for component in settings.metric_weights.values() for metric in component}
    results = {
        result.ticker: result
        for result in score_universe(
            settings,
            {
                "A": {
                    "metrics": dict(blank, revenue_growth=1.0, earnings_growth=0.0),
                    "price_as_of": "2026-01-01",
                },
                "B": {
                    "metrics": dict(blank, revenue_growth=1.0),
                    "price_as_of": "2026-01-01",
                },
                "C": {
                    "metrics": dict(blank, revenue_growth=0.0, earnings_growth=1.0),
                    "price_as_of": "2026-01-01",
                },
            },
        )
    }

    assert results["B"].component_scores["growth"] > results["A"].component_scores["growth"]
    assert results["B"].component_coverage["growth"] < results["A"].component_coverage["growth"]
    assert results["B"].overall_coverage < results["A"].overall_coverage
    assert results["B"].recommendation == "Insufficient coverage"


def test_liquidity_blocks_top_candidate_without_erasing_score():
    loaded = load_settings(Path.cwd())
    raw = copy.deepcopy(loaded.raw)
    raw["scoring"]["validity"]["minimum_metric_peer_count"] = 2
    raw["app"]["minimum_candidate_score"] = 0
    raw["app"]["minimum_overall_coverage"] = 0
    settings = Settings(
        root=loaded.root,
        raw=raw,
        universe=(Security("A", "Alpha", "Industrials"), Security("B", "Beta", "Industrials")),
    )
    blank = {metric: None for component in settings.metric_weights.values() for metric in component}
    results = {
        result.ticker: result
        for result in score_universe(
            settings,
            {
                "A": {
                    "metrics": dict(
                        blank,
                        revenue_growth=0.2,
                        latest_price=0.5,
                        average_dollar_volume_20d=100_000.0,
                    ),
                    "price_as_of": "2026-01-01",
                },
                "B": {
                    "metrics": dict(
                        blank,
                        revenue_growth=0.1,
                        latest_price=10.0,
                        average_dollar_volume_20d=5_000_000.0,
                    ),
                    "price_as_of": "2026-01-01",
                },
            },
        )
    }

    assert results["A"].overall_score is not None
    assert not results["A"].eligible
    assert len(results["A"].eligibility_reasons) == 2
    assert results["B"].eligible


def test_equal_scores_use_ticker_as_the_deterministic_tie_breaker():
    loaded = load_settings(Path.cwd())
    raw = copy.deepcopy(loaded.raw)
    raw["scoring"]["validity"]["minimum_metric_peer_count"] = 2
    settings = Settings(
        root=loaded.root,
        raw=raw,
        universe=(Security("BBB", "Beta", "Industrials"), Security("AAA", "Alpha", "Industrials")),
    )
    blank = {metric: None for component in settings.metric_weights.values() for metric in component}
    shared = dict(
        blank,
        revenue_growth=0.1,
        latest_price=10.0,
        average_dollar_volume_20d=5_000_000.0,
    )

    results = score_universe(
        settings,
        {
            "BBB": {"metrics": dict(shared), "price_as_of": "2026-01-01"},
            "AAA": {"metrics": dict(shared), "price_as_of": "2026-01-01"},
        },
    )

    assert [(result.ticker, result.rank) for result in results] == [("AAA", 1), ("BBB", 2)]
