#!/usr/bin/env bash

set -u

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$project_root" || {
    echo "ERROR: The Stock Research Assistant project folder could not be opened." >&2
    echo "Rerun setup from the project folder to repair the desktop shortcut." >&2
    read -r -p "Press Return to close..." _
    exit 1
}

stockrank_executable="$project_root/.venv/bin/stockrank"
if [[ ! -x "$stockrank_executable" ]]; then
    echo "ERROR: The local application environment is missing." >&2
    echo "Run this command from the project folder, then try the launcher again:" >&2
    echo "bash ./scripts/setup.sh" >&2
    echo >&2
    read -r -p "Press Return to close..." _
    exit 1
fi

"$stockrank_executable" morning
stockrank_exit=$?
if ((stockrank_exit != 0)); then
    echo
    echo "Stock Research Assistant stopped because something requires attention."
    echo "Review the message above before closing this window."
    read -r -p "Press Return to close..." _
fi

exit "$stockrank_exit"
