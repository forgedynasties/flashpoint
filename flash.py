import sys
import os
import subprocess
import re
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QComboBox, QLabel, 
                             QProgressBar, QScrollArea, QFileDialog, QMessageBox)
from PyQt6.QtCore import QTimer, QProcess, Qt

# --- CONFIGURATION ---
QDL_BIN = os.path.expanduser("~/aio/qdl/qdl")
# ---------------------

class DeviceFlashWidget(QWidget):
    def __init__(self, serial, remove_callback, reboot_callback):
        super().__init__()
        self.serial = serial
        self.remove_callback = remove_callback
        self.reboot_callback = reboot_callback
        self.is_flashing = False
        
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)
        self.layout.setSpacing(10)
        
        # Serial
        self.label = QLabel(f"<b>{serial}</b>")
        self.label.setFixedWidth(150)
        
        # Status
        self.status = QLabel("Ready")
        self.status.setFixedWidth(120)
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setStyleSheet("font-weight: bold; color: #1976D2; border: 1px solid #1976D2; border-radius: 4px;")
        
        # ADB Tag
        self.adb_tag = QLabel("ADB OK")
        self.adb_tag.setFixedWidth(65)
        self.adb_tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.adb_tag.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; border-radius: 3px; font-size: 10px;")
        self.adb_tag.hide()

        # Progress
        self.progress = QProgressBar()
        self.progress.setFixedWidth(150)
        
        # Log Preview
        self.log_preview = QLabel("Waiting...")
        self.log_preview.setStyleSheet("color: #666; font-family: monospace; font-size: 10px;")
        
        # Action Buttons
        self.btn_edl = QPushButton("EDL")
        self.btn_edl.setFixedWidth(60)
        self.btn_edl.setStyleSheet("background-color: #EDE7F6; color: #4527A0; font-weight: bold;")
        self.btn_edl.hide() 
        
        self.btn_flash = QPushButton("Flash")
        self.btn_flash.setFixedWidth(60)
        
        self.btn_remove = QPushButton("✕")
        self.btn_remove.setFixedWidth(30)
        self.btn_remove.setStyleSheet("color: red; font-weight: bold;")

        self.layout.addWidget(self.label)
        self.layout.addWidget(self.status)
        self.layout.addWidget(self.adb_tag)
        self.layout.addWidget(self.progress)
        self.layout.addWidget(self.log_preview, 1)
        self.layout.addWidget(self.btn_edl)
        self.layout.addWidget(self.btn_flash)
        self.layout.addWidget(self.btn_remove)

        self.process = QProcess()
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.handle_output)
        self.process.finished.connect(self.handle_finished)
        
        self.btn_remove.clicked.connect(lambda: self.remove_callback(self.serial))
        self.btn_edl.clicked.connect(self.trigger_edl_reboot)

    def trigger_edl_reboot(self):
        self.btn_edl.setText("...")
        self.btn_edl.setEnabled(False)
        self.reboot_callback(self.serial)
        QTimer.singleShot(2500, lambda: self.btn_edl.setText("EDL"))

    def set_boot_mode(self, mode_type, has_adb=False):
        if not self.is_flashing:
            self.status.setText(mode_type)
            color = "#00796B" if "USER" in mode_type else "#7B1FA2"
            self.status.setStyleSheet(f"font-weight: bold; color: {color}; border: 1px solid {color}; border-radius: 4px;")
            self.btn_flash.setEnabled(False)
            self.btn_edl.show()
            self.btn_edl.setEnabled(has_adb)
            self.adb_tag.setVisible(has_adb)

    def reset_to_ready(self):
        if not self.is_flashing:
            self.status.setText("Ready")
            self.status.setStyleSheet("font-weight: bold; color: #1976D2; border: 1px solid #1976D2; border-radius: 4px;")
            self.btn_flash.setEnabled(True)
            self.btn_edl.hide()
            self.adb_tag.hide()

    def start_flash(self, prog, raw, patch):
        if self.is_flashing: return
        self.is_flashing = True
        self.btn_flash.setEnabled(False)
        self.btn_edl.setEnabled(False)
        self.btn_remove.setEnabled(False)
        self.status.setText("FLASHING")
        self.status.setStyleSheet("font-weight: bold; color: #E65100; border: 1px solid #E65100; border-radius: 4px;")
        
        firmware_dir = os.path.dirname(raw)
        args = ["sudo", QDL_BIN, "-S", self.serial, "-s", "emmc", 
                os.path.basename(prog), os.path.basename(raw), 
                os.path.basename(patch), "-u", "1048576"]
        
        self.process.setWorkingDirectory(firmware_dir)
        self.process.start(args[0], args[1:])

    def handle_output(self):
        data = self.process.readAllStandardOutput().data().decode()
        for line in data.splitlines():
            self.log_preview.setText(line.strip()[-60:])
            match = re.search(r"(\d+\.\d+)%", line)
            if match: self.progress.setValue(int(float(match.group(1))))

    def handle_finished(self):
        self.is_flashing = False
        self.btn_remove.setEnabled(True)
        self.btn_flash.setEnabled(True)
        if self.process.exitCode() == 0:
            self.status.setText("SUCCESS")
            self.status.setStyleSheet("font-weight: bold; color: #2E7D32; border: 1px solid #2E7D32; border-radius: 4px;")
            self.progress.setValue(100)
        else:
            self.status.setText("FAILED")
            self.status.setStyleSheet("font-weight: bold; color: #C62828; border: 1px solid #C62828; border-radius: 4px;")

