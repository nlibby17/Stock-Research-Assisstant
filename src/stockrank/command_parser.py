from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping

from stockrank.customization import HORIZONS, PROFILE_NAMES, RISK_LEVELS

CommandHandler = Callable[[argparse.Namespace], int]


def build_command_parser(handlers: Mapping[str, CommandHandler]) -> argparse.ArgumentParser:
    """Build the CLI surface independently from command implementations."""
    parser = argparse.ArgumentParser(
        prog="stockrank", description="Local research-only stock ranking application"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    configure_parser = subparsers.add_parser(
        "configure", help="Create or update this computer's personal profile and universe"
    )
    configure_parser.add_argument("--profile", choices=PROFILE_NAMES)
    configure_parser.add_argument("--horizon", choices=HORIZONS)
    configure_parser.add_argument("--risk", choices=RISK_LEVELS)
    configure_parser.add_argument(
        "--weights",
        help="Advanced component weights: growth=.25,valuation=.20,...",
    )
    configure_parser.add_argument("--candidate-limit", type=int)
    configure_parser.add_argument("--minimum-score", type=float)
    configure_parser.add_argument("--minimum-coverage", type=float)
    universe_group = configure_parser.add_mutually_exclusive_group()
    universe_group.add_argument(
        "--tickers", help="Comma-separated tickers; company and sector metadata are retrieved"
    )
    universe_group.add_argument(
        "--universe-file",
        help="CSV with ticker and optional company/sector columns",
    )
    universe_group.add_argument(
        "--use-default-universe",
        action="store_true",
        help="Keep personal preferences but restore the project's default universe",
    )
    configure_parser.add_argument(
        "--yes", action="store_true", help="Save without interactive prompts"
    )
    configure_parser.add_argument(
        "--reset",
        action="store_true",
        help="Restore project defaults and retain local files as backups",
    )
    configure_parser.set_defaults(handler=handlers["configure"])

    config_check_parser = subparsers.add_parser(
        "config-check", help="Validate active preferences, scoring, and universe"
    )
    config_check_parser.add_argument(
        "--live",
        action="store_true",
        help="Also verify Yahoo price and SEC identity coverage",
    )
    config_check_parser.set_defaults(handler=handlers["config-check"])
    setup_parser = subparsers.add_parser(
        "setup-check", help="Verify configuration and initialize local runtime storage"
    )
    setup_parser.set_defaults(handler=handlers["setup-check"])
    daily_parser = subparsers.add_parser(
        "daily-report", help="Run the complete deterministic daily report workflow"
    )
    daily_parser.add_argument("--force", action="store_true", help="Bypass fresh provider caches")
    daily_parser.set_defaults(handler=handlers["daily-report"])
    morning_parser = subparsers.add_parser(
        "morning", help="Run the daily report and then launch the dashboard"
    )
    morning_parser.add_argument("--force", action="store_true", help="Bypass fresh provider caches")
    morning_parser.set_defaults(handler=handlers["morning"])
    run_parser = subparsers.add_parser("run", help="Retrieve, calculate, rank, and report")
    run_parser.add_argument("--demo", action="store_true", help="Use explicit synthetic demo data")
    run_parser.add_argument("--force", action="store_true", help="Bypass fresh-cache checks")
    run_parser.set_defaults(handler=handlers["run"])
    validate_parser = subparsers.add_parser("validate-latest", help="Validate latest run quality")
    validate_parser.set_defaults(handler=handlers["validate-latest"])
    research_parser = subparsers.add_parser(
        "research-import", help="Validate/import current-source research JSON"
    )
    research_parser.add_argument("--file", required=True)
    research_parser.set_defaults(handler=handlers["research-import"])
    status_parser = subparsers.add_parser("storage-status", help="Inspect runtime storage")
    status_parser.set_defaults(handler=handlers["storage-status"])
    clean_parser = subparsers.add_parser("storage-clean", help="Preview/apply retention cleanup")
    clean_parser.add_argument("--apply", action="store_true")
    clean_parser.set_defaults(handler=handlers["storage-clean"])

    sec_health_parser = subparsers.add_parser(
        "sec-health", help="Verify SEC identity coverage and provider health"
    )
    sec_health_parser.add_argument(
        "--force", action="store_true", help="Bypass the SEC identity cache"
    )
    sec_health_parser.set_defaults(handler=handlers["sec-health"])
    filing_sync_parser = subparsers.add_parser(
        "sec-filings-sync", help="Sync normalized SEC 10-K/10-Q filing metadata"
    )
    filing_sync_parser.add_argument(
        "--force", action="store_true", help="Bypass SEC submissions caches"
    )
    filing_sync_parser.add_argument(
        "--years", type=int, help="Override the configured filing-history window"
    )
    filing_sync_parser.add_argument(
        "--ticker",
        action="append",
        help="Limit sync to a universe ticker; repeat or use comma-separated values",
    )
    filing_sync_parser.set_defaults(handler=handlers["sec-filings-sync"])
    filing_status_parser = subparsers.add_parser(
        "sec-filings-status", help="Inspect stored SEC filing coverage"
    )
    filing_status_parser.set_defaults(handler=handlers["sec-filings-status"])
    fact_sync_parser = subparsers.add_parser(
        "sec-facts-sync", help="Sync normalized SEC Company Facts/XBRL data"
    )
    fact_sync_parser.add_argument(
        "--force", action="store_true", help="Bypass SEC Company Facts caches"
    )
    fact_sync_parser.add_argument(
        "--years", type=int, help="Override the configured Company Facts history window"
    )
    fact_sync_parser.add_argument(
        "--ticker",
        action="append",
        help="Limit sync to a universe ticker; repeat or use comma-separated values",
    )
    fact_sync_parser.set_defaults(handler=handlers["sec-facts-sync"])
    fact_status_parser = subparsers.add_parser(
        "sec-facts-status", help="Inspect normalized SEC Company Facts coverage"
    )
    fact_status_parser.set_defaults(handler=handlers["sec-facts-status"])
    financial_build_parser = subparsers.add_parser(
        "sec-financials-build",
        help="Build immutable point-in-time SEC financial snapshots without ranking changes",
    )
    financial_build_parser.add_argument(
        "--as-of",
        help="ISO date/datetime cutoff; date-only values use the configured local day end",
    )
    financial_build_parser.add_argument(
        "--ticker",
        action="append",
        help="Limit build to a universe ticker; repeat or use comma-separated values",
    )
    financial_build_parser.set_defaults(handler=handlers["sec-financials-build"])
    financial_status_parser = subparsers.add_parser(
        "sec-financials-status", help="Inspect derived SEC financial snapshot coverage"
    )
    financial_status_parser.set_defaults(handler=handlers["sec-financials-status"])
    shadow_run_parser = subparsers.add_parser(
        "provider-shadow-run",
        help="Compare SEC-derived and Yahoo metrics without changing rankings",
    )
    shadow_run_parser.add_argument(
        "--ticker",
        action="append",
        help="Limit comparison to a universe ticker; repeat or use comma-separated values",
    )
    shadow_run_parser.set_defaults(handler=handlers["provider-shadow-run"])
    shadow_status_parser = subparsers.add_parser(
        "provider-shadow-status", help="Inspect provider shadow comparison progress"
    )
    shadow_status_parser.set_defaults(handler=handlers["provider-shadow-status"])
    dashboard_parser = subparsers.add_parser(
        "dashboard", help="Launch the local Streamlit dashboard"
    )
    dashboard_parser.set_defaults(handler=handlers["dashboard"])
    return parser
