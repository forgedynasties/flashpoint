"""Main application window for the flash station."""
import os
import re
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox,
    QLabel, QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem, QProgressBar,
    QPlainTextEdit
)
from PyQt6.QtCore import QTimer, Qt, QProcess

from config import SCAN_INTERVAL_MS, FW_PATH_ENV
from styles import Styles, Colors
from utils_device_manager import DeviceScanner
from utils_flash_manager import FlashManager, RebootManager


class FlashStation(QMainWindow):
    """Main application window for managing device flashing."""
    
    def __init__(self):
        """Initialize the flash station."""
        super().__init__()
        self.setWindowTitle("Qualcomm Flash Station")
        self.setMinimumSize(1000, 600)
        self.setGeometry(100, 100, 1000, 600)
        
        self.devices = {}
        self.adb_transports = {}
        self.device_processes = {}
        
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
        self.setup_device_table()
    
    def setup_header(self):
        """Set up the header section with controls."""
        header = QWidget()
        header.setStyleSheet(Styles.get_header_group_style())
        layout = QHBoxLayout(header)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # Firmware section
        fw_label = QLabel("Firmware:")
        fw_label.setStyleSheet(f"color: {Colors.DARK_TEXT}; font-weight: bold;")
        
        self.fw_combo = QComboBox()
        self.fw_combo.setMinimumWidth(300)
        self.fw_combo.setMaximumWidth(450)
        self.fw_combo.setStyleSheet(Styles.get_combobox_style())
        self.load_env_firmwares()
        
        # Browse button
        btn_browse = QPushButton("Browse")
        btn_browse.setFixedSize(70, 30)
        btn_browse.setStyleSheet(Styles.get_action_button_style())
        btn_browse.clicked.connect(self.pick_folder)
        
        layout.addWidget(fw_label)
        layout.addWidget(self.fw_combo)
        layout.addWidget(btn_browse)
        
        # Spacer
        layout.addStretch()
        
        # Action buttons on the right
        self.btn_reboot_all_edl = QPushButton("Reboot All to EDL")
        self.btn_reboot_all_edl.setFixedSize(130, 30)
        self.btn_reboot_all_edl.setStyleSheet(Styles.get_action_button_style(Colors.EDL_MODE))
        self.btn_reboot_all_edl.clicked.connect(self.reboot_all_to_edl)
        
        self.btn_start_all = QPushButton("Flash All Ready")
        self.btn_start_all.setFixedSize(120, 30)
        self.btn_start_all.setStyleSheet(Styles.get_action_button_style(Colors.SUCCESS))
        self.btn_start_all.clicked.connect(self.flash_all_ready)
        
        layout.addWidget(self.btn_reboot_all_edl)
        layout.addWidget(self.btn_start_all)
        
        self.main_layout.addWidget(header)
    
    def setup_device_table(self):
        """Set up the device table."""
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(["Serial", "Status", "ADB", "Build ID", "Progress", "Logs", "Actions", "Remove"])

        # Set table to stretch and fill available space
        self.table.horizontalHeader().setStretchLastSection(False)

        header = self.table.horizontalHeader()
        resize = header.ResizeMode
        # Fixed-width columns
        for col, width in [(0, 120), (1, 70), (2, 40), (3, 120), (4, 100), (6, 110), (7, 50)]:
            header.setSectionResizeMode(col, resize.Fixed)
            self.table.setColumnWidth(col, width)
        # Logs column stretches to fill remaining space
        header.setSectionResizeMode(5, resize.Stretch)
        
        self.table.verticalHeader().setDefaultSectionSize(50)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(Styles.get_table_style())
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(self.table.SelectionMode.NoSelection)
        
        self.main_layout.addWidget(self.table)
    
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
            device_info = self.devices[serial]
            
            mode = info["mode"].lower()
            has_adb = info.get("has_adb", False)
            build_id = info.get("build_id", "")
            
            # Map mode to status (user, debug, edl)
            if "edl" in mode:
                status = "edl"
            elif "debug" in mode:
                status = "debug"
            elif "user" in mode:
                status = "user"
            else:
                status = "ready"
            
            self.update_device_status(device_info, status, has_adb, build_id)
            
            if "adb_tid" in info:
                self.adb_transports[serial] = info["adb_tid"]
        
        # Remove disconnected devices
        for serial in list(self.devices.keys()):
            if serial not in currently_connected:
                process_info = self.device_processes.get(serial, {})
                is_flashing = process_info.get("is_flashing", False)
                if not is_flashing:
                    self.remove_device(serial)
    
    def add_device_row(self, serial):
        """Add a new device row to the table.
        
        Args:
            serial: Device serial number
        """
        row = self.table.rowCount()
        self.table.insertRow(row)
        
        # Serial column
        serial_item = QTableWidgetItem(serial)
        serial_item.setFlags(serial_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 0, serial_item)
        
        # Status column
        status_item = QTableWidgetItem("ready")
        status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 1, status_item)
        
        # ADB column
        adb_item = QTableWidgetItem("off")
        adb_item.setFlags(adb_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 2, adb_item)
        
        # Build ID column
        build_id_item = QTableWidgetItem("")
        build_id_item.setFlags(build_id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 3, build_id_item)
        
        # Progress column
        progress = QProgressBar()
        progress.setValue(0)
        progress.setStyleSheet(Styles.get_progress_bar_style())
        self.table.setCellWidget(row, 4, progress)

        # Logs column
        log_box = QPlainTextEdit()
        log_box.setReadOnly(True)
        log_box.setMaximumBlockCount(500)
        log_box.setStyleSheet(
            f"background: {Colors.WHITE}; color: {Colors.LIGHT_TEXT};"
            "font-family: monospace; font-size: 10px; border: none; padding: 2px;"
        )
        self.table.setCellWidget(row, 5, log_box)

        # Action buttons column (Flash + EDL)
        action_widget = QWidget()
        action_layout = QHBoxLayout(action_widget)
        action_layout.setContentsMargins(2, 2, 2, 2)
        action_layout.setSpacing(4)

        btn_flash = QPushButton("Flash")
        btn_flash.setMaximumWidth(60)
        btn_flash.setStyleSheet(Styles.get_action_button_style(Colors.PRIMARY))
        btn_flash.clicked.connect(lambda: self.handle_manual_flash(serial))

        btn_edl = QPushButton("EDL")
        btn_edl.setMaximumWidth(50)
        btn_edl.setStyleSheet(Styles.get_action_button_style(Colors.EDL_MODE))
        btn_edl.clicked.connect(lambda: self.handle_edl_reboot(serial))
        btn_edl.hide()

        action_layout.addWidget(btn_flash)
        action_layout.addWidget(btn_edl)
        self.table.setCellWidget(row, 6, action_widget)

        # Remove button column
        btn_remove = QPushButton("X")
        btn_remove.setMaximumWidth(50)
        btn_remove.setStyleSheet(Styles.get_remove_button_style())
        btn_remove.clicked.connect(lambda: self.remove_device(serial))
        self.table.setCellWidget(row, 7, btn_remove)
        
        # Store device info in a dict
        self.devices[serial] = {
            "row": row,
            "status_item": status_item,
            "adb_item": adb_item,
            "build_id_item": build_id_item,
            "progress": progress,
            "log_box": log_box,
            "btn_flash": btn_flash,
            "btn_edl": btn_edl,
            "is_flashing": False,
        }
        
        # Initialize process tracking
        self.device_processes[serial] = {
            "process": None,
            "is_flashing": False,
        }
    
    def update_device_status(self, device_info, status, has_adb, build_id):
        """Update device status in table.
        
        Args:
            device_info: Device info dict from self.devices
            status: Status string (user, debug, edl, ready)
            has_adb: Whether ADB is available
            build_id: Build ID string or empty
        """
        device_info["status_item"].setText(status)
        device_info["adb_item"].setText("on" if has_adb else "off")
        
        # Show build ID only if ADB is on
        if has_adb and build_id:
            device_info["build_id_item"].setText(build_id)
        else:
            device_info["build_id_item"].setText("")
        
        # Show EDL button when ADB is available (for user, debug, or edl status)
        device_info["btn_edl"].setVisible(has_adb)
        device_info["btn_flash"].setEnabled(status == "edl")
    
    def remove_device(self, serial):
        """Remove a device from the table.
        
        Args:
            serial: Device serial number
        """
        if serial in self.devices:
            device_info = self.devices.pop(serial)
            row = device_info["row"]
            self.table.removeRow(row)
            
            # Update row numbers for remaining devices
            for i in range(row, self.table.rowCount()):
                current_serial = self.table.item(i, 0).text()
                if current_serial in self.devices:
                    self.devices[current_serial]["row"] = i
            
            self.adb_transports.pop(serial, None)
            self.device_processes.pop(serial, None)
    
    def handle_edl_reboot(self, serial):
        """Handle EDL reboot button click.
        
        Args:
            serial: Device serial number
        """
        if serial in self.adb_transports:
            tid = self.adb_transports[serial]
            RebootManager.reboot_to_edl(tid)
            
            device_info = self.devices[serial]
            device_info["btn_edl"].setText("...")
            device_info["btn_edl"].setEnabled(False)
            QTimer.singleShot(2000, lambda: self.restore_edl_button(serial))
    
    def restore_edl_button(self, serial):
        """Restore EDL button after timeout."""
        if serial in self.devices:
            device_info = self.devices[serial]
            device_info["btn_edl"].setText("EDL")
            device_info["btn_edl"].setEnabled(True)
    
    def reboot_all_to_edl(self):
        """Reboot all connected devices to EDL mode."""
        for serial in list(self.devices.keys()):
            if serial in self.adb_transports:
                device_info = self.devices[serial]
                if device_info["btn_edl"].isVisible():
                    self.handle_edl_reboot(serial)
    
    def handle_manual_flash(self, serial):
        """Handle flash button click.
        
        Args:
            serial: Device serial number
        """
        fw_path = self.fw_combo.currentText()
        if not os.path.isdir(fw_path):
            QMessageBox.warning(self, "Invalid Path", "Please select a valid firmware folder.")
            return
        
        prog, raw, patch = FlashManager.find_firmware_files(fw_path)
        if prog and raw and patch:
            self.start_flash(serial, prog, raw, patch)
        else:
            QMessageBox.warning(
                self,
                "Incomplete Firmware",
                "Could not find required firmware files (.elf, rawprogram.xml, patch.xml)"
            )
    
    def start_flash(self, serial, prog, raw, patch):
        """Start flashing a device.
        
        Args:
            serial: Device serial number
            prog: Path to prog file
            raw: Path to raw file
            patch: Path to patch file
        """
        if serial not in self.devices or serial not in self.device_processes:
            return
        
        device_info = self.devices[serial]
        process_info = self.device_processes[serial]
        
        if process_info["is_flashing"]:
            return
        
        # Update UI state
        process_info["is_flashing"] = True
        device_info["is_flashing"] = True
        device_info["btn_flash"].setEnabled(False)
        device_info["btn_edl"].setEnabled(False)
        device_info["status_item"].setText("flashing")
        device_info["progress"].setValue(0)
        device_info["log_box"].clear()
        
        # Build and start flash process
        process = QProcess()
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        
        # Store references
        process_info["process"] = process
        process_info["serial"] = serial
        process_info["progress_bar"] = device_info["progress"]
        process_info["status_item"] = device_info["status_item"]
        
        def handle_output():
            data = process.readAllStandardOutput().data().decode()
            for line in data.splitlines():
                stripped = line.strip()
                if stripped:
                    device_info["log_box"].appendPlainText(stripped)
                    match = re.search(r"(\d+\.\d+)%", line)
                    if match:
                        progress_val = int(float(match.group(1)))
                        device_info["progress"].setValue(min(progress_val, 100))
        
        def handle_finished(exit_code):
            process_info["is_flashing"] = False
            device_info["is_flashing"] = False
            device_info["btn_flash"].setEnabled(True)
            
            if exit_code == 0:
                device_info["status_item"].setText("success")
                device_info["progress"].setValue(100)
            else:
                device_info["status_item"].setText("failed")
                device_info["progress"].setValue(0)
        
        process.readyReadStandardOutput.connect(handle_output)
        process.finished.connect(lambda code: handle_finished(code))
        
        firmware_dir = FlashManager.get_working_directory(raw)
        args = FlashManager.build_flash_command(serial, prog, raw, patch)
        
        process.setWorkingDirectory(firmware_dir)
        process.start(args[0], args[1:])
    
    def flash_all_ready(self):
        """Flash all devices that are ready."""
        for serial in list(self.devices.keys()):
            device_info = self.devices[serial]
            if not device_info["is_flashing"] and device_info["status_item"].text() == "edl":
                self.handle_manual_flash(serial)


if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    import sys
    
    app = QApplication(sys.argv)
    window = FlashStation()
    window.show()
    sys.exit(app.exec())
