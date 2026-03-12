"""Device scanning — returns Device objects.

Replaces utils_device_manager.py.
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import Optional

from config import USB_PIDs
from core.device import Device


# ── Internal helpers ──────────────────────────────────────────────────────────


def _usb_path(bus: str, devnum: str) -> Optional[str]:
    """Resolve a sysfs USB path (e.g. '3-1') from bus/device numbers."""
    bus_s, dev_s = str(int(bus)), str(int(devnum))
    try:
        for entry in os.listdir("/sys/bus/usb/devices"):
            base = f"/sys/bus/usb/devices/{entry}"
            try:
                with open(f"{base}/busnum") as f:
                    if f.read().strip() != bus_s:
                        continue
                with open(f"{base}/devnum") as f:
                    if f.read().strip() == dev_s:
                        return entry
            except OSError:
                continue
    except OSError:
        pass
    return None


def _lsusb() -> list[str]:
    try:
        return subprocess.check_output(["lsusb"]).decode().splitlines()
    except Exception:
        return []


# ── Public scan functions ─────────────────────────────────────────────────────


def scan_edl() -> dict[str, Device]:
    """Scan for EDL (QDL mode) devices. Returns {serial: Device(mode='edl')}.

    Serial is always read from the USB hardware descriptor (_SN: field in
    lsusb -v), so it is the same stable key used in booted modes.
    """
    devices: dict[str, Device] = {}
    for line in _lsusb():
        if "05c6:9008" not in line:
            continue
        m = re.search(r"Bus (\d+) Device (\d+)", line)
        if not m:
            continue
        s_bus, s_dev = m.groups()
        usb_path = _usb_path(s_bus, s_dev)

        serial: Optional[str] = None
        try:
            v = subprocess.check_output(
                ["lsusb", "-v", "-s", f"{s_bus}:{s_dev}"],
                stderr=subprocess.DEVNULL,
            ).decode()
            sn_m = re.search(r"_SN:([0-9a-fA-F]+)", v)
            if sn_m:
                serial = sn_m.group(1)
        except Exception:
            pass

        if serial:
            devices[serial] = Device(serial=serial, mode="edl", usb_path=usb_path)

    return devices


def scan_adb() -> dict[str, str]:
    """Return {serial: transport_id} for all devices visible to adb."""
    result: dict[str, str] = {}
    try:
        out = subprocess.check_output(["adb", "devices", "-l"]).decode()
        for line in out.splitlines():
            m = re.match(r"^(\S+)\s+\w+.*transport_id:(\d+)", line)
            if m:
                result[m.group(1)] = m.group(2)
    except Exception:
        pass
    return result


def scan_all() -> dict[str, Device]:
    """Full scan — returns all currently connected devices keyed by serial."""
    devices: dict[str, Device] = {}

    # EDL devices
    devices.update(scan_edl())

    # ADB lookup tables: serial→tid (from scan_adb) and usb_path→tid
    serial_to_tid: dict[str, str] = scan_adb()
    path_to_tid: dict[str, str] = {}
    try:
        out = subprocess.check_output(["adb", "devices", "-l"]).decode()
        for line in out.splitlines():
            m = re.search(r"usb:(\S+).*transport_id:(\d+)", line)
            if m:
                path_to_tid[m.group(1)] = m.group(2)
    except Exception:
        pass

    # Booted devices via lsusb
    try:
        for line in _lsusb():
            if not any(
                pid in line
                for pid in USB_PIDs["USER_BOOTED"] + USB_PIDs["DEBUG_BOOTED"]
            ):
                continue
            m = re.search(r"Bus (\d+) Device (\d+)", line)
            if not m:
                continue
            s_bus, s_dev = m.groups()
            usb_path = _usb_path(s_bus, s_dev)

            # Hardware serial from lsusb -v
            hw_sn: Optional[str] = None
            try:
                v = subprocess.check_output(
                    ["lsusb", "-v", "-s", f"{s_bus}:{s_dev}"],
                    stderr=subprocess.DEVNULL,
                ).decode()
                sn_m = re.search(r"_SN:([0-9a-fA-F]+)", v)
                if sn_m:
                    hw_sn = sn_m.group(1)
            except Exception:
                pass

            if not hw_sn:
                continue

            mode = (
                "user"
                if any(pid in line for pid in USB_PIDs["USER_BOOTED"])
                else "debug"
            )
            tid = (
                serial_to_tid.get(hw_sn)
                or (path_to_tid.get(usb_path) if usb_path else None)
            )
            devices[hw_sn] = Device(
                serial=hw_sn,
                mode=mode,
                usb_path=usb_path,
                transport_id=tid,
            )
    except Exception:
        pass

    return devices
