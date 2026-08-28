from __future__ import annotations

import hashlib
import json
import logging
import logging.handlers
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from stockrank.config import Settings
from stockrank.data import DemoProvider, MarketDataProvider, YFinanceProvider
from stockrank.metrics import apply_sector_conventions, calculate_metrics
from stockrank.models import AnalysisRun, Security
from stockrank.reporting import write_report_bundle
from stockrank.scoring import score_universe
from stockrank.storage import Storage

MARKET_PROXIES = (
    Security("SPY", "S&P 500 ETF", "Broad market"),
    Security("QQQ", "Nasdaq-100 ETF", "Growth/technology"),
    Security("IWM", "Russell 2000 ETF", "Small-cap"),
    Security("VTV", "Vanguard Value ETF", "Value"),
    Security("XLK", "Technology Select Sector SPDR", "Technology"),
    Security("XLF", "Financial Select Sector SPDR", "Financials"),
    Security("XLE", "Energy Select Sector SPDR", "Energy"),
    Security("XLV", "Health Care Select Sector SPDR", "Health care"),
)


def _analysis_status(usable_prices: int, universe_size: int) -> str:
    if usable_prices == universe_size:
        return "completed"
    return "partial" if usable_prices else "failed"


def configure_logging(settings: Settings) -> logging.Logger:
    log_dir = settings.runtime_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("stockrank")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.handlers.RotatingFileHandler(
            log_dir / "stockrank.log",
            maxBytes=int(settings.raw["retention"]["log_max_bytes"]),
            backupCount=int(settings.raw["retention"]["log_backup_count"]),
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def provider_for(settings: Settings, demo: bool = False) -> MarketDataProvider:
    if demo:
        return DemoProvider()
    if settings.provider_name != "yfinance":
        raise ValueError(f"Unsupported provider: {settings.provider_name}")
    raw = settings.raw["provider"]
    return YFinanceProvider(
        retries=int(raw["request_retries"]),
        backoff_seconds=float(raw["retry_backoff_seconds"]),
    )


def _price_cache_key(provider: MarketDataProvider, securities: list[Security]) -> str:
    tickers = ",".join(sorted(security.ticker for security in securities))
    digest = hashlib.sha256(tickers.encode("ascii")).hexdigest()[:16]
    return f"prices:{provider.name}:{digest}"


def _market_context(storage: Storage, provider: MarketDataProvider) -> dict[str, Any]:
    context: dict[str, Any] = {}
    for proxy in MARKET_PROXIES:
        bars = storage.get_price_bars(proxy.ticker, provider.name)
        metrics, warnings = calculate_metrics(bars, None)
        context[proxy.ticker] = {
            "name": proxy.company,
            "category": proxy.sector,
            "price": metrics["latest_price"],
            "price_as_of": bars[-1].date.isoformat() if bars else None,
            "momentum_1m": metrics["momentum_1m"],
            "momentum_3m": metrics["momentum_3m"],
            "warnings": [warning for warning in warnings if "Fundamental" not in warning],
        }
    return context


def run_analysis(
    settings: Settings,
    *,
    demo: bool = False,
    force: bool = False,
) -> tuple[str, Path, list[str]]:
    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    (settings.runtime_dir / "reports").mkdir(parents=True, exist_ok=True)
    (settings.runtime_dir / "tmp").mkdir(parents=True, exist_ok=True)
    logger = configure_logging(settings)
    storage = Storage(settings.database_path)
    storage.initialize()
    provider = provider_for(settings, demo=demo)
    warnings: list[str] = []
    if demo:
        warnings.append("Explicit demo mode: every value is synthetic and unsuitable for investing")
    started_at = datetime.now(UTC)
    logger.info("Starting analysis provider=%s force=%s", provider.name, force)

    all_securities = list(settings.universe) + list(MARKET_PROXIES)
    cache_key = _price_cache_key(provider, all_securities)
    price_ttl = float(settings.raw["provider"]["price_cache_ttl_hours"])
    if force or not storage.cache_is_fresh(cache_key):
        history_days = int(settings.raw["provider"]["price_history_days"])
        try:
            today = datetime.now(UTC).date()
            price_data, price_warnings = provider.fetch_prices(
                all_securities,
                today - timedelta(days=history_days),
                today + timedelta(days=1),
            )
            warnings.extend(price_warnings)
            row_count = storage.upsert_price_bars(
                bar for bars in price_data.values() for bar in bars
            )
            storage.set_cache_status(cache_key, provider.name, price_ttl, "ok", f"{row_count} bars")
            logger.info("Stored %s normalized price bars", row_count)
        except Exception as error:
            message = f"Price refresh failed; cached bars will be used when present: {error}"
            warnings.append(message)
            storage.set_cache_status(cache_key, provider.name, 0, "error", str(error))
            logger.exception("Price refresh failed")

    fundamentals: dict[str, Any] = {}
    fundamental_ttl = float(settings.raw["provider"]["fundamental_cache_ttl_hours"])
    for security in settings.universe:
        cached = (
            None
            if force
            else storage.get_fundamental(security.ticker, provider.name, fresh_only=True)
        )
        if cached:
            fundamentals[security.ticker] = cached
            continue
        try:
            snapshot, fundamental_warnings = provider.fetch_fundamental(security)
        except Exception as error:  # noqa: BLE001 - preserve per-ticker cache fallback.
            snapshot = None
            fundamental_warnings = [f"{security.ticker}: fundamental refresh failed ({error})"]
        warnings.extend(fundamental_warnings)
        if snapshot:
            storage.put_fundamental(snapshot, fundamental_ttl)
            fundamentals[security.ticker] = snapshot
        else:
            stale = storage.get_fundamental(security.ticker, provider.name, fresh_only=False)
            if stale:
                fundamentals[security.ticker] = stale
                warnings.append(
                    f"{security.ticker}: using stale fundamentals fetched {stale.fetched_at.isoformat()}"
                )

    inputs: dict[str, dict[str, Any]] = {}
    all_price_dates: list[date] = []
    for security in settings.universe:
        bars = storage.get_price_bars(security.ticker, provider.name)
        if bars:
            all_price_dates.append(bars[-1].date)
        metrics, metric_warnings = calculate_metrics(bars, fundamentals.get(security.ticker))
        metrics, sector_warnings = apply_sector_conventions(metrics, security.sector)
        metric_warnings.extend(sector_warnings)
        inputs[security.ticker] = {
            "company": (
                fundamentals[security.ticker].company
                if fundamentals.get(security.ticker) and fundamentals[security.ticker].company
                else security.company
            ),
            "sector": security.sector,
            "price_as_of": bars[-1].date.isoformat() if bars else None,
            "metrics": metrics,
            "warnings": metric_warnings,
        }
    results = score_universe(settings, inputs)
    as_of = (
        max(all_price_dates).isoformat()
        if all_price_dates
        else datetime.now(UTC).date().isoformat()
    )
    run_id = str(uuid.uuid4())
    config_snapshot = json.loads(json.dumps(settings.raw))
    config_snapshot["runtime"] = {
        "freshness_label": provider.freshness_label,
        "universe_tickers": [security.ticker for security in settings.universe],
    }
    run = AnalysisRun(
        run_id=run_id,
        started_at=started_at,
        completed_at=None,
        as_of=as_of,
        provider=provider.name,
        universe_name=str(settings.raw["universe"]["name"]),
        model_version=settings.model_version,
        config_snapshot=config_snapshot,
        status="running",
        warnings=warnings,
    )
    storage.create_run(run)
    storage.save_results(run_id, results)
    storage.save_market_context(run_id, _market_context(storage, provider))
    usable_prices = sum(result.latest_price is not None for result in results)
    status = _analysis_status(usable_prices, len(results))
    if status == "partial":
        warnings.append(f"Only {usable_prices}/{len(results)} securities had usable price data")
    elif status == "failed":
        warnings.append("No usable price data was available for the configured universe")
    storage.finish_run(run_id, status, warnings)
    report_path = write_report_bundle(settings, storage, run_id)
    logger.info("Finished run=%s status=%s usable_prices=%s", run_id, status, usable_prices)
    return run_id, report_path, warnings
