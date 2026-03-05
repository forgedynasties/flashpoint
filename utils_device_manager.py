"""Device scanning and detection utilities."""
import subprocess
import re
from config import QDL_BIN, USB_PIDs


class DeviceScanner:
    """Handles all device detection and scanning."""
    
    @staticmethod
    def get_edl_devices():
        """Scan for EDL (QDL mode) devices."""
        devices = set()
        try:
            edl_res = subprocess.check_output(
                ["sudo", QDL_BIN, "list"], stderr=subprocess.STDOUT
            ).decode()
            for s in re.findall(r'05c6:9008\s+([0-9a-fA-F]+)', edl_res):
                devices.add(s)
        except:
            pass
        return devices
    
    @staticmethod
    def get_adb_transport_map():
        """Map USB paths to ADB transport IDs."""
        usb_to_tid = {}
        try:
            adb_out = subprocess.check_output(["adb", "devices", "-l"]).decode()
            for line in adb_out.splitlines():
                m = re.search(r'usb:(\d+-\d+).*transport_id:(\d+)', line)
                if m:
                    usb_to_tid[m.group(1)] = m.group(2)
        except:
            pass
        return usb_to_tid
    
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
                path = f"{s_bus.lstrip('0')}-2"
                
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
                
                if hw_sn:
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
        for serial in edl_devices:
            currently_connected.add(serial)
            devices_info[serial] = {"mode": "EDL", "has_adb": False}
        
        # Booted devices
        booted_devices = DeviceScanner.get_booted_devices()
        for serial, info in booted_devices.items():
            currently_connected.add(serial)
            devices_info[serial] = info
        
        return currently_connected, devices_info
