from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import median

import streamlit as st

from stockrank.config import load_settings
from stockrank.data.sec import SecSubmissions
from stockrank.provider_comparison import load_provider_comparison_config
from stockrank.storage import Storage

st.set_page_config(page_title="Stock Research Assistant", layout="wide")
settings = load_settings(Path.cwd())
storage = Storage(settings.database_path)
storage.initialize()
run = storage.latest_run()

st.title("Personal Stock Research Assistant")
st.caption("Research and ranking only — no brokerage connectivity or trade execution")

if not run:
    st.info("No run exists yet. Run `stockrank run` from the project directory.")
    st.stop()

results = storage.get_results(run["run_id"])
research = storage.get_research(run["run_id"])
context = storage.get_market_context(run["run_id"])
warnings = json.loads(run["warnings_json"])
config = json.loads(run["config_json"])
analysis_completed_at = (
    datetime.fromisoformat(run["completed_at"]) if run["completed_at"] else None
)

if run["provider"] == "demo-synthetic":
    st.error("SYNTHETIC DEMO DATA — do not use for investment decisions")
elif warnings:
    st.warning(f"This run has {len(warnings)} data-quality warning(s). See Data Quality below.")

st.subheader(f"Analysis as of {run['as_of']}")
columns = st.columns(4)
columns[0].metric("Universe", len(results))
columns[1].metric("Eligible candidates", sum(result["eligible"] for result in results))
columns[2].metric("Model", run["model_version"])
columns[3].metric("Provider", run["provider"])
st.caption(config.get("runtime", {}).get("freshness_label", "Freshness unknown"))

st.header("Market Overview")
market_rows = [
    {
        "Ticker": ticker,
        "Role": value["category"],
        "Price": value["price"],
        "As of": value["price_as_of"],
        "1M %": value["momentum_1m"] * 100 if value["momentum_1m"] is not None else None,
        "3M %": value["momentum_3m"] * 100 if value["momentum_3m"] is not None else None,
    }
    for ticker, value in context.items()
]
st.dataframe(
    market_rows,
    width="stretch",
    hide_index=True,
    column_config={
        "Price": st.column_config.NumberColumn(format="$%.2f"),
        "1M %": st.column_config.NumberColumn(format="%.1f%%"),
        "3M %": st.column_config.NumberColumn(format="%.1f%%"),
    },
)
if research and research.get("market_overview", {}).get("summary"):
    # Streamlit treats paired dollar signs as inline LaTeX delimiters. Escape
    # financial dollar amounts so researched prose renders as ordinary text.
    market_summary = research["market_overview"]["summary"].replace("$", r"\$")
    st.markdown(market_summary)
    for source in research["market_overview"].get("sources", []):
        st.markdown(
            f"- [{source.get('title', 'Source')}]({source.get('url', '')}) — "
            f"published {source.get('published_at', 'unknown')}"
        )

st.header("Top Candidates")
limit = int(settings.raw["app"]["top_candidate_limit"])
candidates = [result for result in results if result["eligible"]][:limit]
research_companies = {
    item.get("ticker", "").upper(): item for item in (research or {}).get("companies", [])
}
candidate_rows = []
for result in candidates:
    scores = result["component_scores"]
    note = research_companies.get(result["ticker"])
    candidate_rows.append(
        {
            "Rank": result["rank"],
            "Ticker": result["ticker"],
            "Company": result["company"],
            "Sector": result["sector"],
            "Price": result["latest_price"],
            "Price status": (
                f"latest available ({result['price_as_of']})"
                if result["price_as_of"] == run["as_of"]
                else f"older ({result['price_as_of'] or 'missing'})"
            ),
            "Overall": result["overall_score"],
            "Growth": scores.get("growth"),
            "Valuation": scores.get("valuation"),
            "Quality": scores.get("quality"),
            "Momentum": scores.get("momentum"),
            "Risk": scores.get("risk"),
            "Coverage %": result["overall_coverage"] * 100,
            "Label": result["recommendation"],
            "Catalyst": (note or {}).get("major_catalyst") or "Research pending",
            "Major risk": (note or {}).get("major_risk") or "Research pending",
        }
    )
if candidate_rows:
    st.dataframe(
        candidate_rows,
        width="stretch",
        hide_index=True,
        column_config={
            "Price": st.column_config.NumberColumn(format="$%.2f"),
            "Overall": st.column_config.NumberColumn(format="%.1f"),
            "Growth": st.column_config.NumberColumn(format="%.1f"),
            "Valuation": st.column_config.NumberColumn(format="%.1f"),
            "Quality": st.column_config.NumberColumn(format="%.1f"),
            "Momentum": st.column_config.NumberColumn(format="%.1f"),
            "Risk": st.column_config.NumberColumn(format="%.1f"),
            "Coverage %": st.column_config.NumberColumn(format="%.0f%%"),
        },
    )
else:
    st.info("No company met both score and coverage thresholds; the list is not padded.")

