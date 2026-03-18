#!/usr/bin/env bash
# Factory Flash Station — target machine setup
# Run as: sudo bash setup.sh
#
# What this does:
#   1. Installs all apt dependencies (GUI libs, USB libs, ADB, build tools)
#   2. Installs qdl — prefers a pre-built binary (qdl-prebuilt) next to this
#      script; falls back to building from the qdl/ source directory
#   3. Writes udev rules for all USB VID:PIDs used by the device (EDL, user-
#      booted, debug-booted)
#   4. Adds a sudoers drop-in so any user can run qdl without a password
#   5. Exports env vars into the real user's ~/.bashrc and /etc/environment

set -euo pipefail

# ── Root check ────────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: Run with sudo:  sudo bash setup.sh" >&2
    exit 1
fi

# Resolve the real (non-root) user who invoked sudo
REAL_USER="${SUDO_USER:-}"
if [[ -z "$REAL_USER" ]]; then
    echo "ERROR: Could not determine the invoking user (SUDO_USER is unset)." >&2
    echo "       Run as: sudo bash setup.sh" >&2
    exit 1
fi
REAL_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Factory Flash Station setup"
echo "    Script dir : $SCRIPT_DIR"
echo "    Target user: $REAL_USER ($REAL_HOME)"
echo ""

# ── 1. apt dependencies ───────────────────────────────────────────────────────
echo "[1/5] Installing apt packages..."
apt-get update -y -qq

apt-get install -y \
    adb \
    android-tools-adb \
    build-essential \
    help2man \
    libusb-1.0-0 \
    libusb-1.0-0-dev \
    libx11-xcb1 \
    libxcb-cursor0 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-render-util0 \
    libxcb-xinerama0 \
    libxcb-xkb1 \
    libxkbcommon-x11-0 \
    libxml2 \
    libxml2-dev \
    python3 \
    python3-pip \
    python3-venv \
    usbutils

echo "[1/5] Done."

# ── 2. Install qdl ────────────────────────────────────────────────────────────
echo "[2/5] Installing qdl..."
QDL_INSTALL_PATH="/usr/local/bin/qdl"
PREBUILT="$SCRIPT_DIR/qdl-prebuilt"
QDL_SRC="$SCRIPT_DIR/qdl"

if [[ -f "$PREBUILT" ]]; then
    echo "      Using pre-built binary: $PREBUILT"
    install -m 755 "$PREBUILT" "$QDL_INSTALL_PATH"
    echo "      Installed to $QDL_INSTALL_PATH"
elif [[ -d "$QDL_SRC" && -f "$QDL_SRC/Makefile" ]]; then
    echo "      Building from source: $QDL_SRC"
    make -C "$QDL_SRC" clean
    make -C "$QDL_SRC" -j"$(nproc)"
    install -m 755 "$QDL_SRC/qdl" "$QDL_INSTALL_PATH"
    echo "      Built and installed to $QDL_INSTALL_PATH"
else
    echo "ERROR: Neither $PREBUILT nor $QDL_SRC/Makefile found." >&2
    echo "       Provide either:" >&2
    echo "         • A pre-built binary at: $PREBUILT" >&2
    echo "         • The qdl source tree at: $QDL_SRC" >&2
    exit 1
fi
echo "[2/5] Done."

# ── 3. udev rules for all USB VID:PIDs ───────────────────────────────────────
echo "[3/5] Installing udev rules..."
UDEV_FILE="/etc/udev/rules.d/99-flasher.rules"

cat > "$UDEV_FILE" <<'UDEV_EOF'
# Factory Flash Station — USB device permissions
# Gives read/write access to all users (MODE="0666") for every VID:PID
# used by the target device across all operating modes.

# ── EDL mode (Qualcomm 9008) ─────────────────────────────────────────────────
ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="05c6", ATTR{idProduct}=="9008", MODE="0666", TAG+="uaccess"

# ── ADB user-booted (Google 18d1:4ee1) ───────────────────────────────────────
ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="18d1", ATTR{idProduct}=="4ee1", MODE="0666", TAG+="uaccess"

# ── ADB debug-booted (Google 18d1:4e11) ──────────────────────────────────────
ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="18d1", ATTR{idProduct}=="4e11", MODE="0666", TAG+="uaccess"

