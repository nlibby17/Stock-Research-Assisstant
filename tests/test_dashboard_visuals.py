import tomllib
from pathlib import Path

from stockrank import __version__
from stockrank.version import APP_VERSION


def test_dashboard_theme_uses_restrained_positive_accent():
    with (Path.cwd() / ".streamlit" / "config.toml").open("rb") as handle:
        config = tomllib.load(handle)

    assert config["theme"] == {
        "base": "dark",
        "primaryColor": "#D6A84A",
        "backgroundColor": "#0B1220",
        "secondaryBackgroundColor": "#141E2E",
        "textColor": "#E9EEF6",
        "font": "sans-serif",
    }
    assert config["client"]["toolbarMode"] == "viewer"


def test_dashboard_keeps_visuals_semantic_and_optional():
    dashboard = (Path.cwd() / "src" / "stockrank" / "dashboard.py").read_text(encoding="utf-8")

    assert '"High relative score": "Top tier"' in dashboard
    assert "value = relative_status_label(value)" in dashboard
    assert 'st.header("Candidate Score Comparison")' in dashboard
    assert 'color="#D6A84A"' in dashboard
    assert "candidate_colors = gold_gradient(len(candidates))" in dashboard
    assert "scale=alt.Scale(domain=candidate_tickers, range=candidate_colors)" in dashboard
    assert "def gold_gradient(count: int) -> list[str]:" in dashboard
    assert "#45C895" not in dashboard
    assert "#45c895" not in dashboard
    assert "rgba(69, 200, 149" not in dashboard
    assert "scale=alt.Scale(domain=[0, 100], clamp=True)" in dashboard
    assert ".interactive()" not in dashboard
    assert "sr-positive" in dashboard
    assert "sr-negative" in dashboard
    assert "border-left: 4px solid #d6a84a;" in dashboard
    assert '[data-testid="stTab"][aria-selected="true"]' in dashboard
    assert '[data-testid="stTab"]:hover' in dashboard
    assert ".react-aria-SelectionIndicator" in dashboard
    assert 'st.subheader("3-Month Sector Leaders")' in dashboard
    assert 'market_summary.get("sector_momentum_3m", [])' in dashboard
    assert 'data-tooltip="{html.escape(member_tooltip)}"' in dashboard
    assert "sector_member_tickers(" in dashboard
    assert 'metric_help_key(' in dashboard
    assert '("Score Tier", SCORE_TIER_HELP)' in dashboard
    assert '("1M %", MOMENTUM_1M_HELP)' in dashboard
    assert '("3M %", MOMENTUM_3M_HELP)' in dashboard
    assert "sr-help-icon" not in dashboard
    assert "Score ⓘ" not in dashboard
    assert "Coverage % ⓘ" not in dashboard
    assert "Score Tier ⓘ" not in dashboard
    assert "Ranking style ⓘ" not in dashboard
    assert "score_breakdown(result, run_component_weights)" in dashboard
    assert '<div class="sr-candidate-table sr-market-table"><table><thead><tr>' in dashboard
    assert "<th>Ticker</th><th>Role</th><th>Price</th><th>As of</th>" in dashboard
    assert dashboard.index('<div class="sr-candidate-table sr-market-table">') < dashboard.index(
        'metric_help_key(\n    (\n        ("1M %", MOMENTUM_1M_HELP)'
    )
    assert 'key.caption("**Key:**", width="content")' in dashboard
    assert 'key.caption(label, help=description, width="content")' in dashboard
    assert dashboard.index('+ "</tbody></table></div>",\n        unsafe_allow_html=True,\n    )') < dashboard.index(
        'metric_help_key(\n        (\n            ("Score", SCORE_HELP)'
    )
    assert '<span class="sr-rule-highlight">price ≥ $' in dashboard
    assert 'summary_cards = st.container(horizontal=True, wrap=True, gap="small")' in dashboard
    assert '"Ranking style",\n    profile_name,\n    help=(' in dashboard
    assert '("Score overview", "Research", "Filings & sources")' in dashboard
    assert 'with st.expander("Provider status and diagnostics")' in dashboard
    assert 'with st.expander("Scoring metric peer samples")' in dashboard
    assert 'with st.expander("Run details")' in dashboard
    assert 'with st.expander("Personalize ranking and universe")' in dashboard
    assert 'st.tabs(("Windows", "macOS / Linux"))' in dashboard
    assert '"./.venv/bin/stockrank configure\\n"' in dashboard
    assert '"./.venv/bin/stockrank config-check --live"' in dashboard
    assert '"Coverage %": coverage * 100' in dashboard
    assert "def financial_markdown" in dashboard
    assert "st.markdown(financial_markdown(note.get(field)" in dashboard
    assert "Closing this browser tab does not stop it." in dashboard
    assert dashboard.index('st.header("Research Summary")') < dashboard.index(
        'st.subheader("What changed since the previous comparable report")'
    )
    assert dashboard.index(
        'st.subheader("What changed since the previous comparable report")'
    ) < dashboard.index('st.subheader("Data quality and diagnostics")')
    assert "st.bar_chart(" not in dashboard
    assert "factor_chart = (" in dashboard
    assert ".sr-healthy { color: #e7c97f; }" in dashboard
    assert "st.success(" not in dashboard
    assert "accent_notice(" in dashboard


def test_dashboard_distinguishes_application_and_scoring_versions():
    dashboard = (Path.cwd() / "src" / "stockrank" / "dashboard.py").read_text(encoding="utf-8")
    with (Path.cwd() / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]

    assert __version__ == APP_VERSION == project["version"] == "0.6.0"
    assert 'summary_cards.metric("Scoring model", run["model_version"], width=210)' in dashboard
    assert 'f"Application version: {APP_VERSION} · Run preferences: "' in dashboard


def test_dashboard_uses_stored_report_candidate_rules():
    dashboard = (Path.cwd() / "src" / "stockrank" / "dashboard.py").read_text(
        encoding="utf-8"
    )

    assert 'run_app_config = config.get("app", {})' in dashboard
    assert 'run_eligibility = config.get("scoring", {}).get("eligibility", {})' in dashboard
    assert 'limit = int(run_app_config.get("top_candidate_limit"' in dashboard
    assert 'run_app_config.get("minimum_candidate_score", 0)' in dashboard
    assert 'run_app_config.get("minimum_overall_coverage", 0)' in dashboard


def test_configuration_notice_precedes_summary_cards_and_is_nonurgent():
    dashboard = (Path.cwd() / "src" / "stockrank" / "dashboard.py").read_text(
        encoding="utf-8"
    )

    assert '<div class="sr-notice"><strong>Saved report notice:' in dashboard
    assert dashboard.index('if configuration_differs:') < dashboard.index(
        "summary_cards = st.container"
    )
    assert "background: rgba(88, 135, 184, .13);" in dashboard