st.header("Research Summary")
st.caption("SEC filings shown below were available by this analysis run's completion time.")
for result in candidates:
    note = research_companies.get(result["ticker"])
    with st.expander(f"{result['rank']}. {result['ticker']} — {result['company']}"):
        filings = SecSubmissions.effective_filings(
            tuple(storage.get_sec_filings(result["ticker"])),
            available_at=analysis_completed_at,
        )
        if filings:
            st.subheader("Latest SEC filings")
            for filing in filings[:4]:
                report_period = filing.report_date.isoformat() if filing.report_date else "unknown"
                availability = (
                    filing.accepted_at.isoformat()
                    if filing.accepted_at
                    else filing.availability_date.isoformat()
                )
                st.markdown(
                    f"- [{filing.form}]({filing.filing_index_url}) — "
                    f"period {report_period}; available {availability} "
                    f"({filing.availability_precision})"
                )
        if not note:
            st.info("Current-source Codex research has not been imported for this run.")
            continue
        if result["warnings"]:
            st.caption("Data notes: " + "; ".join(result["warnings"]))
        for label, field in (
            ("Investment thesis", "thesis"),
            ("Bull case", "bull_case"),
            ("Bear case", "bear_case"),
            ("Valuation", "valuation"),
            ("Catalysts", "catalysts"),
            ("Risks", "risks"),
            ("What changed", "what_changed"),
        ):
            st.subheader(label)
            st.write(note.get(field) or "Not provided")
        if note.get("sources"):
            st.subheader("Sources")
            for source in note["sources"]:
                st.markdown(
                    f"- [{source.get('title', 'Source')}]({source.get('url', '')}) — "
                    f"published {source.get('published_at', 'unknown')}; "
                    f"event {source.get('event_at', 'unknown')}"
                )

st.header("Data Quality")
st.caption(
    "SEC Company Facts and Step 2.4A local calculations are monitored here, but "
    "remain isolated from ranking inputs through the Step 2.4B shadow comparison "
    "and explicit Step 2.4C promotion decision."
)
if warnings:
    for warning in warnings:
        st.write(f"- {warning}")
else:
    st.success("No run-level warnings were recorded.")
for provider, label in (
    ("sec-edgar", "SEC identity provider"),
    ("sec-submissions", "SEC submissions provider"),
    ("sec-companyfacts", "SEC Company Facts provider"),
    ("sec-financials", "SEC financial calculation layer"),
    ("provider-shadow", "SEC/Yahoo shadow comparison"),
):
    sec_health = storage.get_provider_health(provider)
    if not sec_health:
        st.caption(f"{label} has not been checked.")
        continue
    health_label = {
        "healthy": "Healthy",
        "degraded": "Degraded",
        "partial": "Partial",
        "unavailable": "Unavailable",
    }.get(sec_health.status, sec_health.status.title())
    st.write(f"**{label}:** {health_label}")
    access_label = (
        "local stored data"
        if provider in {"sec-financials", "provider-shadow"}
        else "cache used"
        if sec_health.cache_hit
        else "live request"
    )
    st.caption(
        f"Checked {sec_health.checked_at.isoformat()} · "
        f"{access_label} · "
        f"{sec_health.latency_ms:.0f} ms · {sec_health.detail}"
    )
financial_rows = []
for security in settings.universe:
    financial_snapshot = storage.latest_sec_financial_snapshot(security.ticker)
    if not financial_snapshot:
        continue
    calculated = {
        (metric.metric_name, metric.period_kind): metric
        for metric in financial_snapshot.metrics
    }
    applicable = [
        metric for metric in financial_snapshot.metrics if metric.quality != "excluded"
    ]
    available = sum(metric.value is not None for metric in applicable)
    revenue_ttm = calculated.get(("revenue", "ttm"))
    revenue_growth = calculated.get(("revenue_growth", "annual"))
    net_margin = calculated.get(("net_margin", "ttm"))
    financial_rows.append(
        {
            "Ticker": security.ticker,
            "Snapshot as of": financial_snapshot.as_of.isoformat(),
            "Formula": financial_snapshot.formula_version,
            "Metric coverage %": 100 * available / len(applicable) if applicable else 0,
            "TTM revenue": (
                float(revenue_ttm.value)
                if revenue_ttm is not None and revenue_ttm.value is not None
                else None
            ),
            "Annual revenue growth %": (
                float(revenue_growth.value * 100)
                if revenue_growth is not None and revenue_growth.value is not None
                else None
            ),
            "TTM net margin %": (
                float(net_margin.value * 100)
                if net_margin is not None and net_margin.value is not None
                else None
            ),
        }
    )
