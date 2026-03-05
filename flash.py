import sys
import os
import subprocess
import re
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLineEdit, QLabel, 
                             QProgressBar, QScrollArea, QFileDialog, QMessageBox)
from PyQt6.QtCore import QTimer, QProcess, Qt

# --- CONFIGURATION ---
QDL_BIN = os.path.expanduser("~/aio/qdl/qdl")
# ---------------------

class DeviceFlashWidget(QWidget):
    def __init__(self, serial, remove_callback):
        super().__init__()
        self.serial = serial
        self.remove_callback = remove_callback
        self.is_flashing = False
        self.is_finished = False
        
        self.layout = QHBoxLayout(self)
        
        # UI Elements
        self.label = QLabel(f"<b>{serial}</b>")
        self.label.setFixedWidth(130)
        
        self.progress = QProgressBar()
        self.status = QLabel("Ready")
        self.status.setFixedWidth(100)
        self.status.setStyleSheet("font-weight: bold; color: #1976D2;")
        
        self.log_preview = QLabel("Waiting...")
        self.log_preview.setStyleSheet("color: #666; font-family: monospace; font-size: 10px;")
        
        self.btn_flash = QPushButton("Flash")
        self.btn_flash.setFixedWidth(60)
        
        self.btn_remove = QPushButton("✕")
        self.btn_remove.setFixedWidth(30)
        self.btn_remove.setStyleSheet("color: red; font-weight: bold;")

        self.layout.addWidget(self.label)
        self.layout.addWidget(self.progress)
        self.layout.addWidget(self.status)
        self.layout.addWidget(self.log_preview, 1)
        self.layout.addWidget(self.btn_flash)
        self.layout.addWidget(self.btn_remove)

        self.process = QProcess()
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.handle_output)
        self.process.finished.connect(self.handle_finished)
        
        self.btn_remove.clicked.connect(lambda: self.remove_callback(self.serial))

    def set_booted_status(self):
        if not self.is_flashing:
            self.status.setText("BOOTED")
            self.status.setStyleSheet("color: #7B1FA2;") # Purple
            self.setStyleSheet("background-color: #F3E5F5;") # Light Purple
            self.log_preview.setText("Device detected in OS mode.")
            self.btn_flash.setEnabled(False)

    def reset_to_ready(self):
        if not self.is_flashing:
            self.status.setText("Ready")
            self.status.setStyleSheet("color: #1976D2;")
            self.setStyleSheet("")
            self.log_preview.setText("Device returned to EDL mode.")
            self.btn_flash.setEnabled(True)

    def set_firmware_params(self, prog, raw, patch):
        self.prog, self.raw, self.patch = prog, raw, patch

    def start_flash(self):
        if self.is_flashing: return
            
        firmware_dir = os.path.dirname(self.raw)
        args = ["sudo", QDL_BIN, "-S", self.serial, "-s", "emmc", 
                os.path.basename(self.prog), os.path.basename(self.raw), 
                os.path.basename(self.patch), "-u", "1048576"]
        
        self.is_flashing = True
        self.is_finished = False
        self.btn_flash.setEnabled(False)
        self.btn_remove.setEnabled(False)
        self.status.setText("FLASHING")
        self.status.setStyleSheet("color: #E65100;")
        self.setStyleSheet("background-color: #FFF3E0;")
        
        self.process.setWorkingDirectory(firmware_dir)
        self.process.start(args[0], args[1:])

    def handle_output(self):
        data = self.process.readAllStandardOutput().data().decode()
        for line in data.splitlines():
            clean = line.strip()
            if not clean: continue
            self.log_preview.setText(clean[-60:])
            match = re.search(r"(\d+\.\d+)%", clean)
            if match:
                self.progress.setValue(int(float(match.group(1))))

    def handle_finished(self):
        self.is_flashing = False
        self.btn_remove.setEnabled(True)
        if self.process.exitCode() == 0:
            self.is_finished = True
            self.status.setText("SUCCESS")
            self.status.setStyleSheet("color: #2E7D32;")
            self.setStyleSheet("background-color: #E8F5E9;")
            self.progress.setValue(100)
            self.btn_flash.setText("Reset")
            self.btn_flash.setEnabled(True)
        else:
            self.status.setText("FAILED")
            self.status.setStyleSheet("color: #C62828;")
            self.setStyleSheet("background-color: #FFEBEE;")
            self.btn_flash.setEnabled(True)
            self.btn_flash.setText("Retry")

