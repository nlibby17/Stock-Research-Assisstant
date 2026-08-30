from __future__ import annotations

import hashlib
import json
import logging
import logging.handlers
import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from stockrank.config import Settings
from stockrank.data import DemoProvider, MarketDataProvider, YFinanceProvider
from stockrank.freshness import PriceFreshness, assess_price_bars
from stockrank.metrics import apply_sector_conventions, calculate_metrics
from stockrank.models import AnalysisRun, PriceBar, Security
from stockrank.price_integrity import assess_price_series, build_reference_sessions
from stockrank.reporting import write_report_bundle
from stockrank.scoring import metric_peer_counts, score_universe
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


def _analysis_status(
    usable_prices: int, universe_size: int, *, price_dates_consistent: bool = True
) -> str:
    if usable_prices == universe_size and price_dates_consistent:
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


def _price_freshness(
    settings: Settings, bars: list[PriceBar] | tuple[PriceBar, ...], *, now: datetime
) -> PriceFreshness:
    provider_config = settings.raw["provider"]
    return assess_price_bars(
        bars,
        now=now,
        timezone_name=str(settings.raw["app"]["timezone"]),
        completion_buffer_minutes=int(provider_config["daily_bar_completion_buffer_minutes"]),
        maximum_age_hours=float(provider_config["maximum_price_age_hours"]),
    )


