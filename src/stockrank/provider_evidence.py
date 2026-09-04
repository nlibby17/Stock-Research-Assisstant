from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class ProductionRunEvidence:
    run_id: str
    status: str
    provider: str
    universe_name: str
    completed_at: datetime | None
    as_of: date
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ProductionResultEvidence:
    ticker: str
    price_as_of: date | None


@dataclass(frozen=True)
class SecFormulaContractEvidence:
    ticker: str
    formula_version: str | None
    formula_manifest: dict[str, Any] | None


@dataclass(frozen=True)
class PromotionEvidence:
    analysis_run_id: str | None
    evidence_date: date | None
    qualified: bool
    reason: str
    formula_contracts: tuple[dict[str, Any], ...]


def _canonical_copy(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, sort_keys=True))


def _formula_contract_set(
    evidence: Iterable[SecFormulaContractEvidence],
) -> tuple[dict[str, Any], ...]:
    unique: dict[str, dict[str, Any]] = {}
    for item in evidence:
        record = {
            "formula_version": item.formula_version,
            "formula_manifest": (
                _canonical_copy(item.formula_manifest)
                if item.formula_manifest is not None
                else None
            ),
        }
        key = json.dumps(record, sort_keys=True, separators=(",", ":"))
        unique[key] = record
    return tuple(unique[key] for key in sorted(unique))


def evaluate_promotion_evidence(
    *,
    full_universe: bool,
    comparison_status: str,
    comparison_as_of: datetime,
    stale_rows: int,
    production_run: ProductionRunEvidence | None,
    production_results: Iterable[ProductionResultEvidence],
    expected_provider: str,
    expected_universe_name: str,
    expected_tickers: frozenset[str],
    formula_contract_evidence: Iterable[SecFormulaContractEvidence],
    supported_formula_version: str,
    supported_formula_manifest: dict[str, Any],
    max_link_age_hours: int,
) -> PromotionEvidence:
    """Evaluate one provider-shadow run without reading or writing external state."""
    contract_values = tuple(formula_contract_evidence)
    contracts_by_ticker: dict[str, SecFormulaContractEvidence] = {}
    for contract in contract_values:
        if contract.ticker in contracts_by_ticker:
            raise ValueError(f"Duplicate SEC formula contract evidence for {contract.ticker}")
        contracts_by_ticker[contract.ticker] = contract
    unexpected_tickers = sorted(contracts_by_ticker.keys() - expected_tickers)
    if unexpected_tickers:
        raise ValueError(
            "Unexpected SEC formula contract evidence for " + ", ".join(unexpected_tickers)
        )
    formula_contracts = _formula_contract_set(contract_values)

    def result(
        reason: str,
        *,
        analysis_run_id: str | None = None,
        evidence_date: date | None = None,
        qualified: bool = False,
    ) -> PromotionEvidence:
        return PromotionEvidence(
            analysis_run_id=analysis_run_id,
            evidence_date=evidence_date,
            qualified=qualified,
            reason=reason,
            formula_contracts=formula_contracts,
        )

    if not full_universe:
        return result("Partial-universe comparisons do not qualify as promotion evidence")
    if production_run is None:
        return result("No production analysis run exists")
    if production_run.status != "completed":
        return result(f"Latest production analysis run is {production_run.status}, not completed")
    if production_run.provider != expected_provider:
        return result(
            f"Latest analysis provider is {production_run.provider}, not {expected_provider}"
        )
    if production_run.universe_name != expected_universe_name:
        return result("Latest analysis used a different universe version")
    if production_run.completed_at is None:
        return result("Latest production analysis has no completion time")
    if any(warning.startswith("Price refresh failed") for warning in production_run.warnings):
        return result("Linked production run used cached prices after a refresh failure")

    analysis_age = comparison_as_of - production_run.completed_at.astimezone(UTC)
    if analysis_age < timedelta(0):
        return result("Latest production analysis completed after this comparison")
    if analysis_age > timedelta(hours=max_link_age_hours):
        return result(
            f"Latest production analysis is too old to link safely (>{max_link_age_hours} hours)"
        )

    results = tuple(production_results)
    actual_tickers = {value.ticker for value in results}
    if actual_tickers != expected_tickers:
        return result("Linked production run does not contain the exact universe")
    if any(value.price_as_of is None for value in results):
        return result("Linked production run has missing price dates")
    price_dates = {value.price_as_of for value in results}
    if len(price_dates) != 1:
        return result("Linked production run has mixed market-data dates")
    evidence_date = next(iter(price_dates))
    if evidence_date != production_run.as_of:
        return result("Production run as-of date does not match its price data")

    linked = {
        "analysis_run_id": production_run.run_id,
        "evidence_date": evidence_date,
    }
    missing_contracts = sorted(
        ticker
        for ticker in expected_tickers
        if ticker not in contracts_by_ticker
        or contracts_by_ticker[ticker].formula_version is None
        or contracts_by_ticker[ticker].formula_manifest is None
    )
    if missing_contracts:
        return result(
            "Missing SEC formula contract for "
            f"{len(missing_contracts)}/{len(expected_tickers)} comparison securities: "
            + ", ".join(missing_contracts),
            **linked,
        )
    if len(formula_contracts) != 1:
        return result(
            "Mixed SEC formula contracts across comparison securities: "
            f"{len(formula_contracts)} distinct contracts",
            **linked,
        )
    actual_contract = formula_contracts[0]
    supported_manifest = _canonical_copy(supported_formula_manifest)
    if (
        actual_contract["formula_version"] != supported_formula_version
        or actual_contract["formula_manifest"] != supported_manifest
    ):
        return result(
            f"Unsupported SEC formula contract: {actual_contract['formula_version']}",
            **linked,
        )
    if stale_rows:
        return result(f"Comparison contains {stale_rows} stale provider rows", **linked)
    if comparison_status != "complete":
        return result("Comparison rows are incomplete", **linked)
    return result(
        "Qualified: complete full-universe comparison linked to a consistent "
        "production market-data date and supported SEC formula contract",
        qualified=True,
        **linked,
    )
