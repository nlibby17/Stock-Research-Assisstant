from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from stockrank.data.sec import SecSubmissions
from stockrank.models import SecFiling

LEGACY_RELATIVE_STATUS = {
    "Strong candidate": "High relative score",
    "Worth further research": "Above-average relative score",
    "Watchlist candidate": "Relative watchlist",
    "Currently unattractive": "Lower relative score",
}
COMPONENTS = ("growth", "valuation", "quality", "momentum", "risk")


@dataclass(frozen=True)
class FilingDisclosure:
    filings: tuple[SecFiling, ...]
    limitation: str | None = None


MISSING_FILING_CUTOFF_MESSAGE = (
    "SEC filing metadata is withheld because this stored run does not have a "
    "timezone-aware completion timestamp."
)


def filings_for_completed_run(
    filings: tuple[SecFiling, ...], completed_at: datetime | None
) -> FilingDisclosure:
    """Select only filings known by an aware, recorded run-completion cutoff."""
    if (
        completed_at is None
        or completed_at.tzinfo is None
        or completed_at.utcoffset() is None
    ):
        return FilingDisclosure((), MISSING_FILING_CUTOFF_MESSAGE)
    return FilingDisclosure(
        SecSubmissions.effective_filings(filings, available_at=completed_at)
    )


def candidate_policy_summary(
    app_config: dict[str, Any], eligibility_config: dict[str, Any]
) -> str | None:
    """Describe the complete candidate policy only when the stored run recorded it."""
    try:
        minimum_score = float(app_config["minimum_candidate_score"])
        minimum_coverage = float(app_config["minimum_overall_coverage"])
        minimum_price = float(eligibility_config["minimum_latest_price"])
        minimum_dollar_volume = float(
            eligibility_config["minimum_average_dollar_volume_20d"]
        )
    except (KeyError, TypeError, ValueError):
        return None
    return (
        f"score ≥ {minimum_score:g}, coverage ≥ {minimum_coverage:.0%}, "
        f"price ≥ ${minimum_price:,.2f}, and 20-day average dollar volume "
        f"≥ ${minimum_dollar_volume:,.0f}"
    )


def no_candidate_explanation(
    results: list[dict[str, Any]],
    app_config: dict[str, Any],
    eligibility_config: dict[str, Any],
) -> str:
    """Explain an empty candidate list without substituting active settings."""
    policy = candidate_policy_summary(app_config, eligibility_config)
    if policy:
        minimum_score = float(app_config["minimum_candidate_score"])
        minimum_coverage = float(app_config["minimum_overall_coverage"])
        minimum_price = float(eligibility_config["minimum_latest_price"])
        minimum_dollar_volume = float(
            eligibility_config["minimum_average_dollar_volume_20d"]
        )
        failure_counts = {"score": 0, "coverage": 0, "price": 0, "liquidity": 0}
        for result in results:
            if result.get("eligible"):
                continue
            score = result.get("overall_score")
            coverage = result.get("overall_coverage")
            price = result.get("latest_price")
            dollar_volume = result.get("metrics", {}).get("average_dollar_volume_20d")
            if score is None or float(score) < minimum_score:
                failure_counts["score"] += 1
            if coverage is None or float(coverage) < minimum_coverage:
                failure_counts["coverage"] += 1
            if price is None or float(price) < minimum_price:
                failure_counts["price"] += 1
            if dollar_volume is None or float(dollar_volume) < minimum_dollar_volume:
                failure_counts["liquidity"] += 1
        failures = ", ".join(
            f"{label} {count}" for label, count in failure_counts.items() if count
        )
        failure_detail = (
            f" Stored exclusions (a company can fail more than one rule): {failures}."
            if failures
            else ""
        )
        return (
            f"No company met all stored candidate eligibility rules ({policy}). "
            f"The list is intentionally not padded.{failure_detail}"
        )
    return (
        "No company was stored as eligible. This legacy run does not contain the complete "
        "candidate-policy thresholds, so current settings are not substituted. The list is "
        "intentionally not padded."
    )


def relative_status_label(value: str) -> str:
    """Present legacy recommendation text using the current universe-relative language."""
    return LEGACY_RELATIVE_STATUS.get(value, value)


def score_breakdown(
    result: dict[str, Any], component_weights: dict[str, float]
) -> str:
    """Describe a stored overall score using its effective component weights."""
    weighted_components = []
    for component in COMPONENTS:
        score = result["component_scores"].get(component)
        coverage = float(result["component_coverage"].get(component, 0.0))
        effective_weight = float(component_weights.get(component, 0.0)) * coverage
        if score is not None and effective_weight > 0:
            weighted_components.append((component, float(score), effective_weight))
    effective_total = sum(item[2] for item in weighted_components)
    if not effective_total:
        return "No component score breakdown is available."
    return " · ".join(
        f"{component.title()} {score:.1f} × {weight / effective_total:.0%}"
        for component, score, weight in weighted_components
    )