# ── Qualcomm debug mode (05c6:901f) ──────────────────────────────────────────
ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="05c6", ATTR{idProduct}=="901f", MODE="0666", TAG+="uaccess"
UDEV_EOF

udevadm control --reload-rules
udevadm trigger
echo "      Rules written to $UDEV_FILE"
echo "[3/5] Done."

# ── 4. sudoers: passwordless qdl ─────────────────────────────────────────────
echo "[4/5] Configuring passwordless sudo for qdl..."
SUDOERS_FILE="/etc/sudoers.d/99-qdl-nopasswd"

cat > "$SUDOERS_FILE" <<SUDOERS_EOF
# Allow any user to run qdl without a password prompt.
# This is needed because qdl requires raw USB access (libusb) and the
# factory app launches it via sudo programmatically.
ALL ALL=(ALL) NOPASSWD: $QDL_INSTALL_PATH
SUDOERS_EOF

chmod 440 "$SUDOERS_FILE"
# Validate syntax — aborts if the file is malformed
visudo -cf "$SUDOERS_FILE"
echo "      Sudoers drop-in written to $SUDOERS_FILE"
echo "[4/5] Done."

# ── 5. Environment variables ──────────────────────────────────────────────────
echo "[5/5] Setting environment variables..."
BASHRC="$REAL_HOME/.bashrc"
PROFILE="$REAL_HOME/.profile"

# The env-var block to write (same content for both .bashrc and .profile)
# .bashrc  → picked up by interactive terminal sessions
# .profile → picked up by the display manager (GDM/LightDM) at login,
#            so GUI apps launched from the file manager also see the vars
_write_env_block() {
    local target="$1"
    # Remove any previous Factory Flash Station block
    sed -i '/^# ── Factory Flash Station/,/^# ─\+$/d' "$target" 2>/dev/null || true
    cat >> "$target" <<ENV_EOF

# ── Factory Flash Station ────────────────────────────────────────
# QDL_BIN: path to the qdl binary installed by setup.sh
export QDL_BIN="$QDL_INSTALL_PATH"

# FACTORY_FW_PATH: directory containing the factory-flash firmware
# (prog*.elf, rawprogram*.xml, patch*.xml).
export FACTORY_FW_PATH="$SCRIPT_DIR/factory"

# PROD_DEBUG_FW_PATH: directory containing the prod/debug firmware
# for the second flash stage.
export PROD_DEBUG_FW_PATH="$SCRIPT_DIR/debug"

# BOOT_TIMEOUT_SEC: seconds to wait for device to boot between stages
export BOOT_TIMEOUT_SEC="120"

# FACTORY_REPORTS_DIR: where flash reports are saved
export FACTORY_REPORTS_DIR="\$HOME/factory_reports"
# ─────────────────────────────────────────────────────────────────
ENV_EOF
}

# Ensure .profile exists (Ubuntu may not create it for all users)
touch "$PROFILE"

_write_env_block "$BASHRC"
_write_env_block "$PROFILE"
chown "$REAL_USER:$REAL_USER" "$BASHRC" "$PROFILE"

# Also set QDL_BIN in /etc/environment so it is available in sudo sessions
# (sudo does not source .bashrc; env vars in /etc/environment are propagated)
if grep -q "^QDL_BIN=" /etc/environment 2>/dev/null; then
    sed -i "s|^QDL_BIN=.*|QDL_BIN=\"$QDL_INSTALL_PATH\"|" /etc/environment
else
    echo "QDL_BIN=\"$QDL_INSTALL_PATH\"" >> /etc/environment
fi

echo "      Env vars written to $BASHRC and $PROFILE"
echo "      QDL_BIN written to /etc/environment"
echo "[5/5] Done."

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "======================================================================"
echo "  Setup complete!"
echo "======================================================================"
echo ""
echo "  Next steps:"
echo "  1. Unplug and replug all USB devices so udev rules take effect."
echo "  2. Edit $BASHRC (and $PROFILE) and fill in the two firmware paths:"
echo "       FACTORY_FW_PATH     — path to factory firmware directory"
echo "       PROD_DEBUG_FW_PATH  — path to prod/debug firmware directory"
echo "  3. Reload your shell:  source $BASHRC"
echo "  4. Run the app:        ./factory2-station"
echo ""
