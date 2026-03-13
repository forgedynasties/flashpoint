#!/usr/bin/env bash
# Build a standalone factory flash station executable using PyInstaller.
# Output: dist/flasher  (single file, runs on any x86-64 Linux with glibc >= this machine's version)
#
# Prerequisites (run once):
#   pip install pyinstaller
#
# Usage:
#   ./build.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

pyinstaller \
    --onefile \
    --name flasher \
    --windowed \
    --add-data "gui:gui" \
    --add-data "core:core" \
    --add-data "config.py:." \
    --hidden-import "PyQt6.sip" \
    factory.py

echo ""
echo "Build complete: dist/flasher"
echo ""
echo "Per-machine setup still required on each target:"
echo "  1. Install xcb libs (see pre-req.md)"
echo "  2. Install adb  (sudo apt install adb)"
echo "  3. Build and place qdl at ~/aio/qdl/qdl  (or set QDL_BIN env var)"
echo "  4. udev rule for Qualcomm EDL (see pre-req.md)"
echo "  5. sudoers NOPASSWD for qdl (see pre-req.md)"
