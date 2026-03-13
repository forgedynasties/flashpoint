#!/usr/bin/env bash
set -euo pipefail

RULES_FILE="99-qualcomm-flasher.rules"
RULES_DIR="/etc/udev/rules.d"

echo "Installing $RULES_FILE → $RULES_DIR/"
sudo cp "$RULES_FILE" "$RULES_DIR/$RULES_FILE"

echo "Reloading udev rules..."
sudo udevadm control --reload-rules
sudo udevadm trigger

echo ""
echo "Done. Reconnect any plugged-in Qualcomm devices for the new rules to apply."
