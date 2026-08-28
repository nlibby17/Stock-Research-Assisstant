from __future__ import annotations

import csv
import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from stockrank.config import (
    COMPONENTS,
    LOCAL_PREFERENCES_PATH,
    VALID_HORIZONS,
    VALID_PROFILES,
    VALID_RISK_LEVELS,
    VALID_SECTORS,
    scoring_fingerprint,
    universe_fingerprint,
)
from stockrank.data import YFinanceProvider
from stockrank.models import Security

LOCAL_UNIVERSE_PATH = Path("config/universe.local.csv")
PROFILE_NAMES = VALID_PROFILES
HORIZONS = VALID_HORIZONS
RISK_LEVELS = VALID_RISK_LEVELS

PROFILE_WEIGHTS: dict[str, dict[str, float]] = {
    "balanced": {
        "growth": 0.25,
        "valuation": 0.20,
        "quality": 0.25,
        "momentum": 0.20,
        "risk": 0.10,
    },
    "growth": {"growth": 0.40, "valuation": 0.10, "quality": 0.25, "momentum": 0.15, "risk": 0.10},
    "value": {"growth": 0.15, "valuation": 0.40, "quality": 0.25, "momentum": 0.10, "risk": 0.10},
    "quality": {"growth": 0.20, "valuation": 0.15, "quality": 0.40, "momentum": 0.10, "risk": 0.15},
    "momentum": {
        "growth": 0.20,
        "valuation": 0.10,
        "quality": 0.15,
        "momentum": 0.40,
        "risk": 0.15,
    },
    "lower_volatility": {
        "growth": 0.15,
        "valuation": 0.15,
        "quality": 0.30,
        "momentum": 0.10,
        "risk": 0.30,
    },
}

RISK_MULTIPLIERS = {
    "conservative": {
        "growth": 0.85,
        "valuation": 1.10,
        "quality": 1.15,
        "momentum": 0.80,
        "risk": 1.50,
    },
    "moderate": {component: 1.0 for component in COMPONENTS},
    "aggressive": {
        "growth": 1.15,
        "valuation": 0.90,
        "quality": 0.90,
        "momentum": 1.20,
        "risk": 0.60,
    },
}

HORIZON_MULTIPLIERS = {
    "short": {"growth": 0.85, "valuation": 0.90, "quality": 0.85, "momentum": 1.35, "risk": 1.00},
    "medium": {component: 1.0 for component in COMPONENTS},
    "long": {"growth": 1.15, "valuation": 1.00, "quality": 1.15, "momentum": 0.60, "risk": 1.05},
}

YAHOO_SECTOR_MAP = {
    "Basic Materials": "Materials",
    "Communication Services": "Communication Services",
    "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Defensive": "Consumer Staples",
    "Energy": "Energy",
    "Financial Services": "Financials",
    "Healthcare": "Health Care",
    "Industrials": "Industrials",
    "Real Estate": "Real Estate",
    "Technology": "Information Technology",
    "Utilities": "Utilities",
}


def _next_backup_path(path: Path) -> Path:
    index = 0
    while True:
        suffix = ".bak" if index == 0 else f".bak.{index}"
        candidate = path.with_name(path.name + suffix)
        if not candidate.exists():
            return candidate
        index += 1


def _replace_preserving_previous(temporary: Path, path: Path) -> None:
    if path.exists():
        os.replace(path, _next_backup_path(path))
    os.replace(temporary, path)


def profile_weights(profile: str, risk: str, horizon: str) -> dict[str, float]:
    if profile not in PROFILE_WEIGHTS:
        raise ValueError("Unknown profile: " + profile)
    if risk not in RISK_LEVELS:
        raise ValueError("Unknown risk tolerance: " + risk)
    if horizon not in HORIZONS:
        raise ValueError("Unknown investment horizon: " + horizon)
    adjusted = {
        component: (
            PROFILE_WEIGHTS[profile][component]
            * RISK_MULTIPLIERS[risk][component]
            * HORIZON_MULTIPLIERS[horizon][component]
        )
        for component in COMPONENTS
    }
    total = sum(adjusted.values())
    return {component: adjusted[component] / total for component in COMPONENTS}


def parse_component_weights(value: str) -> dict[str, float]:
    try:
        weights = {
            key.strip(): float(raw.strip())
            for item in value.split(",")
            for key, raw in [item.split("=", 1)]
        }
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Weights must look like growth=.25,valuation=.20,quality=.25,momentum=.20,risk=.10"
        ) from exc
    if set(weights) != set(COMPONENTS):
        raise ValueError("Custom weights must define exactly: " + ", ".join(COMPONENTS))
    if any(weight < 0 for weight in weights.values()) or not abs(sum(weights.values()) - 1) < 1e-6:
        raise ValueError("Custom weights must be nonnegative and total 1.0")
    return weights


