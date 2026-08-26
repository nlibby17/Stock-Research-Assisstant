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


def percentile_scores(values: dict[str, float | None], direction: str) -> dict[str, float | None]:
    usable = [(ticker, value) for ticker, value in values.items() if _usable(value, direction)]
    output: dict[str, float | None] = {ticker: None for ticker in values}
    if not usable:
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


def recommendation(score: float | None) -> str:
    if score is None:
        return "Insufficient data"
    if score >= 75:
        return "Strong candidate"
    if score >= 65:
        return "Worth further research"
    if score >= 55:
        return "Watchlist candidate"
    return "Currently unattractive"


def score_universe(
    settings: Settings,
    inputs: dict[str, dict[str, Any]],
) -> list[ScoredSecurity]:
    metric_scores: dict[str, dict[str, float | None]] = {}
    all_metric_names = {
        metric for component in settings.metric_weights.values() for metric in component
    }
    for metric in all_metric_names:
        metric_scores[metric] = percentile_scores(
            {ticker: values["metrics"].get(metric) for ticker, values in inputs.items()},
            settings.directions[metric],
        )

    securities = {security.ticker: security for security in settings.universe}
    results: list[ScoredSecurity] = []
    minimum_coverage = float(settings.raw["app"]["minimum_overall_coverage"])
    minimum_score = float(settings.raw["app"]["minimum_candidate_score"])
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
        eligible = bool(
            overall_score is not None
            and overall_score >= minimum_score
            and overall_coverage >= minimum_coverage
        )
        security: Security = securities[ticker]
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
                recommendation=recommendation(overall_score),
                eligible=eligible,
                warnings=list(values.get("warnings", [])),
            )
        )

    results.sort(
        key=lambda result: (
            result.overall_score is not None,
            result.overall_score if result.overall_score is not None else -1,
        ),
        reverse=True,
    )
    rank = 0
    for result in results:
        if result.overall_score is not None:
            rank += 1
            result.rank = rank
    return results
