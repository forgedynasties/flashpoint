"""Factory Assembly Flash Station — automated 3-stage flashing pipeline."""
import json
import logging
import os
import subprocess
from datetime import datetime, timezone

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTableWidget, QTableWidgetItem, QProgressBar,
    QHeaderView, QDialog, QTextEdit, QApplication,
)
from PyQt6.QtCore import QTimer, Qt, QProcess
from PyQt6.QtGui import QColor
from PyQt6.QtNetwork import QLocalServer

from config import (
    SCAN_INTERVAL_MS,
    FACTORY_FW_PATH_ENV, PROD_DEBUG_FW_PATH_ENV,
    BOOT_TIMEOUT_SEC_ENV, DEFAULT_BOOT_TIMEOUT_SEC,
    EXPECTED_BUILD_ID,
    FACTORY_REPORTS_DIR_ENV, DEFAULT_REPORTS_DIR,
    QDL_BIN, QDL_LIST_SOCKET, QDL_PROGRESS_SOCK_PREFIX,
)
from styles import Styles, Colors
from utils_device_manager import DeviceScanner
from utils_flash_manager import FlashManager, RebootManager

log = logging.getLogger(__name__)

# ── Pipeline states ────────────────────────────────────────────────────────────
S_WAITING       = "WAITING"
S_SKIPPED       = "SKIPPED"
S_FLASH1        = "FLASH 1/3"
S_BOOTING       = "BOOTING"
S_REBOOTING_EDL = "TO EDL"
S_FLASH3        = "FLASH 3/3"
S_DONE          = "DONE"
S_FAILED        = "FAILED"
S_TIMEOUT       = "TIMEOUT"

TERMINAL = {S_DONE, S_FAILED, S_TIMEOUT, S_SKIPPED}

STATE_COLORS = {
    S_WAITING:       Colors.TEXT_SECONDARY,
    S_SKIPPED:       Colors.WARNING,
    S_FLASH1:        Colors.WARNING,
    S_BOOTING:       Colors.USER_MODE,
    S_REBOOTING_EDL: Colors.EDL_MODE,
    S_FLASH3:        Colors.WARNING,
    S_DONE:          Colors.SUCCESS,
    S_FAILED:        Colors.ERROR,
    S_TIMEOUT:       Colors.ERROR,
}

STAGE_LABEL = {
    S_WAITING:       "—",
    S_SKIPPED:       "—",
    S_FLASH1:        "1",
    S_BOOTING:       "2",
    S_REBOOTING_EDL: "2",
    S_FLASH3:        "3",
    S_DONE:          "✓",
    S_FAILED:        "✗",
    S_TIMEOUT:       "✗",
}

# ── Columns ────────────────────────────────────────────────────────────────────
COL_SERIAL   = 0
COL_STAGE    = 1
COL_STATUS   = 2
COL_PROGRESS = 3
COL_LOG      = 4
COL_COUNT    = 5


