from __future__ import annotations

import copy
import csv
import hashlib
import json
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from stockrank.models import Security

COMPONENTS = ("growth", "valuation", "quality", "momentum", "risk")
VALID_DIRECTIONS = {"higher", "lower", "lower_positive"}
VALID_SECTORS = {
    "Communication Services",
    "Consumer Discretionary",
    "Consumer Staples",
    "Energy",
    "Financials",
    "Health Care",
    "Industrials",
    "Information Technology",
    "Materials",
    "Real Estate",
    "Utilities",
}
LOCAL_PREFERENCES_PATH = Path("config/preferences.local.toml")
TICKER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,14}$")
KNOWN_MODEL_FINGERPRINTS = {
    "v1.0.0": "a74d77fdd1",
    "v1.1.0": "500e46b066",
}
KNOWN_UNIVERSE_FINGERPRINTS = {"us_diversified_50_v1": "e1e2cd84bf"}
VALID_PROFILES = ("balanced", "growth", "value", "quality", "momentum", "lower_volatility")
VALID_HORIZONS = ("short", "medium", "long")
VALID_RISK_LEVELS = ("conservative", "moderate", "aggressive")


@dataclass(frozen=True)
class Settings:
    root: Path
    raw: dict[str, Any]
    universe: tuple[Security, ...]

    @property
    def runtime_dir(self) -> Path:
        value = Path(self.raw["app"]["runtime_dir"])
        return value if value.is_absolute() else self.root / value

    @property
    def database_path(self) -> Path:
        return self.runtime_dir / "stockrank.sqlite3"

    @property
    def model_version(self) -> str:
        return str(self.raw["scoring"]["model_version"])

    @property
    def provider_name(self) -> str:
        return str(self.raw["provider"]["name"])

    @property
    def component_weights(self) -> dict[str, float]:
        return {key: float(value) for key, value in self.raw["scoring"]["overall"].items()}

    @property
    def metric_weights(self) -> dict[str, dict[str, float]]:
        return {
            component: {
                metric: float(weight) for metric, weight in self.raw["scoring"][component].items()
            }
            for component in COMPONENTS
        }

    @property
    def directions(self) -> dict[str, str]:
        return dict(self.raw["scoring"]["directions"])

    @property
    def sec_user_agent(self) -> str:
        return os.environ.get("SEC_USER_AGENT", "").strip()

    @property
    def sec_cache_dir(self) -> Path:
        return self.runtime_dir / "cache" / "sec"

    @property
    def profile_name(self) -> str:
        return str(self.raw.get("preferences", {}).get("profile", "balanced"))

    @property
    def investment_horizon(self) -> str:
        return str(self.raw.get("preferences", {}).get("investment_horizon", "medium"))

    @property
    def risk_tolerance(self) -> str:
        return str(self.raw.get("preferences", {}).get("risk_tolerance", "moderate"))

    @property
    def local_preferences_path(self) -> Path:
        return self.root / LOCAL_PREFERENCES_PATH

    @property
    def uses_local_preferences(self) -> bool:
        return self.local_preferences_path.is_file()

    @property
    def scoring_fingerprint(self) -> str:
        return scoring_fingerprint(self.raw["scoring"])

    @property
    def universe_fingerprint(self) -> str:
        return universe_fingerprint(self.universe)