class FlashStation(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Qualcomm Pro Flash Station (ADB Link)")
        self.setMinimumSize(1100, 600)
        self.devices = {}

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
        self.timer.start(1000)

    def setup_header(self):
        group = QWidget()
        layout = QHBoxLayout(group)
        self.fw_path = QLineEdit()
        btn_browse = QPushButton("Browse Folder")
        btn_browse.clicked.connect(self.pick_folder)
        
        self.btn_reboot_edl = QPushButton("REBOOT ALL TO EDL")
        self.btn_reboot_edl.setFixedHeight(40)
        self.btn_reboot_edl.setStyleSheet("background-color: #4527A0; color: white; font-weight: bold;")
        self.btn_reboot_edl.clicked.connect(self.reboot_all_to_edl)

        self.btn_start_all = QPushButton("FLASH ALL READY")
        self.btn_start_all.setFixedHeight(40)
        self.btn_start_all.setStyleSheet("background-color: #1B5E20; color: white; font-weight: bold;")
        self.btn_start_all.clicked.connect(self.flash_all_ready)

        layout.addWidget(QLabel("Firmware:"))
        layout.addWidget(self.fw_path)
        layout.addWidget(btn_browse)
        layout.addSpacing(10)
        layout.addWidget(self.btn_reboot_edl)
        layout.addWidget(self.btn_start_all)
        self.main_layout.addWidget(group)

    def pick_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select Firmware Folder")
        if path: self.fw_path.setText(path)

    def reboot_all_to_edl(self):
        """Finds all booted devices via ADB and triggers reboot edl using transport_id"""
        try:
            res = subprocess.check_output(["adb", "devices", "-l"]).decode()
            # Find transport_id for every line that is a 'device'
            transports = re.findall(r'transport_id:(\d+)', res)
            
            if not transports:
                print("[ADB] No booted devices found.")
                return

            for tid in transports:
                print(f"[ADB] Rebooting transport {tid} to EDL...")
                subprocess.Popen(["adb", "-t", tid, "reboot", "edl"])
        except Exception as e:
            print(f"[ADB] Error: {e}")

    def scan(self):
        currently_connected = set()

        # 1. Scan for EDL Devices
        try:
            edl_res = subprocess.check_output(["sudo", QDL_BIN, "list"], stderr=subprocess.STDOUT).decode()
            edl_serials = re.findall(r'05c6:9008\s+([0-9a-fA-F]+)', edl_res)
            for s in edl_serials:
                currently_connected.add(s)
                if s not in self.devices:
                    self.add_device_row(s)
                else:
                    if self.devices[s].status.text() == "BOOTED":
                        self.devices[s].reset_to_ready()
        except: pass

        # 2. Scan for Booted Devices (Normal Mode via lsusb)
        try:
            lsusb_res = subprocess.check_output(["lsusb"], stderr=subprocess.STDOUT).decode()
            booted_serials = re.findall(r'05c6:901f.*?SN:([0-9a-fA-F]+)', lsusb_res)
            for s in booted_serials:
                currently_connected.add(s)
                if s in self.devices:
                    self.devices[s].set_booted_status()
                else:
                    self.add_device_row(s)
                    self.devices[s].set_booted_status()
        except: pass

        # 3. Live Sync
        all_known = list(self.devices.keys())
        for s in all_known:
            if s not in currently_connected:
                if not self.devices[s].is_flashing:
                    self.remove_device(s)

    def add_device_row(self, serial):
        w = DeviceFlashWidget(serial, self.remove_device)
        self.devices[serial] = w
        self.device_layout.insertWidget(self.device_layout.count()-1, w)
        w.btn_flash.clicked.connect(w.start_flash)

    def remove_device(self, serial):
        if serial in self.devices:
            widget = self.devices.pop(serial)
            widget.setParent(None)
            widget.deleteLater()

    def flash_all_ready(self):
        path = self.fw_path.text()
        if not os.path.isdir(path): return
        
        files = os.listdir(path)
        prog = next((f for f in files if "firehose" in f and f.endswith(".elf")), 
                    next((f for f in files if f.endswith(".elf")), None))
        raw = next((f for f in files if "rawprogram" in f and f.endswith(".xml")), None)
        patch = next((f for f in files if "patch" in f and f.endswith(".xml")), None)

        if not all([prog, raw, patch]): return

        prog_p, raw_p, patch_p = [os.path.join(path, f) for f in [prog, raw, patch]]
        for w in self.devices.values():
            if not w.is_flashing and w.status.text() == "Ready":
                w.set_firmware_params(prog_p, raw_p, patch_p)
                w.start_flash()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = FlashStation()
    win.show()
    sys.exit(app.exec())