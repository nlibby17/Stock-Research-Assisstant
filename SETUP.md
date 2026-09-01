# Install and Run Stock Research Assistant

This guide sets up a separate local copy of the application. Reports, caches,
personal settings, and database history stay on that computer and are not downloaded
from GitHub.

## 1. Install Git and Python

Install [Git](https://git-scm.com/downloads). Then install the appropriate Python
version:

- **Windows 10 or 11:** [Python 3.11 or newer](https://www.python.org/downloads/windows/).
- **macOS 12 or newer:** a [current Python 3 release](https://www.python.org/downloads/macos/).
- **macOS 11:** the official
  [Python 3.12.10 universal2 installer](https://www.python.org/downloads/release/python-31210/).
  Python 3.12 can safely exist beside another Python version.

On Windows, allow the Python installer to add Python to `PATH` if that option is
shown.

## 2. Download the project

Open PowerShell on Windows or Terminal on macOS. Run these commands:

```text
git clone https://github.com/nlibby17/Stock-Research-Assistant.git stock-research-assistant
cd stock-research-assistant
```

The second command places the terminal inside the newly downloaded project folder.

## 3. Run the guided setup

### Windows 10 or 11

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

### macOS

```bash
bash ./scripts/setup.sh
```

Setup creates the local Python environment, installs the application, and creates a
private `.env` file without overwriting an existing one. When asked about the
recommended desktop shortcut or launcher, press **Enter** or **Return** for Yes.

The macOS helper automatically uses Python 3.12 and compatible prebuilt packages on
macOS 11. It avoids the PyArrow/libcst compilation and segmentation-fault problems
seen with incompatible versions on that operating system.

## 4. Add the SEC contact identity

Open `.env`:

```powershell
# Windows
notepad .env
```

```bash
# macOS
open -e .env
```

Find `SEC_USER_AGENT` and replace its placeholder with a descriptive application
name and a real contact email, for example:

```text
SEC_USER_AGENT="Personal Stock Research Assistant name@example.com"
```

Save and close the file. This identifies automated requests to the SEC; it is not
an API key, password, mailing-list signup, or brokerage credential.

## 5. Check the installation

```powershell
# Windows
.\.venv\Scripts\stockrank.exe setup-check
```

```bash
# macOS
./.venv/bin/stockrank setup-check
```

Continue when the check reports that setup is ready.

## 6. Run the application

The easiest method is to double-click **Stock Research Assistant** on the desktop.
It runs the complete morning report and opens the dashboard in the default browser.

If you did not create the desktop item, run the appropriate command from the project
folder:

```powershell
# Windows
.\.venv\Scripts\stockrank.exe morning
```

```bash
# macOS
./.venv/bin/stockrank morning
```

The first report may take several minutes while the local SEC and market-data cache
is created. Later reports normally reuse safe cached data and finish faster.

Keep the terminal window open while using the dashboard. To stop the application,
return to that window and press:

- **Windows:** Ctrl+C
- **macOS:** Control+C (⌃C)

Closing only the browser tab does not stop the local dashboard server.

## Create or repair the desktop launcher

Run the appropriate helper from the project folder:

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File .\scripts\install-launcher.ps1
```

```bash
# macOS
bash ./scripts/install-launcher.sh
```

The desktop item points to the launcher retained inside the project. Normal updates
therefore take effect automatically. If the project folder is moved or renamed,
rerun this helper.

## Personalize the rankings and stock universe

Personalization is optional. The default balanced profile and curated 50-stock
universe work immediately.

Start the guided configuration:

```powershell
# Windows
.\.venv\Scripts\stockrank.exe configure
```

```bash
# macOS
./.venv/bin/stockrank configure
```

The guide lets you select a balanced, growth, value, quality, momentum, or
lower-volatility profile; adjust horizon and risk preferences; and keep or replace
the stock universe. It shows the resulting weights before saving.

To paste a custom list directly:

```powershell
# Windows
.\.venv\Scripts\stockrank.exe configure --tickers "MSFT,JPM,PLTR,SOFI"
```

```bash
# macOS
./.venv/bin/stockrank configure --tickers "MSFT,JPM,PLTR,SOFI"
```

To import a CSV, provide a `ticker` column and optional `company` and `sector`
columns:

```powershell
# Windows
.\.venv\Scripts\stockrank.exe configure --universe-file .\my-stocks.csv
```

```bash
# macOS
./.venv/bin/stockrank configure --universe-file ./my-stocks.csv
```

Personal settings are saved as ignored `config/*.local.*` files and never change
another user's installation. After changing them, run the platform's `stockrank
config-check` executable; add `--live` before the first report with a new universe.
Use `stockrank configure --reset` with the same platform-specific executable to
restore all defaults.

## Update an existing installation

Stop the application, open the project folder in PowerShell or Terminal, and run:

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File .\scripts\update.ps1
```

```bash
# macOS
bash ./scripts/update.sh
```

The updater safely downloads project changes, synchronizes dependencies, validates
the installation and personal configuration, and runs the tests. It preserves
`.env`, local preferences, the custom universe, and ignored `runtime/` history.

## Useful troubleshooting

- **The desktop item stopped working after moving the folder:** rerun the launcher
  helper above.
- **The browser did not open:** use the local URL printed in the terminal, normally
  `http://localhost:8765`.
- **The port is already in use:** stop the earlier dashboard terminal with Ctrl+C or
  Control+C, then try again.
- **The launcher says the local environment is missing:** rerun the guided setup.
- **The SEC identity check fails:** reopen `.env`, confirm that the placeholder was
  replaced, save it, and rerun `setup-check`.
- **macOS blocks the launcher:** Control-click it, choose **Open**, and confirm once.

For the deterministic report stages and optional AI/human qualitative research
workflow, see [docs/DAILY_WORKFLOW.md](docs/DAILY_WORKFLOW.md). For architecture and
data-policy details, see [docs/V1_DESIGN.md](docs/V1_DESIGN.md).

## Advanced notes

Experienced users may provide the SEC identity during setup with `-SecUserAgent` on
Windows or `--sec-user-agent` on macOS. Unattended setup can explicitly choose the
desktop item with `-CreateDesktopShortcut`/`-SkipDesktopShortcut` on Windows or
`--desktop-launcher`/`--no-desktop-launcher` on macOS.

Linux users can create `.venv`, install the project with `pip install -e ".[dev]"`,
copy `.env.example` to `.env`, and use `.venv/bin/stockrank` commands. Linux does not
currently have a guided desktop launcher.

To migrate report history between computers, stop the application and copy the
ignored `runtime/` directory separately. Never commit `.env` or `runtime/`.
