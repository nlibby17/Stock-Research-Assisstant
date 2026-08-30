from __future__ import annotations

import math
import statistics
from collections.abc import Iterable
from datetime import date

from stockrank.models import FundamentalSnapshot, PriceBar
from stockrank.price_integrity import assess_price_series, expected_bar_window


def _return_at(closes: list[float], sessions: int) -> float | None:
    if len(closes) <= sessions or closes[-sessions - 1] <= 0:
        return None
    return closes[-1] / closes[-sessions - 1] - 1.0


def _daily_returns(closes: list[float]) -> list[float]:
    return [
        closes[index] / closes[index - 1] - 1
        for index in range(1, len(closes))
        if closes[index - 1] > 0
    ]


def _max_drawdown(closes: list[float]) -> float | None:
    if not closes:
        return None
    peak = closes[0]
    worst = 0.0
    for value in closes:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return worst


def calculate_metrics(
    bars: Iterable[PriceBar],
    fundamentals: FundamentalSnapshot | None,
    *,
    reference_sessions: Iterable[date] | None = None,
) -> tuple[dict[str, float | None], list[str]]:
    ordered = sorted(bars, key=lambda bar: bar.date)
    closes = [bar.adjusted_close for bar in ordered if bar.adjusted_close > 0]
    warnings: list[str] = []
    if len(closes) < 64:
        warnings.append(f"Only {len(closes)} usable sessions; medium-term metrics are sparse")

    continuity = assess_price_series(ordered, reference_sessions)
    warnings.extend(continuity.warnings)

    momentum_windows = {
        "momentum_1m": expected_bar_window(ordered, reference_sessions, 22),
        "momentum_3m": expected_bar_window(ordered, reference_sessions, 64),
        "momentum_6m": expected_bar_window(ordered, reference_sessions, 127),
        "momentum_12m": expected_bar_window(ordered, reference_sessions, 253),
    }
    recent_window = expected_bar_window(ordered, reference_sessions, 64)
    recent_closes = [bar.adjusted_close for bar in recent_window] if recent_window else []
    recent_returns = _daily_returns(recent_closes)
    volatility = (
        statistics.stdev(recent_returns) * math.sqrt(252) if len(recent_returns) >= 20 else None
    )
    recent_bars = expected_bar_window(ordered, reference_sessions, 20) or ()
    dollar_volumes = [
        bar.close * bar.volume for bar in recent_bars if bar.volume is not None and bar.close > 0
    ]
    average_dollar_volume = statistics.fmean(dollar_volumes) if dollar_volumes else None
    sma_window = expected_bar_window(ordered, reference_sessions, 200)
    sma_200 = (
        statistics.fmean(bar.adjusted_close for bar in sma_window) if sma_window else None
    )
    drawdown_window = expected_bar_window(ordered, reference_sessions, 253)
    current = closes[-1] if closes else None

    if continuity.status == "gapped":
        affected = []
        windows = {
            **momentum_windows,
            "volatility_3m": recent_window,
            "average_dollar_volume_20d": recent_bars,
            "price_to_sma_200": sma_window,
            "max_drawdown_1y": drawdown_window,
        }
        for name, window in windows.items():
            if window is None or not window:
                affected.append(name)
        if affected:
            warnings.append(
                "Session gaps made these metrics unavailable: " + ", ".join(sorted(affected))
            )

    fundamental_values: dict[str, float | None] = {
        "market_cap": None,
        "revenue_growth": None,
        "earnings_growth": None,
        "free_cash_flow_margin": None,
        "forward_pe": None,
        "trailing_pe": None,
        "peg_ratio": None,
        "price_to_sales": None,
        "free_cash_flow_yield": None,
        "gross_margin": None,
        "profit_margin": None,
        "return_on_equity": None,
        "debt_to_equity": None,
        "current_ratio": None,
        "beta": None,
    }
    if fundamentals:
        fundamental_values.update(
            {
                "market_cap": fundamentals.market_cap,
                "revenue_growth": fundamentals.revenue_growth,
                "earnings_growth": fundamentals.earnings_growth,
                "free_cash_flow_margin": (
                    fundamentals.free_cash_flow / fundamentals.total_revenue
                    if fundamentals.free_cash_flow is not None
                    and fundamentals.total_revenue
                    and fundamentals.total_revenue > 0
                    else None
                ),
                "forward_pe": fundamentals.forward_pe,
                "trailing_pe": fundamentals.trailing_pe,
                "peg_ratio": fundamentals.peg_ratio,
                "price_to_sales": fundamentals.price_to_sales,
                "free_cash_flow_yield": (
                    fundamentals.free_cash_flow / fundamentals.market_cap
                    if fundamentals.free_cash_flow is not None
                    and fundamentals.market_cap
                    and fundamentals.market_cap > 0
                    else None
                ),
                "gross_margin": fundamentals.gross_margin,
                "profit_margin": fundamentals.profit_margin,
                "return_on_equity": fundamentals.return_on_equity,
                "debt_to_equity": fundamentals.debt_to_equity,
                "current_ratio": fundamentals.current_ratio,
                "beta": fundamentals.beta,
            }
        )
    else:
        warnings.append("Fundamental summary unavailable")

    metrics = {
        **fundamental_values,
        "latest_price": current,
        "momentum_1m": (
            _return_at([bar.adjusted_close for bar in momentum_windows["momentum_1m"]], 21)
            if momentum_windows["momentum_1m"]
            else None
        ),
        "momentum_3m": (
            _return_at([bar.adjusted_close for bar in momentum_windows["momentum_3m"]], 63)
            if momentum_windows["momentum_3m"]
            else None
        ),
        "momentum_6m": (
            _return_at([bar.adjusted_close for bar in momentum_windows["momentum_6m"]], 126)
            if momentum_windows["momentum_6m"]
            else None
        ),
        "momentum_12m": (
            _return_at([bar.adjusted_close for bar in momentum_windows["momentum_12m"]], 252)
            if momentum_windows["momentum_12m"]
            else None
        ),
        "volatility_3m": volatility,
        "max_drawdown_1y": (
            _max_drawdown([bar.adjusted_close for bar in drawdown_window])
            if drawdown_window
            else None
        ),
        "average_dollar_volume_20d": average_dollar_volume,
        "price_to_sma_200": current / sma_200 - 1 if current and sma_200 else None,
    }
    return metrics, warnings


def apply_sector_conventions(
    metrics: dict[str, float | None], sector: str
) -> tuple[dict[str, float | None], list[str]]:
    """Remove ratios that are structurally non-comparable for a sector."""
    output = dict(metrics)
    warnings: list[str] = []
    if sector == "Financials":
        for metric in (
            "free_cash_flow_margin",
            "free_cash_flow_yield",
            "gross_margin",
            "debt_to_equity",
            "current_ratio",
        ):
            output[metric] = None
        warnings.append(
            "Financial-sector convention: industrial FCF, gross-margin, liquidity, "
            "and debt ratios are excluded as non-comparable"
        )
    return output, warnings
