from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from stockrank.storage import Storage

TEXT_FIELDS = (
    "thesis",
    "bull_case",
    "bear_case",
    "valuation",
    "catalysts",
    "risks",
    "what_changed",
    "major_catalyst",
    "major_risk",
)


def validate_research(payload: dict[str, Any], storage: Storage) -> list[str]:
    errors: list[str] = []
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        errors.append("run_id is required")
        return errors
    valid_tickers = {result["ticker"] for result in storage.get_results(run_id)}
    if not valid_tickers:
        errors.append(f"run_id does not exist or has no results: {run_id}")
    companies = payload.get("companies")
    if not isinstance(companies, list):
        errors.append("companies must be a list")
        return errors
    seen: set[str] = set()
    for index, company in enumerate(companies):
        ticker = str(company.get("ticker", "")).upper()
        prefix = f"companies[{index}]"
        if not ticker or ticker not in valid_tickers:
            errors.append(f"{prefix}.ticker is not in this run")
        if ticker in seen:
            errors.append(f"{prefix}.ticker is duplicated")
        seen.add(ticker)
        for field in TEXT_FIELDS:
            value = company.get(field, "")
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{prefix}.{field} must be non-empty text")
        sources = company.get("sources", [])
        if not isinstance(sources, list):
            errors.append(f"{prefix}.sources must be a list")
            continue
        for source_index, source in enumerate(sources):
            source_prefix = f"{prefix}.sources[{source_index}]"
            if not isinstance(source, dict):
                errors.append(f"{source_prefix} must be an object")
                continue
            url = source.get("url", "")
            if urlparse(url).scheme not in {"http", "https"}:
                errors.append(f"{source_prefix}.url must be http(s)")
            for field in ("title", "published_at", "event_at", "source_type"):
                if not source.get(field):
                    errors.append(f"{source_prefix}.{field} is required")
    return errors


def normalize_research(payload: dict[str, Any]) -> dict[str, Any]:
    output = dict(payload)
    output["researched_at"] = output.get("researched_at") or datetime.now(UTC).isoformat()
    return output
