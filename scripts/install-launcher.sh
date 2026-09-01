#!/usr/bin/env bash

set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
desktop_dir="${HOME}/Desktop"

while (($#)); do
    case "$1" in
        --desktop-dir)
            if (($# < 2)); then
                echo "ERROR: --desktop-dir requires a path." >&2
                exit 2
            fi
            desktop_dir="$2"
            shift 2
            ;;
        -h|--help)
            cat <<'EOF'
Usage: bash ./scripts/install-launcher.sh [--desktop-dir PATH]

Creates or repairs the macOS desktop launcher for this project.
EOF
            exit 0
            ;;
        *)
            echo "ERROR: Unknown option: $1" >&2
            exit 2
            ;;
    esac
done

launcher_path="$project_root/launchers/Stock Research Assistant.command"
if [[ ! -f "$launcher_path" ]]; then
    echo "ERROR: The macOS launcher is missing: $launcher_path" >&2
    exit 1
fi
if [[ ! -d "$desktop_dir" ]]; then
    echo "ERROR: The Desktop folder could not be found: $desktop_dir" >&2
    exit 1
fi

chmod u+x "$launcher_path"
desktop_launcher="$desktop_dir/Stock Research Assistant.command"
if [[ -e "$desktop_launcher" && ! -L "$desktop_launcher" ]]; then
    echo "ERROR: A non-shortcut file already exists at $desktop_launcher" >&2
    echo "Move or rename it, then rerun this helper." >&2
    exit 1
fi

if [[ -L "$desktop_launcher" ]]; then
    ln -sfn "$launcher_path" "$desktop_launcher"
else
    ln -s "$launcher_path" "$desktop_launcher"
fi

echo "Desktop launcher created: $desktop_launcher"
