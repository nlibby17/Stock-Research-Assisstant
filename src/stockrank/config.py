from __future__ import annotations

import csv
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stockrank.models import Security

COMPONENTS = ("growth", "valuation", "quality", "momentum", "risk")


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


def load_settings(root: Path | None = None, config_path: Path | None = None) -> Settings:
    root = (root or Path.cwd()).resolve()
    _load_dotenv(root / ".env")
    config_path = config_path or root / "config" / "preferences.toml"
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)
    universe_path = Path(raw["universe"]["path"])
    if not universe_path.is_absolute():
        universe_path = root / universe_path
    universe: list[Security] = []
    with universe_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            universe.append(
                Security(
                    ticker=row["ticker"].strip().upper(),
                    company=row["company"].strip(),
                    sector=row["sector"].strip(),
                )
            )
    if not universe:
        raise ValueError("Configured universe is empty")
    if len({security.ticker for security in universe}) != len(universe):
        raise ValueError("Configured universe contains duplicate tickers")
    return Settings(root=root, raw=raw, universe=tuple(universe))
