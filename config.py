"""Application configuration and constants."""
import os

# Paths and binaries
QDL_BIN = os.path.expanduser("~/aio/qdl/qdl")

# Device scanning
SCAN_INTERVAL_MS = 1500

# EDL reboot button timeout
EDL_REBOOT_TIMEOUT_MS = 2500

# USB PIDs for different device states
USB_PIDs = {
    "EDL": "05c6:9008",
    "USER_BOOTED": ["18d1:4ee1"],
    "DEBUG_BOOTED": ["18d1:4e11", "05c6:901f"],
}

# Default firmware path environment variable
FW_PATH_ENV = "FW_PATH"
