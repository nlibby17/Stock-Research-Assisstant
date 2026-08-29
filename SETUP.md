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

## macOS

The guided installer supports macOS 11 or newer and avoids compiling dependencies:

- On **macOS 12 or newer**, install Git and Python **3.13**.
- On **macOS 11**, install Git and the official
  [Python 3.12.10 universal2 installer](https://www.python.org/downloads/release/python-31210/).
  It supports both Intel and Apple Silicon Macs. Python 3.12 and Python 3.13 can
  safely remain installed together; the setup helper explicitly selects 3.12 on
  macOS 11.

After installation, open Terminal and confirm Git and the Python version for the
Mac are available:

```bash
git --version
# macOS 12 or newer:
python3.13 --version

# macOS 11:
python3.12 --version
```

Clone the repository and enter its folder. These commands work whether Git and
Python came from their official installers or Homebrew:

```bash
git clone https://github.com/nlibby17/Stock-Research-Assisstant.git stock-research-assistant
cd stock-research-assistant
```

Run the guided setup helper. Calling it through `bash` avoids macOS executable-
permission and Finder-download differences:

```bash
bash ./scripts/setup.sh
```

Open the newly created private environment file in TextEdit:

```bash
open -e .env
```

Replace the `SEC_USER_AGENT` placeholder with an application name and a real contact
email, save the file, close TextEdit, and verify the installation:

```bash
./.venv/bin/stockrank setup-check
```

An experienced user may provide the SEC identity during setup instead:

```bash
bash ./scripts/setup.sh \
  --sec-user-agent "Personal Stock Research Assistant name@example.com"
```

The script detects macOS automatically. It prefers Python 3.13 on macOS 12 or newer;
on macOS 11 it selects Python 3.12 and applies the tested PyArrow 17 compatibility
profile. PyArrow 17 provides prebuilt Python 3.12 wheels for macOS 11 Apple Silicon
and macOS 10.15+ Intel. The script creates `.venv`, updates its packaging tools,
installs the project and test tools from prebuilt binary wheels, and never overwrites
an existing `.env` file. Requiring wheels prevents PyArrow or its build dependencies
from getting stuck compiling locally.

If an earlier attempt left a `.venv` made with a different Python version, setup
renames it to a clearly labeled backup and builds a fresh environment with the
correct interpreter. It does not uninstall or modify either system Python. After a
successful setup, the backup may be removed later if it is no longer needed.

For commands in the remainder of this guide, macOS users can replace
`.\.venv\Scripts\stockrank.exe` with `./.venv/bin/stockrank`.

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

## Update an existing installation

### Windows 10 or 11

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

### macOS

Stop the dashboard and any report command, open Terminal in the project folder, and
run:

```bash
bash ./scripts/update.sh
```

The macOS updater applies the same protections as the Windows updater: it refuses
to overwrite local source changes, performs only a fast-forward Git pull,
synchronizes dependencies, validates setup and personal configuration, runs the
test suite, and verifies that `.env`, `config/preferences.local.toml`, and
`config/universe.local.csv` are unchanged. Ignored `runtime/` history is not touched.
For an intentionally faster update, `--skip-tests` skips only the tests:

```bash
bash ./scripts/update.sh --skip-tests
```

The dashboard also contains a read-only **Customize this installation** section
showing the active profile and the commands above. Personal settings are still
changed through `stockrank configure`, where validation and backups are enforced.

## Manual Linux or advanced setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

On Linux, use `.venv/bin/python -m pip install -e ".[dev]"` for the second command.
Then copy `.env.example` to `.env`, configure `SEC_USER_AGENT`, and run the
platform's `stockrank setup-check` executable from the repository root.

## First report

The first live run downloads substantially more SEC data than later cached runs and
can take several minutes:

```powershell
.\.venv\Scripts\stockrank.exe daily-report
.\.venv\Scripts\stockrank.exe dashboard
```

On macOS:

```bash
./.venv/bin/stockrank daily-report
./.venv/bin/stockrank dashboard
```

The dashboard opens locally. The deterministic command produces a base report and
`runtime/reports/research_template.json`; it does not claim to perform qualitative
news research. See `docs/DAILY_WORKFLOW.md` for the optional human/AI research step.

## Existing history

To start fresh, do nothing: `runtime/` is created automatically. To migrate an
existing installation's history, stop the dashboard and all report commands, then
copy the entire `runtime/` directory separately from Git. Never commit `.env` or
`runtime/`.
