#!/usr/bin/env bash
# Factory Flash Station — pre-flight check
# Run from the setup folder before starting production.
# Does NOT require sudo.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BOLD='\033[1m'; NC='\033[0m'

PASS=0; FAIL=0

_ok()   { echo -e "  ${GREEN}✓${NC}  $1"; ((PASS++)); }
_fail() { echo -e "  ${RED}✗${NC}  $1"; ((FAIL++)); }
_warn() { echo -e "  ${YELLOW}!${NC}  $1"; }
_hdr()  { echo -e "\n${BOLD}$1${NC}"; }

# ── 1. Package contents ───────────────────────────────────────────────────────
_hdr "[1/4] Package contents"

# factory2 binary
if [[ -f "$SCRIPT_DIR/factory2-station" && -x "$SCRIPT_DIR/factory2-station" ]]; then
    _ok "factory2-station binary present and executable"
else
    _fail "factory2-station binary missing or not executable"
fi

# setup.sh
if [[ -f "$SCRIPT_DIR/setup.sh" ]]; then
    _ok "setup.sh present"
else
    _fail "setup.sh missing"
fi

# qdl — prebuilt binary or source tree
if [[ -f "$SCRIPT_DIR/qdl-prebuilt" ]]; then
    _ok "qdl-prebuilt binary present"
elif [[ -f "$SCRIPT_DIR/qdl/Makefile" ]]; then
    _ok "qdl/ source tree present (will be built by setup.sh)"
else
    _fail "neither qdl-prebuilt nor qdl/Makefile found"
fi

# factory firmware
_check_fw() {
    local dir="$SCRIPT_DIR/$1"
    if [[ ! -d "$dir" ]]; then
        _fail "$1/ directory missing"
        return
    fi
    local elf raw patch
    elf=$(find "$dir"   -maxdepth 1 -name "prog*.elf"        | head -1)
    raw=$(find "$dir"   -maxdepth 1 -name "rawprogram*.xml"  | head -1)
    patch=$(find "$dir" -maxdepth 1 -name "patch*.xml"       | head -1)
    local missing=()
    [[ -z "$elf"   ]] && missing+=("prog*.elf")
    [[ -z "$raw"   ]] && missing+=("rawprogram*.xml")
    [[ -z "$patch" ]] && missing+=("patch*.xml")
    if [[ ${#missing[@]} -eq 0 ]]; then
        _ok "$1/ firmware complete (elf, rawprogram, patch)"
    else
        _fail "$1/ missing: ${missing[*]}"
    fi
}

_check_fw "factory"
_check_fw "debug"

# ── 2. System setup (post setup.sh) ──────────────────────────────────────────
_hdr "[2/4] System setup"

if [[ -x "/usr/local/bin/qdl" ]]; then
    _ok "qdl installed at /usr/local/bin/qdl"
else
    _fail "qdl not found at /usr/local/bin/qdl — run: sudo bash setup.sh"
fi

if [[ -f "/etc/udev/rules.d/99-flasher.rules" ]]; then
    _ok "udev rules present (99-flasher.rules)"
else
    _fail "udev rules missing — run: sudo bash setup.sh"
fi

if [[ -f "/etc/sudoers.d/99-qdl-nopasswd" ]]; then
    _ok "passwordless sudo for qdl configured"
else
    _fail "sudoers drop-in missing — run: sudo bash setup.sh"
fi

# ── 3. Runtime dependencies ───────────────────────────────────────────────────
_hdr "[3/4] Runtime dependencies"

if command -v adb &>/dev/null; then
    _ok "adb found ($(adb version 2>/dev/null | head -1))"
else
    _fail "adb not found — run: sudo bash setup.sh"
fi

if command -v tmux &>/dev/null; then
    _ok "tmux found"
else
    _warn "tmux not found (only needed for qdl-tmux.sh, not the main app)"
fi

# ── 4. Passwordless sudo for qdl ─────────────────────────────────────────────
_hdr "[4/4] Sudo access"

if sudo -n /usr/local/bin/qdl --help &>/dev/null 2>&1; then
    _ok "passwordless sudo for qdl works"
else
    _fail "passwordless sudo for qdl failed — check /etc/sudoers.d/99-qdl-nopasswd"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "────────────────────────────────────────────"
if [[ $FAIL -eq 0 ]]; then
    echo -e "  ${GREEN}${BOLD}All checks passed ($PASS/$((PASS+FAIL)))${NC}"
    echo -e "  Ready to run: ${BOLD}./factory2-station${NC}"
    echo ""
    exit 0
else
    echo -e "  ${RED}${BOLD}$FAIL check(s) failed${NC}  ($PASS passed)"
    echo -e "  Fix the issues above, then re-run: ${BOLD}bash check.sh${NC}"
    echo ""
    exit 1
fi