def model_identifier(profile: str, scoring: dict[str, Any], weights: dict[str, float]) -> str:
    payload = dict(scoring)
    payload.pop("model_version", None)
    payload["overall"] = weights
    digest = scoring_fingerprint(payload)
    return f"custom-{profile}-{digest}"


def universe_identifier(securities: Iterable[Security]) -> str:
    values = list(securities)
    digest = universe_fingerprint(values)
    return f"custom-{len(values)}-{digest}"


def parse_tickers(value: str) -> list[str]:
    tickers = [item.strip().upper() for item in value.replace("\n", ",").split(",")]
    return list(dict.fromkeys(ticker for ticker in tickers if ticker))


def read_universe_input(path: Path) -> list[Security]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "ticker" not in reader.fieldnames:
            raise ValueError("Universe input CSV requires a ticker column")
        output = []
        for row in reader:
            ticker = (row.get("ticker") or "").strip().upper()
            if not ticker:
                continue
            output.append(
                Security(
                    ticker=ticker,
                    company=(row.get("company") or "").strip(),
                    sector=(row.get("sector") or "").strip(),
                )
            )
    return output


def enrich_universe(
    securities: Iterable[Security], provider: YFinanceProvider | None = None
) -> tuple[list[Security], list[str]]:
    provider = provider or YFinanceProvider()
    output: list[Security] = []
    warnings: list[str] = []
    for security in securities:
        if security.company and security.sector in VALID_SECTORS:
            output.append(security)
            continue
        snapshot, provider_warnings = provider.fetch_fundamental(security)
        warnings.extend(provider_warnings)
        yahoo_sector = snapshot.sector if snapshot else None
        sector = (
            security.sector
            if security.sector in VALID_SECTORS
            else YAHOO_SECTOR_MAP.get(security.sector, "")
            or YAHOO_SECTOR_MAP.get(yahoo_sector or "", "")
        )
        company = security.company or (snapshot.company if snapshot else None) or ""
        output.append(Security(security.ticker, company, sector))
        if not company or sector not in VALID_SECTORS:
            warnings.append(
                f"{security.ticker}: company/sector could not be validated; use a CSV with manual values"
            )
    return output, warnings


def write_local_universe(root: Path, securities: Iterable[Security]) -> Path:
    path = root / LOCAL_UNIVERSE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".csv.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("ticker", "company", "sector"))
        for security in securities:
            writer.writerow((security.ticker, security.company, security.sector))
    _replace_preserving_previous(temporary, path)
    return path


def write_local_preferences(
    root: Path,
    *,
    profile: str,
    horizon: str,
    risk: str,
    weights: dict[str, float],
    model_version: str,
    universe_name: str,
    universe_path: str,
    candidate_limit: int,
    minimum_score: float,
    minimum_coverage: float,
) -> Path:
    path = root / LOCAL_PREFERENCES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    weight_lines = "\n".join(f"{component} = {weights[component]:.12f}" for component in COMPONENTS)
    content = f"""# Personal settings generated by `stockrank configure`.
# This file is local to this computer and intentionally ignored by Git.

[app]
top_candidate_limit = {candidate_limit}
minimum_candidate_score = {minimum_score:.6g}
minimum_overall_coverage = {minimum_coverage:.6g}

[universe]
name = {json.dumps(universe_name)}
path = {json.dumps(universe_path)}
maintenance_mode = "user_approved_manual"

[preferences]
profile = {json.dumps(profile)}
investment_horizon = {json.dumps(horizon)}
risk_tolerance = {json.dumps(risk)}

[scoring]
model_version = {json.dumps(model_version)}

[scoring.overall]
{weight_lines}
"""
    temporary = path.with_suffix(".toml.tmp")
    temporary.write_text(content, encoding="utf-8")
    _replace_preserving_previous(temporary, path)
    return path


def reset_local_customization(root: Path) -> list[Path]:
    backups: list[Path] = []
    for relative in (LOCAL_PREFERENCES_PATH, LOCAL_UNIVERSE_PATH):
        path = root / relative
        if not path.exists():
            continue
        backup = _next_backup_path(path)
        os.replace(path, backup)
        backups.append(backup)
    return backups