class FactoryStation(QMainWindow):
    """Factory assembly flash station — automated 3-stage pipeline."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Factory Flash Station")
        self.setMinimumSize(900, 500)
        self.setGeometry(100, 100, 1100, 650)

        # Firmware paths from env
        self.factory_fw  = os.getenv(FACTORY_FW_PATH_ENV, "")
        self.prod_fw     = os.getenv(PROD_DEBUG_FW_PATH_ENV, "")
        self.boot_timeout_ms = int(os.getenv(BOOT_TIMEOUT_SEC_ENV,
                                             DEFAULT_BOOT_TIMEOUT_SEC)) * 1000

        # Reports directory
        self.reports_dir = os.getenv(FACTORY_REPORTS_DIR_ENV, DEFAULT_REPORTS_DIR)

        # State
        self.devices     = {}   # serial → device dict
        self.adb_map     = {}   # serial → adb transport id
        self.run_active  = False
        self.run_serials = set()
        self.cycle_start: datetime | None = None
        self._flash_count = 0

        self._setup_ui()
        self._setup_scanning()
        self._start_list_server()

    # ── UI setup ───────────────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        root.setStyleSheet(Styles.get_main_window_style())
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._root = root
        self._setup_header(layout)
        self._setup_table(layout)

    def _setup_header(self, parent_layout):
        header = QWidget()
        header.setStyleSheet(Styles.get_header_group_style())
        row = QHBoxLayout(header)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(12)

        def fw_block(label_text, path):
            lbl = QLabel(label_text)
            lbl.setStyleSheet(
                f"color: {Colors.TEXT_SECONDARY}; font-size: 10px;"
                "font-weight: 700; letter-spacing: 0.8px;"
            )
            val = QLabel(path if path else "NOT SET — check env var")
            val.setStyleSheet(
                f"color: {Colors.TEXT_PRIMARY if path else Colors.ERROR};"
                "font-size: 11px;"
            )
            box = QVBoxLayout()
            box.setSpacing(2)
            box.addWidget(lbl)
            box.addWidget(val)
            return box

        row.addLayout(fw_block("FACTORY FIRMWARE", self.factory_fw))
        row.addSpacing(20)
        row.addLayout(fw_block("PROD DEBUG FIRMWARE", self.prod_fw))
        row.addStretch()

        self.lbl_summary = QLabel("")
        self.lbl_summary.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; font-size: 11px; letter-spacing: 0.3px;"
        )
        row.addWidget(self.lbl_summary)
        row.addSpacing(16)

        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setStyleSheet(Styles.get_outlined_button_style(Colors.ERROR))
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_run)
        row.addWidget(self.btn_stop)

        self.btn_start = QPushButton("Start")
        self.btn_start.setStyleSheet(Styles.get_action_button_style(Colors.SUCCESS))
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self._start_run)
        row.addWidget(self.btn_start)

        parent_layout.addWidget(header)

    def _setup_table(self, parent_layout):
        self.table = QTableWidget()
        self.table.setColumnCount(COL_COUNT)
        self.table.setHorizontalHeaderLabels(
            ["Serial", "Stage", "Status", "Progress", "Log"]
        )
        self.table.setStyleSheet(Styles.get_table_style())
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(self.table.SelectionMode.NoSelection)
        self.table.setEditTriggers(self.table.EditTrigger.NoEditTriggers)

        hdr = self.table.horizontalHeader()
        hdr.setStretchLastSection(False)
        R = hdr.ResizeMode
        fixed = {COL_SERIAL: 150, COL_STAGE: 55, COL_STATUS: 110, COL_LOG: 260}
        for col, w in fixed.items():
            hdr.setSectionResizeMode(col, R.Fixed)
            self.table.setColumnWidth(col, w)
        hdr.setSectionResizeMode(COL_PROGRESS, R.Stretch)

        vh = self.table.verticalHeader()
        vh.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vh.setDefaultSectionSize(36)
        vh.setVisible(False)

        parent_layout.addWidget(self.table)

    def _setup_scanning(self):
        self.timer = QTimer()
        self.timer.timeout.connect(self._scan)
        self.timer.start(SCAN_INTERVAL_MS)

    def _start_list_server(self):
        """Launch qdl list-server in the background so EDL device queries work."""
        try:
            self._list_server_proc = subprocess.Popen(
                ["sudo", QDL_BIN, "list-server", "--socket", QDL_LIST_SOCKET],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log.info("Started qdl list-server (pid=%d) on %s",
                     self._list_server_proc.pid, QDL_LIST_SOCKET)
        except Exception as exc:
            log.warning("Could not start qdl list-server: %s", exc)
            self._list_server_proc = None

    def closeEvent(self, event):
        if getattr(self, '_list_server_proc', None):
            log.info("Stopping qdl list-server (pid=%d)", self._list_server_proc.pid)
            self._list_server_proc.terminate()
        super().closeEvent(event)

    # ── Scanning ───────────────────────────────────────────────────────────────

    def _scan(self):
        connected, info_map = DeviceScanner.scan_all()

        # Add new devices not yet in the table — only if already in EDL
        for usb_path in connected:
            if usb_path not in self.devices:
                info = info_map.get(usb_path, {})
                if "edl" in info.get("mode", "").lower():
                    qdl_serial = info.get("qdl_serial", "") or info.get("serial", "")
                    self._add_row(usb_path, qdl_serial)

        # Update per-device state from scan results
        for usb_path, info in info_map.items():
            if usb_path not in self.devices:
                continue
            dev = self.devices[usb_path]
            mode    = info["mode"].lower()
            has_adb = info.get("has_adb", False)
            build_id = info.get("build_id", "")

            # Track ADB transport id
            if "adb_tid" in info:
                self.adb_map[usb_path] = info["adb_tid"]

            # Update qdl_serial whenever we get one (it's stable per device)
            qdl_serial = info.get("qdl_serial", "")
            if qdl_serial and not dev.get("qdl_serial"):
                dev["qdl_serial"] = qdl_serial

            # Update is_edl flag (used by Start button and pipeline)
            dev["is_edl"] = "edl" in mode

            state = dev["state"]

            if state == S_BOOTING:
                if has_adb and build_id:
                    self._cancel_boot_timer(usb_path)
                    if build_id == EXPECTED_BUILD_ID:
                        self._set_state(usb_path, S_REBOOTING_EDL)
                        if usb_path in self.adb_map:
                            RebootManager.reboot_to_edl(self.adb_map[usb_path])
                    else:
                        self._set_failed(usb_path,
                                         f"Build ID mismatch: got {build_id!r}")

            elif state == S_REBOOTING_EDL:
                if dev["is_edl"]:
                    self._start_flash(usb_path, stage=3)

        # Remove WAITING devices that have disconnected (not part of any run)
        for usb_path in list(self.devices.keys()):
            if usb_path not in connected:
                dev = self.devices[usb_path]
                if dev["state"] == S_WAITING:
                    self._remove_row(usb_path)

        self._update_start_btn()
        self._update_summary()

    # ── Row management ─────────────────────────────────────────────────────────

    def _add_row(self, usb_path, qdl_serial=""):
        row = self.table.rowCount()
        self.table.insertRow(row)

        def item(text="", align=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft):
            it = QTableWidgetItem(text)
            it.setTextAlignment(align)
            return it

        center = Qt.AlignmentFlag.AlignCenter

        serial_item = item(qdl_serial or usb_path)
        stage_item  = item("—", center)
        status_item = item(S_WAITING, center)
        status_item.setForeground(QColor(STATE_COLORS[S_WAITING]))

        self.table.setItem(row, COL_SERIAL,  serial_item)
        self.table.setItem(row, COL_STAGE,   stage_item)
        self.table.setItem(row, COL_STATUS,  status_item)

        # Progress bar
        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setValue(0)
        progress.setTextVisible(True)
        progress.setStyleSheet(Styles.get_progress_bar_style())
        pw = QWidget()
        pw.setStyleSheet("background: transparent;")
        pl = QHBoxLayout(pw)
        pl.setContentsMargins(6, 6, 6, 6)
        pl.addWidget(progress)
        self.table.setCellWidget(row, COL_PROGRESS, pw)

        # Log label
        log_lbl = QLabel()
        log_lbl.setStyleSheet(Styles.get_log_box_style())
        log_lbl.setContentsMargins(6, 0, 6, 0)
        self.table.setCellWidget(row, COL_LOG, log_lbl)

        self.devices[usb_path] = {
            "row":         row,
            "qdl_serial":  qdl_serial,
            "state":       S_WAITING,
            "fail_reason": "",
            "is_edl":      False,
            "serial_item": serial_item,
            "stage_item":  stage_item,
            "status_item": status_item,
            "progress":    progress,
            "log_lbl":     log_lbl,
            "process":     None,
            "boot_timer":  None,
        }

    def _remove_row(self, usb_path):
        dev = self.devices.pop(usb_path)
        self.table.removeRow(dev["row"])
        # Fix row indices for remaining devices
        for d in self.devices.values():
            if d["row"] > dev["row"]:
                d["row"] -= 1
        self.adb_map.pop(usb_path, None)

    # ── State machine ──────────────────────────────────────────────────────────

    def _set_state(self, usb_path, state, fail_reason=""):
        dev = self.devices[usb_path]
        dev["state"]       = state
        dev["fail_reason"] = fail_reason

        dev["status_item"].setText(state)
        dev["status_item"].setForeground(QColor(STATE_COLORS.get(state, Colors.TEXT_SECONDARY)))
        dev["stage_item"].setText(STAGE_LABEL.get(state, "—"))

        # Progress bar appearance
        if state in (S_BOOTING, S_REBOOTING_EDL):
            dev["progress"].setRange(0, 0)   # indeterminate spinner
        elif state == S_DONE:
            dev["progress"].setRange(0, 100)
            dev["progress"].setValue(100)
            dev["progress"].setStyleSheet(Styles.get_progress_bar_style(Colors.SUCCESS))
        elif state in (S_FAILED, S_TIMEOUT):
            dev["progress"].setRange(0, 100)
            dev["progress"].setValue(0)
            dev["progress"].setStyleSheet(Styles.get_progress_bar_style(Colors.ERROR))
            if fail_reason:
                dev["log_lbl"].setText(fail_reason)
        elif state in (S_FLASH1, S_FLASH3):
            dev["progress"].setRange(0, 100)
            dev["progress"].setValue(0)
            dev["progress"].setStyleSheet(Styles.get_progress_bar_style(Colors.WARNING))
        else:
            dev["progress"].setRange(0, 100)
            dev["progress"].setValue(0)
            dev["progress"].setStyleSheet(Styles.get_progress_bar_style())

    def _set_failed(self, usb_path, reason):
        self._set_state(usb_path, S_FAILED, reason)
        self._check_complete()

    # ── Run control ────────────────────────────────────────────────────────────

    def _start_run(self):
        if self.run_active:
            return

        self.run_active  = True
        self.run_serials = set(self.devices.keys())
        self.cycle_start = datetime.now()

        self.btn_start.setEnabled(False)
        self.btn_start.setText("Running...")
        self.btn_stop.setEnabled(True)

        for usb_path in list(self.run_serials):
            dev = self.devices[usb_path]
            if dev["is_edl"]:
                self._start_flash(usb_path, stage=1)
            else:
                self._set_state(usb_path, S_SKIPPED)
                dev["log_lbl"].setText("Not in EDL at start")

        self._check_complete()

    def _stop_run(self):
        for usb_path, dev in self.devices.items():
            self._cancel_boot_timer(usb_path)
            proc = dev.get("process")
            if proc and proc.state() != QProcess.ProcessState.NotRunning:
                proc.kill()
                dev["process"] = None
            if dev["state"] not in TERMINAL:
                self._set_state(usb_path, S_FAILED, "Stopped by operator")

        self.run_active = False
        self.run_serials.clear()
        self.btn_stop.setEnabled(False)
        self.btn_start.setEnabled(True)
        self.btn_start.setText("Start")
        self._update_summary()

    # ── Flash ──────────────────────────────────────────────────────────────────

    def _start_flash(self, usb_path, stage: int):
        dev = self.devices[usb_path]
        fw_path = self.factory_fw if stage == 1 else self.prod_fw
        state   = S_FLASH1       if stage == 1 else S_FLASH3
        qdl_serial = dev.get("qdl_serial", "")

        if not qdl_serial:
            self._set_failed(usb_path,
                             f"Stage {stage}: no QDL serial for device at {usb_path}")
            return

        prog, raw, patch = FlashManager.find_firmware_files(fw_path)
        if not (prog and raw and patch):
            self._set_failed(usb_path,
                             f"Stage {stage} firmware not found in: {fw_path}")
            return

        self._set_state(usb_path, state)
        dev["log_lbl"].setText("")

        self._flash_count += 1
        if self._flash_count == 1:
            self.timer.stop()

        # Progress socket server — GUI listens, qdl connects as client
        sock_name = f"{QDL_PROGRESS_SOCK_PREFIX}{usb_path}-s{stage}"
        QLocalServer.removeServer(sock_name)
        progress_server = QLocalServer()
        progress_server.listen(sock_name)
        progress_sock_path = progress_server.fullServerName()
        log.debug("Progress server for %s stage %d at %s", usb_path, stage, progress_sock_path)

        dev["progress_server"] = progress_server
        dev["progress_socket"] = None

        process = QProcess()
        dev["process"] = process

        def on_progress_connected():
            sock = progress_server.nextPendingConnection()
            if not sock:
                return
            dev["progress_socket"] = sock
            log.debug("Progress socket connected for %s stage %d", usb_path, stage)
            sock.readyRead.connect(lambda: _read_progress(sock))

        def _read_progress(sock):
            data = bytes(sock.readAll()).decode(errors='replace')
            for line in data.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    event = msg.get("event")
                    if event == "progress":
                        pct = min(int(msg["percent"]), 100)
                        dev["progress"].setValue(pct)
                        dev["log_lbl"].setText(
                            f'{msg["task"]} {msg["percent"]:.1f}%')
                    elif event in ("info", "error"):
                        dev["log_lbl"].setText(msg.get("message", "").strip())
                        log.log(
                            logging.WARNING if event == "error" else logging.DEBUG,
                            "qdl [%s s%d] %s: %s", usb_path, stage, event,
                            msg.get("message", ""))
                except (json.JSONDecodeError, KeyError):
                    dev["log_lbl"].setText(line)

        # Drain stdout to prevent pipe blocking
        process.readyReadStandardOutput.connect(
            lambda: log.debug("qdl stdout [%s s%d]: %s", usb_path, stage,
                              process.readAllStandardOutput().data()
                              .decode(errors='replace').strip()))

        def on_finished(code):
            log.info("qdl stage %d finished for %s with exit code %d", stage, usb_path, code)
            if dev.get("progress_socket"):
                dev["progress_socket"].close()
            progress_server.close()
            QLocalServer.removeServer(sock_name)
            dev["process"] = None
            self._flash_count = max(0, self._flash_count - 1)
            if self._flash_count == 0:
                self.timer.start(SCAN_INTERVAL_MS)
            if code == 0:
                dev["progress"].setValue(100)
                if stage == 1:
                    self._set_state(usb_path, S_BOOTING)
                    dev["log_lbl"].setText("Waiting for device to boot…")
                    self._start_boot_timer(usb_path)
                else:
                    self._set_state(usb_path, S_DONE)
                    dev["log_lbl"].setText("Complete")
            else:
                self._set_failed(usb_path, f"Stage {stage} flash failed (exit {code})")
            self._check_complete()

        progress_server.newConnection.connect(on_progress_connected)
        process.finished.connect(lambda code: on_finished(code))
        args = FlashManager.build_flash_command(qdl_serial, prog, raw, patch,
                                                progress_socket=progress_sock_path)
        log.info("Starting stage %d flash for %s (qdl_serial=%s): %s", stage, usb_path, qdl_serial, " ".join(args))
        process.setWorkingDirectory(FlashManager.get_working_directory(raw))
        process.start(args[0], args[1:])

    # ── Boot timer ─────────────────────────────────────────────────────────────

    def _start_boot_timer(self, usb_path):
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._on_boot_timeout(usb_path))
        timer.start(self.boot_timeout_ms)
        self.devices[usb_path]["boot_timer"] = timer

    def _cancel_boot_timer(self, usb_path):
        dev = self.devices.get(usb_path, {})
        t = dev.get("boot_timer")
        if t:
            t.stop()
            dev["boot_timer"] = None

    def _on_boot_timeout(self, usb_path):
        if usb_path in self.devices and self.devices[usb_path]["state"] == S_BOOTING:
            self._set_state(usb_path, S_TIMEOUT,
                            f"Device did not boot within {self.boot_timeout_ms // 1000}s")
            self._check_complete()

    # ── Session complete ───────────────────────────────────────────────────────

    def _check_complete(self):
        if not self.run_active:
            return
        pending = [
            s for s in self.run_serials
            if s in self.devices and self.devices[s]["state"] not in TERMINAL
        ]
        if not pending:
            self.run_active = False
            self.btn_stop.setEnabled(False)
            self.btn_start.setText("Start")
            self.btn_start.setEnabled(True)
            self._update_summary()
            QTimer.singleShot(400, self._show_report)

    # ── Report dialog ──────────────────────────────────────────────────────────

    def _show_report(self):
        now       = datetime.now()
        started   = self.cycle_start or now
        elapsed   = now - started
        total_sec = int(elapsed.total_seconds())
        duration  = f"{total_sec // 60}m {total_sec % 60}s"
        ts_label  = started.strftime("%Y-%m-%d  %H:%M:%S")

        done = skipped = failed = timeout = 0
        lines = []
        for usb_path in sorted(self.run_serials):
            dev = self.devices.get(usb_path)
            if not dev:
                continue
            state  = dev["state"]
            reason = dev["fail_reason"]
            display = dev.get("qdl_serial") or usb_path
            if state == S_DONE:             done    += 1
            elif state == S_SKIPPED:        skipped += 1
            elif state == S_TIMEOUT:        timeout += 1
            elif state == S_FAILED:         failed  += 1
            suffix = f"  —  {reason}" if reason else ""
            lines.append(f"{display:<22}  {state:<14}{suffix}")

        summary = (
            f"  DONE: {done}    FAILED: {failed}"
            f"    TIMEOUT: {timeout}    SKIPPED: {skipped}"
        )
        report_text = (
            f"Cycle started : {ts_label}\n"
            f"Duration      : {duration}\n"
            f"Devices       : {len(self.run_serials)}\n"
            + summary + "\n"
            + "─" * 60 + "\n"
            + "\n".join(lines)
        )

        self._save_report(report_text, started)

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Session Report  —  {duration}")
        dlg.setMinimumWidth(620)
        dlg.setStyleSheet(
            f"background-color: {Colors.BG_SURFACE}; color: {Colors.TEXT_PRIMARY};"
        )

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("Session Complete")
        title.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; font-size: 14px; font-weight: 700;"
        )
        layout.addWidget(title)

        meta = QLabel(f"Started {ts_label}   ·   Duration {duration}   ·   {len(self.run_serials)} devices")
        meta.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        layout.addWidget(meta)

        box = QTextEdit()
        box.setReadOnly(True)
        box.setPlainText(report_text)
        box.setStyleSheet(
            f"background: {Colors.BG_BASE}; color: {Colors.TEXT_PRIMARY};"
            "font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 11px;"
            "border: none; padding: 8px;"
        )
        box.setMinimumHeight(200)
        layout.addWidget(box)

        btn_row = QHBoxLayout()
        btn_copy = QPushButton("Copy to Clipboard")
        btn_copy.setStyleSheet(Styles.get_outlined_button_style(Colors.PRIMARY))
        btn_copy.clicked.connect(
            lambda: QApplication.clipboard().setText(report_text)
        )
        btn_close = QPushButton("Close")
        btn_close.setStyleSheet(Styles.get_outlined_button_style(Colors.TEXT_SECONDARY))
        btn_close.clicked.connect(dlg.accept)

        btn_row.addWidget(btn_copy)
        btn_row.addStretch()
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        dlg.finished.connect(self._auto_new_cycle)
        dlg.exec()

    def _save_report(self, text: str, started: datetime):
        try:
            os.makedirs(self.reports_dir, exist_ok=True)
            filename = f"cycle_{started.strftime('%Y%m%d_%H%M%S')}.txt"
            path = os.path.join(self.reports_dir, filename)
            with open(path, "w") as f:
                f.write(text + "\n")
        except Exception as e:
            print(f"[factory] could not save report: {e}")

    def _new_cycle(self):
        """Clear all terminal-state devices and reset for the next batch."""
        for usb_path in list(self.devices.keys()):
            if self.devices[usb_path]["state"] in TERMINAL:
                self._remove_row(usb_path)
        self.run_serials.clear()
        self._update_summary()
        self._update_start_btn()

    def _auto_new_cycle(self):
        """Called when the report dialog closes — clear state then wait for next batch."""
        self._new_cycle()
        self._show_replug_dialog()

    def _show_replug_dialog(self):
        """Modal dialog asking operator to plug in next batch in EDL."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Next Batch")
        dlg.setMinimumWidth(400)
        dlg.setStyleSheet(
            f"background-color: {Colors.BG_SURFACE}; color: {Colors.TEXT_PRIMARY};"
        )

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(14)

        title = QLabel("Replug Devices for Next Batch")
        title.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; font-size: 14px; font-weight: 700;"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        instr = QLabel("Connect all devices in EDL mode.")
        instr.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        instr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(instr)

        count_lbl = QLabel("Waiting for EDL devices…")
        count_lbl.setStyleSheet(
            f"color: {Colors.EDL_MODE}; font-size: 13px; font-weight: 600;"
        )
        count_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(count_lbl)

        btn_row = QHBoxLayout()
        btn_start = QPushButton("Start Now")
        btn_start.setStyleSheet(Styles.get_action_button_style(Colors.SUCCESS))
        btn_start.setEnabled(False)
        btn_start.clicked.connect(dlg.accept)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setStyleSheet(Styles.get_outlined_button_style(Colors.TEXT_SECONDARY))
        btn_cancel.clicked.connect(dlg.reject)

        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_start)
        layout.addLayout(btn_row)

        # Poll for EDL devices using the scan timer
        poll = QTimer(dlg)
        def _check_edl():
            edl_count = sum(
                1 for d in self.devices.values() if d["is_edl"]
            )
            if edl_count:
                count_lbl.setText(f"{edl_count} device{'s' if edl_count > 1 else ''} in EDL — ready")
                btn_start.setEnabled(True)
            else:
                count_lbl.setText("Waiting for EDL devices…")
                btn_start.setEnabled(False)

        poll.timeout.connect(_check_edl)
        poll.start(SCAN_INTERVAL_MS)

        result = dlg.exec()
        poll.stop()

        if result == QDialog.DialogCode.Accepted:
            QTimer.singleShot(100, self._start_run)

    # ── Header helpers ─────────────────────────────────────────────────────────

    def _update_start_btn(self):
        if self.run_active:
            return
        has_edl = any(d["is_edl"] for d in self.devices.values())
        self.btn_start.setEnabled(has_edl)

    def _update_summary(self):
        if not self.run_serials:
            self.lbl_summary.setText("")
            return
        counts = {s: 0 for s in [S_DONE, S_FAILED, S_TIMEOUT, S_SKIPPED]}
        for serial in self.run_serials:
            dev = self.devices.get(serial)
            if dev and dev["state"] in counts:
                counts[dev["state"]] += 1
        total = len(self.run_serials)
        done    = counts[S_DONE]
        failed  = counts[S_FAILED] + counts[S_TIMEOUT]
        skipped = counts[S_SKIPPED]
        self.lbl_summary.setText(
            f"{done}/{total} DONE   {failed} FAILED   {skipped} SKIPPED"
        )


if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    import sys

    app = QApplication(sys.argv)
    window = FactoryStation()
    window.show()
    sys.exit(app.exec())
