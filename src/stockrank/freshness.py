from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from stockrank.models import PriceBar


@dataclass(frozen=True)
class PriceFreshness:
    usable_bars: tuple[PriceBar, ...]
    latest_date: str | None
    latest_fetched_at: str | None
    age_hours: float | None
    status: str
    invalid_bar_count: int
    incomplete_bar_count: int
    future_bar_count: int
    warnings: tuple[str, ...]


def _completed_after(buffer_minutes: int) -> time:
    minutes = 16 * 60 + buffer_minutes
    return time(minutes // 60, minutes % 60)


def assess_price_bars(
    bars: list[PriceBar] | tuple[PriceBar, ...],
    *,
    now: datetime,
    timezone_name: str,
    completion_buffer_minutes: int,
    maximum_age_hours: float,
) -> PriceFreshness:
    """Return completed, positive daily bars and an explicit freshness state."""
    if now.tzinfo is None:
        raise ValueError("Price freshness time must include a timezone")
    timezone = ZoneInfo(timezone_name)
    now_utc = now.astimezone(UTC)
    local_today = now_utc.astimezone(timezone).date()
    completed_after = _completed_after(completion_buffer_minutes)
    usable: list[PriceBar] = []
    invalid_count = 0
    incomplete_count = 0
    future_count = 0
    for bar in sorted(bars, key=lambda value: value.date):
        if (
            not math.isfinite(bar.close)
            or not math.isfinite(bar.adjusted_close)
            or bar.close <= 0
            or bar.adjusted_close <= 0
        ):
            invalid_count += 1
            continue
        if bar.date > local_today:
            future_count += 1
            continue
        fetched_local = bar.fetched_at.astimezone(timezone)
        if bar.date == fetched_local.date() and fetched_local.time() < completed_after:
            incomplete_count += 1
            continue
        usable.append(bar)

    warnings: list[str] = []
    if invalid_count:
        warnings.append(f"Ignored {invalid_count} nonpositive or invalid daily price bar(s)")
    if incomplete_count:
        warnings.append(
            f"Ignored {incomplete_count} current-session daily bar(s) fetched before "
            f"{completed_after.strftime('%H:%M')} {timezone_name}"
        )
    if future_count:
        warnings.append(f"Ignored {future_count} future-dated daily price bar(s)")
    if not usable:
        return PriceFreshness(
            usable_bars=(),
            latest_date=None,
            latest_fetched_at=None,
            age_hours=None,
            status="missing",
            invalid_bar_count=invalid_count,
            incomplete_bar_count=incomplete_count,
            future_bar_count=future_count,
            warnings=tuple(warnings),
        )

    latest = usable[-1]
    assumed_close = datetime.combine(latest.date, time(16, 0), timezone).astimezone(UTC)
    age_hours = max(0.0, (now_utc - assumed_close).total_seconds() / 3600)
    if age_hours > maximum_age_hours:
        warnings.append(
            f"Latest completed price is {age_hours:.1f} hours old, above the "
            f"{maximum_age_hours:g}-hour limit"
        )
        status = "stale"
        accepted: tuple[PriceBar, ...] = ()
    else:
        status = "usable"
        accepted = tuple(usable)
    return PriceFreshness(
        usable_bars=accepted,
        latest_date=latest.date.isoformat(),
        latest_fetched_at=latest.fetched_at.isoformat(),
        age_hours=age_hours,
        status=status,
        invalid_bar_count=invalid_count,
        incomplete_bar_count=incomplete_count,
        future_bar_count=future_count,
        warnings=tuple(warnings),
    )
