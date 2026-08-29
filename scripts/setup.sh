#!/usr/bin/env bash

set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$project_root"

sec_user_agent=""
while (($#)); do
    case "$1" in
        --sec-user-agent)
            if (($# < 2)); then
                echo "ERROR: --sec-user-agent requires a value." >&2
                exit 2
            fi
            sec_user_agent="$2"
            shift 2
            ;;
        -h|--help)
            cat <<'EOF'
Usage: bash ./scripts/setup.sh [--sec-user-agent "Application name email@example.com"]

Creates .venv, installs the application and development checks, creates .env when
needed, and optionally configures the SEC contact identity.
EOF
            exit 0
            ;;
        *)
            echo "ERROR: Unknown option: $1" >&2
            exit 2
            ;;
    esac
done

if ! command -v git >/dev/null 2>&1; then
    echo "ERROR: Git was not found. Install Git, reopen Terminal, and rerun this script." >&2
    exit 1
fi

macos_major=""
macos_version=""
if [[ "$(uname -s)" == "Darwin" ]] && command -v sw_vers >/dev/null 2>&1; then
    macos_version="$(sw_vers -productVersion)"
    macos_major="${macos_version%%.*}"
    if ((macos_major < 11)); then
        echo "ERROR: This guided setup supports macOS 11 or newer; found macOS $macos_version." >&2
        exit 1
    fi
fi

python_executable=""
if [[ "$macos_major" == "11" ]]; then
    python_candidates=(
        python3.12
        /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12
        python3
        python
    )
else
    python_candidates=(python3.13 python3 python)
fi

for candidate in "${python_candidates[@]}"; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if [[ "$macos_major" == "11" ]]; then
            version_is_compatible="$($candidate -c 'import sys; print(sys.version_info[:2] == (3, 12))')"
        else
            version_is_compatible="$($candidate -c 'import sys; print(sys.version_info >= (3, 11))')"
        fi
        if [[ "$version_is_compatible" == "True" ]]; then
            python_executable="$candidate"
            break
        fi
    fi
done

if [[ -z "$python_executable" ]]; then
    if [[ "$macos_major" == "11" ]]; then
        echo "ERROR: macOS $macos_version requires Python 3.12 for this application, but it was not found." >&2
        echo "Install the official Python 3.12.10 macOS universal2 package, reopen Terminal, and rerun:" >&2
        echo "https://www.python.org/downloads/release/python-31210/" >&2
    else
        echo "ERROR: Python 3.11 or newer was not found." >&2
        echo "Install Python 3.13 from python.org, reopen Terminal, and rerun this script." >&2
    fi
    exit 1
fi

python_version="$($python_executable -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')"
echo "Using $python_executable (Python $python_version)."

dependency_constraints=()
if [[ "$macos_major" == "11" ]]; then
    dependency_constraints=(--constraint "$project_root/constraints/macos-11-py312.txt")
    echo "Using the tested macOS 11 dependency compatibility profile."
fi

if [[ -x ".venv/bin/python" ]]; then
    environment_version="$(.venv/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    selected_version="$($python_executable -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    if [[ "$environment_version" != "$selected_version" ]]; then
        backup_path=".venv-backups/python-$environment_version"
        backup_number=2
        while [[ -e "$backup_path" ]]; do
            backup_path=".venv-backups/python-$environment_version-$backup_number"
            ((backup_number += 1))
        done
        mkdir -p ".venv-backups"
        echo "Preserving the existing Python $environment_version environment as $backup_path."
        mv ".venv" "$backup_path"
    fi
fi

if [[ ! -x ".venv/bin/python" ]]; then
    echo "Creating the local Python environment..."
    "$python_executable" -m venv .venv
fi

echo "Updating Python packaging tools..."
".venv/bin/python" -m ensurepip --upgrade
".venv/bin/python" -m pip install \
    --disable-pip-version-check --upgrade pip setuptools wheel

echo "Installing the application and verification tools..."
if ! ".venv/bin/python" -m pip install \
    --disable-pip-version-check --only-binary=:all: \
    "${dependency_constraints[@]}" -e ".[dev]"; then
    echo "ERROR: Dependency installation failed without compiling packages from source." >&2
    echo "Confirm the supported Python version and that its architecture matches the Mac." >&2
    exit 1
fi

if [[ ! -f ".env" ]]; then
    cp ".env.example" ".env"
    echo "Created .env from the safe example file."
fi

if [[ -n "${sec_user_agent//[[:space:]]/}" ]]; then
    SEC_USER_AGENT_VALUE="$sec_user_agent" ".venv/bin/python" - <<'PY'
import os
from pathlib import Path

env_path = Path(".env")
sec_user_agent = os.environ["SEC_USER_AGENT_VALUE"].strip()
if "\n" in sec_user_agent or "\r" in sec_user_agent:
    raise SystemExit("SEC user agent must be a single line.")
replacement = "SEC_USER_AGENT=" + sec_user_agent
lines = env_path.read_text(encoding="utf-8-sig").splitlines()
updated = []
replaced = False
for line in lines:
    if line.startswith("SEC_USER_AGENT="):
        updated.append(replacement)
        replaced = True
    else:
        updated.append(line)
if not replaced:
    updated.append(replacement)
env_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
PY
    ".venv/bin/stockrank" setup-check
else
    echo
    echo "Installation complete. Edit .env and replace the SEC_USER_AGENT placeholder."
    echo "A simple option on macOS is: open -e .env"
    echo "Then run: ./.venv/bin/stockrank setup-check"
fi
