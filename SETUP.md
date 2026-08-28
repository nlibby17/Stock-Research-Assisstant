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
