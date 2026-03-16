#!/usr/bin/env python3
"""CLI tool for testing device detection without running the GUI.

Commands:
  edl           List EDL devices via qdl list-server socket
  booted        List booted devices via pyudev
  all           List all connected devices
  monitor       Poll for device changes and print diffs
  server-check  Verify the qdl list-server is reachable and show its output

Examples:
  python scan.py server-check
  python scan.py edl -v
  python scan.py monitor --interval 3
  python scan.py all --socket /tmp/qdl-list.sock
"""

import argparse
import json
import logging
import os
import socket as _socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import QDL_LIST_SOCKET
from utils_device_manager import DeviceScanner

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_server_check(socket_path: str) -> None:
    """Check whether the qdl list-server is reachable and print its response."""
    log.info("Connecting to qdl list-server at %s …", socket_path)
    try:
        sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(socket_path)
        buf = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
        sock.close()
        devices = json.loads(buf.decode())
        log.info("Server reachable — %d EDL device(s) found", len(devices))
        _print_json(devices)
    except FileNotFoundError:
        log.error("Socket not found: %s", socket_path)
        log.error("Start the server with:  sudo qdl list-server --socket %s", socket_path)
        sys.exit(1)
    except Exception as exc:
        log.error("Cannot reach qdl list-server at %s: %s", socket_path, exc)
        sys.exit(1)


def cmd_edl(socket_path: str) -> None:
    devices = DeviceScanner.get_edl_devices(socket_path)
    log.info("%d EDL device(s)", len(devices))
    _print_json(devices)


def cmd_booted() -> None:
    devices = DeviceScanner.get_booted_devices()
    log.info("%d booted device(s)", len(devices))
    _print_json(devices)


def cmd_all(socket_path: str) -> None:
    _, devices = DeviceScanner.scan_all(socket_path)
    log.info("%d total device(s)", len(devices))
    _print_json(devices)


def cmd_monitor(socket_path: str, interval: float) -> None:
    log.info("Monitoring every %.1fs  (Ctrl-C to stop) …", interval)
    prev: dict = {}
    try:
        while True:
            _, devices = DeviceScanner.scan_all(socket_path)
            if devices != prev:
                print(f"\n[{time.strftime('%H:%M:%S')}] {len(devices)} device(s)")
                _print_json(devices)
                prev = devices
            time.sleep(interval)
    except KeyboardInterrupt:
        print()
        log.info("Stopped.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Device scanner CLI for 2flasher-gui",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "command",
        choices=["edl", "booted", "all", "monitor", "server-check"],
    )
    parser.add_argument(
        "--socket", default=QDL_LIST_SOCKET,
        metavar="PATH",
        help=f"qdl list-server socket (default: {QDL_LIST_SOCKET})",
    )
    parser.add_argument(
        "--interval", type=float, default=2.0, metavar="SEC",
        help="Poll interval for monitor mode (default: 2.0)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    dispatch = {
        "server-check": lambda: cmd_server_check(args.socket),
        "edl":          lambda: cmd_edl(args.socket),
        "booted":       lambda: cmd_booted(),
        "all":          lambda: cmd_all(args.socket),
        "monitor":      lambda: cmd_monitor(args.socket, args.interval),
    }
    dispatch[args.command]()


if __name__ == "__main__":
    main()
