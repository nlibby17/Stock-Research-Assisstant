from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from stockrank.models import FundamentalSnapshot, PriceBar, Security


class MarketDataProvider(ABC):
    name: str
    freshness_label: str

    @abstractmethod
    def fetch_prices(
        self, securities: list[Security], start: date, end: date
    ) -> tuple[dict[str, list[PriceBar]], list[str]]:
        """Return normalized bars and non-fatal warnings."""

    @abstractmethod
    def fetch_fundamental(self, security: Security) -> tuple[FundamentalSnapshot | None, list[str]]:
        """Return one summarized fundamental snapshot and warnings."""