def _ranked_candidates(results: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return [result for result in results if result["eligible"]][:limit]


def ranking_change_summary(
    current_results: list[dict[str, Any]],
    previous_results: list[dict[str, Any]],
    *,
    current_limit: int,
    previous_limit: int | None = None,
    mover_limit: int = 5,
    score_threshold: float = 1.0,
) -> dict[str, list[dict[str, Any]]]:
    """Summarize observable ranking changes between comparable stored runs."""
    previous_limit = current_limit if previous_limit is None else previous_limit
    current_by_ticker = {result["ticker"]: result for result in current_results}
    previous_by_ticker = {result["ticker"]: result for result in previous_results}
    current_top = _ranked_candidates(current_results, current_limit)
    previous_top = _ranked_candidates(previous_results, previous_limit)
    current_top_tickers = {result["ticker"] for result in current_top}
    previous_top_tickers = {result["ticker"] for result in previous_top}

    new_candidates = [
        {
            "Ticker": result["ticker"],
            "Rank": result["rank"],
            "Score": result["overall_score"],
        }
        for result in current_top
        if result["ticker"] not in previous_top_tickers
    ]
    exited_candidates = [
        {
            "Ticker": result["ticker"],
            "Previous rank": result["rank"],
            "Previous score": result["overall_score"],
        }
        for result in previous_top
        if result["ticker"] not in current_top_tickers
    ]

    movers: list[dict[str, Any]] = []
    score_changes: list[dict[str, Any]] = []
    for ticker in current_by_ticker.keys() & previous_by_ticker.keys():
        current = current_by_ticker[ticker]
        previous = previous_by_ticker[ticker]
        if current["rank"] is not None and previous["rank"] is not None:
            rank_change = int(previous["rank"]) - int(current["rank"])
            if rank_change:
                movers.append(
                    {
                        "Ticker": ticker,
                        "Previous rank": previous["rank"],
                        "Current rank": current["rank"],
                        "Rank change": rank_change,
                    }
                )
        if current["overall_score"] is not None and previous["overall_score"] is not None:
            score_change = float(current["overall_score"]) - float(previous["overall_score"])
            if abs(score_change) >= score_threshold:
                score_changes.append(
                    {
                        "Ticker": ticker,
                        "Previous score": previous["overall_score"],
                        "Current score": current["overall_score"],
                        "Score change": score_change,
                    }
                )

    gainers = sorted(
        (row for row in movers if row["Rank change"] > 0),
        key=lambda row: (-row["Rank change"], row["Ticker"]),
    )[:mover_limit]
    decliners = sorted(
        (row for row in movers if row["Rank change"] < 0),
        key=lambda row: (row["Rank change"], row["Ticker"]),
    )[:mover_limit]
    score_changes.sort(key=lambda row: (-abs(row["Score change"]), row["Ticker"]))
    return {
        "new_candidates": new_candidates,
        "exited_candidates": exited_candidates,
        "rank_gainers": gainers,
        "rank_decliners": decliners,
        "score_changes": score_changes[:mover_limit],
    }


def rankings_csv(results: list[dict[str, Any]]) -> bytes:
    """Return a flat, Excel-friendly UTF-8 CSV for a stored ranking run."""
    columns = (
        "Rank",
        "Ticker",
        "Company",
        "Sector",
        "Price",
        "Price as of",
        "Overall score",
        "Coverage percent",
        "Eligible",
        "Eligibility notes",
        "Relative status",
        "Growth score",
        "Growth coverage percent",
        "Valuation score",
        "Valuation coverage percent",
        "Quality score",
        "Quality coverage percent",
        "Momentum score",
        "Momentum coverage percent",
        "Risk score",
        "Risk coverage percent",
    )
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for result in results:
        component_scores = result.get("component_scores", {})
        component_coverage = result.get("component_coverage", {})
        writer.writerow(
            {
                "Rank": result["rank"],
                "Ticker": result["ticker"],
                "Company": result["company"],
                "Sector": result["sector"],
                "Price": result["latest_price"],
                "Price as of": result["price_as_of"],
                "Overall score": result["overall_score"],
                "Coverage percent": round(float(result["overall_coverage"]) * 100, 2),
                "Eligible": "yes" if result["eligible"] else "no",
                "Eligibility notes": "; ".join(result.get("eligibility_reasons", [])),
                "Relative status": relative_status_label(result["recommendation"]),
                "Growth score": component_scores.get("growth"),
                "Growth coverage percent": round(
                    float(component_coverage.get("growth", 0.0)) * 100, 2
                ),
                "Valuation score": component_scores.get("valuation"),
                "Valuation coverage percent": round(
                    float(component_coverage.get("valuation", 0.0)) * 100, 2
                ),
                "Quality score": component_scores.get("quality"),
                "Quality coverage percent": round(
                    float(component_coverage.get("quality", 0.0)) * 100, 2
                ),
                "Momentum score": component_scores.get("momentum"),
                "Momentum coverage percent": round(
                    float(component_coverage.get("momentum", 0.0)) * 100, 2
                ),
                "Risk score": component_scores.get("risk"),
                "Risk coverage percent": round(float(component_coverage.get("risk", 0.0)) * 100, 2),
            }
        )
    return output.getvalue().encode("utf-8-sig")
