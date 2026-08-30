from __future__ import annotations

import math
from typing import Any

from stockrank.config import Settings
from stockrank.models import ScoredSecurity, Security


def _usable(value: float | None, direction: str) -> bool:
    if value is None or not math.isfinite(value):
        return False
    if direction == "lower_positive":
        return value > 0
    return True


def percentile_scores(
    values: dict[str, float | None],
    direction: str,
    *,
    minimum_peer_count: int = 1,
) -> dict[str, float | None]:
    if minimum_peer_count < 1:
        raise ValueError("Minimum metric peer count must be at least 1")
    usable = [(ticker, value) for ticker, value in values.items() if _usable(value, direction)]
    output: dict[str, float | None] = {ticker: None for ticker in values}
    if len(usable) < minimum_peer_count:
        return output
    sorted_values = sorted(value for _, value in usable)
    if len(sorted_values) == 1:
        only_ticker = usable[0][0]
        output[only_ticker] = 50.0
        return output
    for ticker, value in usable:
        positions = [index for index, candidate in enumerate(sorted_values) if candidate == value]
        rank = sum(positions) / len(positions)
        percentile = rank / (len(sorted_values) - 1) * 100.0
        if direction in {"lower", "lower_positive"}:
            percentile = 100.0 - percentile
        output[ticker] = percentile
    return output


def metric_peer_counts(settings: Settings, inputs: dict[str, dict[str, Any]]) -> dict[str, int]:
    return {
        metric: sum(
            _usable(values["metrics"].get(metric), settings.directions[metric])
            for values in inputs.values()
        )
        for metric in {name for component in settings.metric_weights.values() for name in component}
    }


def recommendation(
    score: float | None,
    coverage: float,
    minimum_coverage: float,
) -> str:
    if score is None:
        return "Insufficient data"
    if coverage < minimum_coverage:
        return "Insufficient coverage"
    if score >= 75:
        return "High relative score"
    if score >= 65:
        return "Above-average relative score"
    if score >= 55:
        return "Relative watchlist"
    return "Lower relative score"


def candidate_eligibility_reasons(
    metrics: dict[str, float | None],
    *,
    minimum_latest_price: float,
    minimum_average_dollar_volume_20d: float,
) -> list[str]:
    """Explain price/liquidity conditions that block top-candidate eligibility."""
    reasons: list[str] = []
    latest_price = metrics.get("latest_price")
    if latest_price is None or not math.isfinite(latest_price):
        reasons.append("latest price is unavailable")
    elif latest_price < minimum_latest_price:
        reasons.append(
            f"latest price {latest_price:.2f} is below the {minimum_latest_price:.2f} minimum"
        )

    dollar_volume = metrics.get("average_dollar_volume_20d")
    if dollar_volume is None or not math.isfinite(dollar_volume):
        reasons.append("20-day average dollar volume is unavailable")
    elif dollar_volume < minimum_average_dollar_volume_20d:
        reasons.append(
            f"20-day average dollar volume {dollar_volume:,.0f} is below the "
            f"{minimum_average_dollar_volume_20d:,.0f} minimum"
        )
    return reasons


def score_universe(
    settings: Settings,
    inputs: dict[str, dict[str, Any]],
) -> list[ScoredSecurity]:
    metric_scores: dict[str, dict[str, float | None]] = {}
    all_metric_names = {
        metric for component in settings.metric_weights.values() for metric in component
    }
    peer_counts = metric_peer_counts(settings, inputs)
    minimum_peer_count = int(settings.raw["scoring"]["validity"]["minimum_metric_peer_count"])
    for metric in all_metric_names:
        metric_scores[metric] = percentile_scores(
            {ticker: values["metrics"].get(metric) for ticker, values in inputs.items()},
            settings.directions[metric],
            minimum_peer_count=minimum_peer_count,
        )

    securities = {security.ticker: security for security in settings.universe}
    results: list[ScoredSecurity] = []
    minimum_coverage = float(settings.raw["app"]["minimum_overall_coverage"])
    minimum_score = float(settings.raw["app"]["minimum_candidate_score"])
    eligibility_policy = settings.raw["scoring"]["eligibility"]
    minimum_latest_price = float(eligibility_policy["minimum_latest_price"])
    minimum_dollar_volume = float(eligibility_policy["minimum_average_dollar_volume_20d"])
    for ticker, values in inputs.items():
        component_scores: dict[str, float | None] = {}
        component_coverage: dict[str, float] = {}
        per_metric_scores: dict[str, float | None] = {}
        for component, weights in settings.metric_weights.items():
            total_weight = sum(weights.values())
            available_weight = 0.0
            weighted_score = 0.0
            for metric, weight in weights.items():
                metric_score = metric_scores[metric].get(ticker)
                per_metric_scores[metric] = metric_score
                if metric_score is not None:
                    available_weight += weight
                    weighted_score += weight * metric_score
            coverage = available_weight / total_weight if total_weight else 0.0
            component_coverage[component] = coverage
            component_scores[component] = (
                weighted_score / available_weight if available_weight else None
            )

        effective_total = 0.0
        overall_numerator = 0.0
        configured_total = sum(settings.component_weights.values())
        for component, weight in settings.component_weights.items():
            component_score = component_scores[component]
            effective_weight = weight * component_coverage[component]
            if component_score is not None and effective_weight > 0:
                effective_total += effective_weight
                overall_numerator += effective_weight * component_score
        overall_coverage = effective_total / configured_total if configured_total else 0.0
        overall_score = overall_numerator / effective_total if effective_total else None
        eligibility_reasons = candidate_eligibility_reasons(
            values["metrics"],
            minimum_latest_price=minimum_latest_price,
            minimum_average_dollar_volume_20d=minimum_dollar_volume,
        )
        eligible = bool(
            overall_score is not None
            and overall_score >= minimum_score
            and overall_coverage >= minimum_coverage
            and not eligibility_reasons
        )
        security: Security = securities[ticker]
        result_warnings = list(values.get("warnings", []))
        if eligibility_reasons:
            result_warnings.append(
                "Top-candidate eligibility withheld: " + "; ".join(eligibility_reasons)
            )
        weak_metrics = sorted(
            metric
            for metric in all_metric_names
            if peer_counts[metric] < minimum_peer_count
            and _usable(values["metrics"].get(metric), settings.directions[metric])
        )
        if weak_metrics:
            result_warnings.append(
                f"Percentile withheld below the {minimum_peer_count}-peer minimum: "
                + ", ".join(f"{metric} ({peer_counts[metric]})" for metric in weak_metrics)
            )
        results.append(
            ScoredSecurity(
                ticker=ticker,
                company=values.get("company") or security.company,
                sector=values.get("sector") or security.sector,
                latest_price=values["metrics"].get("latest_price"),
                price_as_of=values.get("price_as_of"),
                metrics=values["metrics"],
                metric_scores=per_metric_scores,
                component_scores=component_scores,
                component_coverage=component_coverage,
                overall_score=overall_score,
                overall_coverage=overall_coverage,
                recommendation=recommendation(
                    overall_score,
                    overall_coverage,
                    minimum_coverage,
                ),
                eligible=eligible,
                eligibility_reasons=eligibility_reasons,
                warnings=result_warnings,
            )
        )

    results.sort(
        key=lambda result: (
            result.overall_score is None,
            -(result.overall_score if result.overall_score is not None else -1),
            result.ticker,
        ),
    )
    rank = 0
    for result in results:
        if result.overall_score is not None:
            rank += 1
            result.rank = rank
    return results
