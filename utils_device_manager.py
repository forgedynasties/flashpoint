"""Device scanning and detection utilities."""
import json
import logging
import re
import socket as _socket
import subprocess

import pyudev

from config import QDL_LIST_SOCKET, USB_PIDs

log = logging.getLogger(__name__)

_udev_context = pyudev.Context()

# Map VID:PID strings to mode labels for booted devices
_BOOTED_PID_MODE = {
    "18d1:4ee1": "USER BOOTED",
    "18d1:4e11": "DEBUG BOOTED",
    "05c6:901f": "DEBUG BOOTED",
}


class DeviceScanner:
    """Handles all device detection and scanning."""

    # ------------------------------------------------------------------
    # EDL via qdl list-server socket
    # ------------------------------------------------------------------

    @staticmethod
    def _query_list_socket(socket_path=QDL_LIST_SOCKET):
        """Connect to the qdl list-server socket and return the device list.

        Returns a list of dicts with 'vid', 'pid', 'serial', 'usb_path',
        or None if the server is unreachable.
        """
        try:
            sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
            sock.settimeout(1.0)
            sock.connect(socket_path)
            buf = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
            sock.close()
            raw = buf.decode()
            log.info("[EDL-TRACE] raw socket response: %r", raw)
            devices = json.loads(raw)
            log.info("[EDL-TRACE] parsed %d device(s) from list-server", len(devices))
            for d in devices:
                log.info("[EDL-TRACE]   entry: %s", d)
            return devices
        except FileNotFoundError:
            log.warning("[EDL-TRACE] list-server socket not found at %s — "
                        "run: sudo qdl list-server --socket %s",
                        socket_path, socket_path)
            return None
        except Exception as exc:
            log.warning("[EDL-TRACE] list-server query failed (%s): %s", socket_path, exc)
            return None

    @staticmethod
    def get_edl_devices(list_socket=QDL_LIST_SOCKET):
        """Return {usb_path: {serial, usb_path}} for EDL devices via the qdl list-server.

        Keyed by usb_path so duplicate serials don't collide.
        """
        device_list = DeviceScanner._query_list_socket(list_socket)
        if device_list is None:
            log.warning("No EDL devices returned (list-server unavailable)")
            return {}
        devices = {}
        for dev in device_list:
            path = (dev.get("usb_path") or "").strip()
            serial = (dev.get("serial") or "").strip()
            key = path or serial  # path is preferred; fall back to serial if qdl omits it
            if not key:
                log.warning("[EDL-TRACE] skipping entry with no path and no serial: %s", dev)
                continue
            devices[key] = {"serial": serial, "usb_path": path or None}
            log.info("[EDL-TRACE] get_edl_devices: key=%r serial=%r path=%r", key, serial, path)
        log.info("[EDL-TRACE] get_edl_devices returning keys: %s", list(devices.keys()))
        return devices

    # ------------------------------------------------------------------
    # Booted devices via pyudev
    # ------------------------------------------------------------------

    @staticmethod
    def _usb_devices(vid, pid):
        """Yield pyudev Device objects matching VID and PID."""
        for device in _udev_context.list_devices(subsystem='usb', DEVTYPE='usb_device'):
            try:
                if (device.attributes.asstring('idVendor') == vid and
                        device.attributes.asstring('idProduct') == pid):
                    yield device
            except KeyError:
                continue

    @staticmethod
    def _serial_from_device(device):
        """Read USB serial from a pyudev device, stripping any _SN: prefix."""
        try:
            raw = device.attributes.asstring('serial')
            m = re.search(r'_SN:([0-9a-fA-F]+)', raw)
            return m.group(1) if m else raw
        except KeyError:
            return None

    @staticmethod
    def get_adb_transport_map():
        """Map USB paths to ADB transport IDs.

        Returns {usb_path: transport_id}. Always called fresh — transport IDs
        change after every device reconnect so they must never be cached long-term.
        """
        usb_to_tid = {}
        try:
            adb_out = subprocess.check_output(["adb", "devices", "-l"]).decode()
            for line in adb_out.splitlines():
                m = re.search(r'usb:(\S+).*transport_id:(\d+)', line)
                if m:
                    usb_to_tid[m.group(1)] = m.group(2)
            log.debug("ADB transport map: %s", usb_to_tid)
        except Exception as exc:
            log.debug("ADB transport map unavailable: %s", exc)
        return usb_to_tid

    @staticmethod
    def get_build_id(transport_id):
        """Get build ID from device via ADB transport ID."""
        try:
            output = subprocess.check_output(
                ["adb", "-t", transport_id, "shell", "getprop", "ro.build.id"],
                stderr=subprocess.DEVNULL,
                timeout=2
            ).decode().strip()
            log.debug("Build ID for transport %s: %r", transport_id, output)
            return output if output else ""
        except Exception as exc:
            log.debug("get_build_id failed for transport %s: %s", transport_id, exc)
            return ""

    @staticmethod
    def get_booted_devices():
        """Scan for booted devices (USER/DEBUG modes) via pyudev.

        Returns {usb_path: {serial, mode, has_adb, path, [adb_tid]}}.
        Keyed by usb_path (sysfs sys_name) so duplicate serials don't collide.
        """
        devices = {}
        usb_to_tid = DeviceScanner.get_adb_transport_map()

        for vidpid, mode in _BOOTED_PID_MODE.items():
            vid, pid = vidpid.split(':')
            for device in DeviceScanner._usb_devices(vid, pid):
                path = device.sys_name  # e.g. "3-9.4.2" — stable physical port identifier
                if not path:
                    log.debug("Skipping booted device with no path (vid=%s pid=%s)", vid, pid)
                    continue

                hw_sn = DeviceScanner._serial_from_device(device) or path
                has_adb = (vidpid in ("18d1:4e11", "05c6:901f") or path in usb_to_tid)

                devices[path] = {
                    "serial": hw_sn,
                    "mode": mode,
                    "has_adb": has_adb,
                    "path": path,
                }
                if has_adb and path in usb_to_tid:
                    devices[path]["adb_tid"] = usb_to_tid[path]

                log.debug("Booted device: serial=%s mode=%s path=%s adb=%s",
                          hw_sn, mode, path, has_adb)

        return devices

    # ------------------------------------------------------------------
    # Combined scan
    # ------------------------------------------------------------------

    @staticmethod
    def scan_all(list_socket=QDL_LIST_SOCKET):
        """Complete device scan.

        Returns (set_of_usb_paths, devices_info_dict) where devices_info_dict
        is keyed by usb_path and each entry contains at least a 'serial' field.
        """
        currently_connected = set()
        devices_info = {}

        edl_devices = DeviceScanner.get_edl_devices(list_socket)
        for path, info in edl_devices.items():
            currently_connected.add(path)
            devices_info[path] = {
                "mode": "EDL",
                "has_adb": False,
                "path": path,
                "serial": info.get("serial", ""),
            }
        log.info("[EDL-TRACE] scan_all: %d EDL device(s): %s", len(edl_devices), list(edl_devices.keys()))

        booted_devices = DeviceScanner.get_booted_devices()
        for path, info in booted_devices.items():
            currently_connected.add(path)
            devices_info[path] = info
            if info.get("has_adb") and "adb_tid" in info:
                build_id = DeviceScanner.get_build_id(info["adb_tid"])
                if build_id:
                    devices_info[path]["build_id"] = build_id
        log.info("[EDL-TRACE] scan_all: %d booted device(s): %s", len(booted_devices), list(booted_devices.keys()))
        log.info("[EDL-TRACE] scan_all: total currently_connected: %s", sorted(currently_connected))
        return currently_connected, devices_info
