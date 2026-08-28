from __future__ import annotations

import csv
import io
from typing import Any


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
        "Recommendation",
        "Growth score",
        "Valuation score",
        "Quality score",
        "Momentum score",
        "Risk score",
    )
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for result in results:
        component_scores = result.get("component_scores", {})
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
                "Recommendation": result["recommendation"],
                "Growth score": component_scores.get("growth"),
                "Valuation score": component_scores.get("valuation"),
                "Quality score": component_scores.get("quality"),
                "Momentum score": component_scores.get("momentum"),
                "Risk score": component_scores.get("risk"),
            }
        )
    return output.getvalue().encode("utf-8-sig")
