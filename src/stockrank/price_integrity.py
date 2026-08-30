from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from math import ceil

from stockrank.models import PriceBar

DEFAULT_CONTINUITY_LOOKBACK = 253
DEFAULT_SESSION_CONSENSUS = 0.75


@dataclass(frozen=True)
class PriceSeriesIntegrity:
    status: str
    expected_session_count: int
    observed_session_count: int
    missing_sessions: tuple[date, ...]
    warnings: tuple[str, ...]


def build_reference_sessions(
    series_by_ticker: Mapping[str, Iterable[PriceBar]],
    *,
    consensus_ratio: float = DEFAULT_SESSION_CONSENSUS,
) -> tuple[date, ...]:
    """Infer provider trading sessions from dates shared by most available securities."""
    if not 0 < consensus_ratio <= 1:
        raise ValueError("Trading-session consensus ratio must be above 0 and at most 1")
    observed_series = [
        {bar.date for bar in bars}
        for bars in series_by_ticker.values()
        if bars
    ]
    if not observed_series:
        return ()
    required = max(1, ceil(len(observed_series) * consensus_ratio))
    counts = Counter(session for sessions in observed_series for session in sessions)
    return tuple(sorted(session for session, count in counts.items() if count >= required))


def assess_price_series(
    bars: Iterable[PriceBar],
    reference_sessions: Iterable[date] | None,
    *,
    lookback_sessions: int = DEFAULT_CONTINUITY_LOOKBACK,
) -> PriceSeriesIntegrity:
    """Check a security against a provider-derived trading-session calendar."""
    if lookback_sessions <= 0:
        raise ValueError("Price-series lookback must be positive")
    observed = tuple(sorted({bar.date for bar in bars}))
    if not observed:
        return PriceSeriesIntegrity("missing", 0, 0, (), ())
    if reference_sessions is None:
        return PriceSeriesIntegrity(
            "unverified",
            0,
            len(observed),
            (),
            (),
        )
    reference = tuple(sorted(set(reference_sessions)))
    if not reference:
        return PriceSeriesIntegrity(
            "unverified",
            0,
            len(observed),
            (),
            ("Trading-session continuity could not be checked because the reference is empty",),
        )

    latest = observed[-1]
    first = observed[0]
    eligible = [session for session in reference if first <= session <= latest]
    checked = tuple(eligible[-lookback_sessions:])
    if latest not in reference:
        checked_set = set(checked)
        return PriceSeriesIntegrity(
            "unverified",
            len(checked),
            sum(session in checked_set for session in observed),
            (),
            (
                (
                    f"Latest price date {latest.isoformat()} is absent from the "
                    "provider-derived session reference"
                ),
            ),
        )
    observed_set = set(observed)
    missing = tuple(session for session in checked if session not in observed_set)
    observed_checked = len(checked) - len(missing)
    if not missing:
        return PriceSeriesIntegrity("complete", len(checked), observed_checked, (), ())

    preview = ", ".join(session.isoformat() for session in missing[-5:])
    suffix = "" if len(missing) <= 5 else f" (latest 5 of {len(missing)})"
    return PriceSeriesIntegrity(
        "gapped",
        len(checked),
        observed_checked,
        missing,
        (
            (
                f"Missing {len(missing)} expected trading session(s) in the latest "
                f"{len(checked)}-session integrity window: {preview}{suffix}"
            ),
        ),
    )


def expected_bar_window(
    bars: Iterable[PriceBar],
    reference_sessions: Iterable[date] | None,
    required_bars: int,
) -> tuple[PriceBar, ...] | None:
    """Return an exact trailing session window, or None when history is short or gapped."""
    if required_bars <= 0:
        raise ValueError("Required bar count must be positive")
    ordered = tuple(sorted(bars, key=lambda bar: bar.date))
    if reference_sessions is None:
        return ordered[-required_bars:] if len(ordered) >= required_bars else None
    reference = tuple(sorted(set(reference_sessions)))
    if not ordered or not reference:
        return None
    latest = ordered[-1].date
    if latest not in reference:
        return None
    eligible = [session for session in reference if session <= latest]
    if len(eligible) < required_bars:
        return None
    expected = eligible[-required_bars:]
    by_date = {bar.date: bar for bar in ordered}
    if any(session not in by_date for session in expected):
        return None
    return tuple(by_date[session] for session in expected)
