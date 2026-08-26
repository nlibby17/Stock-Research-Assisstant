import copy
from pathlib import Path

from stockrank.config import Settings, load_settings
from stockrank.models import Security
from stockrank.scoring import percentile_scores, score_universe


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


def test_missing_aware_score_reports_coverage():
    loaded = load_settings(Path.cwd())
    raw = copy.deepcopy(loaded.raw)
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
