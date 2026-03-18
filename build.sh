#!/usr/bin/env bash
# Build factory2.py into a standalone executable using PyInstaller.
# Run this on the *development* machine, then ship the output to the target.
#
# Usage:
#   bash build.sh
#
# Output:
#   dist/factory2-station   — self-contained binary; copy to target machine
#
# What to ship to the target Ubuntu machine:
#   dist/factory2-station   the app binary
#   setup.sh                run once with sudo on the target
#   qdl/                    qdl source tree (built by setup.sh), OR
#   qdl-prebuilt            pre-built qdl binary (setup.sh installs this
#                           to /usr/local/bin/qdl if present)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Activate venv ─────────────────────────────────────────────────────────────
VENV_DIR="/home/cd4li/flashing/flasher-gui/.venv"
if [[ ! -f "$VENV_DIR/bin/activate" ]]; then
    echo "ERROR: venv not found at $VENV_DIR" >&2
    exit 1
fi
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"
echo "[build] Using venv: $VENV_DIR"

# ── Ensure PyInstaller is available ───────────────────────────────────────────
if ! python3 -c "import PyInstaller" &>/dev/null; then
    echo "[build] PyInstaller not found — installing..."
    pip install --quiet pyinstaller
fi

# ── Install Python dependencies ───────────────────────────────────────────────
echo "[build] Installing Python requirements..."
pip install --quiet -r requirements.txt

# ── Build ─────────────────────────────────────────────────────────────────────
echo "[build] Running PyInstaller..."
python3 -m PyInstaller \
    --onefile \
    --name factory2-station \
    --add-data "check.svg:." \
    --hidden-import PyQt6.QtNetwork \
    --hidden-import pyudev \
    --collect-all PyQt6 \
    factory2.py

echo ""
echo "======================================================================"
echo "  Build complete:  dist/factory2-station"
echo "======================================================================"
echo ""
echo "  Ship the following to the target Ubuntu machine:"
echo "    dist/factory2-station   — the application binary"
echo "    setup.sh                — run once with: sudo bash setup.sh"
echo "    qdl/                    — qdl source (compiled by setup.sh), OR"
echo "    qdl-prebuilt            — drop a pre-built qdl binary here and"
echo "                              setup.sh will install it instead of"
echo "                              building from source"
echo ""