def _market_context(
    storage: Storage,
    provider: MarketDataProvider,
    settings: Settings,
    *,
    now: datetime,
    reference_sessions: tuple[date, ...],
) -> tuple[dict[str, Any], list[str]]:
    context: dict[str, Any] = {}
    context_warnings: list[str] = []
    for proxy in MARKET_PROXIES:
        freshness = _price_freshness(
            settings, storage.get_price_bars(proxy.ticker, provider.name), now=now
        )
        bars = list(freshness.usable_bars)
        metrics, warnings = calculate_metrics(
            bars, None, reference_sessions=reference_sessions
        )
        price_warnings = list(freshness.warnings)
        if freshness.status != "usable":
            context_warnings.append(
                f"{proxy.ticker}: market-context price data is {freshness.status}"
            )
        context[proxy.ticker] = {
            "name": proxy.company,
            "category": proxy.sector,
            "price": metrics["latest_price"],
            "price_as_of": bars[-1].date.isoformat() if bars else None,
            "momentum_1m": metrics["momentum_1m"],
            "momentum_3m": metrics["momentum_3m"],
            "warnings": price_warnings
            + [warning for warning in warnings if "Fundamental" not in warning],
        }
    return context, context_warnings


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
    price_refresh_status = "cache_reused"
    refreshed_price_tickers: set[str] = set()
    price_filter_counts = {"invalid": 0, "incomplete": 0, "future": 0}
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
            completed_price_data: dict[str, tuple[PriceBar, ...]] = {}
            for ticker, bars in price_data.items():
                freshness = _price_freshness(settings, bars, now=started_at)
                if freshness.usable_bars:
                    completed_price_data[ticker] = freshness.usable_bars
                    refreshed_price_tickers.add(ticker)
                price_filter_counts["invalid"] += freshness.invalid_bar_count
                price_filter_counts["incomplete"] += freshness.incomplete_bar_count
                price_filter_counts["future"] += freshness.future_bar_count
            if price_filter_counts["invalid"]:
                warnings.append(
                    "Price refresh ignored "
                    f"{price_filter_counts['invalid']} invalid or nonpositive daily bar(s)"
                )
            if price_filter_counts["future"]:
                warnings.append(
                    f"Price refresh ignored {price_filter_counts['future']} future-dated bar(s)"
                )
            row_count = storage.upsert_price_bars(
                bar for bars in completed_price_data.values() for bar in bars
            )
            expected_tickers = {security.ticker for security in all_securities}
            missing_refresh = sorted(expected_tickers - refreshed_price_tickers)
            if missing_refresh:
                price_refresh_status = "partial"
                warnings.append(
                    "Price refresh was incomplete; cached bars will be checked for: "
                    + ", ".join(missing_refresh)
                )
                storage.set_cache_status(
                    cache_key,
                    provider.name,
                    0,
                    "partial",
                    f"{row_count} bars; missing={','.join(missing_refresh)}",
                )
            else:
                price_refresh_status = "complete"
                storage.set_cache_status(
                    cache_key, provider.name, price_ttl, "ok", f"{row_count} bars"
                )
            logger.info("Stored %s normalized price bars", row_count)
        except Exception as error:
            price_refresh_status = "failed_cached_fallback"
            message = f"Price refresh failed; cached bars will be used when present: {error}"
            warnings.append(message)
            storage.set_cache_status(cache_key, provider.name, 0, "error", str(error))
            logger.exception("Price refresh failed")

    fundamentals: dict[str, Any] = {}
    fundamental_notes: dict[str, list[str]] = {}
    fundamental_lineage: dict[str, dict[str, Any]] = {}
    fundamental_ttl = float(settings.raw["provider"]["fundamental_cache_ttl_hours"])
    maximum_fundamental_age = float(settings.raw["provider"]["maximum_stale_fundamental_hours"])
    for security in settings.universe:
        cached = (
            None
            if force
            else storage.get_fundamental(security.ticker, provider.name, fresh_only=True)
        )
        if cached:
            age_hours = max(
                0.0,
                (started_at - cached.fetched_at.astimezone(UTC)).total_seconds() / 3600,
            )
            if age_hours <= maximum_fundamental_age:
                fundamentals[security.ticker] = cached
                fundamental_lineage[security.ticker] = {
                    "status": "fresh_cache",
                    "source": cached.source,
                    "fetched_at": cached.fetched_at.isoformat(),
                    "age_hours": round(age_hours, 3),
                }
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
            fundamental_lineage[security.ticker] = {
                "status": "refreshed",
                "source": snapshot.source,
                "fetched_at": snapshot.fetched_at.isoformat(),
                "age_hours": 0.0,
            }
        else:
            stale = storage.get_fundamental(security.ticker, provider.name, fresh_only=False)
            if stale:
                age_hours = max(
                    0.0,
                    (started_at - stale.fetched_at.astimezone(UTC)).total_seconds() / 3600,
                )
                if age_hours <= maximum_fundamental_age:
                    fundamentals[security.ticker] = stale
                    note = (
                        f"Using stale fundamentals fetched {stale.fetched_at.isoformat()} "
                        f"({age_hours:.1f} hours old)"
                    )
                    fundamental_notes.setdefault(security.ticker, []).append(note)
                    warnings.append(f"{security.ticker}: {note.lower()}")
                    status = "stale_fallback"
                else:
                    note = (
                        f"Rejected fundamentals fetched {stale.fetched_at.isoformat()} because "
                        f"they are {age_hours:.1f} hours old, above the "
                        f"{maximum_fundamental_age:g}-hour limit"
                    )
                    fundamental_notes.setdefault(security.ticker, []).append(note)
                    warnings.append(f"{security.ticker}: {note.lower()}")
                    status = "rejected_stale"
                fundamental_lineage[security.ticker] = {
                    "status": status,
                    "source": stale.source,
                    "fetched_at": stale.fetched_at.isoformat(),
                    "age_hours": round(age_hours, 3),
                }
            else:
                fundamental_lineage[security.ticker] = {
                    "status": "unavailable",
                    "source": provider.name,
                    "fetched_at": None,
                    "age_hours": None,
                }

    price_freshness = {
        security.ticker: _price_freshness(
            settings,
            storage.get_price_bars(security.ticker, provider.name),
            now=started_at,
        )
        for security in all_securities
    }
    reference_sessions = build_reference_sessions(
        {
            proxy.ticker: price_freshness[proxy.ticker].usable_bars
            for proxy in MARKET_PROXIES
            if price_freshness[proxy.ticker].usable_bars
        }
    )
    if not reference_sessions:
        warnings.append(
            "Trading-session reference could not be built; session-based metrics are unavailable"
        )

    inputs: dict[str, dict[str, Any]] = {}
    all_price_dates: list[date] = []
    price_lineage: dict[str, dict[str, Any]] = {}
    for security in settings.universe:
        freshness = price_freshness[security.ticker]
        bars = list(freshness.usable_bars)
        if bars:
            all_price_dates.append(bars[-1].date)
        continuity = assess_price_series(bars, reference_sessions)
        metrics, metric_warnings = calculate_metrics(
            bars,
            fundamentals.get(security.ticker),
            reference_sessions=reference_sessions,
            minimum_debt_to_equity=float(
                settings.raw["scoring"]["validity"]["minimum_debt_to_equity"]
            ),
            maximum_return_on_equity=float(
                settings.raw["scoring"]["validity"]["maximum_return_on_equity"]
            ),
        )
        metric_warnings.extend(freshness.warnings)
        metric_warnings.extend(fundamental_notes.get(security.ticker, []))
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
        price_lineage[security.ticker] = {
            "status": freshness.status,
            "price_as_of": freshness.latest_date,
            "fetched_at": freshness.latest_fetched_at,
            "age_hours": (
                round(freshness.age_hours, 3) if freshness.age_hours is not None else None
            ),
            "included_in_refresh": security.ticker in refreshed_price_tickers,
            "series_status": continuity.status,
            "expected_sessions_checked": continuity.expected_session_count,
            "observed_sessions_checked": continuity.observed_session_count,
            "missing_session_count": len(continuity.missing_sessions),
            "missing_sessions": [value.isoformat() for value in continuity.missing_sessions[-10:]],
        }
    gapped_tickers = sorted(
        ticker
        for ticker, lineage in price_lineage.items()
        if lineage["series_status"] == "gapped"
    )
    if gapped_tickers:
        warnings.append(
            "Price-series continuity gaps reduced session-based metric coverage for: "
            + ", ".join(gapped_tickers)
        )
    unverified_tickers = sorted(
        ticker
        for ticker, lineage in price_lineage.items()
        if lineage["series_status"] == "unverified"
    )
    if unverified_tickers:
        warnings.append(
            "Price-series continuity could not be verified for: "
            + ", ".join(unverified_tickers)
        )
    peer_counts = metric_peer_counts(settings, inputs)
    minimum_peer_count = int(
        settings.raw["scoring"]["validity"]["minimum_metric_peer_count"]
    )
    weak_peer_metrics = sorted(
        metric for metric, count in peer_counts.items() if count < minimum_peer_count
    )
    if weak_peer_metrics:
        warnings.append(
            f"Metrics below the {minimum_peer_count}-peer percentile minimum: "
            + ", ".join(f"{metric} ({peer_counts[metric]})" for metric in weak_peer_metrics)
        )
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
        "scoring_quality": {
            "minimum_metric_peer_count": minimum_peer_count,
            "metric_peer_counts": peer_counts,
            "metrics_below_minimum": weak_peer_metrics,
        },
        "data_freshness": {
            "price_refresh_status": price_refresh_status,
            "price_refresh_filter_counts": price_filter_counts,
            "price_series_status_counts": dict(
                Counter(value["series_status"] for value in price_lineage.values())
            ),
            "trading_session_reference": {
                "method": "75% consensus of usable broad-market proxy price series",
                "source_series": sum(
                    bool(price_freshness[proxy.ticker].usable_bars) for proxy in MARKET_PROXIES
                ),
                "session_count": len(reference_sessions),
            },
            "maximum_price_age_hours": float(settings.raw["provider"]["maximum_price_age_hours"]),
            "maximum_stale_fundamental_hours": maximum_fundamental_age,
            "prices": price_lineage,
            "fundamentals": fundamental_lineage,
        },
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
    market_context, market_warnings = _market_context(
        storage,
        provider,
        settings,
        now=started_at,
        reference_sessions=reference_sessions,
    )
    warnings.extend(market_warnings)
    storage.save_market_context(run_id, market_context)
    usable_prices = sum(result.latest_price is not None for result in results)
    result_price_dates = {
        result.price_as_of for result in results if result.price_as_of is not None
    }
    price_dates_consistent = len(result_price_dates) <= 1
    status = _analysis_status(
        usable_prices,
        len(results),
        price_dates_consistent=price_dates_consistent,
    )
    if not price_dates_consistent:
        warnings.append(
            "Configured securities have mixed completed price dates: "
            + ", ".join(sorted(result_price_dates))
        )
    if status == "partial":
        warnings.append(f"Only {usable_prices}/{len(results)} securities had usable price data")
    elif status == "failed":
        warnings.append("No usable price data was available for the configured universe")
    storage.finish_run(run_id, status, warnings)
    report_path = write_report_bundle(settings, storage, run_id)
    logger.info("Finished run=%s status=%s usable_prices=%s", run_id, status, usable_prices)
    return run_id, report_path, warnings
