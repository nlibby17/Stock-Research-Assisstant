# Stock Research Assistant

[![CI](https://github.com/nlibby17/Stock-Research-Assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/nlibby17/Stock-Research-Assistant/actions/workflows/ci.yml)
[MIT licensed](LICENSE)

A local, research-only application that reviews a customizable universe of U.S.
stocks, ranks them with an interpretable scoring model, and presents the results in
a browser dashboard. It does not connect to a broker or place trades.

![Dashboard overview showing run status, ranking configuration, and market overview](docs/images/dashboard-overview.jpg)

## What it does

- Ranks an explicit stock universe using growth, valuation, quality, momentum, and
  risk metrics.
- Shows score composition, data coverage, market context, sector leaders, SEC
  filings, and source-aware research details.
- Uses local SQLite history so reports remain reproducible and comparable.
- Supports personal ranking profiles and custom ticker universes on each computer.
- Runs locally on Windows and macOS with a guided installer and desktop launcher.

Scores describe a stock's relative position within the selected universe. They are
not expected returns, investment advice, or a claim that future performance can be
predicted.

## Quick start

Install [Git](https://git-scm.com/downloads) and [Python](https://www.python.org/downloads/),
then open PowerShell on Windows or Terminal on macOS. macOS 11 users should follow
the specific Python requirement in [SETUP.md](SETUP.md).

```text
git clone https://github.com/nlibby17/Stock-Research-Assistant.git stock-research-assistant
cd stock-research-assistant
```

Run the guided installer:

```powershell
# Windows 10 or 11
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

```bash
# macOS
bash ./scripts/setup.sh
```

The installer creates a private `.env` file. Add a descriptive application name and
your real email address to `SEC_USER_AGENT`, then run `setup-check` as explained in
[SETUP.md](SETUP.md). The email is identification requested by the SEC, not an API
key or account registration.

For the simplest daily use, accept the installer's recommended desktop launcher and
double-click **Stock Research Assistant**. It builds the report and opens the
dashboard automatically.

You can also run it from the project folder:

```powershell
# Windows
.\.venv\Scripts\stockrank.exe morning
```

```bash
# macOS
./.venv/bin/stockrank morning
```

Keep the terminal window open while using the dashboard. Stop the application with
**Ctrl+C** on Windows or **Control+C (⌃C)** on macOS. The first report takes longer
because it must build the local data cache.

For complete, beginner-friendly installation, running, personalization, and update
instructions, see **[SETUP.md](SETUP.md)**.

## Dashboard

The dashboard presents the current market context, ranked candidates, score and
coverage breakdowns, three-month sector leaders, qualitative research, SEC filings,
and comparisons with a compatible previous report. All current rankings can be
downloaded as an Excel-friendly CSV.

![Expanded Research Summary for one candidate showing score, coverage, factors, and research tabs](docs/images/dashboard-research-summary.jpg)

*Example from a stored local report. Rankings are research outputs, not investment
recommendations.*

## Personalization

The default installation uses a balanced profile and an explicit 50-stock universe.
Run `stockrank configure` to choose a growth, value, quality, momentum,
lower-volatility, or balanced profile and to supply your own tickers. Personal files
remain local and are ignored by Git, so different computers can use different
settings safely.

Automatic discovery of a broader stock universe is planned but is not active yet.
The application never silently adds securities to a user's approved universe.

## How it works

1. Yahoo Finance supplies daily prices and summarized screening fundamentals.
2. SEC EDGAR supplies official company identity, filing, and Company Facts data.
3. Tested Python code calculates metrics, coverage, and relative scores.
4. SQLite stores compact caches and immutable run history locally.
5. Streamlit reads those results into the local dashboard.

Missing or stale values remain visible instead of being fabricated. SEC-derived
financial calculations are currently compared with the production provider in an
isolated shadow layer and do not silently alter rankings.

Optional current-news and qualitative research can be completed by a person or any
capable AI agent. The repository does not require an OpenAI API key and is not tied
to Codex.

## Project documentation

- [SETUP.md](SETUP.md) — install, run, personalize, update, and troubleshoot.
- [Daily workflow](docs/DAILY_WORKFLOW.md) — deterministic report and optional
  qualitative research process.
- [Roadmap](docs/ROADMAP.md) — current progress, acceptance gates, and future work.
- [V1 design](docs/V1_DESIGN.md) — architecture, calculations, sources, storage,
  limitations, and policy details.
- [Refactoring review](docs/REFACTORING_REVIEW.md) — approved code-structure review
  and implementation ledger.

## Important limitations

Yahoo Finance is convenient but unofficial and does not provide point-in-time
fundamentals suitable for a valid historical fundamental backtest. Some companies
also have sparse price, fundamental, or SEC coverage. The application reports those
limitations and keeps data coverage separate from score.

Runtime databases, caches, reports, logs, personal configuration, and `.env` are
stored locally and excluded from Git.

## License

The source and documentation are available under the [MIT License](LICENSE),
copyright 2026 `nlibby17`. Third-party data and services remain subject to their own
terms.
