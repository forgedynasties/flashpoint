"""Main application window for the flash station."""
import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox,
    QLabel, QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem,
    QCheckBox, QHeaderView, QSizePolicy,
)
from PyQt6.QtCore import QTimer, Qt, QRect
from PyQt6.QtGui import QColor, QPen, QBrush

from config import FW_PATH_ENV
from gui.styles import Styles, Colors, STATUS_COLORS
from core.device import Device
from core.scanner import scan_all
from core.qdl_wrapper import FlashManager
from gui.base_station import BaseFlashStation

# Column indices
COL_CHECK    = 0
COL_SERIAL   = 1
COL_STATUS   = 2
COL_ADB      = 3
COL_USB      = 4
COL_BUILD    = 5
COL_PROGRESS = 6
COL_LOGS     = 7
COL_ACTIONS  = 8
COL_COUNT    = 9


class CheckboxHeader(QHeaderView):
    """Header view that draws a real checkbox indicator in column 0."""

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._checked = False
        self.setSectionsClickable(True)

    def set_check_state(self, checked: bool):
        if self._checked != checked:
            self._checked = checked
            self.viewport().update()

    def paintSection(self, painter, rect, logicalIndex):
        painter.save()
        super().paintSection(painter, rect, logicalIndex)
        painter.restore()
        if logicalIndex == 0:
            size = 12
            x = rect.x() + (rect.width() - size) // 2
            y = rect.y() + (rect.height() - size) // 2
            box = QRect(x, y, size, size)
            painter.setRenderHint(painter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor(Colors.BORDER_LIGHT), 1.5))
            painter.setBrush(
                QBrush(QColor(Colors.PRIMARY)) if self._checked
                else QBrush(QColor(Colors.BG_ELEVATED))
            )
            painter.drawRoundedRect(box, 2, 2)
            if self._checked:
                painter.setPen(QPen(QColor(Colors.WHITE), 1.8))
                painter.drawLine(x + 2, y + 6, x + 5, y + 9)
                painter.drawLine(x + 5, y + 9, x + 10, y + 3)


