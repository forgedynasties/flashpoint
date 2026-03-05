import sys
import os
import subprocess
import re
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLineEdit, QLabel, 
                             QProgressBar, QScrollArea, QFileDialog, QMessageBox)
from PyQt6.QtCore import QTimer, QProcess

# --- CONFIGURATION ---
# Ensure this path is correct and has NOPASSWD rights in /etc/sudoers
QDL_BIN = os.path.expanduser("~/aio/qdl/qdl")
# ---------------------

class DeviceFlashWidget(QWidget):
    """Individual UI row for a single device"""
    def __init__(self, serial):
        super().__init__()
        self.serial = serial
        self.layout = QHBoxLayout(self)
        
        self.label = QLabel(f"Serial: {serial}")
        self.label.setFixedWidth(150)
        self.progress = QProgressBar()
        self.status = QLabel("Ready")
        self.status.setFixedWidth(120)
        self.log_preview = QLabel("")
        self.log_preview.setStyleSheet("color: #666; font-family: monospace; font-size: 10px;")

        self.layout.addWidget(self.label)
        self.layout.addWidget(self.progress)
        self.layout.addWidget(self.status)
        self.layout.addWidget(self.log_preview, 1)

        self.process = QProcess()
        # Merge stdout and stderr so we see "Unable to open" errors
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.handle_output)
        self.process.finished.connect(self.handle_finished)

    def start_flash(self, prog_path, raw_path, patch_path):
        # 1. Determine the folder where firmware lives
        firmware_dir = os.path.dirname(raw_path)
        
        # 2. Get filenames only (qdl needs them relative to its working dir)
        prog_name = os.path.basename(prog_path)
        raw_name = os.path.basename(raw_path)
        patch_name = os.path.basename(patch_path)

        # 3. Build Command (including sudo and optimized chunk size)
        args = ["sudo", QDL_BIN, "-S", self.serial, "-s", "emmc", 
                prog_name, raw_name, patch_name, "-u", "1048576"]
        
        # 4. Set CWD to firmware dir so qdl finds all the .bin files
        self.process.setWorkingDirectory(firmware_dir)
        
        self.progress.setValue(0)
        self.status.setText("Flashing...")
        
        print(f"\n[DEBUG] Starting Flash: {self.serial}")
        print(f"[DEBUG] Directory: {firmware_dir}")
        print(f"[DEBUG] Command: {' '.join(args)}")
        
        self.process.start(args[0], args[1:])

    def handle_output(self):
        data = self.process.readAllStandardOutput().data().decode()
        for line in data.splitlines():
            clean = line.strip()
            if not clean: continue
            
            # Print full log to terminal for debugging
            print(f"[{self.serial}] {clean}")
            
            # Show last part of log in GUI
            self.log_preview.setText(clean[-60:])
            
            # Parse progress percentage
            match = re.search(r"(\d+\.\d+)%", clean)
            if match:
                self.progress.setValue(int(float(match.group(1))))
            
            if "successfully" in clean.lower():
                self.status.setText("Flashing...")

    def handle_finished(self):
        if self.process.exitCode() == 0:
            self.status.setText("SUCCESS")
            self.progress.setValue(100)
            print(f"[INFO] {self.serial} Flash Completed.")
        else:
            self.status.setText("FAILED")
            print(f"[ERROR] {self.serial} Flash Failed (Exit Code: {self.process.exitCode()})")

class FlashStation(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Qualcomm Parallel Flash Station")
        self.setMinimumSize(950, 500)
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

        # Monitor for devices every 500ms
        self.timer = QTimer()
        self.timer.timeout.connect(self.scan)
        self.timer.start(500)

    def setup_header(self):
        group = QWidget()
        layout = QHBoxLayout(group)
        
        self.fw_path = QLineEdit()
        self.fw_path.setPlaceholderText("Select Firmware Directory...")
        
        btn_browse = QPushButton("Browse")
        btn_browse.clicked.connect(self.pick_folder)
        
        btn_flash = QPushButton("START ALL")
        btn_flash.setMinimumHeight(40)
        btn_flash.setStyleSheet("background-color: #1b5e20; color: white; font-weight: bold;")
        btn_flash.clicked.connect(self.flash_all)

        layout.addWidget(QLabel("Firmware:"))
        layout.addWidget(self.fw_path)
        layout.addWidget(btn_browse)
        layout.addWidget(btn_flash)
        self.main_layout.addWidget(group)

    def pick_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select Firmware Folder")
        if path:
            self.fw_path.setText(path)

    def scan(self):
        try:
            # Use sudo list to avoid udev permission issues
            res = subprocess.check_output(["sudo", QDL_BIN, "list"], stderr=subprocess.STDOUT).decode()
            serials = re.findall(r'05c6:9008\s+([0-9a-fA-F]+)', res)
            
            for s in serials:
                if s not in self.devices:
                    print(f"[INFO] Device Detected: {s}")
                    w = DeviceFlashWidget(s)
                    self.devices[s] = w
                    # Insert widget before the stretch
                    self.device_layout.insertWidget(self.device_layout.count()-1, w)
        except Exception:
            pass

    def flash_all(self):
        path = self.fw_path.text()
        if not os.path.isdir(path):
            QMessageBox.critical(self, "Error", "Invalid Firmware Directory")
            return

        # Automatically detect the 3 required files
        files = os.listdir(path)
        # Prioritize files with 'firehose' in the name for the loader
        prog = next((f for f in files if "firehose" in f and f.endswith(".elf")), 
                    next((f for f in files if f.endswith(".elf")), None))
        raw = next((f for f in files if "rawprogram" in f and f.endswith(".xml")), None)
        patch = next((f for f in files if "patch" in f and f.endswith(".xml")), None)

        if not all([prog, raw, patch]):
            QMessageBox.warning(self, "Missing Files", f"Found:\nProg: {prog}\nRaw: {raw}\nPatch: {patch}")
            return

        prog_p, raw_p, patch_p = [os.path.join(path, f) for f in [prog, raw, patch]]

        for widget in self.devices.values():
            if widget.status.text() in ["Ready", "FAILED", "SUCCESS"]:
                widget.start_flash(prog_p, raw_p, patch_p)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = FlashStation()
    window.show()
    sys.exit(app.exec())