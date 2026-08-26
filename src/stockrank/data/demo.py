from __future__ import annotations

import hashlib
import math
import random
from datetime import UTC, date, datetime, timedelta

from stockrank.data.base import MarketDataProvider
from stockrank.models import FundamentalSnapshot, PriceBar, Security


class DemoProvider(MarketDataProvider):
    """Deterministic synthetic provider. Never selected implicitly."""

    name = "demo-synthetic"
    freshness_label = "Synthetic demonstration data; not market data"

    @staticmethod
    def _seed(ticker: str) -> int:
        return int(hashlib.sha256(ticker.encode("ascii")).hexdigest()[:8], 16)

    def fetch_prices(
        self, securities: list[Security], start: date, end: date
    ) -> tuple[dict[str, list[PriceBar]], list[str]]:
        output: dict[str, list[PriceBar]] = {}
        fetched_at = datetime.now(UTC)
        for security in securities:
            randomizer = random.Random(self._seed(security.ticker))
            price = 35.0 + (self._seed(security.ticker) % 220)
            drift = ((self._seed(security.ticker) % 21) - 6) / 100_000
            current = start
            bars: list[PriceBar] = []
            while current < end:
                if current.weekday() < 5:
                    daily = drift + randomizer.gauss(
                        0, 0.013 + (self._seed(security.ticker) % 8) / 1000
                    )
                    open_price = price
                    price = max(2.0, price * math.exp(daily))
                    high = max(open_price, price) * (1 + randomizer.random() * 0.01)
                    low = min(open_price, price) * (1 - randomizer.random() * 0.01)
                    volume = int(500_000 + randomizer.random() * 12_000_000)
                    bars.append(
                        PriceBar(
                            ticker=security.ticker,
                            date=current,
                            open=open_price,
                            high=high,
                            low=low,
                            close=price,
                            adjusted_close=price,
                            volume=volume,
                            source=self.name,
                            fetched_at=fetched_at,
                        )
                    )
                current += timedelta(days=1)
            output[security.ticker] = bars
        return output, ["Explicit demo mode: every value is synthetic and unsuitable for investing"]

    def fetch_fundamental(self, security: Security) -> tuple[FundamentalSnapshot | None, list[str]]:
        seed = self._seed(security.ticker)
        randomizer = random.Random(seed + 17)
        market_cap = (8 + seed % 900) * 1_000_000_000.0
        revenue = market_cap * randomizer.uniform(0.15, 1.2)
        margin = randomizer.uniform(-0.03, 0.32)
        free_cash_flow = revenue * max(-0.05, margin - randomizer.uniform(0.01, 0.08))
        return (
            FundamentalSnapshot(
                ticker=security.ticker,
                source=self.name,
                fetched_at=datetime.now(UTC),
                company=security.company,
                sector=security.sector,
                industry="Synthetic",
                market_cap=market_cap,
                revenue_growth=randomizer.uniform(-0.08, 0.38),
                earnings_growth=randomizer.uniform(-0.20, 0.55),
                free_cash_flow=free_cash_flow,
                total_revenue=revenue,
                forward_pe=randomizer.uniform(8, 48),
                trailing_pe=randomizer.uniform(10, 60),
                peg_ratio=randomizer.uniform(0.6, 3.2),
                price_to_sales=randomizer.uniform(0.8, 15),
                gross_margin=randomizer.uniform(0.18, 0.82),
                profit_margin=margin,
                return_on_equity=randomizer.uniform(-0.05, 0.55),
                debt_to_equity=randomizer.uniform(5, 240),
                current_ratio=randomizer.uniform(0.7, 3.2),
                beta=randomizer.uniform(0.55, 1.9),
            ),
            [],
        )
