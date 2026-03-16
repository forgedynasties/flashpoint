"""Device scanning and detection utilities."""
import subprocess
import re
import pyudev
from config import USB_PIDs


_udev_context = pyudev.Context()

# Map VID:PID strings to mode labels for booted devices
_BOOTED_PID_MODE = {
    "18d1:4ee1": "USER BOOTED",
    "18d1:4e11": "DEBUG BOOTED",
    "05c6:901f": "DEBUG BOOTED",
}


class DeviceScanner:
    """Handles all device detection and scanning."""

    @staticmethod
    def _usb_devices(vid, pid):
        """Yield pyudev Device objects matching the given VID and PID."""
        for device in _udev_context.list_devices(subsystem='usb', DEVTYPE='usb_device'):
            try:
                if (device.attributes.asstring('idVendor') == vid and
                        device.attributes.asstring('idProduct') == pid):
                    yield device
            except KeyError:
                continue

    @staticmethod
    def _serial_from_device(device):
        """Read the USB serial string from a pyudev device, stripping any _SN: prefix."""
        try:
            raw = device.attributes.asstring('serial')
            m = re.search(r'_SN:([0-9a-fA-F]+)', raw)
            return m.group(1) if m else raw
        except KeyError:
            return None

    @staticmethod
    def get_edl_devices():
        """Scan for EDL (QDL mode) devices via udev. Returns dict of serial -> usb_path."""
        devices = {}
        for device in DeviceScanner._usb_devices('05c6', '9008'):
            serial = DeviceScanner._serial_from_device(device)
            if serial:
                devices[serial] = device.sys_name  # e.g. "3-1"
        return devices

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
        except Exception:
            pass
        return usb_to_tid

    @staticmethod
    def get_build_id(transport_id):
        """Get build ID from device via ADB using transport ID."""
        try:
            output = subprocess.check_output(
                ["adb", "-t", transport_id, "shell", "getprop", "ro.build.id"],
                stderr=subprocess.DEVNULL,
                timeout=2
            ).decode().strip()
            return output if output else ""
        except Exception:
            return ""

    @staticmethod
    def get_booted_devices():
        """Scan for booted devices (USER/DEBUG modes) via udev."""
        devices = {}
        usb_to_tid = DeviceScanner.get_adb_transport_map()

        for vidpid, mode in _BOOTED_PID_MODE.items():
            vid, pid = vidpid.split(':')
            for device in DeviceScanner._usb_devices(vid, pid):
                hw_sn = DeviceScanner._serial_from_device(device)
                if not hw_sn:
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

        return devices

    @staticmethod
    def scan_all():
        """Complete device scan returning currently connected devices."""
        currently_connected = set()
        devices_info = {}

        # EDL Devices
        edl_devices = DeviceScanner.get_edl_devices()
        for serial, path in edl_devices.items():
            currently_connected.add(serial)
            devices_info[serial] = {"mode": "EDL", "has_adb": False, "path": path}

        # Booted devices
        booted_devices = DeviceScanner.get_booted_devices()
        for serial, info in booted_devices.items():
            currently_connected.add(serial)
            devices_info[serial] = info

            # Get build_id if ADB is available
            if info.get("has_adb") and "adb_tid" in info:
                build_id = DeviceScanner.get_build_id(info["adb_tid"])
                if build_id:
                    devices_info[serial]["build_id"] = build_id

        return currently_connected, devices_info
