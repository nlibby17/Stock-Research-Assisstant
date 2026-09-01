from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any

from stockrank.models import SecCompanyFactsRefreshState, SecFiling

REFRESH_CLOCK_SKEW_TOLERANCE = timedelta(minutes=5)


@dataclass(frozen=True)
class CompanyFactsRefreshPolicy:
    full_refresh_hours: float = 168.0
    recent_filing_window_hours: float = 48.0
    recent_filing_retry_hours: float = 6.0

    def __post_init__(self) -> None:
        if self.full_refresh_hours <= 0:
            raise ValueError("SEC Company Facts full refresh interval must be positive")
        if self.recent_filing_window_hours < 0:
            raise ValueError("SEC Company Facts recent filing window cannot be negative")
        if self.recent_filing_retry_hours <= 0:
            raise ValueError("SEC Company Facts recent filing retry interval must be positive")


@dataclass(frozen=True)
class CompanyFactsRefreshDecision:
    refresh: bool
    reason: str
    bypass_raw_cache: bool = False


def _fingerprint(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def identity_fingerprint(ciks: Iterable[str]) -> str:
    return _fingerprint(sorted(set(ciks)))


def filing_fingerprint(filings: Iterable[SecFiling]) -> str:
    rows = sorted(
        (
            filing.cik,
            filing.accession_number,
            filing.form,
            filing.filing_date.isoformat(),
            filing.accepted_at.isoformat() if filing.accepted_at else "",
        )
        for filing in filings
    )
    return _fingerprint(rows)


def companyfacts_config_fingerprint(
    *,
    history_years: int,
    forms: Iterable[str],
    concepts: Iterable[Any],
) -> str:
    concept_rows = []
    for concept in concepts:
        concept_rows.append(
            {
                "canonical_name": str(concept.canonical_name),
                "period_type": str(concept.period_type),
                "units": list(concept.units),
                "members": [list(member) for member in concept.members],
            }
        )
    return _fingerprint(
        {
            "history_years": history_years,
            "forms": sorted({str(form).upper() for form in forms}),
            "concepts": concept_rows,
        }
    )


def latest_filing_at(filings: Iterable[SecFiling]) -> datetime | None:
    values = []
    for filing in filings:
        values.append(
            filing.accepted_at
            or datetime.combine(filing.availability_date, time.min, tzinfo=UTC)
        )
    return max(values) if values else None


def decide_companyfacts_refresh(
    *,
    now: datetime,
    force: bool,
    has_local_facts: bool,
    state: SecCompanyFactsRefreshState | None,
    current_identity_fingerprint: str,
    current_filing_fingerprint: str,
    current_config_fingerprint: str,
    current_latest_filing_at: datetime | None,
    policy: CompanyFactsRefreshPolicy,
) -> CompanyFactsRefreshDecision:
    if now.tzinfo is None:
        raise ValueError("SEC Company Facts refresh time must include a timezone")
    now = now.astimezone(UTC)
    if force:
        return CompanyFactsRefreshDecision(True, "forced refresh", True)
    if not has_local_facts:
        return CompanyFactsRefreshDecision(True, "missing local facts")
    if state is None:
        return CompanyFactsRefreshDecision(True, "initialize adaptive refresh state")
    if state.identity_fingerprint != current_identity_fingerprint:
        return CompanyFactsRefreshDecision(True, "SEC identity changed")
    if state.config_fingerprint != current_config_fingerprint:
        return CompanyFactsRefreshDecision(True, "Company Facts configuration changed")
    if state.filing_fingerprint != current_filing_fingerprint:
        return CompanyFactsRefreshDecision(True, "new or changed SEC filing", True)

    refreshed_at = _validated_refresh_timestamp(
        state.last_successful_refresh_at,
        now=now,
        invalid_reason="invalid refresh timestamp",
        future_reason="future refresh timestamp",
    )
    if isinstance(refreshed_at, CompanyFactsRefreshDecision):
        return refreshed_at
    stored_latest_filing_at = _validated_optional_refresh_timestamp(
        state.latest_filing_at,
        now=now,
        invalid_reason="invalid stored latest filing timestamp",
        future_reason="future stored latest filing timestamp",
    )
    if isinstance(stored_latest_filing_at, CompanyFactsRefreshDecision):
        return stored_latest_filing_at
    current_latest_filing_at = _validated_optional_refresh_timestamp(
        current_latest_filing_at,
        now=now,
        invalid_reason="invalid latest filing timestamp",
        future_reason="future latest filing timestamp",
    )
    if isinstance(current_latest_filing_at, CompanyFactsRefreshDecision):
        return current_latest_filing_at

    age = now - refreshed_at
    if current_latest_filing_at is not None:
        filing_age = now - current_latest_filing_at
        if (
            timedelta(0) <= filing_age <= timedelta(hours=policy.recent_filing_window_hours)
            and age >= timedelta(hours=policy.recent_filing_retry_hours)
        ):
            return CompanyFactsRefreshDecision(True, "recent filing follow-up", True)
    if age >= timedelta(hours=policy.full_refresh_hours):
        return CompanyFactsRefreshDecision(True, "periodic safety refresh", True)
    return CompanyFactsRefreshDecision(False, "unchanged filings; reused local facts")


def _validated_refresh_timestamp(
    value: datetime,
    *,
    now: datetime,
    invalid_reason: str,
    future_reason: str,
) -> datetime | CompanyFactsRefreshDecision:
    if value.tzinfo is None or value.utcoffset() is None:
        return CompanyFactsRefreshDecision(True, invalid_reason, True)
    normalized = value.astimezone(UTC)
    if normalized > now + REFRESH_CLOCK_SKEW_TOLERANCE:
        return CompanyFactsRefreshDecision(True, future_reason, True)
    return normalized


def _validated_optional_refresh_timestamp(
    value: datetime | None,
    *,
    now: datetime,
    invalid_reason: str,
    future_reason: str,
) -> datetime | CompanyFactsRefreshDecision | None:
    if value is None:
        return None
    return _validated_refresh_timestamp(
        value,
        now=now,
        invalid_reason=invalid_reason,
        future_reason=future_reason,
    )
