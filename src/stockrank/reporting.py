from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from stockrank.config import Settings
from stockrank.data.sec import SecSubmissions
from stockrank.presentation import relative_status_label
from stockrank.storage import Storage

METRIC_LABELS = {
    "revenue_growth": "revenue growth",
    "earnings_growth": "earnings growth",
    "free_cash_flow_margin": "FCF margin",
    "forward_pe": "forward P/E",
    "peg_ratio": "PEG",
    "price_to_sales": "price/sales",
    "free_cash_flow_yield": "FCF yield",
    "return_on_equity": "return on equity",
    "profit_margin": "profit margin",
    "gross_margin": "gross margin",
    "debt_to_equity": "debt/equity",
    "current_ratio": "current ratio",
    "momentum_1m": "1-month momentum",
    "momentum_3m": "3-month momentum",
    "momentum_6m": "6-month momentum",
    "momentum_12m": "12-month momentum",
    "volatility_3m": "3-month volatility",
    "max_drawdown_1y": "one-year drawdown",
    "market_cap": "market capitalization",
}


def _fmt(value: Any, kind: str = "number") -> str:
    if value is None:
        return "N/A"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "N/A"
    if kind == "score":
        return f"{number:.1f}"
    if kind == "percent":
        return f"{number * 100:.1f}%"
    if kind == "price":
        return f"${number:,.2f}"
    if kind == "market_cap":
        if abs(number) >= 1_000_000_000_000:
            return f"${number / 1_000_000_000_000:.2f}T"
        return f"${number / 1_000_000_000:.1f}B"
    return f"{number:,.2f}"


def _run_dict(row: Any) -> dict[str, Any]:
    value = dict(row)
    value["config"] = json.loads(value.pop("config_json"))
    value["warnings"] = json.loads(value.pop("warnings_json"))
    return value


def _research_for_ticker(research: dict[str, Any] | None, ticker: str) -> dict[str, Any] | None:
    if not research:
        return None
    for company in research.get("companies", []):
        if company.get("ticker", "").upper() == ticker.upper():
            return company
    return None


def _note_value(note: dict[str, Any] | None, field: str, fallback: str) -> str:
    if not note:
        return fallback
    value = note.get(field)
    return value if isinstance(value, str) and value.strip() else fallback


def _drivers(result: dict[str, Any]) -> tuple[str, str]:
    values = [
        (metric, score) for metric, score in result["metric_scores"].items() if score is not None
    ]
    if not values:
        return "No scored metrics", "No scored metrics"
    strongest = sorted(values, key=lambda item: item[1], reverse=True)[:3]
    weakest = sorted(values, key=lambda item: item[1])[:2]
    strong_text = ", ".join(
        f"{METRIC_LABELS.get(metric, metric)} ({score:.0f})" for metric, score in strongest
    )
    weak_text = ", ".join(
        f"{METRIC_LABELS.get(metric, metric)} ({score:.0f})" for metric, score in weakest
    )
    return strong_text, weak_text


