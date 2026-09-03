from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from stockrank.models import SecCompanyFact


@dataclass(frozen=True)
class SecCompanyFactVintage:
    fact_key: str
    observation_key: str
    observed_at: datetime
    fact: SecCompanyFact


def reconstruct_sec_company_fact(
    base_fact: SecCompanyFact,
    payload: Mapping[str, Any],
    *,
    observed_at: datetime,
) -> SecCompanyFact:
    """Restore calculation-relevant fact fields from one immutable observation."""
    if observed_at.tzinfo is None:
        raise ValueError("Stored SEC fact observation time must include a timezone")
    return replace(
        base_fact,
        concept_priority=int(payload["concept_priority"]),
        period_type=str(payload["period_type"]),
        value=Decimal(str(payload["value"])),
        fiscal_year=(int(payload["fiscal_year"]) if payload["fiscal_year"] is not None else None),
        fiscal_period=(
            str(payload["fiscal_period"]) if payload["fiscal_period"] is not None else None
        ),
        form=str(payload["form"]),
        filed_date=date.fromisoformat(str(payload["filed_date"])),
        frame=str(payload["frame"]) if payload["frame"] is not None else None,
        accepted_at=(
            datetime.fromisoformat(str(payload["accepted_at"]))
            if payload["accepted_at"] is not None
            else None
        ),
        availability_date=date.fromisoformat(str(payload["availability_date"])),
        availability_precision=str(payload["availability_precision"]),
        fetched_at=observed_at,
    )


def select_sec_company_fact_vintages(
    vintages: Iterable[SecCompanyFactVintage],
    *,
    observed_at_or_before: datetime,
) -> tuple[SecCompanyFact, ...]:
    """Select the latest known payload for each stable fact key at a cutoff."""
    if observed_at_or_before.tzinfo is None:
        raise ValueError("SEC fact observation cutoff must include a timezone")
    cutoff = observed_at_or_before.astimezone(UTC)
    selected: dict[str, SecCompanyFactVintage] = {}
    for vintage in vintages:
        if vintage.observed_at.tzinfo is None:
            raise ValueError("Stored SEC fact observation time must include a timezone")
        observed_at = vintage.observed_at.astimezone(UTC)
        if observed_at > cutoff:
            continue
        current = selected.get(vintage.fact_key)
        rank = (observed_at, vintage.observation_key)
        if current is None or rank > (
            current.observed_at.astimezone(UTC),
            current.observation_key,
        ):
            selected[vintage.fact_key] = vintage
    return tuple(
        sorted(
            (vintage.fact for vintage in selected.values()),
            key=lambda fact: (fact.end_date, fact.filed_date, fact.accession_number),
            reverse=True,
        )
    )
