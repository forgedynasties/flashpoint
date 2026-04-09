#!/usr/bin/env bash
# Launch the Factory Flash Station from anywhere.
# Usage:  ./run-factory.sh
#         bash /path/to/run-factory.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
QDL_SRC="$SCRIPT_DIR/qdl/qdl"

# ── QDL_BIN ──────────────────────────────────────────────────────────────────
# Prefer the env var if already set (e.g. from setup.sh / .bashrc).
# Fall back to the built binary next to this script.
if [[ -z "${QDL_BIN:-}" ]]; then
    if [[ -x "$QDL_SRC" ]]; then
        export QDL_BIN="$QDL_SRC"
    elif command -v qdl &>/dev/null; then
        export QDL_BIN="$(command -v qdl)"
    else
        echo "ERROR: QDL_BIN is not set and no qdl binary was found." >&2
        echo "       Either run setup.sh first, or:" >&2
        echo "         export QDL_BIN=/path/to/qdl" >&2
        exit 1
    fi
fi

# ── Virtualenv ────────────────────────────────────────────────────────────────
if [[ ! -f "$VENV/bin/activate" ]]; then
    echo "ERROR: virtualenv not found at $VENV" >&2
    echo "       Run setup.sh first, or:  python3 -m venv $VENV && pip install -r requirements.txt" >&2
    exit 1
fi

source "$VENV/bin/activate"

# ── Launch ────────────────────────────────────────────────────────────────────
echo "QDL_BIN=$QDL_BIN"
exec python3 "$SCRIPT_DIR/factory2.py" "$@"
