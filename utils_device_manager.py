"""Device scanning and detection utilities."""
import subprocess
import re
import os
from config import QDL_BIN, USB_PIDs


class DeviceScanner:
    """Handles all device detection and scanning."""
    
    @staticmethod
    def get_edl_devices():
        """Scan for EDL (QDL mode) devices. Returns dict of serial -> usb_path (or None)."""
        # Collect USB paths for all EDL PIDs found in lsusb
        edl_paths = []
        try:
            lsusb_res = subprocess.check_output(["lsusb"]).decode()
            for line in lsusb_res.splitlines():
                if "05c6:9008" not in line:
                    continue
                bus_match = re.search(r'Bus (\d+) Device (\d+)', line)
                if not bus_match:
                    continue
                s_bus, s_dev = bus_match.groups()
                path = DeviceScanner.get_usb_path(s_bus, s_dev)
                edl_paths.append(path)
        except:
            pass

        devices = {}
        try:
            edl_res = subprocess.check_output(
                ["sudo", QDL_BIN, "list"], stderr=subprocess.STDOUT
            ).decode()
            serials = re.findall(r'05c6:9008\s+([0-9a-fA-F]+)', edl_res)
            for i, s in enumerate(serials):
                path = edl_paths[i] if i < len(edl_paths) else None
                devices[s] = path
        except:
            pass
        return devices
    
    @staticmethod
    def get_usb_path(bus, devnum):
        """Resolve USB path (e.g. '3-1') from bus and device numbers via sysfs."""
        bus_s = str(int(bus))
        dev_s = str(int(devnum))
        try:
            for entry in os.listdir('/sys/bus/usb/devices'):
                base = f'/sys/bus/usb/devices/{entry}'
                try:
                    with open(f'{base}/busnum') as f:
                        if f.read().strip() != bus_s:
                            continue
                    with open(f'{base}/devnum') as f:
                        if f.read().strip() == dev_s:
                            return entry  # e.g. "3-1"
                except OSError:
                    continue
        except OSError:
            pass
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
        except:
            pass
        return usb_to_tid
    
    @staticmethod
    def get_build_id(transport_id):
        """Get build ID from device via ADB using transport ID.

        Args:
            transport_id: ADB transport ID string

        Returns:
            Build ID string or empty string if not available
        """
        try:
            output = subprocess.check_output(
                ["adb", "-t", transport_id, "shell", "getprop", "ro.build.id"],
                stderr=subprocess.DEVNULL,
                timeout=2
            ).decode().strip()
            return output if output else ""
        except:
            return ""
    
    @staticmethod
    def get_booted_devices():
        """Scan for booted devices (USER/DEBUG modes)."""
        devices = {}
        usb_to_tid = DeviceScanner.get_adb_transport_map()
        
        try:
            lsusb_res = subprocess.check_output(["lsusb"]).decode()
            for line in lsusb_res.splitlines():
                if not any(x in line for x in USB_PIDs["USER_BOOTED"] + USB_PIDs["DEBUG_BOOTED"]):
                    continue
                
                bus_match = re.search(r'Bus (\d+) Device (\d+)', line)
                if not bus_match:
                    continue
                
                s_bus, s_dev = bus_match.groups()
                path = DeviceScanner.get_usb_path(s_bus, s_dev)
                
                hw_sn = None
                try:
                    v_out = subprocess.check_output(
                        ["lsusb", "-v", "-s", f"{s_bus}:{s_dev}"],
                        stderr=subprocess.DEVNULL
                    ).decode()
                    sn_match = re.search(r'_SN:([0-9a-fA-F]+)', v_out)
                    if sn_match:
                        hw_sn = sn_match.group(1)
                except:
                    pass
                
                if hw_sn and path:
                    has_adb = (
                        "18d1:4e11" in line or
                        "05c6:901f" in line or
                        path in usb_to_tid
                    )
                    mode = "USER BOOTED" if "4ee1" in line or "4e11" in line else "DEBUG BOOTED"

                    devices[hw_sn] = {
                        "mode": mode,
                        "has_adb": has_adb,
                        "path": path,
                    }

                    if has_adb and path in usb_to_tid:
                        devices[hw_sn]["adb_tid"] = usb_to_tid[path]
        except:
            pass
        
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
            
            # Get build_id if ADB is available, using transport ID
            if info.get("has_adb") and "adb_tid" in info:
                build_id = DeviceScanner.get_build_id(info["adb_tid"])
                if build_id:
                    devices_info[serial]["build_id"] = build_id
        
        return currently_connected, devices_info