def render_report(settings: Settings, storage: Storage, run_id: str) -> str:
    with storage.connect() as connection:
        row = connection.execute(
            "SELECT * FROM analysis_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    if not row:
        raise ValueError(f"Unknown run_id: {run_id}")
    run = _run_dict(row)
    analysis_completed_at = (
        datetime.fromisoformat(run["completed_at"]) if run["completed_at"] else None
    )
    results = storage.get_results(run_id)
    research = storage.get_research(run_id)
    context = storage.get_market_context(run_id)
    previous = storage.previous_comparable_run(run_id)
    previous_results = (
        {result["ticker"]: result for result in storage.get_results(previous["run_id"])}
        if previous
        else {}
    )
    limit = int(settings.raw["app"]["top_candidate_limit"])
    candidates = [result for result in results if result["eligible"]][:limit]
    freshness = run["config"].get("runtime", {}).get("freshness_label", "Unknown")
    freshness_record = run["config"].get("runtime", {}).get("data_freshness", {})
    scoring_quality = run["config"].get("runtime", {}).get("scoring_quality", {})
    fundamental_states = Counter(
        value.get("status", "unknown")
        for value in freshness_record.get("fundamentals", {}).values()
    )
    fundamental_summary = (
        ", ".join(f"{key}={value}" for key, value in sorted(fundamental_states.items()))
        if fundamental_states
        else "legacy run; detailed status unavailable"
    )
    price_series_states = Counter(
        value.get("series_status", "legacy")
        for value in freshness_record.get("prices", {}).values()
    )
    price_series_summary = (
        ", ".join(f"{key}={value}" for key, value in sorted(price_series_states.items()))
        if price_series_states
        else "legacy run; continuity status unavailable"
    )
    peer_minimum = scoring_quality.get("minimum_metric_peer_count")
    peer_counts = scoring_quality.get("metric_peer_counts", {})
    weak_peer_metrics = scoring_quality.get("metrics_below_minimum", [])
    if peer_minimum is None:
        peer_summary = "legacy run; peer adequacy unavailable"
    else:
        weakest_samples = sorted(peer_counts.items(), key=lambda item: (item[1], item[0]))[:5]
        weakest_summary = ", ".join(
            f"{METRIC_LABELS.get(metric, metric)}={count}"
            for metric, count in weakest_samples
        )
        threshold_summary = (
            "all configured metrics passed"
            if not weak_peer_metrics
            else "below minimum: "
            + ", ".join(
                f"{METRIC_LABELS.get(metric, metric)}={peer_counts.get(metric, 0)}"
                for metric in weak_peer_metrics
            )
        )
        peer_summary = (
            f"minimum {peer_minimum}; {threshold_summary}; "
            f"five smallest samples: {weakest_summary or 'unavailable'}"
        )
    preferences = run["config"].get("preferences", {})

    lines = [
        "# Morning Stock Analysis",
        "",
        f"**Run:** `{run_id}`  ",
        f"**Market data as of:** {run['as_of']}  ",
        f"**Generated:** {run.get('completed_at') or run['started_at']}  ",
        f"**Provider/status:** {run['provider']} / {run['status']}  ",
        f"**Freshness:** {freshness}  ",
        (
            "**Price refresh:** "
            f"{freshness_record.get('price_refresh_status', 'legacy status unavailable')}  "
        ),
        f"**Price-series continuity:** {price_series_summary}  ",
        f"**Fundamental states:** {fundamental_summary}  ",
        f"**Metric peer adequacy:** {peer_summary}  ",
        f"**Universe/model:** {run['universe_name']} / {run['model_version']}",
        (
            "**Personal profile:** "
            f"{preferences.get('profile', 'balanced')} · "
            f"horizon {preferences.get('investment_horizon', 'medium')} · "
            f"risk {preferences.get('risk_tolerance', 'moderate')}"
        ),
        "",
        (
            "> Research and ranking aid only. Prices are treated as end-of-day/previous-close. "
            "No brokerage connection or trade execution is present."
        ),
        (
            "> Scores are relative to this run's selected universe, not absolute investment "
            "judgments. Missing metrics receive no invented value or penalty; they reduce the "
            "separately reported coverage instead."
        ),
        "",
        "## Market Overview",
        "",
        "Quantitative ETF proxies provide context; they are not forecasts.",
        "",
        "| Proxy | Role | Price | As of | 1M | 3M |",
        "|---|---|---:|---|---:|---:|",
    ]
    for ticker, value in context.items():
        lines.append(
            f"| {ticker} | {value['category']} | {_fmt(value['price'], 'price')} | "
            f"{value['price_as_of'] or 'N/A'} | {_fmt(value['momentum_1m'], 'percent')} | "
            f"{_fmt(value['momentum_3m'], 'percent')} |"
        )
    if research and research.get("market_overview", {}).get("summary"):
        lines.extend(
            ["", "**Current researched context:** " + research["market_overview"]["summary"]]
        )
        if research["market_overview"].get("sources"):
            lines.extend(["", "**Market sources:**", ""])
            for source in research["market_overview"]["sources"]:
                lines.append(
                    f"- [{source.get('title', 'Source')}]({source.get('url', '')}) — "
                    f"published {source.get('published_at') or 'date unavailable'}; "
                    f"event {source.get('event_at') or 'date unavailable'}; "
                    f"{source.get('source_type') or 'unclassified'}"
                )
    else:
        lines.extend(["", "Current macro/sector/news interpretation is pending research."])

    lines.extend(
        [
            "",
            "## Top Candidates Within This Universe",
            "",
        ]
    )
    if candidates:
        lines.extend(
            [
                "| Rank | Ticker | Company | Sector | Price | Score | Coverage | Relative label |",
                "|---:|---|---|---|---:|---:|---:|---|",
            ]
        )
        for result in candidates:
            lines.append(
                f"| {result['rank']} | {result['ticker']} | {result['company']} | "
                f"{result['sector']} | {_fmt(result['latest_price'], 'price')} | "
                f"{_fmt(result['overall_score'], 'score')} | "
                f"{result['overall_coverage'] * 100:.0f}% | "
                f"{relative_status_label(result['recommendation'])} |"
            )
        lines.extend(
            [
                "",
                (
                    "Scores use only available metrics. Coverage shows how much of the configured "
                    "model contributed; component coverage, catalysts, risks, filings, and source "
                    "notes are shown below."
                ),
            ]
        )
    else:
        lines.append(
            "No company met both the configured score threshold and data-coverage threshold. "
            "The list is intentionally not padded."
        )

    lines.extend(["", "## Research Summary", ""])
    for result in candidates:
        note = _research_for_ticker(research, result["ticker"])
        strong, weak = _drivers(result)
        component_scorecard = " · ".join(
            f"{component} {_fmt(result['component_scores'].get(component), 'score')} "
            f"({result['component_coverage'].get(component, 0.0) * 100:.0f}% coverage)"
            for component in ("growth", "valuation", "quality", "momentum", "risk")
        )
        prior = previous_results.get(result["ticker"])
        if prior and prior["overall_score"] is not None and result["overall_score"] is not None:
            delta = result["overall_score"] - prior["overall_score"]
            change = f"Score changed {delta:+.1f} from prior run; rank {prior['rank']} → {result['rank']}."
        else:
            change = "No comparable prior completed run is available."
        lines.extend(
            [
                f"### {result['rank']}. {result['ticker']} — {result['company']}",
                "",
                (
                    "**Scorecard:** "
                    f"overall {_fmt(result['overall_score'], 'score')} · "
                    f"overall coverage {result['overall_coverage'] * 100:.0f}% · "
                    f"{component_scorecard}"
                ),
                "",
                (
                    "**Calculated score rationale:** within the selected universe, strongest "
                    f"scored factors: {strong}. Weakest scored factors: {weak}. Missing factors "
                    "are reflected in coverage and are not assumed neutral."
                ),
                "",
                f"**Investment thesis (research interpretation):** {_note_value(note, 'thesis', 'Pending current-source research. Quantitative rank alone is not a thesis.')}",
                "",
                f"**Bull case:** {_note_value(note, 'bull_case', 'Pending current-source research.')}",
                "",
                f"**Bear case:** {_note_value(note, 'bear_case', 'Pending current-source research.')}",
                "",
                f"**Valuation:** {_note_value(note, 'valuation', 'Quantitative valuation component shown above; contextual assessment pending research.')}",
                "",
                f"**Catalysts:** {_note_value(note, 'catalysts', 'Pending verification from dated primary/reliable sources.')}",
                "",
                f"**Risks:** {_note_value(note, 'risks', 'Pending verification; see weak quantitative factors above.')}",
                "",
                f"**What changed:** {_note_value(note, 'what_changed', change)}",
                "",
            ]
        )
        filings = SecSubmissions.effective_filings(
            tuple(storage.get_sec_filings(result["ticker"])),
            available_at=analysis_completed_at,
        )
        if filings:
            lines.extend(["**Latest SEC filings:**", ""])
            for filing in filings[:4]:
                report_period = filing.report_date.isoformat() if filing.report_date else "unknown"
                availability = (
                    filing.accepted_at.isoformat()
                    if filing.accepted_at
                    else filing.availability_date.isoformat()
                )
                lines.append(
                    f"- [{filing.form}]({filing.filing_index_url}) — period "
                    f"{report_period}; available {availability} "
                    f"({filing.availability_precision})"
                )
            lines.append("")
        if result["warnings"]:
            lines.append("**Data notes:** " + "; ".join(result["warnings"]))
            lines.append("")
        if note and note.get("sources"):
            lines.append("**Sources:**")
            lines.append("")
            for source in note["sources"]:
                title = source.get("title") or source.get("url") or "Source"
                lines.append(
                    f"- [{title}]({source.get('url', '')}) — published "
                    f"{source.get('published_at') or 'date unavailable'}; event "
                    f"{source.get('event_at') or 'date unavailable'}; "
                    f"{source.get('source_type') or 'unclassified'}"
                )
            lines.append("")

    if run["warnings"]:
        lines.extend(["## Data Quality Warnings", ""])
        for warning in run["warnings"]:
            lines.append(f"- {warning}")
        lines.append("")
    lines.extend(
        [
            "## Method and Evidence Labels",
            "",
            (
                "- Prices/summary fundamentals: directly retrieved provider fields; per-stock "
                "fetch times and age decisions are retained in the run freshness record."
            ),
            "- Returns, volatility, drawdown, ratios, percentiles and scores: calculated locally.",
            "- Analyst expectations: included only when explicitly sourced in research notes.",
            "- Thesis, cases and contextual valuation: research interpretation, not sourced fact or certainty.",
            "- Future outcomes and proposed catalysts: inherently uncertain; speculation must be labelled.",
            "",
        ]
    )
    return "\n".join(lines)


def research_template(storage: Storage, run_id: str, limit: int) -> dict[str, Any]:
    results = [result for result in storage.get_results(run_id) if result["eligible"]][:limit]
    return {
        "run_id": run_id,
        "researched_at": None,
        "market_overview": {"summary": "", "sources": []},
        "companies": [
            {
                "ticker": result["ticker"],
                "thesis": "",
                "bull_case": "",
                "bear_case": "",
                "valuation": "",
                "catalysts": "",
                "risks": "",
                "what_changed": "",
                "major_catalyst": "",
                "major_risk": "",
                "sources": [],
            }
            for result in results
        ],
        "source_schema": {
            "required": ["title", "url", "published_at", "event_at", "source_type"],
            "source_type_examples": [
                "SEC filing",
                "company IR",
                "earnings release",
                "reliable news",
                "analyst expectation",
            ],
            "note": "Use concise notes and URLs only; do not archive article or filing bodies.",
        },
    }


def _stored_run_as_of(storage: Storage, run_id: str) -> str:
    with storage.connect() as connection:
        run = connection.execute(
            "SELECT as_of FROM analysis_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    if not run:
        raise ValueError(f"Unknown run_id: {run_id}")
    return str(run["as_of"])


def write_report_bundle(settings: Settings, storage: Storage, run_id: str) -> Path:
    report_dir = settings.runtime_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report = render_report(settings, storage, run_id)
    latest = report_dir / "latest.md"
    latest.write_text(report, encoding="utf-8")
    as_of = _stored_run_as_of(storage, run_id)
    historical = report_dir / f"{as_of}_{run_id[:8]}.md"
    historical.write_text(report, encoding="utf-8")
    template = research_template(storage, run_id, int(settings.raw["app"]["top_candidate_limit"]))
    (report_dir / "research_template.json").write_text(
        json.dumps(template, indent=2, sort_keys=True), encoding="utf-8"
    )
    return latest
