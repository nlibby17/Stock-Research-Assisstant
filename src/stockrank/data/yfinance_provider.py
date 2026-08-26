from __future__ import annotations

import math
import time
from datetime import UTC, date, datetime
from typing import Any

from stockrank.data.base import MarketDataProvider
from stockrank.models import FundamentalSnapshot, PriceBar, Security


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


class YFinanceProvider(MarketDataProvider):
    name = "yfinance"
    freshness_label = "End-of-day/previous-close; unofficial personal-use source; no SLA"

    def __init__(self, retries: int = 2, backoff_seconds: float = 2.0):
        self.retries = max(1, retries)
        self.backoff_seconds = max(0.0, backoff_seconds)

    @staticmethod
    def _module():
        try:
            import yfinance as yf
        except ImportError as error:
            raise RuntimeError(
                "yfinance is not installed. Run: python -m pip install -e ."
            ) from error
        return yf

    def fetch_prices(
        self, securities: list[Security], start: date, end: date
    ) -> tuple[dict[str, list[PriceBar]], list[str]]:
        yf = self._module()
        tickers = [security.ticker for security in securities]
        warnings: list[str] = []
        last_error: Exception | None = None
        frame = None
        for attempt in range(self.retries):
            try:
                frame = yf.download(
                    tickers=tickers,
                    start=start.isoformat(),
                    end=end.isoformat(),
                    auto_adjust=False,
                    actions=False,
                    group_by="ticker",
                    threads=True,
                    progress=False,
                    timeout=20,
                )
                if frame is not None and not frame.empty:
                    break
            except Exception as error:  # noqa: BLE001 - third-party provider exceptions vary.
                last_error = error
            if attempt + 1 < self.retries:
                time.sleep(self.backoff_seconds * (attempt + 1))
        if frame is None or frame.empty:
            detail = f": {last_error}" if last_error else ""
            raise RuntimeError(f"Yahoo price download returned no data{detail}")

        fetched_at = datetime.now(UTC)
        output: dict[str, list[PriceBar]] = {}
        multi = getattr(frame.columns, "nlevels", 1) > 1
        for ticker in tickers:
            try:
                sub = frame[ticker] if multi else frame
            except KeyError:
                warnings.append(f"{ticker}: missing from batch price response")
                continue
            bars: list[PriceBar] = []
            for index, row in sub.iterrows():
                close = _number(row.get("Close"))
                adjusted = _number(row.get("Adj Close")) or close
                if close is None or adjusted is None:
                    continue
                volume_value = _number(row.get("Volume"))
                bars.append(
                    PriceBar(
                        ticker=ticker,
                        date=index.date(),
                        open=_number(row.get("Open")),
                        high=_number(row.get("High")),
                        low=_number(row.get("Low")),
                        close=close,
                        adjusted_close=adjusted,
                        volume=int(volume_value) if volume_value is not None else None,
                        source=self.name,
                        fetched_at=fetched_at,
                    )
                )
            if bars:
                output[ticker] = bars
            else:
                warnings.append(f"{ticker}: no usable daily price bars")
        return output, warnings

    def fetch_fundamental(self, security: Security) -> tuple[FundamentalSnapshot | None, list[str]]:
        yf = self._module()
        warnings: list[str] = []
        info: dict[str, Any] | None = None
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                info = yf.Ticker(security.ticker).get_info()
                if info:
                    break
            except Exception as error:  # noqa: BLE001 - third-party provider exceptions vary.
                last_error = error
            if attempt + 1 < self.retries:
                time.sleep(self.backoff_seconds * (attempt + 1))
        if not info:
            warnings.append(f"{security.ticker}: fundamental summary unavailable ({last_error})")
            return None, warnings

        snapshot = FundamentalSnapshot(
            ticker=security.ticker,
            source=self.name,
            fetched_at=datetime.now(UTC),
            company=info.get("longName") or info.get("shortName") or security.company,
            sector=info.get("sector") or security.sector,
            industry=info.get("industry"),
            market_cap=_number(info.get("marketCap")),
            revenue_growth=_number(info.get("revenueGrowth")),
            earnings_growth=_number(info.get("earningsGrowth")),
            free_cash_flow=_number(info.get("freeCashflow")),
            total_revenue=_number(info.get("totalRevenue")),
            forward_pe=_number(info.get("forwardPE")),
            trailing_pe=_number(info.get("trailingPE")),
            peg_ratio=_number(info.get("pegRatio")),
            price_to_sales=_number(info.get("priceToSalesTrailing12Months")),
            gross_margin=_number(info.get("grossMargins")),
            profit_margin=_number(info.get("profitMargins")),
            return_on_equity=_number(info.get("returnOnEquity")),
            debt_to_equity=_number(info.get("debtToEquity")),
            current_ratio=_number(info.get("currentRatio")),
            beta=_number(info.get("beta")),
            provider_price=_number(info.get("currentPrice") or info.get("regularMarketPrice")),
        )
        populated = sum(
            value is not None
            for field, value in snapshot.to_dict().items()
            if field not in {"ticker", "source", "fetched_at", "company", "sector", "industry"}
        )
        if populated < 5:
            warnings.append(f"{security.ticker}: sparse fundamental summary ({populated} fields)")
        return snapshot, warnings