def _load_dotenv(path: Path) -> None:
    """Small dependency-free .env loader; existing environment always wins."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    output = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(output.get(key), dict):
            output[key] = _deep_merge(output[key], value)
        else:
            output[key] = copy.deepcopy(value)
    return output


def scoring_fingerprint(scoring: dict[str, Any]) -> str:
    payload = copy.deepcopy(scoring)
    payload.pop("model_version", None)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:10]


def legacy_scoring_fingerprint(scoring: dict[str, Any]) -> str:
    """Identify custom profiles created before calculation versions were fingerprinted."""
    payload = copy.deepcopy(scoring)
    payload.pop("model_version", None)
    payload.pop("calculation_version", None)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:10]


def universe_fingerprint(securities: tuple[Security, ...] | list[Security]) -> str:
    payload = [(value.ticker, value.company, value.sector) for value in securities]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode("utf-8")).hexdigest()[
        :10
    ]


def _read_universe(root: Path, configured_path: str) -> tuple[Security, ...]:
    universe_path = Path(configured_path)
    if not universe_path.is_absolute():
        universe_path = root / universe_path
    universe: list[Security] = []
    with universe_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"ticker", "company", "sector"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("Universe CSV requires ticker, company, and sector columns")
        for row_number, row in enumerate(reader, start=2):
            ticker = (row.get("ticker") or "").strip().upper()
            company = (row.get("company") or "").strip()
            sector = (row.get("sector") or "").strip()
            if not ticker and not company and not sector:
                continue
            if not ticker or not company or not sector:
                raise ValueError(f"Universe CSV row {row_number} is incomplete")
            universe.append(Security(ticker=ticker, company=company, sector=sector))
    return tuple(universe)


def validate_settings(settings: Settings) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    raw = settings.raw
    if settings.profile_name not in VALID_PROFILES:
        errors.append("preferences.profile must be one of: " + ", ".join(VALID_PROFILES))
    if settings.investment_horizon not in VALID_HORIZONS:
        errors.append("preferences.investment_horizon must be one of: " + ", ".join(VALID_HORIZONS))
    if settings.risk_tolerance not in VALID_RISK_LEVELS:
        errors.append("preferences.risk_tolerance must be one of: " + ", ".join(VALID_RISK_LEVELS))
    try:
        ZoneInfo(str(raw["app"]["timezone"]))
    except (KeyError, ZoneInfoNotFoundError):
        errors.append("app.timezone must be a valid IANA timezone")
    try:
        candidate_limit = int(raw["app"]["top_candidate_limit"])
        minimum_score = float(raw["app"]["minimum_candidate_score"])
        minimum_coverage = float(raw["app"]["minimum_overall_coverage"])
        if candidate_limit < 1:
            errors.append("app.top_candidate_limit must be at least 1")
        if not 0 <= minimum_score <= 100:
            errors.append("app.minimum_candidate_score must be between 0 and 100")
        if not 0 <= minimum_coverage <= 1:
            errors.append("app.minimum_overall_coverage must be between 0 and 1")
    except (KeyError, TypeError, ValueError):
        errors.append("App thresholds must be valid numbers")

    if settings.provider_name != "yfinance":
        errors.append("provider.name must be yfinance in the current application version")
    try:
        maximum_price_age = float(raw["provider"]["maximum_price_age_hours"])
        maximum_fundamental_age = float(raw["provider"]["maximum_stale_fundamental_hours"])
        completion_buffer = int(raw["provider"]["daily_bar_completion_buffer_minutes"])
        if maximum_price_age <= 0:
            errors.append("provider.maximum_price_age_hours must be positive")
        if maximum_fundamental_age <= 0:
            errors.append("provider.maximum_stale_fundamental_hours must be positive")
        if not 0 <= completion_buffer <= 180:
            errors.append("provider.daily_bar_completion_buffer_minutes must be between 0 and 180")
    except (KeyError, TypeError, ValueError):
        errors.append("Provider freshness limits must be valid numbers")
    if not settings.model_version.strip():
        errors.append("scoring.model_version must not be empty")
    if not str(settings.raw["scoring"].get("calculation_version", "")).strip():
        errors.append("scoring.calculation_version must not be empty")
    expected_model = KNOWN_MODEL_FINGERPRINTS.get(settings.model_version)
    if expected_model and settings.scoring_fingerprint != expected_model:
        errors.append(
            f"scoring.model_version {settings.model_version} does not match its registered weights"
        )
    if settings.model_version.startswith("custom-") and not settings.model_version.endswith(
        settings.scoring_fingerprint
    ):
        if settings.model_version.endswith(legacy_scoring_fingerprint(settings.raw["scoring"])):
            warnings.append(
                "Custom profile predates calculation-version tracking; rerun `stockrank "
                "configure` before the next report to create a fully versioned model identifier"
            )
        else:
            errors.append("Custom model identifier does not match the effective scoring configuration")
    try:
        overall = settings.component_weights
        if set(overall) != set(COMPONENTS):
            errors.append(
                "scoring.overall must define growth, valuation, quality, momentum, and risk"
            )
        elif (
            any(weight < 0 for weight in overall.values())
            or not abs(sum(overall.values()) - 1) < 1e-6
        ):
            errors.append("scoring.overall weights must be nonnegative and total 1.0")
        metric_weights = settings.metric_weights
        for component, weights in metric_weights.items():
            if not weights:
                errors.append(f"scoring.{component} must contain at least one metric")
            elif (
                any(weight < 0 for weight in weights.values())
                or not abs(sum(weights.values()) - 1) < 1e-6
            ):
                errors.append(f"scoring.{component} weights must be nonnegative and total 1.0")
        metrics = {metric for weights in metric_weights.values() for metric in weights}
        directions = settings.directions
        missing_directions = sorted(metrics - directions.keys())
        if missing_directions:
            errors.append("Missing scoring directions: " + ", ".join(missing_directions))
        invalid_directions = sorted(
            metric for metric in metrics if directions.get(metric) not in VALID_DIRECTIONS
        )
        if invalid_directions:
            errors.append("Invalid scoring directions: " + ", ".join(invalid_directions))
    except (KeyError, TypeError, ValueError):
        errors.append("Scoring configuration is incomplete or contains nonnumeric weights")

    if not settings.universe:
        errors.append("Configured universe is empty")
    tickers = [security.ticker for security in settings.universe]
    duplicates = sorted({ticker for ticker in tickers if tickers.count(ticker) > 1})
    if duplicates:
        errors.append("Configured universe contains duplicate tickers: " + ", ".join(duplicates))
    for security in settings.universe:
        if not TICKER_PATTERN.fullmatch(security.ticker):
            errors.append(f"Invalid ticker format: {security.ticker}")
        if not security.company:
            errors.append(f"{security.ticker}: company name is empty")
        if security.sector not in VALID_SECTORS:
            errors.append(f"{security.ticker}: unsupported sector '{security.sector}'")
    if len(settings.universe) < 10:
        warnings.append("Universes below 10 stocks produce unstable percentile rankings")
    if len(settings.universe) > 250:
        warnings.append("Universes above 250 stocks may be slow and trigger provider rate limits")
    universe_name = str(raw.get("universe", {}).get("name", ""))
    if not universe_name:
        errors.append("universe.name must not be empty")
    expected_universe = KNOWN_UNIVERSE_FINGERPRINTS.get(universe_name)
    if expected_universe and settings.universe_fingerprint != expected_universe:
        errors.append(f"universe.name {universe_name} does not match its registered membership")
    if universe_name.startswith("custom-") and not universe_name.endswith(
        settings.universe_fingerprint
    ):
        errors.append("Custom universe identifier does not match its effective membership")
    return errors, warnings


def load_settings(root: Path | None = None, config_path: Path | None = None) -> Settings:
    root = (root or Path.cwd()).resolve()
    _load_dotenv(root / ".env")
    use_local = config_path is None
    config_path = config_path or root / "config" / "preferences.toml"
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)
    local_path = root / LOCAL_PREFERENCES_PATH
    if use_local and local_path.is_file():
        with local_path.open("rb") as handle:
            raw = _deep_merge(raw, tomllib.load(handle))
    universe = _read_universe(root, str(raw["universe"]["path"]))
    settings = Settings(root=root, raw=raw, universe=universe)
    errors, _ = validate_settings(settings)
    if errors:
        raise ValueError("Invalid configuration: " + "; ".join(errors))
    return settings
