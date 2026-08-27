from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import streamlit as st

from stockrank.config import load_settings
from stockrank.data.sec import SecSubmissions
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
    "SEC Company Facts are normalized and monitored here, but remain isolated "
    "from ranking inputs until the Step 2.4 provider comparison is approved."
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
    st.caption(
        f"Checked {sec_health.checked_at.isoformat()} · "
        f"{'cache used' if sec_health.cache_hit else 'live request'} · "
        f"{sec_health.latency_ms:.0f} ms · {sec_health.detail}"
    )
with st.expander("Scoring configuration snapshot"):
    st.json(config.get("scoring", {}))