if financial_rows:
    with st.expander("Step 2.4A SEC financial snapshots (not ranking inputs)"):
        st.dataframe(
            financial_rows,
            width="stretch",
            hide_index=True,
            column_config={
                "Metric coverage %": st.column_config.NumberColumn(format="%.0f%%"),
                "TTM revenue": st.column_config.NumberColumn(format="$%.0f"),
                "Annual revenue growth %": st.column_config.NumberColumn(format="%.1f%%"),
                "TTM net margin %": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )
try:
    shadow_config = load_provider_comparison_config(settings)
except ValueError as shadow_config_error:
    st.error(f"Provider comparison configuration error: {shadow_config_error}")
else:
    shadow_run = storage.latest_provider_comparison_run(full_universe_only=True)
    if shadow_run:
        shadow_rows = storage.get_provider_metric_comparisons(
            shadow_run.comparison_run_id
        )
        full_shadow_dates = storage.provider_comparison_full_universe_dates(
            shadow_config.version, str(settings.raw["app"]["timezone"])
        )
        classification_counts = Counter(row.classification for row in shadow_rows)
        with st.expander("Step 2.4B SEC/Yahoo shadow comparison (not ranking inputs)"):
            st.caption(
                f"Run {shadow_run.comparison_run_id} · "
                f"as of {shadow_run.as_of.isoformat()} · "
                f"config {shadow_run.config_version} · "
                f"promotion evidence {full_shadow_dates}/"
                f"{shadow_config.required_full_universe_dates} distinct analysis dates"
            )
            summary_columns = st.columns(5)
            for column, classification in zip(
                summary_columns,
                (
                    "comparable",
                    "approximately_comparable",
                    "materially_different",
                    "missing",
                    "structurally_incomparable",
                ),
            ):
                column.metric(
                    classification.replace("_", " ").title(),
                    classification_counts.get(classification, 0),
                )
            metric_summary = []
            for metric_name in sorted({row.metric_name for row in shadow_rows}):
                metric_values = [
                    row for row in shadow_rows if row.metric_name == metric_name
                ]
                counts = Counter(row.classification for row in metric_values)
                relative_values = [
                    float(row.relative_difference * 100)
                    for row in metric_values
                    if row.relative_difference is not None
                ]
                metric_summary.append(
                    {
                        "Metric": metric_name,
                        "Comparable": counts.get("comparable", 0),
                        "Approximate": counts.get("approximately_comparable", 0),
                        "Material": counts.get("materially_different", 0),
                        "Missing": counts.get("missing", 0),
                        "Structural": counts.get("structurally_incomparable", 0),
                        "Median relative difference %": (
                            median(relative_values) if relative_values else None
                        ),
                    }
                )
            st.subheader("Classification by metric")
            st.dataframe(
                metric_summary,
                width="stretch",
                hide_index=True,
                column_config={
                    "Median relative difference %": st.column_config.NumberColumn(
                        format="%.1f%%"
                    )
                },
            )
            sector_summary = []
            for sector_name in sorted({row.sector for row in shadow_rows}):
                sector_values = [row for row in shadow_rows if row.sector == sector_name]
                counts = Counter(row.classification for row in sector_values)
                sector_summary.append(
                    {
                        "Sector": sector_name,
                        "Comparable": counts.get("comparable", 0),
                        "Approximate": counts.get("approximately_comparable", 0),
                        "Material": counts.get("materially_different", 0),
                        "Missing": counts.get("missing", 0),
                        "Structural": counts.get("structurally_incomparable", 0),
                    }
                )
            st.subheader("Classification by sector")
            st.dataframe(sector_summary, width="stretch", hide_index=True)
            material_rows = sorted(
                (
                    row
                    for row in shadow_rows
                    if row.classification == "materially_different"
                ),
                key=lambda row: row.relative_difference or 0,
                reverse=True,
            )
            if material_rows:
                st.subheader("Material discrepancies")
                st.dataframe(
                    [
                        {
                            "Ticker": row.ticker,
                            "Sector": row.sector,
                            "Metric": row.metric_name,
                            "SEC": float(row.sec_value) if row.sec_value is not None else None,
                            "Yahoo": (
                                float(row.yahoo_value)
                                if row.yahoo_value is not None
                                else None
                            ),
                            "Relative difference %": (
                                float(row.relative_difference * 100)
                                if row.relative_difference is not None
                                else None
                            ),
                            "SEC period end": (
                                row.sec_end_date.isoformat() if row.sec_end_date else None
                            ),
                            "Period alignment": row.period_alignment,
                        }
                        for row in material_rows
                    ],
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Relative difference %": st.column_config.NumberColumn(
                            format="%.1f%%"
                        )
                    },
                )
            fallback_counts = Counter(
                row.fallback_candidate for row in shadow_rows if row.fallback_candidate
            )
            if fallback_counts:
                st.caption(
                    "Fallback candidates for Step 2.4C review only: "
                    + ", ".join(
                        f"{name.replace('_', ' ')}={count}"
                        for name, count in sorted(fallback_counts.items())
                    )
                )
with st.expander("Scoring configuration snapshot"):
    st.json(config.get("scoring", {}))
