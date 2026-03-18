"""Application configuration and constants."""
import os

# Paths and binaries — can be overridden by the QDL_BIN env var (set by setup.sh)
QDL_BIN = os.environ.get("QDL_BIN", "/usr/local/bin/qdl")

# IPC socket paths
QDL_LIST_SOCKET          = "/tmp/qdl-list.sock"
QDL_PROGRESS_SOCK_PREFIX = "qdl-progress-"  # Qt local server name prefix

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
FACTORY_FW_PATH_ENV      = "FACTORY_FW_PATH"
PROD_DEBUG_FW_PATH_ENV   = "PROD_DEBUG_FW_PATH"
BOOT_TIMEOUT_SEC_ENV     = "BOOT_TIMEOUT_SEC"
DEFAULT_BOOT_TIMEOUT_SEC = 120
EXPECTED_BUILD_ID        = "AQ3A.250226.002"
FACTORY_REPORTS_DIR_ENV  = "FACTORY_REPORTS_DIR"
DEFAULT_REPORTS_DIR      = os.path.expanduser("~/factory_reports")