class FlashStation(BaseFlashStation):
    """Main application window for managing device flashing."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Qualcomm Flash Station")
        self.setMinimumSize(1000, 600)
        self.setGeometry(100, 100, 1200, 700)

        # {serial: Device}  — pure device state
        self.devices: dict[str, Device] = {}
        # {serial: dict}    — widget refs + is_flashing flag
        self._rows: dict[str, dict] = {}
        self.edl_pending: set[str] = set()

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

        fw_label = QLabel("FIRMWARE")
        fw_label.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; font-weight: 700; font-size: 10px; letter-spacing: 0.8px;"
        )

        self.fw_combo = QComboBox()
        self.fw_combo.setMinimumWidth(300)
        self.fw_combo.setMaximumWidth(450)
        self.fw_combo.setStyleSheet(Styles.get_combobox_style())
        self.load_env_firmwares()

        btn_browse = QPushButton("Browse")
        btn_browse.setStyleSheet(Styles.get_outlined_button_style(Colors.PRIMARY))
        btn_browse.clicked.connect(self.pick_folder)

        layout.addWidget(fw_label)
        layout.addWidget(self.fw_combo)
        layout.addWidget(btn_browse)
        layout.addStretch()

        self.lbl_selected = QLabel("0 / 0 selected")
        self.lbl_selected.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; font-size: 11px; letter-spacing: 0.3px;"
        )
        layout.addWidget(self.lbl_selected)
        layout.addSpacing(10)

        self.btn_reboot_all_edl = QPushButton("Reboot All to EDL")
        self.btn_reboot_all_edl.setStyleSheet(Styles.get_outlined_button_style(Colors.EDL_MODE))
        self.btn_reboot_all_edl.clicked.connect(self.reboot_all_to_edl)

        self.btn_start_all = QPushButton("Flash Selected")
        self.btn_start_all.setStyleSheet(Styles.get_action_button_style(Colors.SUCCESS))
        self.btn_start_all.clicked.connect(self.flash_all_ready)

        layout.addWidget(self.btn_reboot_all_edl)
        layout.addWidget(self.btn_start_all)

        self.main_layout.addWidget(header)

    def setup_device_table(self):
        self.table = QTableWidget()
        self.table.setColumnCount(COL_COUNT)
        self.table.setHorizontalHeaderLabels([
            "", "Serial", "Status", "ADB", "USB Port", "Build ID",
            "Progress", "Logs", "Actions",
        ])

        self.check_header = CheckboxHeader(self.table)
        self.table.setHorizontalHeader(self.check_header)
        self.check_header.setStretchLastSection(False)

        hdr = self.check_header
        resize = hdr.ResizeMode
        fixed_cols = {
            COL_CHECK: 42, COL_SERIAL: 130, COL_STATUS: 90, COL_ADB: 55,
            COL_USB: 75, COL_BUILD: 160, COL_LOGS: 220, COL_ACTIONS: 140,
        }
        for col, width in fixed_cols.items():
            hdr.setSectionResizeMode(col, resize.Fixed)
            self.table.setColumnWidth(col, width)
        hdr.setSectionResizeMode(COL_PROGRESS, resize.Stretch)

        vh = self.table.verticalHeader()
        vh.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vh.setDefaultSectionSize(36)
        vh.setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(Styles.get_table_style())
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(self.table.SelectionMode.NoSelection)

        self.check_header.sectionClicked.connect(self._toggle_select_all)

        self.main_layout.addWidget(self.table)

    def setup_scanning(self):
        self._setup_scanning()

    def _scan(self):
        self.scan()

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
        found = scan_all()

        for serial, device in found.items():
            if serial not in self.devices:
                self._add_row(serial)
            self.devices[serial] = device
            self._update_row(serial, device)
            if serial in self.edl_pending and not device.is_edl:
                self.edl_pending.discard(serial)
                self._update_ui_lock()

        for serial in list(self.devices.keys()):
            if serial not in found:
                if not self._rows.get(serial, {}).get("is_flashing", False):
                    self._remove_device(serial)

        self._update_selection_label()

    # ------------------------------------------------------------------
    # Row management
    # ------------------------------------------------------------------

    def _add_row(self, serial: str):
        row = self.table.rowCount()
        self.table.insertRow(row)

        chk = QCheckBox()
        chk.setChecked(False)
        chk.setStyleSheet(Styles.get_checkbox_style())
        chk_widget = QWidget()
        chk_widget.setStyleSheet("background: transparent;")
        chk_layout = QHBoxLayout(chk_widget)
        chk_layout.addWidget(chk)
        chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chk_layout.setContentsMargins(0, 0, 0, 0)
        chk.clicked.connect(lambda checked, s=serial: self._on_checkbox_clicked(s, checked))
        self.table.setCellWidget(row, COL_CHECK, chk_widget)

        def _item(text=""):
            it = QTableWidgetItem(text)
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            return it

        status_item   = _item("ready")
        adb_item      = _item("off")
        usb_item      = _item("")
        build_id_item = _item("")

        self.table.setItem(row, COL_SERIAL, _item(serial))
        self.table.setItem(row, COL_STATUS, status_item)
        self.table.setItem(row, COL_ADB,    adb_item)
        self.table.setItem(row, COL_USB,    usb_item)
        self.table.setItem(row, COL_BUILD,  build_id_item)

        pw, progress = self._make_progress_widget()
        self.table.setCellWidget(row, COL_PROGRESS, pw)

        log_box = self._make_log_label()
        self.table.setCellWidget(row, COL_LOGS, log_box)

        action_widget = QWidget()
        action_widget.setStyleSheet("background: transparent;")
        action_layout = QHBoxLayout(action_widget)
        action_layout.setContentsMargins(4, 4, 4, 4)
        action_layout.setSpacing(4)

        _exp = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        btn_flash = QPushButton("Flash")
        btn_flash.setMinimumWidth(52)
        btn_flash.setSizePolicy(_exp)
        btn_flash.setStyleSheet(Styles.get_action_button_style(Colors.PRIMARY))
        btn_flash.clicked.connect(lambda: self._handle_manual_flash(serial))

        btn_edl = QPushButton("EDL")
        btn_edl.setMinimumWidth(46)
        btn_edl.setSizePolicy(_exp)
        btn_edl.setStyleSheet(Styles.get_outlined_button_style(Colors.EDL_MODE))
        btn_edl.clicked.connect(lambda: self._handle_edl_reboot(serial))
        btn_edl.hide()

        action_layout.addWidget(btn_flash)
        action_layout.addWidget(btn_edl)
        self.table.setCellWidget(row, COL_ACTIONS, action_widget)

        self._rows[serial] = {
            "row":           row,
            "chk":           chk,
            "status_item":   status_item,
            "adb_item":      adb_item,
            "usb_item":      usb_item,
            "build_id_item": build_id_item,
            "progress":      progress,
            "log_box":       log_box,
            "btn_flash":     btn_flash,
            "btn_edl":       btn_edl,
            "is_flashing":   False,
            "process":       None,
        }
        self._update_selection_label()

    def _update_row(self, serial: str, device: Device):
        row = self._rows.get(serial)
        if not row:
            return

        old_status = row["status_item"].text()
        status = device.mode  # "edl" | "debug" | "user"

        row["status_item"].setText(status)
        row["status_item"].setForeground(
            QColor(STATUS_COLORS.get(status, Colors.TEXT_SECONDARY))
        )

        adb_on = device.has_adb
        row["adb_item"].setText("on" if adb_on else "off")
        row["adb_item"].setForeground(
            QColor(Colors.SUCCESS if adb_on else Colors.TEXT_DIM)
        )
        row["usb_item"].setText(device.usb_path or "")
        row["usb_item"].setForeground(QColor(Colors.TEXT_SECONDARY))

        # Silently uncheck devices leaving EDL
        if old_status == "edl" and status != "edl" and row["chk"].isChecked():
            row["chk"].blockSignals(True)
            row["chk"].setChecked(False)
            row["chk"].blockSignals(False)
            self._update_selection_label()

        row["build_id_item"].setText(device.build_id or "")
        row["btn_edl"].setVisible(adb_on)
        row["btn_flash"].setEnabled(device.is_edl and not row["is_flashing"])

    def _remove_device(self, serial: str):
        if serial not in self._rows:
            return
        row_info = self._rows.pop(serial)
        self.devices.pop(serial, None)
        row = row_info["row"]
        self.table.removeRow(row)
        for i in range(row, self.table.rowCount()):
            item = self.table.item(i, COL_SERIAL)
            if item and item.text() in self._rows:
                self._rows[item.text()]["row"] = i
        self.edl_pending.discard(serial)
        self._update_ui_lock()
        self._update_selection_label()

    # ------------------------------------------------------------------
    # Selection helpers
    # ------------------------------------------------------------------

    def _checked_serials(self) -> list[str]:
        return [s for s, r in self._rows.items() if r["chk"].isChecked()]

    def _update_selection_label(self):
        total   = len(self._rows)
        checked = len(self._checked_serials())
        self.lbl_selected.setText(f"{checked} / {total} selected")
        edl = [s for s, d in self.devices.items() if d.is_edl]
        all_edl_checked = bool(edl) and all(self._rows[s]["chk"].isChecked() for s in edl)
        self.check_header.set_check_state(all_edl_checked)

    def _toggle_select_all(self, section):
        if section != COL_CHECK:
            return
        edl = [s for s, d in self.devices.items() if d.is_edl]
        all_checked = bool(edl) and all(self._rows[s]["chk"].isChecked() for s in edl)
        selecting = not all_checked
        for s, r in self._rows.items():
            dev = self.devices.get(s)
            r["chk"].setChecked(selecting and dev is not None and dev.is_edl)
        self._update_selection_label()
        if selecting:
            non_edl_adb = [
                s for s, d in self.devices.items()
                if not d.is_edl and d.has_adb
            ]
            if non_edl_adb:
                self._show_edl_warning_multi(non_edl_adb)

    def _on_checkbox_clicked(self, serial: str, checked: bool):
        if serial not in self._rows:
            return
        dev = self.devices.get(serial)
        if checked and (dev is None or not dev.is_edl):
            self._rows[serial]["chk"].setChecked(False)
            self._show_edl_warning(serial)
            return
        self._update_selection_label()

    def _make_dialog(self):
        msg = QMessageBox(self)
        msg.setStyleSheet(f"""
            QMessageBox {{
                background-color: {Colors.BG_ELEVATED};
                color: {Colors.TEXT_PRIMARY};
            }}
            QMessageBox QLabel {{
                color: {Colors.TEXT_PRIMARY};
                font-size: 12px;
                min-width: 280px;
            }}
            QPushButton {{
                background-color: {Colors.BG_SURFACE};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER_LIGHT};
                padding: 5px 16px;
                min-width: 80px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {Colors.PRIMARY};
                color: {Colors.WHITE};
                border-color: {Colors.PRIMARY};
            }}
            QPushButton:pressed {{
                background-color: {Colors.PRIMARY}AA;
            }}
        """)
        return msg

    def _show_edl_warning(self, serial: str):
        if serial not in self.devices:
            return
        device = self.devices[serial]
        msg = self._make_dialog()
        msg.setWindowTitle("Device Not in EDL")
        msg.setText(
            f"Device <b>{serial}</b> is not in EDL mode.<br><br>"
            "Only devices in EDL mode can be selected for flashing."
        )
        if device.has_adb:
            msg.setInformativeText("Would you like to reboot this device to EDL mode now?")
            btn_reboot = msg.addButton("Reboot to EDL", QMessageBox.ButtonRole.AcceptRole)
            msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            msg.exec()
            if msg.clickedButton() == btn_reboot:
                self._handle_edl_reboot(serial)
        else:
            msg.setInformativeText("Connect the device via ADB first to reboot it to EDL mode.")
            msg.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
            msg.exec()

    def _show_edl_warning_multi(self, serials: list[str]):
        msg = self._make_dialog()
        msg.setWindowTitle("Devices Not in EDL")
        msg.setText(f"{len(serials)} device(s) are not in EDL mode and were not selected.")
        msg.setInformativeText("Would you like to reboot them all to EDL mode now?")
        btn_reboot = msg.addButton("Reboot All to EDL", QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() == btn_reboot:
            for serial in serials:
                self._handle_edl_reboot(serial)

    # ------------------------------------------------------------------
    # EDL reboot
    # ------------------------------------------------------------------

    def _handle_edl_reboot(self, serial: str):
        device = self.devices.get(serial)
        if device and device.has_adb:
            device.reboot_to_edl()
            self.edl_pending.add(serial)
            self._update_ui_lock()

    def reboot_all_to_edl(self):
        for serial, device in list(self.devices.items()):
            if device.has_adb and self._rows.get(serial, {}).get("btn_edl", None) and \
               self._rows[serial]["btn_edl"].isVisible():
                self._handle_edl_reboot(serial)

    # ------------------------------------------------------------------
    # UI lock
    # ------------------------------------------------------------------

    def _any_flashing(self) -> bool:
        return any(r["is_flashing"] for r in self._rows.values())

    def _update_ui_lock(self):
        self.central_widget.setEnabled(not self._any_flashing() and not self.edl_pending)

    # ------------------------------------------------------------------
    # Flashing
    # ------------------------------------------------------------------

    def _handle_manual_flash(self, serial: str):
        fw_path = self.fw_combo.currentText()
        if not os.path.isdir(fw_path):
            QMessageBox.warning(self, "Invalid Path", "Please select a valid firmware folder.")
            return
        device = self.devices.get(serial)
        if not device:
            return
        try:
            args, cwd = device.flash_command(fw_path)
        except FileNotFoundError:
            QMessageBox.warning(
                self, "Incomplete Firmware",
                "Could not find required firmware files (.elf, rawprogram.xml, patch.xml)",
            )
            return
        self._start_flash(serial, args, cwd)

    def flash_all_ready(self):
        selected = self._checked_serials()
        if not selected:
            QMessageBox.warning(self, "No Devices Selected",
                                "No devices are selected. Please check the devices you want to flash.")
            return

        targets = [
            s for s in selected
            if self.devices.get(s, Device(s, "")).is_edl and not self._rows[s]["is_flashing"]
        ]
        if not targets:
            QMessageBox.warning(self, "No EDL Devices",
                                "None of the selected devices are in EDL mode.")
            return

        serial_list = "\n".join(f"  • {s}" for s in targets)
        reply = QMessageBox.question(
            self, "Confirm Flash",
            f"Flash {len(targets)} device(s)?\n\n{serial_list}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            for serial in targets:
                self._handle_manual_flash(serial)

    def _start_flash(self, serial: str, args: list[str], cwd: str):
        row = self._rows.get(serial)
        if not row or row["is_flashing"]:
            return

        row["is_flashing"] = True
        row["btn_flash"].setEnabled(False)
        row["btn_edl"].setEnabled(False)
        row["status_item"].setText("flashing")
        row["status_item"].setForeground(QColor(Colors.WARNING))
        row["progress"].setStyleSheet(Styles.get_progress_bar_style(Colors.WARNING))
        row["progress"].setValue(0)
        row["log_box"].setText("")
        self._update_ui_lock()

        def on_done(exit_code: int) -> None:
            row["is_flashing"] = False
            row["process"] = None
            row["btn_flash"].setEnabled(True)
            if exit_code == 0:
                row["status_item"].setText("success")
                row["status_item"].setForeground(QColor(Colors.SUCCESS))
                row["progress"].setValue(100)
                row["progress"].setStyleSheet(Styles.get_progress_bar_style(Colors.SUCCESS))
            else:
                row["status_item"].setText("failed")
                row["status_item"].setForeground(QColor(Colors.ERROR))
                row["progress"].setValue(0)
                row["progress"].setStyleSheet(Styles.get_progress_bar_style(Colors.ERROR))
            self._update_ui_lock()

        row["process"] = self._launch_flash_process(
            args, cwd,
            on_log=row["log_box"].setText,
            on_progress=row["progress"].setValue,
            on_done=on_done,
        )


if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    import sys

    app = QApplication(sys.argv)
    window = FlashStation()
    window.show()
    sys.exit(app.exec())
