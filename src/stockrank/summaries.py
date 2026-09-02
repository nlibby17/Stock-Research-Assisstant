from __future__ import annotations

import math
from collections import defaultdict
from statistics import median
from typing import Any


def _descending_finite(value: Any) -> tuple[int, float]:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return (1, 0.0)
    if not math.isfinite(numeric):
        return (1, 0.0)
    return (0, -numeric)


def market_context_leadership_order(
    context: dict[str, dict[str, Any]],
) -> list[tuple[str, dict[str, Any]]]:
    """Order market proxies by three-month return without mutating stored context."""

    def leadership_key(item: tuple[str, dict[str, Any]]) -> tuple[int, float, int, float, str]:
        ticker, values = item
        return (
            *_descending_finite(values.get("momentum_3m")),
            *_descending_finite(values.get("momentum_1m")),
            str(ticker),
        )

    return sorted(context.items(), key=leadership_key)


def sector_member_tickers(results: list[dict[str, Any]], sector: str) -> list[str]:
    """Return tickers with usable three-month momentum in one sector."""
    tickers = []
    for result in results:
        value = result.get("metrics", {}).get("momentum_3m")
        ticker = str(result.get("ticker", "")).strip().upper()
        if (
            str(result.get("sector", "")).strip() == sector
            and ticker
            and value is not None
            and math.isfinite(float(value))
        ):
            tickers.append(ticker)
    return sorted(tickers)


def sector_momentum_leaders(
    results: list[dict[str, Any]],
    *,
    minimum_members: int = 3,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Rank sectors by median three-month return within the stored universe."""
    if minimum_members < 1:
        raise ValueError("minimum_members must be at least 1")
    if limit < 1:
        raise ValueError("limit must be at least 1")
    by_sector: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for result in results:
        value = result.get("metrics", {}).get("momentum_3m")
        sector = str(result.get("sector", "")).strip()
        ticker = str(result.get("ticker", "")).strip().upper()
        if sector and ticker and value is not None and math.isfinite(float(value)):
            by_sector[sector].append((ticker, float(value)))
    rows = [
        {
            "sector": sector,
            "median_return_3m": median(value for _, value in values),
            "member_count": len(values),
            "tickers": sorted(ticker for ticker, _ in values),
        }
        for sector, values in by_sector.items()
        if len(values) >= minimum_members
    ]
    rows.sort(key=lambda row: (-row["median_return_3m"], row["sector"]))
    return rows[:limit]
