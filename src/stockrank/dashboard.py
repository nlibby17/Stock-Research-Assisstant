from __future__ import annotations

import html
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import median

import streamlit as st

from stockrank.config import load_settings
from stockrank.data.sec import SecSubmissions
from stockrank.presentation import ranking_change_summary, rankings_csv
from stockrank.provider_comparison import load_provider_comparison_config
from stockrank.storage import Storage
from stockrank.version import APP_VERSION

st.set_page_config(page_title="Stock Research Assistant", layout="wide")
st.markdown(
    """
    <style>
    .block-container {
        max-width: 1280px;
        padding-top: 2rem;
        padding-bottom: 4rem;
    }
    .sr-hero {
        align-items: center;
        background: #141e2e;
        border: 1px solid #293750;
        border-left: 4px solid #45c895;
        border-radius: 14px;
        display: flex;
        justify-content: space-between;
        margin-bottom: 1.35rem;
        padding: 1.4rem 1.6rem;
    }
    .sr-eyebrow {
        color: #8fa1b9;
        font-size: .72rem;
        font-weight: 700;
        letter-spacing: .12em;
        margin-bottom: .35rem;
        text-transform: uppercase;
    }
    .sr-hero h1 {
        color: #f4f7fb;
        font-size: 2rem;
        letter-spacing: -.025em;
        margin: 0 0 .3rem 0;
    }
    .sr-hero p { color: #a9b7ca; margin: 0; }
    .sr-hero-meta {
        align-items: flex-end;
        display: flex;
        flex-direction: column;
        gap: .55rem;
        margin-left: 1rem;
    }
    .sr-status, .sr-pill {
        border-radius: 999px;
        display: inline-block;
        font-size: .78rem;
        font-weight: 650;
        padding: .32rem .68rem;
        white-space: nowrap;
    }
    .sr-status { background: rgba(69, 200, 149, .14); color: #70ddb3; }
    .sr-pill { background: #1b283b; border: 1px solid #30415c; color: #c9d3e1; }
    [data-testid="stMetric"] {
        background: #141e2e;
        border: 1px solid #293750;
        border-radius: 12px;
        min-height: 105px;
        padding: .85rem 1rem;
    }
    [data-testid="stMetricLabel"] { color: #94a6bd; }
    [data-testid="stMetricValue"] { color: #f1f5fa; }
    h2 {
        border-bottom: 1px solid #25344b;
        letter-spacing: -.018em;
        padding-bottom: .45rem;
    }
    h3 { color: #dfe7f2; font-size: 1.05rem !important; }
    [data-testid="stDataFrame"] {
        border: 1px solid #293750;
        border-radius: 11px;
        overflow: hidden;
    }
    [data-testid="stExpander"] {
        background: rgba(20, 30, 46, .72);
        border-color: #293750;
        border-radius: 11px;
    }
    [data-testid="stDownloadButton"] button {
        background: rgba(69, 200, 149, .1);
        border-color: #45c895;
        color: #b9f2da;
    }
    .sr-badge-row { display: flex; flex-wrap: wrap; gap: .45rem; margin: .35rem 0 1rem; }
    .sr-change-badge {
        background: #1b283b;
        border: 1px solid #30415c;
        border-radius: 9px;
        color: #dce4ef;
        font-size: .84rem;
        padding: .45rem .62rem;
    }
    .sr-positive { border-color: rgba(69, 200, 149, .5); color: #70ddb3; }
    .sr-negative { border-color: rgba(239, 112, 118, .48); color: #f29a9e; }
    .sr-neutral { color: #9fb0c5; }
    .sr-status-grid {
        display: grid;
        gap: .7rem;
        grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
        margin: .8rem 0 1rem;
    }
    .sr-provider-card {
        background: #141e2e;
        border: 1px solid #293750;
        border-radius: 11px;
        min-height: 102px;
        padding: .8rem .9rem;
    }
    .sr-provider-name { color: #a9b7ca; font-size: .78rem; margin-bottom: .45rem; }
    .sr-provider-state { font-size: 1rem; font-weight: 700; margin-bottom: .25rem; }
    .sr-provider-detail { color: #8193ab; font-size: .74rem; }
    .sr-healthy { color: #70ddb3; }
    .sr-attention { color: #f0c36d; }
    .sr-unavailable { color: #f29a9e; }
    @media (max-width: 720px) {
        .sr-hero { align-items: flex-start; flex-direction: column; }
        .sr-hero-meta { align-items: flex-start; margin: .9rem 0 0 0; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)
settings = load_settings(Path.cwd())
storage = Storage(settings.database_path)
storage.initialize()
run = storage.latest_run()

if not run:
    st.title("Personal Stock Research Assistant")
    st.caption("Research and ranking only — no brokerage connectivity or trade execution")
    st.info("No run exists yet. Run `stockrank run` from the project directory.")
    st.stop()

results = storage.get_results(run["run_id"])
previous_run = storage.previous_comparable_run(run["run_id"])
previous_results = storage.get_results(previous_run["run_id"]) if previous_run else []
research = storage.get_research(run["run_id"])
context = storage.get_market_context(run["run_id"])
warnings = json.loads(run["warnings_json"])
config = json.loads(run["config_json"])
analysis_completed_at = datetime.fromisoformat(run["completed_at"]) if run["completed_at"] else None


def preference_label(value: object) -> str:
    return str(value).replace("_", " ").replace("-", "–").title()


def compact_recommendation(value: str) -> str:
    return {
        "Strong candidate": "Strong",
        "Worth further research": "Research",
        "Watchlist candidate": "Watchlist",
    }.get(value, value)


def financial_markdown(value: object) -> str:
    """Keep ordinary currency amounts out of Streamlit's dollar-delimited math parser."""
    return str(value).replace("$", r"\$")


def change_badges(rows: list[dict], *, kind: str) -> str:
    if not rows:
        return '<span class="sr-neutral">None</span>'
    badges = []
    for row in rows:
        ticker = html.escape(str(row["Ticker"]))
        if kind == "entry":
            text = f"{ticker} · rank {row['Rank']}"
            tone = "sr-positive"
        elif kind == "exit":
            text = f"{ticker} · was {row['Previous rank']}"
            tone = "sr-negative"
        elif kind == "gain":
            text = f"{ticker} ↑{abs(row['Rank change'])} · {row['Previous rank']}→{row['Current rank']}"
            tone = "sr-positive"
        elif kind == "decline":
            text = f"{ticker} ↓{abs(row['Rank change'])} · {row['Previous rank']}→{row['Current rank']}"
            tone = "sr-negative"
        else:
            delta = float(row["Score change"])
            arrow = "↑" if delta > 0 else "↓"
            tone = "sr-positive" if delta > 0 else "sr-negative"
            text = f"{ticker} {arrow}{abs(delta):.1f} · {row['Previous score']:.1f}→{row['Current score']:.1f}"
        badges.append(f'<span class="sr-change-badge {tone}">{text}</span>')
    return '<div class="sr-badge-row">' + "".join(badges) + "</div>"


run_preferences = config.get("preferences", {})
profile_name = preference_label(run_preferences.get("profile", "balanced"))
run_status = preference_label(run["status"])
st.markdown(
    f"""
    <div class="sr-hero">
      <div>
        <div class="sr-eyebrow">Daily research brief</div>
        <h1>Personal Stock Research Assistant</h1>
        <p>Analysis as of {html.escape(str(run["as_of"]))} · research and ranking only</p>
      </div>
      <div class="sr-hero-meta">
        <span class="sr-status">{html.escape(run_status)}</span>
        <span class="sr-pill">{html.escape(profile_name)} · {len(results)} stocks · Scoring {html.escape(str(run["model_version"]))} · App {html.escape(APP_VERSION)}</span>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

if run["provider"] == "demo-synthetic":
    st.error("SYNTHETIC DEMO DATA — do not use for investment decisions")
elif warnings:
    st.warning(f"This run has {len(warnings)} data-quality warning(s). See Data Quality below.")

columns = st.columns(5)
columns[0].metric("Universe", len(results))
columns[1].metric("Eligible candidates", sum(result["eligible"] for result in results))
columns[2].metric("Scoring model", run["model_version"])
columns[3].metric("Provider", run["provider"])
columns[4].metric("Profile", profile_name)
st.caption(config.get("runtime", {}).get("freshness_label", "Freshness unknown"))
st.caption(
    f"Application version: {APP_VERSION} · Run preferences: "
    f"horizon={preference_label(run_preferences.get('investment_horizon', 'medium'))} · "
    f"risk={preference_label(run_preferences.get('risk_tolerance', 'moderate'))}"
)
if (
    run["model_version"] != settings.model_version
    or run["universe_name"] != str(settings.raw["universe"]["name"])
    or run_preferences.get("profile", "balanced") != settings.profile_name
    or run_preferences.get("investment_horizon", "medium") != settings.investment_horizon
    or run_preferences.get("risk_tolerance", "moderate") != settings.risk_tolerance
):
    st.warning(
        "Your active personal configuration differs from this stored report. "
        "Run `stockrank daily-report` to create a report using the active settings."
    )

with st.expander("Customize this installation"):
    st.write(
        "Personalization is optional. The guided command can change the ranking profile, "
        "investment horizon, risk tolerance, candidate thresholds, and stock universe."
    )
    st.write(
        f"**Active configuration:** {preference_label(settings.profile_name)} profile · "
        f"{preference_label(settings.investment_horizon)} horizon · "
        f"{preference_label(settings.risk_tolerance)} risk · "
        f"{len(settings.universe)} stocks"
    )
    st.code(r".\.venv\Scripts\stockrank.exe configure", language="powershell")
    st.caption("After saving preferences, validate them before the next report:")
    st.code(r".\.venv\Scripts\stockrank.exe config-check --live", language="powershell")
    st.caption(
        "Personal files stay on this computer and are ignored by Git. The dashboard "
        "does not edit them directly."
    )

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
    st.markdown(financial_markdown(research["market_overview"]["summary"]))
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
    candidate_rows.append(
        {
            "Rank": result["rank"],
            "Ticker": result["ticker"],
            "Company": result["company"],
            "Sector": result["sector"],
            "Price": result["latest_price"],
            "Score": result["overall_score"],
            "Coverage %": result["overall_coverage"] * 100,
            "Status": compact_recommendation(result["recommendation"]),
        }
    )
if candidate_rows:
    st.caption(
        "A compact ranking view. Open a company under Research Summary for factor "
        "scores, catalysts, risks, filings, and sources."
    )
    st.dataframe(
        candidate_rows,
        width="stretch",
        hide_index=True,
        column_config={
            "Rank": st.column_config.NumberColumn(width="small"),
            "Ticker": st.column_config.TextColumn(width="small"),
            "Company": st.column_config.TextColumn(width="medium"),
            "Sector": st.column_config.TextColumn(width="medium"),
            "Price": st.column_config.NumberColumn(format="$%.2f"),
            "Score": st.column_config.ProgressColumn(
                format="%.1f", min_value=0, max_value=100, width="medium"
            ),
            "Coverage %": st.column_config.NumberColumn(format="%.0f%%"),
            "Status": st.column_config.TextColumn(width="small"),
        },
    )
    st.download_button(
        "Download all current rankings (CSV)",
        data=rankings_csv(results),
        file_name=f"stockrank-rankings-{run['as_of']}.csv",
        mime="text/csv",
        help="Exports all ranked stocks, including scores, coverage, eligibility, and factors.",
    )
    with st.expander("Candidate score comparison"):
        st.caption("Overall scores for the current eligible top list.")
        st.bar_chart(
            [
                {"Ticker": result["ticker"], "Overall score": result["overall_score"]}
                for result in candidates
            ],
            x="Ticker",
            y="Overall score",
            color="#45C895",
            height=280,
            sort=False,
        )
else:
    st.info("No company met both score and coverage thresholds; the list is not padded.")

st.header("What Changed Since the Previous Comparable Report")
if not previous_run:
    st.info("No earlier completed run with the same model and universe is available yet.")
else:
    previous_config = json.loads(previous_run["config_json"])
    previous_limit = int(previous_config.get("app", {}).get("top_candidate_limit", limit))
    changes = ranking_change_summary(
        results,
        previous_results,
        current_limit=limit,
        previous_limit=previous_limit,
    )
    st.caption(
        f"Compared with {previous_run['as_of']} · run {previous_run['run_id'][:8]} · "
        "same universe and scoring model. These are observed changes, not causal explanations."
    )
    change_columns = st.columns(2)
    with change_columns[0]:
        st.subheader("Top-list entries")
        st.markdown(
            change_badges(changes["new_candidates"], kind="entry"),
            unsafe_allow_html=True,
        )
    with change_columns[1]:
        st.subheader("Top-list exits")
        st.markdown(
            change_badges(changes["exited_candidates"], kind="exit"),
            unsafe_allow_html=True,
        )
    mover_columns = st.columns(2)
    with mover_columns[0]:
        st.subheader("Largest rank gains")
        st.markdown(
            change_badges(changes["rank_gainers"], kind="gain"),
            unsafe_allow_html=True,
        )
    with mover_columns[1]:
        st.subheader("Largest rank declines")
        st.markdown(
            change_badges(changes["rank_decliners"], kind="decline"),
            unsafe_allow_html=True,
        )
    st.subheader("Largest score changes of at least 1 point")
    st.markdown(
        change_badges(changes["score_changes"], kind="score"),
        unsafe_allow_html=True,
    )

st.header("Research Summary")
st.caption(
    "Open a company for its score profile, qualitative research, filings, and sources. "
    "SEC filings were filtered to information available by this run's completion time."
)
for result in candidates:
    note = research_companies.get(result["ticker"])
    with st.expander(f"{result['rank']}. {result['ticker']} — {result['company']}"):
        filings = SecSubmissions.effective_filings(
            tuple(storage.get_sec_filings(result["ticker"])),
            available_at=analysis_completed_at,
        )
        overview_tab, research_tab, evidence_tab = st.tabs(
            ("Score overview", "Research", "Filings & sources")
        )
        with overview_tab:
            overview_columns = st.columns(4)
            overview_columns[0].metric("Overall score", f"{result['overall_score']:.1f}")
            overview_columns[1].metric("Price", f"${result['latest_price']:,.2f}")
            overview_columns[2].metric("Coverage", f"{result['overall_coverage'] * 100:.0f}%")
            overview_columns[3].metric("Status", compact_recommendation(result["recommendation"]))
            st.caption("Price as of " + (result["price_as_of"] or "unavailable"))
            factor_rows = [
                {"Factor": component.title(), "Score": result["component_scores"].get(component)}
                for component in ("growth", "valuation", "quality", "momentum", "risk")
                if result["component_scores"].get(component) is not None
            ]
            if factor_rows:
                st.bar_chart(
                    factor_rows,
                    x="Factor",
                    y="Score",
                    color="#45C895",
                    height=245,
                    sort=False,
                )
            if result["warnings"]:
                st.caption("Data notes: " + "; ".join(result["warnings"]))
        with research_tab:
            if not note:
                st.info("Current-source qualitative research has not been imported for this run.")
            else:
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
                    st.markdown(financial_markdown(note.get(field) or "Not provided"))
        with evidence_tab:
            if filings:
                st.subheader("Latest SEC filings")
                for filing in filings[:4]:
                    report_period = (
                        filing.report_date.isoformat() if filing.report_date else "unknown"
                    )
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
            else:
                st.caption("No qualifying SEC filing metadata is stored for this company.")
            if note and note.get("sources"):
                st.subheader("Research sources")
                for source in note["sources"]:
                    st.markdown(
                        f"- [{source.get('title', 'Source')}]({source.get('url', '')}) — "
                        f"published {source.get('published_at', 'unknown')}; "
                        f"event {source.get('event_at', 'unknown')}"
                    )
            elif note:
                st.caption("No qualitative research sources were imported for this company.")

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
provider_health_rows = []
for provider, label in (
    ("sec-edgar", "SEC identity provider"),
    ("sec-submissions", "SEC submissions provider"),
    ("sec-companyfacts", "SEC Company Facts provider"),
    ("sec-financials", "SEC financial calculation layer"),
    ("provider-shadow", "SEC/Yahoo shadow comparison"),
):
    sec_health = storage.get_provider_health(provider)
    if not sec_health:
        provider_health_rows.append(
            {
                "label": label,
                "status": "Not checked",
                "tone": "sr-attention",
                "access": "No stored health record",
                "detail": "Run the daily workflow to populate this status.",
            }
        )
        continue
    health_label = {
        "healthy": "Healthy",
        "degraded": "Degraded",
        "partial": "Partial",
        "unavailable": "Unavailable",
    }.get(sec_health.status, sec_health.status.title())
    tone = (
        "sr-healthy"
        if sec_health.status == "healthy"
        else "sr-unavailable"
        if sec_health.status == "unavailable"
        else "sr-attention"
    )
    access_label = (
        "local stored data"
        if provider in {"sec-financials", "provider-shadow"}
        else "cache used"
        if sec_health.cache_hit
        else "live request"
    )
    health_detail = sec_health.detail
    if provider == "provider-shadow":
        health_detail = "; ".join(
            part for part in health_detail.split("; ") if not part.startswith("full_dates=")
        )
    provider_health_rows.append(
        {
            "label": label,
            "status": health_label,
            "tone": tone,
            "access": access_label,
            "detail": (
                f"Checked {sec_health.checked_at.isoformat()} · "
                f"{sec_health.latency_ms:.0f} ms · {health_detail}"
            ),
        }
    )
provider_cards = []
for item in provider_health_rows:
    provider_cards.append(
        '<div class="sr-provider-card">'
        f'<div class="sr-provider-name">{html.escape(item["label"])}</div>'
        f'<div class="sr-provider-state {item["tone"]}">{html.escape(item["status"])}</div>'
        f'<div class="sr-provider-detail">{html.escape(item["access"])}</div>'
        "</div>"
    )
st.markdown(
    '<div class="sr-status-grid">' + "".join(provider_cards) + "</div>",
    unsafe_allow_html=True,
)
with st.expander("Provider diagnostics and timestamps"):
    for item in provider_health_rows:
        st.write(f"**{item['label']}:** {item['status']}")
        st.caption(f"{item['access']} · {item['detail']}")
financial_rows = []
for security in settings.universe:
    financial_snapshot = storage.latest_sec_financial_snapshot(security.ticker)
    if not financial_snapshot:
        continue
    calculated = {
        (metric.metric_name, metric.period_kind): metric for metric in financial_snapshot.metrics
    }
    applicable = [metric for metric in financial_snapshot.metrics if metric.quality != "excluded"]
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
    shadow_run = storage.latest_provider_comparison_run(
        full_universe_only=True,
        config_version=shadow_config.version,
        universe_name=str(settings.raw["universe"]["name"]),
    )
    if shadow_run:
        shadow_rows = storage.get_provider_metric_comparisons(shadow_run.comparison_run_id)
        full_shadow_dates = storage.provider_comparison_full_universe_dates(
            shadow_config.version,
            str(settings.raw["app"]["timezone"]),
            universe_name=str(settings.raw["universe"]["name"]),
        )
        classification_counts = Counter(row.classification for row in shadow_rows)
        with st.expander("Step 2.4B SEC/Yahoo shadow comparison (not ranking inputs)"):
            st.caption(
                f"Run {shadow_run.comparison_run_id} · "
                f"command time {shadow_run.as_of.isoformat()} · "
                f"config {shadow_run.config_version} · "
                f"promotion evidence {full_shadow_dates}/"
                f"{shadow_config.required_full_universe_dates} distinct market-data dates"
            )
            if shadow_run.evidence_qualified and shadow_run.evidence_date:
                st.success(
                    f"This run qualifies for {shadow_run.evidence_date.isoformat()} "
                    f"(production run {shadow_run.analysis_run_id})."
                )
            else:
                st.warning(
                    "This run does not add promotion evidence: " + shadow_run.evidence_reason
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
                metric_values = [row for row in shadow_rows if row.metric_name == metric_name]
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
                    "Median relative difference %": st.column_config.NumberColumn(format="%.1f%%")
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
                (row for row in shadow_rows if row.classification == "materially_different"),
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
                                float(row.yahoo_value) if row.yahoo_value is not None else None
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
                        "Relative difference %": st.column_config.NumberColumn(format="%.1f%%")
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
with st.expander("Personal profile and scoring configuration used for this run"):
    st.write(
        {
            "profile": run_preferences.get("profile", "balanced"),
            "investment_horizon": run_preferences.get("investment_horizon", "medium"),
            "risk_tolerance": run_preferences.get("risk_tolerance", "moderate"),
            "universe_name": run["universe_name"],
            "universe_size": len(results),
        }
    )
    st.json(config.get("scoring", {}))
