import tomllib
from pathlib import Path


def test_dashboard_theme_uses_restrained_positive_accent():
    with (Path.cwd() / ".streamlit" / "config.toml").open("rb") as handle:
        config = tomllib.load(handle)

    assert config["theme"] == {
        "base": "dark",
        "primaryColor": "#45C895",
        "backgroundColor": "#0B1220",
        "secondaryBackgroundColor": "#141E2E",
        "textColor": "#E9EEF6",
        "font": "sans-serif",
    }


def test_dashboard_keeps_visuals_semantic_and_optional():
    dashboard = (Path.cwd() / "src" / "stockrank" / "dashboard.py").read_text(encoding="utf-8")

    assert '"Strong candidate": "Strong"' in dashboard
    assert 'with st.expander("Candidate score comparison")' in dashboard
    assert 'color="#45C895"' in dashboard
    assert "sr-positive" in dashboard
    assert "sr-negative" in dashboard
    assert '("Score overview", "Research", "Filings & sources")' in dashboard
    assert 'with st.expander("Provider diagnostics and timestamps")' in dashboard