class FlashStation(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Qualcomm Pro Flash Station")
        self.setMinimumSize(1100, 600)
        self.devices = {}
        self.adb_transports = {}

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)

        self.setup_header()

        self.scroll = QScrollArea()
        self.container = QWidget()
        self.device_layout = QVBoxLayout(self.container)
        self.device_layout.addStretch() 
        self.scroll.setWidget(self.container)
        self.scroll.setWidgetResizable(True)
        self.main_layout.addWidget(self.scroll)

        self.timer = QTimer()
        self.timer.timeout.connect(self.scan)
        self.timer.start(1500)

    def setup_header(self):
        group = QWidget()
        layout = QHBoxLayout(group)
        self.fw_combo = QComboBox()
        self.fw_combo.setMinimumWidth(400)
        self.load_env_firmwares()
        
        btn_browse = QPushButton("Browse Folder")
        btn_browse.clicked.connect(self.pick_folder)

        self.btn_reboot_all_edl = QPushButton("REBOOT ALL TO EDL")
        self.btn_reboot_all_edl.setStyleSheet("background-color: #4527A0; color: white; font-weight: bold;")
        self.btn_reboot_all_edl.clicked.connect(self.reboot_all_to_edl)
        
        self.btn_start_all = QPushButton("FLASH ALL READY")
        self.btn_start_all.setStyleSheet("background-color: #1B5E20; color: white; font-weight: bold;")
        self.btn_start_all.clicked.connect(self.flash_all_ready)

        layout.addWidget(QLabel("<b>Firmware:</b>"))
        layout.addWidget(self.fw_combo)
        layout.addWidget(btn_browse)
        layout.addStretch()
        layout.addWidget(self.btn_reboot_all_edl)
        layout.addWidget(self.btn_start_all)
        self.main_layout.addWidget(group)

    def load_env_firmwares(self):
        base_path = os.getenv("FW_PATH")
        if not base_path or not os.path.isdir(base_path):
            self.fw_combo.addItem("Set FW_PATH env...")
            return
        dirs = [e.path for e in os.scandir(base_path) if e.is_dir() and self.validate_fw_folder(e.path)]
        if dirs:
            self.fw_combo.clear()
            self.fw_combo.addItems(dirs)

    def validate_fw_folder(self, path):
        try:
            files = os.listdir(path)
            return any(f.endswith(".elf") for f in files) and any("rawprogram" in f for f in files)
        except: return False

    def pick_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select Firmware Folder")
        if path and self.validate_fw_folder(path):
            if self.fw_combo.findText(path) == -1: self.fw_combo.insertItem(0, path)
            self.fw_combo.setCurrentText(path)

    def scan(self):
        currently_connected = set()
        usb_to_tid = {}
        
        # 1. Map ADB transport IDs to USB paths
        try:
            adb_out = subprocess.check_output(["adb", "devices", "-l"]).decode()
            for line in adb_out.splitlines():
                m = re.search(r'usb:(\d+-\d+).*transport_id:(\d+)', line)
                if m: usb_to_tid[m.group(1)] = m.group(2)
        except: pass

        # 2. EDL Devices (QDL)
        try:
            edl_res = subprocess.check_output(["sudo", QDL_BIN, "list"], stderr=subprocess.STDOUT).decode()
            for s in re.findall(r'05c6:9008\s+([0-9a-fA-F]+)', edl_res):
                currently_connected.add(s)
                if s not in self.devices: self.add_device_row(s)
                self.devices[s].reset_to_ready()
        except: pass

        # 3. Booted Devices (MTP: 4ee1 or MTP+ADB: 4e11)
        try:
            lsusb_res = subprocess.check_output(["lsusb"]).decode()
            for line in lsusb_res.splitlines():
                if any(x in line for x in ["18d1:4ee1", "18d1:4e11", "05c6:901f"]):
                    bus_match = re.search(r'Bus (\d+) Device (\d+)', line)
                    if not bus_match: continue
                    
                    s_bus, s_dev = bus_match.groups()
                    path = f"{s_bus.lstrip('0')}-2" 
                    
                    hw_sn = None
                    try:
                        # Scan verbose to find the SN: part in iProduct
                        v_out = subprocess.check_output(["lsusb", "-v", "-s", f"{s_bus}:{s_dev}"], stderr=subprocess.DEVNULL).decode()
                        # This matches your string: TRINKET-IOT-IDP_CID:0411_SN:F8AB9155
                        sn_match = re.search(r'_SN:([0-9a-fA-F]+)', v_out)
                        if sn_match:
                            hw_sn = sn_match.group(1)
                    except: pass

                    if hw_sn:
                        currently_connected.add(hw_sn)
                        if hw_sn not in self.devices: self.add_device_row(hw_sn)
                        
                        # ADB is active if PID is 4e11 (User) or 901f (Debug)
                        # OR if it's found in the adb devices -l transport list
                        has_adb = "18d1:4e11" in line or "05c6:901f" in line or path in usb_to_tid
                        
                        mode = "USER BOOTED" if ("4ee1" in line or "4e11" in line) else "DEBUG BOOTED"
                        self.devices[hw_sn].set_boot_mode(mode, has_adb)
                        
                        if has_adb and path in usb_to_tid:
                            self.adb_transports[hw_sn] = usb_to_tid[path]
        except: pass

        # 4. Clean up disconnected
        for s in list(self.devices.keys()):
            if s not in currently_connected and not self.devices[s].is_flashing:
                self.remove_device(s)

    def add_device_row(self, serial):
        w = DeviceFlashWidget(serial, self.remove_device, self.reboot_to_edl)
        self.devices[serial] = w
        self.device_layout.insertWidget(self.device_layout.count()-1, w)
        w.btn_flash.clicked.connect(lambda: self.handle_manual_flash(w))

    def reboot_to_edl(self, serial):
        if serial in self.adb_transports:
            tid = self.adb_transports[serial]
            subprocess.Popen(["adb", "-t", tid, "reboot", "edl"])

    def reboot_all_to_edl(self):
        for serial, tid in self.adb_transports.items():
            if serial in self.devices and self.devices[serial].btn_edl.isVisible():
                self.devices[serial].trigger_edl_reboot()

    def handle_manual_flash(self, widget):
        path = self.fw_combo.currentText()
        if not os.path.isdir(path): return
        files = os.listdir(path)
        try:
            prog = next(f for f in files if f.endswith(".elf"))
            raw = next(f for f in files if "rawprogram" in f and f.endswith(".xml"))
            patch = next(f for f in files if "patch" in f and f.endswith(".xml"))
            widget.start_flash(os.path.join(path, prog), os.path.join(path, raw), os.path.join(path, patch))
        except: pass

    def remove_device(self, serial):
        if serial in self.devices:
            widget = self.devices.pop(serial)
            widget.setParent(None)
            widget.deleteLater()

    def flash_all_ready(self):
        for w in self.devices.values():
            if not w.is_flashing and w.status.text() == "Ready":
                self.handle_manual_flash(w)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = FlashStation()
    win.show()
    sys.exit(app.exec())