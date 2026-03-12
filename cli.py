"""CLI entry point.

Usage:
    python cli.py list
    python cli.py flash <fw_path> [serial ...]
    python cli.py edl [serial ...]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import threading

from core.scanner import scan_all


# ── Helpers ───────────────────────────────────────────────────────────────────


def _resolve(args_serials: list[str], filter_fn) -> dict:
    """Return {serial: Device} filtered by serials arg (empty = all matching filter_fn)."""
    devices = scan_all()
    if args_serials:
        missing = [s for s in args_serials if s not in devices]
        if missing:
            print(f"error: unknown serial(s): {', '.join(missing)}", file=sys.stderr)
            sys.exit(1)
        return {s: devices[s] for s in args_serials}
    return {s: d for s, d in devices.items() if filter_fn(d)}


def _run_flash(serial: str, args: list[str], cwd: str) -> int:
    proc = subprocess.Popen(
        args, cwd=cwd,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    assert proc.stdout
    for line in proc.stdout:
        print(f"[{serial}] {line}", end="", flush=True)
    proc.wait()
    return proc.returncode


# ── Subcommands ───────────────────────────────────────────────────────────────


def cmd_list(_args: argparse.Namespace) -> int:
    devices = scan_all()
    if not devices:
        print("No devices found.")
        return 0

    fmt = "{:<22}  {:<8}  {:<5}  {:<14}  {}"
    print(fmt.format("SERIAL", "MODE", "ADB", "BUILD ID", "USB PATH"))
    print("─" * 70)
    for serial, dev in sorted(devices.items()):
        print(fmt.format(
            serial,
            dev.mode,
            "yes" if dev.has_adb else "no",
            dev.build_id or "—",
            dev.usb_path or "—",
        ))
    return 0


def cmd_flash(args: argparse.Namespace) -> int:
    targets = _resolve(args.serials, lambda d: d.is_edl)
    if not targets:
        print("No EDL devices found.", file=sys.stderr)
        return 1

    not_edl = [s for s, d in targets.items() if not d.is_edl]
    if not_edl:
        print(f"error: not in EDL mode: {', '.join(not_edl)}", file=sys.stderr)
        return 1

    failed: list[str] = []
    lock = threading.Lock()

    def _flash(serial: str, device):
        try:
            cmd_args, cwd = device.flash_command(args.fw)
        except FileNotFoundError as e:
            with lock:
                print(f"[{serial}] error: {e}", file=sys.stderr)
                failed.append(serial)
            return
        code = _run_flash(serial, cmd_args, cwd)
        if code != 0:
            with lock:
                failed.append(serial)
            print(f"[{serial}] failed (exit {code})", file=sys.stderr)
        else:
            print(f"[{serial}] done")

    threads = [
        threading.Thread(target=_flash, args=(s, d), daemon=True)
        for s, d in targets.items()
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    return 0 if not failed else 1


def cmd_edl(args: argparse.Namespace) -> int:
    targets = _resolve(args.serials, lambda d: d.has_adb)
    if not targets:
        print("No ADB-accessible devices found.", file=sys.stderr)
        return 1

    no_adb = [s for s, d in targets.items() if not d.has_adb]
    if no_adb:
        print(f"error: no ADB transport for: {', '.join(no_adb)}", file=sys.stderr)
        return 1

    for serial, device in targets.items():
        device.reboot_to_edl()
        print(f"[{serial}] rebooting to EDL")

    return 0


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(prog="flasher", description="Qualcomm flash station CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List all connected devices")

    p_flash = sub.add_parser("flash", help="Flash firmware to EDL device(s)")
    p_flash.add_argument("fw", metavar="fw_path", help="Firmware folder path")
    p_flash.add_argument("serials", nargs="*", metavar="serial",
                         help="Device serial(s) to flash — defaults to all EDL devices")

    p_edl = sub.add_parser("edl", help="Reboot device(s) to EDL mode via ADB")
    p_edl.add_argument("serials", nargs="*", metavar="serial",
                       help="Device serial(s) to reboot — defaults to all ADB-accessible devices")

    args = parser.parse_args()
    return {"list": cmd_list, "flash": cmd_flash, "edl": cmd_edl}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
