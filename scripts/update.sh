#!/usr/bin/env bash

set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$project_root"

skip_tests=false
while (($#)); do
    case "$1" in
        --skip-tests)
            skip_tests=true
            shift
            ;;
        -h|--help)
            echo "Usage: bash ./scripts/update.sh [--skip-tests]"
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
if ! command -v shasum >/dev/null 2>&1; then
    echo "ERROR: The macOS shasum utility was not found." >&2
    exit 1
fi
if [[ ! -d ".git" ]]; then
    echo "ERROR: This folder is not a Git clone. Use scripts/setup.sh for a new installation." >&2
    exit 1
fi
if [[ ! -x ".venv/bin/python" || ! -x ".venv/bin/stockrank" ]]; then
    echo "ERROR: The local Python environment is missing. Run scripts/setup.sh first." >&2
    exit 1
fi

dependency_constraints=()
if [[ "$(uname -s)" == "Darwin" ]] && command -v sw_vers >/dev/null 2>&1; then
    macos_version="$(sw_vers -productVersion)"
    macos_major="${macos_version%%.*}"
    environment_version="$(.venv/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    if ((macos_major < 11)); then
        echo "ERROR: This updater supports macOS 11 or newer; found macOS $macos_version." >&2
        exit 1
    fi
    if [[ "$macos_major" == "11" ]]; then
        if [[ "$environment_version" != "3.12" ]]; then
            echo "ERROR: macOS 11 requires the Python 3.12 environment created by scripts/setup.sh." >&2
            echo "Run: bash ./scripts/setup.sh" >&2
            exit 1
        fi
        dependency_constraints=(--constraint "$project_root/constraints/macos-11-py312.txt")
    fi
fi

source_changes="$(git status --porcelain --untracked-files=all)"
if [[ -n "$source_changes" ]]; then
    echo "Update stopped because source-controlled or untracked project files changed:"
    printf '%s\n' "$source_changes" | sed 's/^/  /'
    echo "Commit, remove, or preserve those files outside the project before updating." >&2
    exit 1
fi

branch="$(git symbolic-ref --quiet --short HEAD || true)"
if [[ -z "$branch" ]]; then
    echo "ERROR: Update requires a normal checked-out branch, not a detached commit." >&2
    exit 1
fi

hash_file() {
    shasum -a 256 "$1" | awk '{print $1}'
}

env_hash=""
preferences_hash=""
universe_hash=""
[[ ! -f ".env" ]] || env_hash="$(hash_file ".env")"
[[ ! -f "config/preferences.local.toml" ]] || preferences_hash="$(hash_file "config/preferences.local.toml")"
[[ ! -f "config/universe.local.csv" ]] || universe_hash="$(hash_file "config/universe.local.csv")"

echo "Updating branch '$branch' with a fast-forward-only pull..."
git pull --ff-only origin "$branch"

echo "Synchronizing Python dependencies..."
".venv/bin/python" -m ensurepip --upgrade
".venv/bin/python" -m pip install \
    --disable-pip-version-check --quiet --upgrade pip setuptools wheel
".venv/bin/python" -m pip install \
    --disable-pip-version-check --quiet --only-binary=:all: \
    "${dependency_constraints[@]}" -e ".[dev]"

echo "Validating the installation and active personal configuration..."
".venv/bin/stockrank" setup-check
".venv/bin/stockrank" config-check

if [[ "$skip_tests" == false ]]; then
    echo "Running the automated test suite..."
    pytest_temp="$project_root/runtime/tmp/pytest-update-$$"
    mkdir -p "$pytest_temp"
    ".venv/bin/python" -m pytest -q -p no:cacheprovider --basetemp "$pytest_temp"
fi

verify_personal_file() {
    local path="$1"
    local original_hash="$2"
    if [[ -n "$original_hash" ]]; then
        if [[ ! -f "$path" ]]; then
            echo "ERROR: Personal file disappeared during update: $path" >&2
            exit 1
        fi
        if [[ "$(hash_file "$path")" != "$original_hash" ]]; then
            echo "ERROR: Personal file changed unexpectedly during update: $path" >&2
            exit 1
        fi
    fi
}

verify_personal_file ".env" "$env_hash"
verify_personal_file "config/preferences.local.toml" "$preferences_hash"
verify_personal_file "config/universe.local.csv" "$universe_hash"

echo "Update complete. Personal settings and runtime data were preserved."
