import sys
import os
import subprocess
import re
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLineEdit, QLabel, 
                             QProgressBar, QScrollArea, QFileDialog, QMessageBox)
from PyQt6.QtCore import QTimer, QProcess, Qt

QDL_BIN = os.path.expanduser("~/aio/qdl/qdl")

class DeviceFlashWidget(QWidget):
    def __init__(self, serial, remove_callback):
        super().__init__()
        self.serial = serial
        self.remove_callback = remove_callback
        self.is_flashing = False
        self.is_finished = False # New state to prevent accidental re-flashing
        
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
        
        # Individual Actions
        self.btn_flash = QPushButton("Flash")
        self.btn_flash.setFixedWidth(60)
        
        self.btn_remove = QPushButton("✕")
        self.btn_remove.setFixedWidth(30)
        self.btn_remove.setToolTip("Remove from list")
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

    def set_firmware_params(self, prog, raw, patch):
        self.prog, self.raw, self.patch = prog, raw, patch

    def start_flash(self):
        if self.is_flashing or self.is_finished:
            return
            
        firmware_dir = os.path.dirname(self.raw)
        args = ["sudo", QDL_BIN, "-S", self.serial, "-s", "emmc", 
                os.path.basename(self.prog), os.path.basename(self.raw), 
                os.path.basename(self.patch), "-u", "1048576"]
        
        self.is_flashing = True
        self.btn_flash.setEnabled(False)
        self.btn_remove.setEnabled(False)
        self.status.setText("FLASHING")
        self.status.setStyleSheet("color: #E65100;") # Orange
        self.setStyleSheet("background-color: #FFF3E0;") # Light Orange tint
        
        self.process.setWorkingDirectory(firmware_dir)
        self.process.start(args[0], args[1:])

    def handle_output(self):
        data = self.process.readAllStandardOutput().data().decode()
        for line in data.splitlines():
            clean = line.strip()
            if not clean: continue
            print(f"[{self.serial}] {clean}")
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
            self.status.setStyleSheet("color: #2E7D32;") # Green
            self.setStyleSheet("background-color: #E8F5E9;") # Light Green
            self.progress.setValue(100)
            self.btn_flash.setText("Reset")
            self.btn_flash.setEnabled(True)
            self.btn_flash.clicked.disconnect()
            self.btn_flash.clicked.connect(self.reset_device)
        else:
            self.status.setText("FAILED")
            self.status.setStyleSheet("color: #C62828;") # Red
            self.setStyleSheet("background-color: #FFEBEE;") # Light Red
            self.btn_flash.setEnabled(True)
            self.btn_flash.setText("Retry")

    def reset_device(self):
        """Allows re-flashing if explicitly clicked"""
        self.is_finished = False
        self.status.setText("Ready")
        self.status.setStyleSheet("color: #1976D2;")
        self.setStyleSheet("")
        self.progress.setValue(0)
        self.btn_flash.setText("Flash")
        self.btn_flash.clicked.disconnect()
        self.btn_flash.clicked.connect(self.start_flash)

class FlashStation(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Qualcomm Pro Flash Station")
        self.setMinimumSize(1000, 600)
        self.devices = {}

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)

        self.setup_header()

        # Labels for the list
        list_header = QHBoxLayout()
        list_header.addWidget(QLabel("<b>Device Serial</b>"), 0)
        list_header.addWidget(QLabel("<b>Progress</b>"), 1)
        list_header.addWidget(QLabel("<b>Status</b>"), 0)
        list_header.addWidget(QLabel("<b>Logs</b>"), 1)
        list_header.setContentsMargins(10, 0, 110, 0)
        self.main_layout.addLayout(list_header)

        self.scroll = QScrollArea()
        self.container = QWidget()
        self.device_layout = QVBoxLayout(self.container)
        self.device_layout.addStretch() 
        self.scroll.setWidget(self.container)
        self.scroll.setWidgetResizable(True)
        self.main_layout.addWidget(self.scroll)

        self.timer = QTimer()
        self.timer.timeout.connect(self.scan)
        self.timer.start(800) # Slightly slower scan to save CPU

    def setup_header(self):
        group = QWidget()
        layout = QHBoxLayout(group)
        self.fw_path = QLineEdit()
        btn_browse = QPushButton("Browse Folder")
        btn_browse.clicked.connect(self.pick_folder)
        
        self.btn_start_all = QPushButton("FLASH ALL READY")
        self.btn_start_all.setFixedHeight(40)
        self.btn_start_all.setStyleSheet("background-color: #1B5E20; color: white; font-weight: bold;")
        self.btn_start_all.clicked.connect(self.flash_all_ready)

        self.btn_clear_done = QPushButton("Clear Finished")
        self.btn_clear_done.clicked.connect(self.clear_finished)

        layout.addWidget(QLabel("Firmware:"))
        layout.addWidget(self.fw_path)
        layout.addWidget(btn_browse)
        layout.addSpacing(20)
        layout.addWidget(self.btn_clear_done)
        layout.addWidget(self.btn_start_all)
        self.main_layout.addWidget(group)

    def pick_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select Firmware Folder")
        if path: self.fw_path.setText(path)

    def scan(self):
        try:
            res = subprocess.check_output(["sudo", QDL_BIN, "list"], stderr=subprocess.STDOUT).decode()
            serials = re.findall(r'05c6:9008\s+([0-9a-fA-F]+)', res)
            
            for s in serials:
                if s not in self.devices:
                    w = DeviceFlashWidget(s, self.remove_device)
                    self.devices[s] = w
                    self.device_layout.insertWidget(self.device_layout.count()-1, w)
                    # Connect individual flash button
                    w.btn_flash.clicked.connect(w.start_flash)
        except: pass

    def remove_device(self, serial):
        if serial in self.devices:
            widget = self.devices.pop(serial)
            widget.setParent(None)
            widget.deleteLater()

    def clear_finished(self):
        to_remove = [s for s, w in self.devices.items() if w.is_finished and not w.is_flashing]
        for s in to_remove:
            self.remove_device(s)

    def flash_all_ready(self):
        path = self.fw_path.text()
        if not os.path.isdir(path): return

        files = os.listdir(path)
        prog = next((f for f in files if "firehose" in f and f.endswith(".elf")), 
                    next((f for f in files if f.endswith(".elf")), None))
        raw = next((f for f in files if "rawprogram" in f and f.endswith(".xml")), None)
        patch = next((f for f in files if "patch" in f and f.endswith(".xml")), None)

        if not all([prog, raw, patch]):
            QMessageBox.warning(self, "Files Missing", "Check folder for .elf and .xml files.")
            return

        prog_p, raw_p, patch_p = [os.path.join(path, f) for f in [prog, raw, patch]]

        for w in self.devices.values():
            if not w.is_flashing and not w.is_finished:
                w.set_firmware_params(prog_p, raw_p, patch_p)
                w.start_flash()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = FlashStation()
    win.show()
    sys.exit(app.exec())