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
            devices = json.loads(buf.decode())
            log.debug("qdl list-server returned %d device(s)", len(devices))
            return devices
        except FileNotFoundError:
            log.warning("qdl list-server socket not found at %s — "
                        "run: sudo qdl list-server --socket %s",
                        socket_path, socket_path)
            return None
        except Exception as exc:
            log.warning("qdl list-server query failed (%s): %s", socket_path, exc)
            return None

    @staticmethod
    def get_edl_devices(list_socket=QDL_LIST_SOCKET):
        """Return {serial: usb_path} for EDL devices via the qdl list-server."""
        device_list = DeviceScanner._query_list_socket(list_socket)
        if device_list is None:
            log.warning("No EDL devices returned (list-server unavailable)")
            return {}
        devices = {}
        for dev in device_list:
            serial = dev.get("serial", "").strip()
            if serial:
                devices[serial] = dev.get("usb_path") or None
                log.debug("EDL device: serial=%s path=%s", serial, devices[serial])
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
        """Map USB paths to ADB transport IDs."""
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
        """Scan for booted devices (USER/DEBUG modes) via pyudev."""
        devices = {}
        usb_to_tid = DeviceScanner.get_adb_transport_map()

        for vidpid, mode in _BOOTED_PID_MODE.items():
            vid, pid = vidpid.split(':')
            for device in DeviceScanner._usb_devices(vid, pid):
                hw_sn = DeviceScanner._serial_from_device(device)
                if not hw_sn:
                    log.debug("Skipping booted device with no serial (vid=%s pid=%s)", vid, pid)
                    continue

                path = device.sys_name
                has_adb = (vidpid in ("18d1:4e11", "05c6:901f") or path in usb_to_tid)

                devices[hw_sn] = {
                    "mode": mode,
                    "has_adb": has_adb,
                    "path": path,
                }
                if has_adb and path in usb_to_tid:
                    devices[hw_sn]["adb_tid"] = usb_to_tid[path]

                log.debug("Booted device: serial=%s mode=%s path=%s adb=%s",
                          hw_sn, mode, path, has_adb)

        return devices

    # ------------------------------------------------------------------
    # Combined scan
    # ------------------------------------------------------------------

    @staticmethod
    def scan_all(list_socket=QDL_LIST_SOCKET):
        """Complete device scan. Returns (set_of_serials, devices_info_dict)."""
        currently_connected = set()
        devices_info = {}

        edl_devices = DeviceScanner.get_edl_devices(list_socket)
        for serial, path in edl_devices.items():
            currently_connected.add(serial)
            devices_info[serial] = {"mode": "EDL", "has_adb": False, "path": path}

        booted_devices = DeviceScanner.get_booted_devices()
        for serial, info in booted_devices.items():
            currently_connected.add(serial)
            devices_info[serial] = info
            if info.get("has_adb") and "adb_tid" in info:
                build_id = DeviceScanner.get_build_id(info["adb_tid"])
                if build_id:
                    devices_info[serial]["build_id"] = build_id

        log.debug("scan_all: %d device(s) connected", len(currently_connected))
        return currently_connected, devices_info
