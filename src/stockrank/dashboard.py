from __future__ import annotations

import html
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import median

import altair as alt
import streamlit as st

from stockrank.config import load_settings
from stockrank.presentation import (
    candidate_policy_summary,
    filings_for_completed_run,
    no_candidate_explanation,
    ranking_change_summary,
    rankings_csv,
    relative_status_label,
    score_breakdown,
)
from stockrank.provider_comparison import load_provider_comparison_config
from stockrank.storage import Storage
from stockrank.summaries import sector_member_tickers
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
        border-left: 4px solid #d6a84a;
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
    .sr-status { background: rgba(214, 168, 74, .14); color: #e7c97f; }
    .sr-pill {
        background: rgba(214, 168, 74, .10);
        border: 1px solid rgba(214, 168, 74, .42);
        color: #c9d3e1;
    }
    [data-testid="stMetric"] {
        background: #141e2e;
        border: 1px solid #293750;
        border-radius: 12px;
        min-height: 105px;
        padding: .85rem 1rem;
    }
    [data-testid="stMetricLabel"] { color: #94a6bd; }
    [data-testid="stMetricValue"] { color: #f1f5fa; }
    .sr-notice {
        background: rgba(88, 135, 184, .13);
        border: 1px solid rgba(111, 166, 217, .38);
        border-left: 4px solid #6fa6d9;
        border-radius: 10px;
        color: #c9d8e8;
        margin: .35rem 0 1rem;
        padding: .78rem .95rem;
    }
    .sr-notice strong { color: #e2edf8; }
    .sr-notice code { color: #dce9f6; }
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
    [data-testid="stExpander"] details > summary:hover {
        background: rgba(214, 168, 74, .07);
        color: #f1ddb0 !important;
    }
    [data-testid="stDownloadButton"] button {
        background: rgba(139, 123, 200, .14);
        border-color: #8b7bc8;
        color: #d8d0f3;
    }
    [data-testid="stDownloadButton"] button:hover {
        background: rgba(139, 123, 200, .24);
        border-color: #aa9bdd;
        color: #eee9ff;
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
    .sr-positive { border-color: rgba(214, 168, 74, .5); color: #e7c97f; }
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
    .sr-healthy { color: #e7c97f; }
    .sr-attention { color: #f0c36d; }
    .sr-unavailable { color: #f29a9e; }
    .sr-sector-grid {
        display: grid;
        gap: .7rem;
        grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
        margin: .65rem 0 .45rem;
    }
    .sr-sector-card {
        background: linear-gradient(145deg, #172235, #121b2a);
        border: 1px solid #34435a;
        border-top: 3px solid #d6a84a;
        border-radius: 11px;
        cursor: help;
        padding: .8rem .9rem;
        position: relative;
    }
    .sr-sector-card::after {
        background: #0f1724;
        border: 1px solid #3b4b62;
        border-radius: 8px;
        bottom: calc(100% + 8px);
        color: #e9eef6;
        content: attr(data-tooltip);
        font-size: .78rem;
        left: 50%;
        max-width: 260px;
        opacity: 0;
        padding: .5rem .65rem;
        pointer-events: none;
        position: absolute;
        text-align: center;
        transform: translate(-50%, 5px);
        transition: opacity .14s ease, transform .14s ease;
        visibility: hidden;
        white-space: normal;
        width: max-content;
        z-index: 20;
    }
    .sr-sector-card:hover::after {
        opacity: 1;
        transform: translate(-50%, 0);
        visibility: visible;
    }
    .sr-sector-rank { color: #d6a84a; font-size: .72rem; font-weight: 700; }
    .sr-sector-name { color: #f1f5fa; font-size: 1rem; font-weight: 700; margin: .2rem 0; }
    .sr-sector-return { color: #e7c97f; font-size: 1.25rem; font-weight: 700; }
    .sr-sector-members { color: #8fa1b9; font-size: .74rem; }
    .sr-candidate-table {
        border: 1px solid #293750;
        border-radius: 11px;
        margin: .55rem 0 1rem;
        overflow-x: auto;
    }
    .sr-candidate-table table { border-collapse: collapse; min-width: 920px; width: 100%; }
    .sr-candidate-table.sr-market-table table { min-width: 680px; }
    .sr-candidate-table th {
        background: #111a29;
        color: #9eacc0;
        font-size: .78rem;
        font-weight: 600;
        padding: .7rem .65rem;
        text-align: left;
        white-space: nowrap;
    }
    [data-testid="stTab"][aria-selected="true"] { color: #e7c97f !important; }
    [data-testid="stTab"]:hover {
        background: rgba(214, 168, 74, .07) !important;
        color: #f1ddb0 !important;
    }
    [data-testid="stTab"][aria-selected="true"] .react-aria-SelectionIndicator {
        background-color: #d6a84a !important;
    }
    .sr-candidate-table td {
        border-top: 1px solid #293750;
        color: #e9eef6;
        font-size: .82rem;
        padding: .62rem .65rem;
        white-space: nowrap;
    }
    .sr-candidate-table .sr-number { text-align: right; }
    .sr-score-cell { align-items: center; display: flex; gap: .55rem; min-width: 150px; }
    .sr-score-track {
        background: #202c3e;
        border-radius: 999px;
        cursor: help;
        height: .45rem;
        overflow: hidden;
        width: 105px;
    }
    .sr-score-fill { background: #d6a84a; border-radius: inherit; height: 100%; }
    .sr-score-value { color: #dfe7f2; font-variant-numeric: tabular-nums; }
    .sr-candidate-intro {
        color: #8fa1b9;
        font-size: .88rem;
        margin: .15rem 0 .45rem;
    }
    .sr-rule-highlight { color: #e7c97f; }
    .sr-accent-notice {
        background: rgba(214, 168, 74, .10);
        border: 1px solid rgba(214, 168, 74, .42);
        border-left: 4px solid #d6a84a;
        border-radius: 9px;
        color: #ead9b4;
        margin: .5rem 0;
        padding: .72rem .85rem;
    }
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
previous_run, comparison_limitations = storage.previous_comparable_run_assessment(run["run_id"])
previous_results = storage.get_results(previous_run["run_id"]) if previous_run else []
research = storage.get_research(run["run_id"])
context = storage.get_market_context(run["run_id"])
warnings = json.loads(run["warnings_json"])
config = json.loads(run["config_json"])
manifest = json.loads(run["manifest_json"]) if run["manifest_json"] else None
reproducibility_reasons = json.loads(run["reproducibility_reasons_json"])
analysis_completed_at = datetime.fromisoformat(run["completed_at"]) if run["completed_at"] else None
freshness_record = config.get("runtime", {}).get("data_freshness", {})
scoring_quality = config.get("runtime", {}).get("scoring_quality", {})
market_summary = config.get("runtime", {}).get("market_summary", {})
run_component_weights = config.get("scoring", {}).get("overall", {})

SCORE_HELP = (
    "Overall score combines the stock's available growth, valuation, quality, "
    "momentum, and risk scores."
)
COVERAGE_HELP = "Coverage is the share of weighted scoring inputs with usable data."
SCORE_TIER_HELP = "Score tier is based on the stock's score relative to the selected universe."
MOMENTUM_1M_HELP = "Price return over approximately the trailing one month."
MOMENTUM_3M_HELP = "Price return over approximately the trailing three months."


def preference_label(value: object) -> str:
    return str(value).replace("_", " ").replace("-", "–").title()


def score_tier(value: str) -> str:
    value = relative_status_label(value)
    return {
        "High relative score": "Top tier",
        "Above-average relative score": "Upper tier",
        "Relative watchlist": "Watchlist tier",
        "Lower relative score": "Lower tier",
        "Insufficient coverage": "Insufficient data",
    }.get(value, value)


def financial_markdown(value: object) -> str:
    """Keep ordinary currency amounts out of Streamlit's dollar-delimited math parser."""
    return str(value).replace("$", r"\$")


def metric_help_key(items: tuple[tuple[str, str], ...]) -> None:
    """Render a compact native-help key immediately below a table."""
    key = st.container(horizontal=True, gap="small")
    key.caption("**Key:**", width="content")
    for label, description in items:
        key.caption(label, help=description, width="content")


def gold_gradient(count: int) -> list[str]:
    """Return a rank-ordered gold gradient that remains visibly gold at both ends."""
    if count <= 0:
        return []
    start = (214, 168, 74)
    end = (241, 220, 162)
    denominator = max(count - 1, 1)
    return [
        "#" + "".join(f"{round(a + (b - a) * index / denominator):02X}" for a, b in zip(start, end))
        for index in range(count)
    ]


def accent_notice(message: str) -> None:
    """Render a non-urgent positive message using the dashboard's gold accent."""
    st.markdown(
        f'<div class="sr-accent-notice">{html.escape(message)}</div>',
        unsafe_allow_html=True,
    )


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
run_app_config = config.get("app", {})
run_eligibility = config.get("scoring", {}).get("eligibility", {})
profile_name = preference_label(run_preferences.get("profile", "balanced"))
run_status = preference_label(run["status"])
configuration_differs = bool(
    run["model_version"] != settings.model_version
    or run["universe_name"] != str(settings.raw["universe"]["name"])
    or run_preferences.get("profile", "balanced") != settings.profile_name
    or run_preferences.get("investment_horizon", "medium") != settings.investment_horizon
    or run_preferences.get("risk_tolerance", "moderate") != settings.risk_tolerance
)
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
st.caption(
    "To stop the dashboard, return to its terminal and press Control+C "
    "(⌃C on macOS; Ctrl+C on Windows). Closing this browser tab does not stop it."
)
if configuration_differs:
    st.markdown(
        '<div class="sr-notice"><strong>Saved report notice:</strong> Your active personal '
        "configuration differs from this stored report. Run <code>stockrank morning</code> "
        "to create and open an updated report.</div>",
        unsafe_allow_html=True,
    )

if run["provider"] == "demo-synthetic":
    st.error("SYNTHETIC DEMO DATA — do not use for investment decisions")
elif warnings:
    st.warning(
        f"This run has {len(warnings)} data-quality warning(s). "
        "See Data quality and diagnostics below."
    )

summary_cards = st.container(horizontal=True, wrap=True, gap="small")
summary_cards.metric("Universe", len(results), width=210)
summary_cards.metric(
    "Eligible candidates", sum(result["eligible"] for result in results), width=210
)
summary_cards.metric("Scoring model", run["model_version"], width=210)
summary_cards.metric("Provider", run["provider"], width=210)
summary_cards.metric(
    "Ranking style",
    profile_name,
    help=(
        "The selected weighting profile. Balanced is a real profile; other profiles tilt "
        "the ranking toward growth, value, quality, momentum, or lower volatility."
    ),
    width=210,
)
with st.expander("Run details"):
    st.caption(config.get("runtime", {}).get("freshness_label", "Freshness unknown"))
    if scoring_quality:
        weak_peer_metrics = scoring_quality.get("metrics_below_minimum", [])
        st.caption(
            f"Metric peer minimum: {scoring_quality.get('minimum_metric_peer_count')} · "
            + (
                "All configured metrics passed"
                if not weak_peer_metrics
                else "Below minimum: " + ", ".join(weak_peer_metrics)
            )
        )
    if freshness_record:
        fundamental_states = Counter(
            value.get("status", "unknown")
            for value in freshness_record.get("fundamentals", {}).values()
        )
        price_series_states = Counter(
            value.get("series_status", "legacy")
            for value in freshness_record.get("prices", {}).values()
        )
        st.caption(
            "Price refresh: "
            f"{preference_label(freshness_record.get('price_refresh_status', 'unknown'))} · "
            "Price-series continuity: "
            + ", ".join(
                f"{preference_label(key)} {value}"
                for key, value in sorted(price_series_states.items())
            )
            + " · "
            "Fundamentals: "
            + ", ".join(
                f"{preference_label(key)} {value}"
                for key, value in sorted(fundamental_states.items())
            )
        )
    st.caption(
        f"Application version: {APP_VERSION} · Run preferences: "
        f"horizon={preference_label(run_preferences.get('investment_horizon', 'medium'))} · "
        f"risk={preference_label(run_preferences.get('risk_tolerance', 'moderate'))}"
    )
    if run["reproducibility_status"] == "recorded" and manifest:
        st.caption(
            "Reproducibility: recorded · "
            f"manifest {manifest['manifest_version']} · "
            f"contract {manifest['calculation_contract_fingerprint'][:10]}"
        )
if run["reproducibility_status"] != "recorded" or not manifest:
    st.warning(
        "This legacy run has limited reproducibility: "
        + "; ".join(reproducibility_reasons or ["formal manifest unavailable"])
    )
with st.expander("Personalize ranking and universe"):
    st.write(
        "Change the ranking style, horizon, risk tolerance, candidate thresholds, or universe."
    )
    st.write(
        f"**Active configuration:** {preference_label(settings.profile_name)} profile · "
        f"{preference_label(settings.investment_horizon)} horizon · "
        f"{preference_label(settings.risk_tolerance)} risk · "
        f"{len(settings.universe)} stocks"
    )
    windows_tab, unix_tab = st.tabs(("Windows", "macOS / Linux"))
    with windows_tab:
        st.code(
            ".\\.venv\\Scripts\\stockrank.exe configure\n"
            ".\\.venv\\Scripts\\stockrank.exe config-check --live",
            language="powershell",
        )
    with unix_tab:
        st.code(
            "./.venv/bin/stockrank configure\n"
            "./.venv/bin/stockrank config-check --live",
            language="bash",
        )
    st.caption(
        "Run configure first, then config-check. Personal settings stay on this computer."
    )

st.header("Market Overview")
market_table_rows = []
for ticker, value in context.items():
    price = value["price"]
    momentum_1m = value["momentum_1m"]
    momentum_3m = value["momentum_3m"]
    market_table_rows.append(
        "<tr>"
        f"<td>{html.escape(str(ticker))}</td>"
        f"<td>{html.escape(str(value['category']))}</td>"
        f'<td class="sr-number">{f"${float(price):,.2f}" if price is not None else "Unavailable"}</td>'
        f"<td>{html.escape(str(value['price_as_of'] or 'Unavailable'))}</td>"
        f'<td class="sr-number">{f"{float(momentum_1m):.1%}" if momentum_1m is not None else "Unavailable"}</td>'
        f'<td class="sr-number">{f"{float(momentum_3m):.1%}" if momentum_3m is not None else "Unavailable"}</td>'
        "</tr>"
    )
st.markdown(
    '<div class="sr-candidate-table sr-market-table"><table><thead><tr>'
    "<th>Ticker</th><th>Role</th><th>Price</th><th>As of</th><th>1M %</th><th>3M %</th>"
    "</tr></thead><tbody>"
    + "".join(market_table_rows)
    + "</tbody></table></div>",
    unsafe_allow_html=True,
)
metric_help_key(
    (
        ("1M %", MOMENTUM_1M_HELP),
        ("3M %", MOMENTUM_3M_HELP),
    )
)
if research and research.get("market_overview", {}).get("summary"):
    st.markdown(financial_markdown(research["market_overview"]["summary"]))
    for source in research["market_overview"].get("sources", []):
        st.markdown(
            f"- [{source.get('title', 'Source')}]({source.get('url', '')}) — "
            f"published {source.get('published_at', 'unknown')}"
        )

st.subheader("3-Month Sector Leaders")
sector_leaders = market_summary.get("sector_momentum_3m", [])
if sector_leaders:
    sector_cards = []
    for position, leader in enumerate(sector_leaders, start=1):
        sector_name = str(leader["sector"])
        included_tickers = leader.get("tickers") or sector_member_tickers(
            results, sector_name
        )
        member_tooltip = "Included stocks: " + ", ".join(included_tickers)
        sector_cards.append(
            f'<div class="sr-sector-card" data-tooltip="{html.escape(member_tooltip)}">'
            f'<div class="sr-sector-rank">#{position} IN THIS UNIVERSE</div>'
            f'<div class="sr-sector-name">{html.escape(sector_name)}</div>'
            f'<div class="sr-sector-return">{float(leader["median_return_3m"]):+.1%}</div>'
            f'<div class="sr-sector-members">{int(leader["member_count"])} usable companies</div>'
            "</div>"
        )
    st.markdown(
        '<div class="sr-sector-grid">' + "".join(sector_cards) + "</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Median three-month stock return within this selected universe; sectors need at "
        "least three usable companies. This is not a whole-market sector ranking."
    )
else:
    st.caption(
        "Sector leaders will appear after the next report created with scoring model v1.3.0 "
        "or newer. Existing reports are preserved unchanged."
    )

st.header("Top Candidates Within This Universe")
limit = int(run_app_config.get("top_candidate_limit", settings.raw["app"]["top_candidate_limit"]))
candidates = [result for result in results if result["eligible"]][:limit]
research_companies = {
    item.get("ticker", "").upper(): item for item in (research or {}).get("companies", [])
}
if candidates:
    stored_policy = candidate_policy_summary(run_app_config, run_eligibility)
    qualification_rules = (
        '<span class="sr-rule-highlight">' + html.escape(stored_policy) + "</span>"
        if stored_policy
        else "complete stored thresholds unavailable for this legacy run"
    )
    st.markdown(
        '<div class="sr-candidate-intro">Highest eligible scores within this universe. '
        f"Entry requires {qualification_rules}. These are relative research "
        "rankings, not buy or sell recommendations.</div>",
        unsafe_allow_html=True,
    )
    candidate_table_rows = []
    for result in candidates:
        breakdown = html.escape(score_breakdown(result, run_component_weights), quote=True)
        score = float(result["overall_score"])
        candidate_table_rows.append(
            "<tr>"
            f'<td class="sr-number">{int(result["rank"])}</td>'
            f'<td>{html.escape(str(result["ticker"]))}</td>'
            f'<td>{html.escape(str(result["company"]))}</td>'
            f'<td>{html.escape(str(result["sector"]))}</td>'
            f'<td class="sr-number">${float(result["latest_price"]):,.2f}</td>'
            f'<td title="{breakdown}"><div class="sr-score-cell">'
            f'<div class="sr-score-track" title="{breakdown}">'
            f'<div class="sr-score-fill" style="width:{score:.1f}%"></div></div>'
            f'<span class="sr-score-value">{score:.1f}</span></div></td>'
            f'<td class="sr-number">{float(result["overall_coverage"]):.0%}</td>'
            f'<td>{html.escape(score_tier(result["recommendation"]))}</td>'
            "</tr>"
        )
    st.markdown(
        '<div class="sr-candidate-table"><table><thead><tr>'
        "<th>Rank</th><th>Ticker</th><th>Company</th><th>Sector</th><th>Price</th>"
        "<th>Score</th><th>Coverage %</th><th>Score Tier</th>"
        "</tr></thead><tbody>"
        + "".join(candidate_table_rows)
        + "</tbody></table></div>",
        unsafe_allow_html=True,
    )
    metric_help_key(
        (
            ("Score", SCORE_HELP),
            ("Coverage %", COVERAGE_HELP),
            ("Score Tier", SCORE_TIER_HELP),
        )
    )
    st.download_button(
        "Download all current rankings (CSV)",
        data=rankings_csv(results),
        file_name=f"stockrank-rankings-{run['as_of']}.csv",
        mime="text/csv",
        help=(
            "Exports all relative rankings, including scores, coverage, eligibility, and factors."
        ),
    )
    st.header("Candidate Score Comparison")
    st.caption("Overall scores for the current eligible top list.")
    chart_rows = [
        {
            "Ticker": result["ticker"],
            "Overall score": result["overall_score"],
            "Score breakdown": score_breakdown(result, run_component_weights),
        }
        for result in candidates
    ]
    candidate_tickers = [result["ticker"] for result in candidates]
    candidate_colors = gold_gradient(len(candidates))
    score_chart = (
        alt.Chart(alt.Data(values=chart_rows))
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X(
                "Ticker:N",
                sort=candidate_tickers,
                axis=alt.Axis(labelAngle=0, title=None),
            ),
            y=alt.Y(
                "Overall score:Q",
                scale=alt.Scale(domain=[0, 100], clamp=True),
                axis=alt.Axis(title="Overall score", titlePadding=14),
            ),
            color=alt.Color(
                "Ticker:N",
                scale=alt.Scale(domain=candidate_tickers, range=candidate_colors),
                legend=None,
            ),
            tooltip=[
                alt.Tooltip("Ticker:N"),
                alt.Tooltip("Overall score:Q", format=".1f"),
                alt.Tooltip("Score breakdown:N"),
            ],
        )
        .properties(height=280, padding={"left": 18, "right": 8, "top": 4, "bottom": 4})
    )
    st.altair_chart(score_chart, width="stretch", theme=None)
else:
    st.info(no_candidate_explanation(results, run_app_config, run_eligibility))

st.header("Research Summary")
filing_cutoff_disclosure = filings_for_completed_run((), analysis_completed_at)
if filing_cutoff_disclosure.limitation:
    st.caption(
        "Open a company for its score profile, qualitative research, filings, and sources. "
        + filing_cutoff_disclosure.limitation
    )
else:
    st.caption(
        "Open a company for its score profile, qualitative research, filings, and sources. "
        "SEC filings were filtered to information available by this run's completion time."
    )
for result in candidates:
    note = research_companies.get(result["ticker"])
    with st.expander(f"{result['rank']}. {result['ticker']} — {result['company']}"):
        filing_disclosure = filings_for_completed_run(
            tuple(storage.get_sec_filings(result["ticker"])),
            analysis_completed_at,
        )
        filings = filing_disclosure.filings
        overview_tab, research_tab, evidence_tab = st.tabs(
            ("Score overview", "Research", "Filings & sources")
        )
        with overview_tab:
            overview_columns = st.columns(4)
            overview_columns[0].metric(
                "Overall score", f"{result['overall_score']:.1f}", help=SCORE_HELP
            )
            overview_columns[1].metric("Price", f"${result['latest_price']:,.2f}")
            overview_columns[2].metric(
                "Coverage", f"{result['overall_coverage'] * 100:.0f}%", help=COVERAGE_HELP
            )
            overview_columns[3].metric(
                "Score Tier",
                score_tier(result["recommendation"]),
                help=SCORE_TIER_HELP,
            )
            st.caption("Price as of " + (result["price_as_of"] or "unavailable"))
            factor_rows = []
            for component in ("growth", "valuation", "quality", "momentum", "risk"):
                coverage = float(result["component_coverage"].get(component, 0.0))
                factor_rows.append(
                    {
                        "Factor": component.title(),
                        "Score": result["component_scores"].get(component),
                        "Coverage %": coverage * 100,
                        "Data status": (
                            "Complete"
                            if coverage >= 1.0 - 1e-9
                            else "Partial"
                            if coverage > 0
                            else "Unavailable"
                        ),
                    }
                )
            st.dataframe(
                factor_rows,
                width="stretch",
                hide_index=True,
                column_config={
                    "Score": st.column_config.NumberColumn(format="%.1f", help=SCORE_HELP),
                    "Coverage %": st.column_config.NumberColumn(
                        format="%.0f%%", help=COVERAGE_HELP
                    ),
                },
            )
            scored_factor_rows = [row for row in factor_rows if row["Score"] is not None]
            if scored_factor_rows:
                factor_chart = (
                    alt.Chart(alt.Data(values=scored_factor_rows))
                    .mark_bar(
                        color="#D6A84A", cornerRadiusTopLeft=3, cornerRadiusTopRight=3
                    )
                    .encode(
                        x=alt.X(
                            "Factor:N",
                            sort=["Growth", "Valuation", "Quality", "Momentum", "Risk"],
                            axis=alt.Axis(labelAngle=0, title=None),
                        ),
                        y=alt.Y(
                            "Score:Q",
                            scale=alt.Scale(domain=[0, 100], clamp=True),
                            axis=alt.Axis(title="Factor score", titlePadding=14),
                        ),
                        tooltip=[
                            alt.Tooltip("Factor:N"),
                            alt.Tooltip("Score:Q", format=".1f"),
                            alt.Tooltip("Coverage %:Q", format=".0f"),
                            alt.Tooltip("Data status:N"),
                        ],
                    )
                    .properties(
                        height=245,
                        padding={"left": 18, "right": 8, "top": 4, "bottom": 4},
                    )
                )
                st.altair_chart(factor_chart, width="stretch", theme=None)
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
            elif filing_disclosure.limitation:
                st.caption(filing_disclosure.limitation)
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

st.subheader("What changed since the previous comparable report")
if not previous_run:
    detail = "; ".join(comparison_limitations)
    st.info(
        "No earlier run passed the complete historical-comparison contract."
        + (f" Nearest-history limitation: {detail}." if detail else "")
    )
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
        "same recorded calculation contract and exact universe membership. "
        "These are observed changes, not causal explanations."
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

st.subheader("Data quality and diagnostics")
st.caption(
    "SEC Company Facts and Step 2.4A local calculations are monitored here, but "
    "remain isolated from ranking inputs through the Step 2.4B shadow comparison "
    "and explicit Step 2.4C promotion decision."
)
if warnings:
    for warning in warnings:
        st.write(f"- {warning}")
else:
    st.caption("No run-level warnings were recorded.")
if scoring_quality:
    peer_counts = scoring_quality.get("metric_peer_counts", {})
    peer_minimum = scoring_quality.get("minimum_metric_peer_count")
    with st.expander("Scoring metric peer samples"):
        st.caption(
            "Percentiles are calculated only when a metric meets the configured peer minimum. "
            "Smaller samples are withheld rather than allowed to create extreme ranks."
        )
        st.dataframe(
            [
                {
                    "Metric": preference_label(metric),
                    "Usable peers": count,
                    "Minimum": peer_minimum,
                    "Status": "Eligible" if count >= peer_minimum else "Withheld",
                }
                for metric, count in sorted(
                    peer_counts.items(), key=lambda item: (item[1], item[0])
                )
            ],
            width="stretch",
            hide_index=True,
        )
if freshness_record:
    with st.expander("Per-stock price and fundamental freshness"):
        price_records = freshness_record.get("prices", {})
        fundamental_records = freshness_record.get("fundamentals", {})
        freshness_rows = []
        for ticker in sorted(set(price_records) | set(fundamental_records)):
            price = price_records.get(ticker, {})
            fundamental = fundamental_records.get(ticker, {})
            freshness_rows.append(
                {
                    "Ticker": ticker,
                    "Price status": preference_label(price.get("status", "unknown")),
                    "Price as of": price.get("price_as_of"),
                    "Price age (hours)": price.get("age_hours"),
                    "Fundamental status": preference_label(fundamental.get("status", "unknown")),
                    "Fundamentals fetched": fundamental.get("fetched_at"),
                    "Fundamental age (hours)": fundamental.get("age_hours"),
                }
            )
        st.dataframe(
            freshness_rows,
            width="stretch",
            hide_index=True,
            column_config={
                "Price age (hours)": st.column_config.NumberColumn(format="%.1f"),
                "Fundamental age (hours)": st.column_config.NumberColumn(format="%.1f"),
            },
        )
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
with st.expander("Provider status and diagnostics"):
    st.markdown(
        '<div class="sr-status-grid">' + "".join(provider_cards) + "</div>",
        unsafe_allow_html=True,
    )
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
            "Formula evidence": (
                financial_snapshot.formula_manifest["fingerprint"][:10]
                if financial_snapshot.formula_manifest
                else "Legacy limited"
            ),
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
                accent_notice(
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
