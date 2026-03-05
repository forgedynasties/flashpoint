"""Main application window for the flash station."""
import os
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox,
    QLabel, QScrollArea, QFileDialog, QMessageBox
)
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QFont

from config import SCAN_INTERVAL_MS, FW_PATH_ENV
from styles import Styles, Colors
from widgets_device import DeviceFlashWidget
from utils_device_manager import DeviceScanner
from utils_flash_manager import FlashManager, RebootManager


class FlashStation(QMainWindow):
    """Main application window for managing device flashing."""
    
    def __init__(self):
        """Initialize the flash station."""
        super().__init__()
        self.setWindowTitle("Qualcomm Pro Flash Station")
        self.setMinimumSize(1200, 650)
        self.setGeometry(100, 100, 1200, 650)
        
        self.devices = {}
        self.adb_transports = {}
        
        self.setup_ui()
        self.setup_scanning()
    
    def setup_ui(self):
        """Set up the user interface."""
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.central_widget.setStyleSheet(Styles.get_main_window_style())
        
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        self.setup_header()
        self.setup_device_list()
    
    def setup_header(self):
        """Set up the header section with controls."""
        header = QWidget()
        header.setStyleSheet(Styles.get_header_group_style())
        layout = QHBoxLayout(header)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        
        # Firmware selector
        fw_label = QLabel("Firmware:")
        fw_font = fw_label.font()
        fw_font.setBold(True)
        fw_label.setFont(fw_font)
        
        self.fw_combo = QComboBox()
        self.fw_combo.setMinimumWidth(450)
        self.fw_combo.setStyleSheet("""
            QComboBox {
                padding: 6px;
                border: 1px solid #E0E0E0;
                border-radius: 4px;
                background-color: white;
            }
        """)
        self.load_env_firmwares()
        
        # Browse button
        btn_browse = QPushButton("📁 Browse Folder")
        btn_browse.setStyleSheet(Styles.get_action_button_style())
        btn_browse.clicked.connect(self.pick_folder)
        
        layout.addWidget(fw_label)
        layout.addWidget(self.fw_combo)
        layout.addWidget(btn_browse)
        layout.addStretch()
        
        # Reboot to EDL button
        self.btn_reboot_all_edl = QPushButton("🔌 REBOOT ALL TO EDL")
        self.btn_reboot_all_edl.setStyleSheet(Styles.get_action_button_style(Colors.TAG_PURPLE))
        self.btn_reboot_all_edl.setMinimumWidth(180)
        self.btn_reboot_all_edl.clicked.connect(self.reboot_all_to_edl)
        
        # Flash all ready button
        self.btn_start_all = QPushButton("⚡ FLASH ALL READY")
        self.btn_start_all.setStyleSheet(Styles.get_action_button_style(Colors.SUCCESS))
        self.btn_start_all.setMinimumWidth(160)
        self.btn_start_all.clicked.connect(self.flash_all_ready)
        
        layout.addWidget(self.btn_reboot_all_edl)
        layout.addWidget(self.btn_start_all)
        
        self.main_layout.addWidget(header)
    
    def setup_device_list(self):
        """Set up the scrollable device list."""
        self.scroll = QScrollArea()
        self.scroll.setStyleSheet(Styles.get_scroll_area_style())
        self.scroll.setWidgetResizable(True)
        
        self.container = QWidget()
        self.container.setStyleSheet("background-color: #F5F5F5;")
        self.device_layout = QVBoxLayout(self.container)
        self.device_layout.setContentsMargins(8, 8, 8, 8)
        self.device_layout.setSpacing(6)
        self.device_layout.addStretch()
        
        self.scroll.setWidget(self.container)
        self.main_layout.addWidget(self.scroll)
    
    def setup_scanning(self):
        """Set up device scanning timer."""
        self.timer = QTimer()
        self.timer.timeout.connect(self.scan)
        self.timer.start(SCAN_INTERVAL_MS)
    
    def load_env_firmwares(self):
        """Load firmware folders from FW_PATH environment variable."""
        base_path = os.getenv(FW_PATH_ENV)
        if not base_path or not os.path.isdir(base_path):
            self.fw_combo.addItem("Set FW_PATH env...")
            return
        
        dirs = [
            e.path for e in os.scandir(base_path)
            if e.is_dir() and FlashManager.validate_firmware_folder(e.path)
        ]
        
        if dirs:
            self.fw_combo.clear()
            self.fw_combo.addItems(dirs)
    
    def pick_folder(self):
        """Open folder picker dialog."""
        path = QFileDialog.getExistingDirectory(self, "Select Firmware Folder")
        if path and FlashManager.validate_firmware_folder(path):
            if self.fw_combo.findText(path) == -1:
                self.fw_combo.insertItem(0, path)
            self.fw_combo.setCurrentText(path)
    
    def scan(self):
        """Scan for connected devices."""
        currently_connected, devices_info = DeviceScanner.scan_all()
        
        # Add new devices
        for serial in currently_connected:
            if serial not in self.devices:
                self.add_device_row(serial)
            
            # Update device status
            info = devices_info[serial]
            device = self.devices[serial]
            
            if info["mode"] == "EDL":
                device.reset_to_ready()
            else:
                device.set_boot_mode(info["mode"], info.get("has_adb", False))
                if "adb_tid" in info:
                    self.adb_transports[serial] = info["adb_tid"]
        
        # Remove disconnected devices
        for serial in list(self.devices.keys()):
            if serial not in currently_connected and not self.devices[serial].is_flashing:
                self.remove_device(serial)
    
    def add_device_row(self, serial):
        """Add a new device widget to the list.
        
        Args:
            serial: Device serial number
        """
        widget = DeviceFlashWidget(serial, self.remove_device, self.reboot_to_edl)
        self.devices[serial] = widget
        self.device_layout.insertWidget(self.device_layout.count() - 1, widget)
        widget.btn_flash.clicked.connect(lambda: self.handle_manual_flash(widget))
    
    def remove_device(self, serial):
        """Remove a device widget.
        
        Args:
            serial: Device serial number
        """
        if serial in self.devices:
            widget = self.devices.pop(serial)
            widget.setParent(None)
            widget.deleteLater()
            self.adb_transports.pop(serial, None)
    
    def reboot_to_edl(self, serial):
        """Reboot device to EDL mode.
        
        Args:
            serial: Device serial number
        """
        if serial in self.adb_transports:
            tid = self.adb_transports[serial]
            RebootManager.reboot_to_edl(tid)
    
    def reboot_all_to_edl(self):
        """Reboot all connected devices to EDL mode."""
        for serial, tid in self.adb_transports.items():
            if serial in self.devices and self.devices[serial].btn_edl.isVisible():
                self.devices[serial].trigger_edl_reboot()
    
    def handle_manual_flash(self, widget):
        """Handle manual flash button click.
        
        Args:
            widget: DeviceFlashWidget instance
        """
        fw_path = self.fw_combo.currentText()
        if not os.path.isdir(fw_path):
            QMessageBox.warning(self, "Invalid Path", "Please select a valid firmware folder.")
            return
        
        prog, raw, patch = FlashManager.find_firmware_files(fw_path)
        if prog and raw and patch:
            widget.start_flash(prog, raw, patch)
        else:
            QMessageBox.warning(
                self,
                "Incomplete Firmware",
                "Could not find required firmware files (.elf, rawprogram.xml, patch.xml)"
            )
    
    def flash_all_ready(self):
        """Flash all devices that are ready."""
        for widget in self.devices.values():
            if not widget.is_flashing and widget.status.text() == "Ready":
                self.handle_manual_flash(widget)
