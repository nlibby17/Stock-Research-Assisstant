# Setup on a New Computer

This application is local by design. Each clone creates its own ignored `runtime/`
directory containing its SQLite database, caches, reports, and logs. A new user does
not need another user's runtime data.

## Windows 10 or 11

Install Git and Python 3.11 or newer, clone the repository, and open PowerShell in
the repository root. Then run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

Edit `.env` and replace the `SEC_USER_AGENT` placeholder with an application name
and a real contact email. The SEC requests this identification for automated data
access; it is not an API key. Then verify the installation:

```powershell
.\.venv\Scripts\stockrank.exe setup-check
```

An experienced user may supply the value during setup instead:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1 `
  -SecUserAgent "Personal Stock Research Assistant name@example.com"
```

## Personalize your installation

Personalization is optional. The default balanced profile and curated 50-stock
universe work immediately. To create settings for this computer, run:

```powershell
.\.venv\Scripts\stockrank.exe configure
```

The guided command asks for a ranking profile, investment horizon, risk tolerance,
candidate thresholds, and whether to keep or replace the stock universe. Available
profiles are balanced, growth, value, quality, momentum, and lower-volatility.
Horizon and risk choices adjust the effective component weights; the command shows
the exact weights and asks for confirmation before saving them.

To supply a universe directly, either paste tickers:

```powershell
.\.venv\Scripts\stockrank.exe configure --tickers "MSFT,JPM,PLTR,SOFI"
```

or import a CSV containing `ticker` and optional `company` and `sector` columns:

```powershell
.\.venv\Scripts\stockrank.exe configure --universe-file .\my-stocks.csv
```

When names or sectors are omitted, the command attempts to retrieve them from
Yahoo. It displays warnings when metadata cannot be validated and does not save an
invalid universe. For scripting or experienced users, run `stockrank configure
--help`; `--yes` accepts a fully specified non-interactive configuration, and
`--weights` accepts advanced component weights that total 1.0.

Personal settings are written to `config/preferences.local.toml` and a custom
universe to `config/universe.local.csv`. Both are ignored by Git, so two computers
can use the same repository with different preferences. Every effective scoring
configuration and universe receives a reproducible identifier, and previous reports
retain the configuration with which they were created.

Validate locally after any change:

```powershell
.\.venv\Scripts\stockrank.exe config-check
```

Before the first live report for a new universe, also verify Yahoo price and SEC
identity coverage:

```powershell
.\.venv\Scripts\stockrank.exe config-check --live
```

Obscure, newly listed, foreign, OTC, or unusually structured securities may lack
reliable Yahoo fundamentals, sufficient price history, or SEC Company Facts. The
application reports those limitations rather than filling gaps. Automatic discovery
of obscure candidates is a later Step 2.5 proposal workflow; this command activates
only tickers the user explicitly supplies and approves.

To keep personal profile choices but restore the default 50-stock universe, run
`stockrank configure --use-default-universe`. To restore every project default, run:

```powershell
.\.venv\Scripts\stockrank.exe configure --reset
```

Reset preserves the prior local files as ignored `.bak` files.

## Update an existing Windows installation

Stop the dashboard and any report command, open PowerShell in the project folder,
and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\update.ps1
```

The updater refuses to proceed when tracked or untracked project files have local
changes, uses a fast-forward-only Git pull, synchronizes Python dependencies, checks
the installation and active configuration, and runs the tests. It verifies that
`.env`, `config/preferences.local.toml`, and `config/universe.local.csv` are unchanged;
ignored `runtime/` data is not touched. If you intentionally need a faster update,
`-SkipTests` skips only the test suite—not setup or configuration validation.

The dashboard also contains a read-only **Customize this installation** section
showing the active profile and the commands above. Personal settings are still
changed through `stockrank configure`, where validation and backups are enforced.

## Manual or non-Windows setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

On macOS or Linux, use `.venv/bin/python -m pip install -e ".[dev]"` for the second
command. Then copy `.env.example` to `.env`, configure `SEC_USER_AGENT`, and run
the platform's `stockrank setup-check` executable from the repository root.

## First report

The first live run downloads substantially more SEC data than later cached runs and
can take several minutes:

```powershell
.\.venv\Scripts\stockrank.exe daily-report
.\.venv\Scripts\stockrank.exe dashboard
```

The dashboard opens locally. The deterministic command produces a base report and
`runtime/reports/research_template.json`; it does not claim to perform qualitative
news research. See `docs/DAILY_WORKFLOW.md` for the optional human/AI research step.

## Existing history

To start fresh, do nothing: `runtime/` is created automatically. To migrate an
existing installation's history, stop the dashboard and all report commands, then
copy the entire `runtime/` directory separately from Git. Never commit `.env` or
`runtime/`.
