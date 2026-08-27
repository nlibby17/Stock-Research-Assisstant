# Stock Research Assistant

A local, research-only U.S. stock screener and ranking application. It downloads
daily market data, keeps compact historical results in SQLite, calculates an
interpretable score, and presents the result in a Streamlit dashboard. It never
connects to a broker and it never places trades.

Version 1 is deliberately modest: an explicit 50-company, all-sector universe,
end-of-day/previous-close analysis, and a replaceable data-provider interface.
Python performs every deterministic calculation. Codex performs the current-news,
filing, earnings, and qualitative research only when asked; there is no OpenAI API
integration.

## Quick start

Python 3.11+ is required.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Edit `.env` and set `SEC_USER_AGENT` to a descriptive application/contact value.
The default Yahoo provider does not require an API key.

```powershell
# Network-backed analysis
stockrank run

# Deterministic synthetic data, clearly labelled (useful for setup/tests only)
stockrank run --demo

# Dashboard
stockrank dashboard

# SEC ticker/CIK/exchange identity and provider-health check
stockrank sec-health

# Bypass the 24-hour SEC identity cache for an explicit live check
stockrank sec-health --force

# Storage inspection and safe cleanup preview
stockrank storage-status
stockrank storage-clean
```

The latest Markdown report is written to `runtime/reports/latest.md`. Runtime
outputs are intentionally ignored by Git.

## Architecture

The pipeline is split into replaceable layers:

1. `stockrank.data` retrieves price and summarized fundamental fields and
   provides the rate-limited SEC identity client.
2. `stockrank.storage` caches normalized values and writes immutable run history.
3. `stockrank.metrics` calculates returns, volatility, drawdown, and liquidity.
4. `stockrank.scoring` creates percentile-based component and overall scores.
5. `stockrank.reporting` produces the report and Codex research template.
6. `stockrank.dashboard` reads the same SQLite history in Streamlit.

Configuration lives in `config/preferences.toml`; the explicit universe is
`config/universe.csv`. See [docs/V1_DESIGN.md](docs/V1_DESIGN.md) for the full
architecture, source assessment, scoring rules, roadmap, retention policy, and
deferred metrics. See [CODEX.md](CODEX.md) for the standard morning workflow.

## Data sources and freshness

- **Yahoo Finance via yfinance (V1 screening source):** no key, unofficial library,
  personal research/educational use only, no service-level agreement. Daily prices
  are treated as end-of-day or previous-close—not real-time—even if a quote field
  appears newer. Fundamentals can be stale, inconsistently populated, or restated.
- **SEC EDGAR:** official, no-key ticker/CIK/exchange mappings, submissions, and
  XBRL APIs. Step 2.1 provides a declared, HTTPS-only client capped at five requests
  per second, with retry handling, a 24-hour identity cache, an explicitly labelled
  stale fallback capped at seven days, and persistent provider-health status.
  Filing discovery and Company Facts normalization follow in Steps 2.2 and 2.3.

Source and as-of timestamps are retained. Missing fields stay missing; the pipeline
does not fabricate or silently replace them. A failed source can fall back to a
still-usable local normalized cache. Demo data is never used implicitly.

## Scoring

Model `v1.0.0` uses these component weights:

- Growth 25%: revenue growth 45%, earnings growth 35%, free-cash-flow margin 20%.
- Valuation 20%: forward P/E 40%, PEG 25%, price/sales 20%, FCF yield 15%.
- Quality/health 25%: ROE 25%, profit margin 25%, gross margin 15%, debt/equity
  20% (lower is better), current ratio 15%.
- Momentum 20%: 1/3/6/12-month total returns at 10/25/30/35%.
- Risk 10%: 3-month annualized volatility 50% (lower is better), one-year maximum
  drawdown 30% (shallower is better), market capitalization 20%.

Each raw metric becomes a 0–100 percentile within that run's available universe.
Missing metrics are excluded and remaining weights are rescaled. Coverage is
reported, and a security needs at least 60% effective overall coverage to be
eligible for the top list. The report includes only scores of 55 or better, up to
10 names; it does not pad the list. Every run stores the complete configuration,
metric directions, model version, and weights so an old ranking remains legible.

## Data retained

SQLite retains compact daily bars, summarized fundamental cache entries, immutable
run rows, raw calculated metrics, component scores, rankings, labels, coverage,
research source metadata, configuration snapshots, and the latest provider-health
record. A transient runtime cache retains SEC JSON long enough to limit repeat
requests; it is not a historical archive. The application does not retain article
bodies, filing documents, credentials, or brokerage information.

Defaults: price bars 550 days, fundamental cache 24 hours, price-fetch status 6
hours, generated reports 30 days, temporary files 1 day, and rotating logs capped
near 6 MB. A new 50-stock installation should remain roughly 15–35 MB; immutable
daily run history will add approximately 20–40 MB per year at this size. Use
`stockrank storage-status` to inspect exact sizes and `stockrank storage-clean` for
a dry-run cleanup; add `--apply` to perform it. Historical run results are preserved.

## Important limitations

This is a ranking and research aid, not investment advice or a prediction engine.
Yahoo fields are convenient but not point-in-time fundamentals, so this version is
not a valid historical fundamental backtest. Analyst revisions, price targets,
earnings surprises/calendars, peer-relative valuation, insider/institutional flows,
and news catalysts are qualitative research inputs in V1 rather than ranking
factors. They require either careful primary-source work or a better licensed data
feed. The schema preserves as-of dates and model versions so a future point-in-time
provider can be added without replacing the scoring engine.

The V1 universe is manually curated under `config/universe_policy.toml`. Automatic
maintenance is intentionally deferred until exchange-listing data can be joined to
SEC ticker/CIK data and checked for liquidity, security type, corporate actions,
delistings, fundamental coverage, and sector balance. Future changes will create a
new dated universe version; prior run membership will never be rewritten.
