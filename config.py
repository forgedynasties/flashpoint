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

# Base app firmware env var
FW_PATH_ENV = "FW_PATH"

# Factory app env vars
FACTORY_FW_PATH_ENV      = "FACTORY"
PROD_DEBUG_FW_PATH_ENV   = "DEBUG"
BOOT_TIMEOUT_SEC_ENV     = "BOOT_TIMEOUT_SEC"
DEFAULT_BOOT_TIMEOUT_SEC = 120
EXPECTED_BUILD_ID        = "AQ3A.250226.002"
FACTORY_REPORTS_DIR_ENV  = "REPORTS"
DEFAULT_REPORTS_DIR      = os.path.expanduser("~/factory_reports")
