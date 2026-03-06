"""Main application window for the flash station."""
import os
import re
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox,
    QLabel, QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem, QProgressBar,
    QPlainTextEdit, QCheckBox
)
from PyQt6.QtCore import QTimer, Qt, QProcess

from config import SCAN_INTERVAL_MS, FW_PATH_ENV
from styles import Styles, Colors
from utils_device_manager import DeviceScanner
from utils_flash_manager import FlashManager, RebootManager

# Column indices
COL_CHECK   = 0
COL_SERIAL  = 1
COL_STATUS  = 2
COL_ADB     = 3
COL_BUILD   = 4
COL_PROGRESS = 5
COL_LOGS    = 6
COL_ACTIONS = 7
COL_REMOVE  = 8
COL_COUNT   = 9


class FlashStation(QMainWindow):
    """Main application window for managing device flashing."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Qualcomm Flash Station")
        self.setMinimumSize(1100, 600)
        self.setGeometry(100, 100, 1100, 600)

        self.devices = {}
        self.adb_transports = {}
        self.device_processes = {}

        self.setup_ui()
        self.setup_scanning()

    def setup_ui(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.central_widget.setStyleSheet(Styles.get_main_window_style())

        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.setup_header()
        self.setup_device_table()

    def setup_header(self):
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

        btn_browse = QPushButton("Browse")
        btn_browse.setFixedSize(70, 30)
        btn_browse.setStyleSheet(Styles.get_action_button_style())
        btn_browse.clicked.connect(self.pick_folder)

        layout.addWidget(fw_label)
        layout.addWidget(self.fw_combo)
        layout.addWidget(btn_browse)

        layout.addStretch()

        # Selection count label
        self.lbl_selected = QLabel("0 / 0 selected")
        self.lbl_selected.setStyleSheet(f"color: {Colors.LIGHT_TEXT}; font-size: 11px;")
        layout.addWidget(self.lbl_selected)

        # Selection buttons
        btn_select_all = QPushButton("Select All")
        btn_select_all.setFixedSize(90, 30)
        btn_select_all.setStyleSheet(Styles.get_action_button_style())
        btn_select_all.clicked.connect(self.select_all)

        btn_deselect_all = QPushButton("Deselect All")
        btn_deselect_all.setFixedSize(95, 30)
        btn_deselect_all.setStyleSheet(Styles.get_action_button_style())
        btn_deselect_all.clicked.connect(self.deselect_all)

        btn_select_edl = QPushButton("Select EDL")
        btn_select_edl.setFixedSize(90, 30)
        btn_select_edl.setStyleSheet(Styles.get_action_button_style(Colors.EDL_MODE))
        btn_select_edl.clicked.connect(self.select_edl_only)

        layout.addWidget(btn_select_all)
        layout.addWidget(btn_deselect_all)
        layout.addWidget(btn_select_edl)

        # Divider spacing
        layout.addSpacing(10)

        # Flash / reboot buttons
        self.btn_reboot_all_edl = QPushButton("Reboot All to EDL")
        self.btn_reboot_all_edl.setFixedSize(130, 30)
        self.btn_reboot_all_edl.setStyleSheet(Styles.get_action_button_style(Colors.EDL_MODE))
        self.btn_reboot_all_edl.clicked.connect(self.reboot_all_to_edl)

        self.btn_start_all = QPushButton("Flash Selected")
        self.btn_start_all.setFixedSize(110, 30)
        self.btn_start_all.setStyleSheet(Styles.get_action_button_style(Colors.SUCCESS))
        self.btn_start_all.clicked.connect(self.flash_all_ready)

        layout.addWidget(self.btn_reboot_all_edl)
        layout.addWidget(self.btn_start_all)

        self.main_layout.addWidget(header)

    def setup_device_table(self):
        self.table = QTableWidget()
        self.table.setColumnCount(COL_COUNT)
        self.table.setHorizontalHeaderLabels([
            "☑", "Serial", "Status", "ADB", "Build ID",
            "Progress", "Logs", "Actions", "Remove"
        ])

        self.table.horizontalHeader().setStretchLastSection(False)

        hdr = self.table.horizontalHeader()
        resize = hdr.ResizeMode
        fixed_cols = {
            COL_CHECK: 35, COL_SERIAL: 120, COL_STATUS: 70, COL_ADB: 40,
            COL_BUILD: 120, COL_PROGRESS: 100, COL_ACTIONS: 110, COL_REMOVE: 50
        }
        for col, width in fixed_cols.items():
            hdr.setSectionResizeMode(col, resize.Fixed)
            self.table.setColumnWidth(col, width)
        hdr.setSectionResizeMode(COL_LOGS, resize.Stretch)

        self.table.verticalHeader().setDefaultSectionSize(50)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(Styles.get_table_style())
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(self.table.SelectionMode.NoSelection)

        self.main_layout.addWidget(self.table)

    def setup_scanning(self):
        self.timer = QTimer()
        self.timer.timeout.connect(self.scan)
        self.timer.start(SCAN_INTERVAL_MS)

    # ------------------------------------------------------------------
    # Firmware helpers
    # ------------------------------------------------------------------

    def load_env_firmwares(self):
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
        path = QFileDialog.getExistingDirectory(self, "Select Firmware Folder")
        if path and FlashManager.validate_firmware_folder(path):
            if self.fw_combo.findText(path) == -1:
                self.fw_combo.insertItem(0, path)
            self.fw_combo.setCurrentText(path)

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def scan(self):
        currently_connected, devices_info = DeviceScanner.scan_all()

        for serial in currently_connected:
            if serial not in self.devices:
                self.add_device_row(serial)

            info = devices_info[serial]
            device_info = self.devices[serial]

            mode = info["mode"].lower()
            has_adb = info.get("has_adb", False)
            build_id = info.get("build_id", "")

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

        for serial in list(self.devices.keys()):
            if serial not in currently_connected:
                if not self.device_processes.get(serial, {}).get("is_flashing", False):
                    self.remove_device(serial)

        self._update_selection_label()

    # ------------------------------------------------------------------
    # Row management
    # ------------------------------------------------------------------

    def add_device_row(self, serial):
        row = self.table.rowCount()
        self.table.insertRow(row)

        # Checkbox column
        chk = QCheckBox()
        chk.setChecked(False)
        chk_widget = QWidget()
        chk_layout = QHBoxLayout(chk_widget)
        chk_layout.addWidget(chk)
        chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chk_layout.setContentsMargins(0, 0, 0, 0)
        chk.stateChanged.connect(self._update_selection_label)
        self.table.setCellWidget(row, COL_CHECK, chk_widget)

        # Serial
        serial_item = QTableWidgetItem(serial)
        serial_item.setFlags(serial_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, COL_SERIAL, serial_item)

        # Status
        status_item = QTableWidgetItem("ready")
        status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, COL_STATUS, status_item)

        # ADB
        adb_item = QTableWidgetItem("off")
        adb_item.setFlags(adb_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, COL_ADB, adb_item)

        # Build ID
        build_id_item = QTableWidgetItem("")
        build_id_item.setFlags(build_id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, COL_BUILD, build_id_item)

        # Progress
        progress = QProgressBar()
        progress.setValue(0)
        progress.setStyleSheet(Styles.get_progress_bar_style())
        self.table.setCellWidget(row, COL_PROGRESS, progress)

        # Logs
        log_box = QPlainTextEdit()
        log_box.setReadOnly(True)
        log_box.setMaximumBlockCount(500)
        log_box.setStyleSheet(
            f"background: {Colors.WHITE}; color: {Colors.LIGHT_TEXT};"
            "font-family: monospace; font-size: 10px; border: none; padding: 2px;"
        )
        self.table.setCellWidget(row, COL_LOGS, log_box)

        # Actions (Flash + EDL)
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
        self.table.setCellWidget(row, COL_ACTIONS, action_widget)

        # Remove
        btn_remove = QPushButton("X")
        btn_remove.setMaximumWidth(50)
        btn_remove.setStyleSheet(Styles.get_remove_button_style())
        btn_remove.clicked.connect(lambda: self.remove_device(serial))
        self.table.setCellWidget(row, COL_REMOVE, btn_remove)

        self.devices[serial] = {
            "row": row,
            "chk": chk,
            "status_item": status_item,
            "adb_item": adb_item,
            "build_id_item": build_id_item,
            "progress": progress,
            "log_box": log_box,
            "btn_flash": btn_flash,
            "btn_edl": btn_edl,
            "is_flashing": False,
        }

        self.device_processes[serial] = {
            "process": None,
            "is_flashing": False,
        }

        self._update_selection_label()

    def update_device_status(self, device_info, status, has_adb, build_id):
        device_info["status_item"].setText(status)
        device_info["adb_item"].setText("on" if has_adb else "off")

        if has_adb and build_id:
            device_info["build_id_item"].setText(build_id)
        else:
            device_info["build_id_item"].setText("")

        device_info["btn_edl"].setVisible(has_adb)
        device_info["btn_flash"].setEnabled(status == "edl")

    def remove_device(self, serial):
        if serial in self.devices:
            device_info = self.devices.pop(serial)
            row = device_info["row"]
            self.table.removeRow(row)

            for i in range(row, self.table.rowCount()):
                item = self.table.item(i, COL_SERIAL)
                if item and item.text() in self.devices:
                    self.devices[item.text()]["row"] = i

            self.adb_transports.pop(serial, None)
            self.device_processes.pop(serial, None)
            self._update_selection_label()

    # ------------------------------------------------------------------
    # Selection helpers
    # ------------------------------------------------------------------

    def _checked_serials(self):
        return [s for s, d in self.devices.items() if d["chk"].isChecked()]

    def _update_selection_label(self):
        total = len(self.devices)
        checked = len(self._checked_serials())
        self.lbl_selected.setText(f"{checked} / {total} selected")

    def select_all(self):
        for d in self.devices.values():
            d["chk"].setChecked(True)

    def deselect_all(self):
        for d in self.devices.values():
            d["chk"].setChecked(False)

    def select_edl_only(self):
        for d in self.devices.values():
            d["chk"].setChecked(d["status_item"].text() == "edl")

    # ------------------------------------------------------------------
    # EDL reboot
    # ------------------------------------------------------------------

    def handle_edl_reboot(self, serial):
        if serial in self.adb_transports:
            RebootManager.reboot_to_edl(self.adb_transports[serial])
            device_info = self.devices[serial]
            device_info["btn_edl"].setText("...")
            device_info["btn_edl"].setEnabled(False)
            QTimer.singleShot(2000, lambda: self.restore_edl_button(serial))

    def restore_edl_button(self, serial):
        if serial in self.devices:
            device_info = self.devices[serial]
            device_info["btn_edl"].setText("EDL")
            device_info["btn_edl"].setEnabled(True)

    def reboot_all_to_edl(self):
        for serial in list(self.devices.keys()):
            if serial in self.adb_transports:
                if self.devices[serial]["btn_edl"].isVisible():
                    self.handle_edl_reboot(serial)

    # ------------------------------------------------------------------
    # Flashing
    # ------------------------------------------------------------------

    def handle_manual_flash(self, serial):
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

    def flash_all_ready(self):
        selected = self._checked_serials()

        if not selected:
            QMessageBox.warning(
                self, "No Devices Selected",
                "No devices are selected. Please check the devices you want to flash."
            )
            return

        # Only flash selected devices that are in EDL mode and not already flashing
        targets = [
            s for s in selected
            if self.devices[s]["status_item"].text() == "edl"
            and not self.devices[s]["is_flashing"]
        ]

        if not targets:
            QMessageBox.warning(
                self, "No EDL Devices",
                "None of the selected devices are in EDL mode."
            )
            return

        serial_list = "\n".join(f"  • {s}" for s in targets)
        reply = QMessageBox.question(
            self, "Confirm Flash",
            f"Flash {len(targets)} device(s)?\n\n{serial_list}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            for serial in targets:
                self.handle_manual_flash(serial)

    def start_flash(self, serial, prog, raw, patch):
        if serial not in self.devices or serial not in self.device_processes:
            return

        device_info = self.devices[serial]
        process_info = self.device_processes[serial]

        if process_info["is_flashing"]:
            return

        process_info["is_flashing"] = True
        device_info["is_flashing"] = True
        device_info["btn_flash"].setEnabled(False)
        device_info["btn_edl"].setEnabled(False)
        device_info["status_item"].setText("flashing")
        device_info["progress"].setValue(0)
        device_info["log_box"].clear()

        process = QProcess()
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)

        process_info["process"] = process

        def handle_output():
            data = process.readAllStandardOutput().data().decode()
            for line in data.splitlines():
                stripped = line.strip()
                if stripped:
                    device_info["log_box"].appendPlainText(stripped)
                    match = re.search(r"(\d+\.\d+)%", line)
                    if match:
                        device_info["progress"].setValue(min(int(float(match.group(1))), 100))

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


if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    import sys

    app = QApplication(sys.argv)
    window = FlashStation()
    window.show()
    sys.exit(app.exec())
