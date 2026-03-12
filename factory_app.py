"""Factory Assembly Flash Station — serial-keyed 3-stage pipeline.

Devices are keyed by serial throughout (matching app.py). ADB transport IDs
are looked up by serial from 'adb devices -l' rather than by USB path, which
avoids path-matching failures that caused BOOTING timeouts when the sysfs
path and ADB-reported path didn't agree.
"""
import os
import re
from datetime import datetime
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTableWidget, QTableWidgetItem, QProgressBar,
    QHeaderView, QDialog, QTextEdit, QApplication,
)
from PyQt6.QtCore import QTimer, Qt, QProcess
from PyQt6.QtGui import QColor

from config import (
    SCAN_INTERVAL_MS,
    FACTORY_FW_PATH_ENV, PROD_DEBUG_FW_PATH_ENV,
    BOOT_TIMEOUT_SEC_ENV, DEFAULT_BOOT_TIMEOUT_SEC,
    EXPECTED_BUILD_ID,
    FACTORY_REPORTS_DIR_ENV, DEFAULT_REPORTS_DIR,
)
from styles import Styles, Colors
from utils_device_manager import DeviceScanner
from utils_flash_manager import FlashManager, RebootManager

# ── Pipeline states ─────────────────────────────────────────────────────────────
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

COL_SERIAL   = 0
COL_STAGE    = 1
COL_STATUS   = 2
COL_PROGRESS = 3
COL_LOG      = 4
COL_COUNT    = 5


class FactoryStation(QMainWindow):
    """Factory assembly flash station — serial-keyed 3-stage pipeline."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Factory Flash Station")
        self.setMinimumSize(900, 500)
        self.setGeometry(100, 100, 1100, 650)

        self.factory_fw      = os.getenv(FACTORY_FW_PATH_ENV, "")
        self.prod_fw         = os.getenv(PROD_DEBUG_FW_PATH_ENV, "")
        self.boot_timeout_ms = int(os.getenv(
            BOOT_TIMEOUT_SEC_ENV, DEFAULT_BOOT_TIMEOUT_SEC)) * 1000
        self.reports_dir = os.getenv(FACTORY_REPORTS_DIR_ENV, DEFAULT_REPORTS_DIR)

        # Keyed by device serial
        self.devices     = {}
        self.run_active  = False
        self.run_serials = set()
        self.cycle_start = None

        self._setup_ui()
        self._setup_scanning()

    # ── UI setup ────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        root.setStyleSheet(Styles.get_main_window_style())
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
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
                f"color: {Colors.TEXT_PRIMARY if path else Colors.ERROR}; font-size: 11px;"
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

    # ── Scanning ────────────────────────────────────────────────────────────────

    def _scan(self):
        edl_devices   = DeviceScanner.get_edl_devices()    # {serial: path}
        adb_by_serial = DeviceScanner.get_adb_serial_map() # {serial: tid}

        # Register new EDL devices not yet in the table
        for serial in edl_devices:
            if serial not in self.devices:
                self._add_row(serial)

        # Advance state machine for each tracked device
        for serial in list(self.devices.keys()):
            dev   = self.devices[serial]
            state = dev["state"]

            if state == S_WAITING:
                if serial in edl_devices:
                    dev["is_edl"] = True
                else:
                    # Unplugged before run started
                    self._remove_row(serial)

            elif state == S_BOOTING:
                # Device serial appears in ADB → it has booted
                if serial in adb_by_serial:
                    self._check_build_id(serial, adb_by_serial[serial])

            elif state == S_REBOOTING_EDL:
                # Waiting for device to come back as EDL
                if serial in edl_devices:
                    self._start_flash(serial, stage=3)

        self._update_start_btn()
        self._update_summary()

    # ── Row management ──────────────────────────────────────────────────────────

    def _add_row(self, serial):
        row = self.table.rowCount()
        self.table.insertRow(row)

        def item(text="", align=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft):
            it = QTableWidgetItem(text)
            it.setTextAlignment(align)
            return it

        center = Qt.AlignmentFlag.AlignCenter

        serial_item = item(serial)
        stage_item  = item("—", center)
        status_item = item(S_WAITING, center)
        status_item.setForeground(QColor(STATE_COLORS[S_WAITING]))

        self.table.setItem(row, COL_SERIAL,  serial_item)
        self.table.setItem(row, COL_STAGE,   stage_item)
        self.table.setItem(row, COL_STATUS,  status_item)

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

        log_lbl = QLabel()
        log_lbl.setStyleSheet(Styles.get_log_box_style())
        log_lbl.setContentsMargins(6, 0, 6, 0)
        self.table.setCellWidget(row, COL_LOG, log_lbl)

        self.devices[serial] = {
            "row":           row,
            "state":         S_WAITING,
            "fail_reason":   "",
            "is_edl":        True,
            "stage_item":    stage_item,
            "status_item":   status_item,
            "progress":      progress,
            "log_lbl":       log_lbl,
            "process":       None,
            "boot_timer":    None,
            "build_id_proc": None,
        }

    def _remove_row(self, serial):
        dev = self.devices.pop(serial)
        self.table.removeRow(dev["row"])
        for d in self.devices.values():
            if d["row"] > dev["row"]:
                d["row"] -= 1

    # ── State machine ────────────────────────────────────────────────────────────

    def _set_state(self, serial, state, fail_reason=""):
        dev = self.devices[serial]
        dev["state"]       = state
        dev["fail_reason"] = fail_reason

        dev["status_item"].setText(state)
        dev["status_item"].setForeground(
            QColor(STATE_COLORS.get(state, Colors.TEXT_SECONDARY))
        )
        dev["stage_item"].setText(STAGE_LABEL.get(state, "—"))

        if state in (S_BOOTING, S_REBOOTING_EDL):
            dev["progress"].setRange(0, 0)
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

    def _set_failed(self, serial, reason):
        self._set_state(serial, S_FAILED, reason)
        self._check_complete()

    # ── Run control ──────────────────────────────────────────────────────────────

    def _start_run(self):
        if self.run_active:
            return
        self.run_active  = True
        self.run_serials = set(self.devices.keys())
        self.cycle_start = datetime.now()

        self.btn_start.setEnabled(False)
        self.btn_start.setText("Running...")
        self.btn_stop.setEnabled(True)

        for serial in list(self.run_serials):
            dev = self.devices[serial]
            if dev["is_edl"]:
                self._start_flash(serial, stage=1)
            else:
                self._set_state(serial, S_SKIPPED)
                dev["log_lbl"].setText("Not in EDL at start")

        self._check_complete()

    def _stop_run(self):
        for serial, dev in self.devices.items():
            self._cancel_boot_timer(serial)
            self._cancel_build_id_check(serial)
            proc = dev.get("process")
            if proc and proc.state() != QProcess.ProcessState.NotRunning:
                proc.kill()
                dev["process"] = None
            if dev["state"] not in TERMINAL:
                self._set_state(serial, S_FAILED, "Stopped by operator")

        self.run_active = False
        self.run_serials.clear()
        self.btn_stop.setEnabled(False)
        self.btn_start.setEnabled(True)
        self.btn_start.setText("Start")
        self._update_summary()

    # ── Flash ────────────────────────────────────────────────────────────────────

    def _start_flash(self, serial, stage):
        dev = self.devices[serial]

        # Guard against re-entry (scan calls this for stage 3 every cycle)
        if stage == 1 and dev["state"] == S_FLASH1:
            return
        if stage == 3 and dev["state"] == S_FLASH3:
            return

        fw_path = self.factory_fw if stage == 1 else self.prod_fw
        state   = S_FLASH1        if stage == 1 else S_FLASH3

        prog, raw, patch = FlashManager.find_firmware_files(fw_path)
        if not (prog and raw and patch):
            self._set_failed(serial, f"Stage {stage} firmware not found in: {fw_path}")
            return

        self._set_state(serial, state)
        dev["log_lbl"].setText("")
        dev["is_edl"] = False

        process = QProcess()
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        dev["process"] = process

        def on_output():
            data = process.readAllStandardOutput().data().decode()
            for line in data.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                dev["log_lbl"].setText(stripped)
                m = re.search(r"(\d+\.\d+)%", stripped)
                if m:
                    dev["progress"].setValue(min(int(float(m.group(1))), 100))

        def on_finished(code, _status):
            dev["process"] = None
            if code == 0:
                dev["progress"].setValue(100)
                if stage == 1:
                    self._set_state(serial, S_BOOTING)
                    dev["log_lbl"].setText("Waiting for device to boot…")
                    self._start_boot_timer(serial)
                else:
                    self._set_state(serial, S_DONE)
                    dev["log_lbl"].setText("Complete")
            else:
                self._set_failed(serial, f"Stage {stage} flash failed (exit {code})")
            self._check_complete()

        process.readyReadStandardOutput.connect(on_output)
        process.finished.connect(on_finished)
        args = FlashManager.build_flash_command(serial, prog, raw, patch)
        process.setWorkingDirectory(FlashManager.get_working_directory(raw))
        process.start(args[0], args[1:])

    # ── Build ID check (non-blocking QProcess) ───────────────────────────────────

    def _check_build_id(self, serial, tid):
        """Start an async adb getprop. No-ops if one is already in flight.
        Retries each scan cycle until ADB responds with output."""
        dev = self.devices.get(serial)
        if not dev or dev.get("build_id_proc"):
            return

        proc = QProcess()
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        dev["build_id_proc"] = proc

        def on_finished(code, _status):
            if serial not in self.devices:
                return
            dev["build_id_proc"] = None
            if dev["state"] != S_BOOTING:
                return
            output = proc.readAllStandardOutput().data().decode().strip()
            if not output:
                return   # ADB not ready yet — retry next scan cycle
            self._cancel_boot_timer(serial)
            if output == EXPECTED_BUILD_ID:
                self._set_state(serial, S_REBOOTING_EDL)
                dev["log_lbl"].setText("Rebooting to EDL…")
                RebootManager.reboot_to_edl(tid)
            else:
                self._set_failed(serial, f"Build ID mismatch: {output!r}")

        proc.finished.connect(on_finished)
        proc.start("adb", ["-t", tid, "shell", "getprop", "ro.build.id"])

    def _cancel_build_id_check(self, serial):
        dev = self.devices.get(serial, {})
        p = dev.get("build_id_proc")
        if p and p.state() != QProcess.ProcessState.NotRunning:
            p.kill()
        dev["build_id_proc"] = None

    # ── Boot timer ───────────────────────────────────────────────────────────────

    def _start_boot_timer(self, serial):
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._on_boot_timeout(serial))
        timer.start(self.boot_timeout_ms)
        self.devices[serial]["boot_timer"] = timer

    def _cancel_boot_timer(self, serial):
        dev = self.devices.get(serial, {})
        t = dev.get("boot_timer")
        if t:
            t.stop()
            dev["boot_timer"] = None

    def _on_boot_timeout(self, serial):
        if serial in self.devices and self.devices[serial]["state"] == S_BOOTING:
            self._set_state(serial, S_TIMEOUT,
                            f"No boot within {self.boot_timeout_ms // 1000}s")
            self._check_complete()

    # ── Session complete ──────────────────────────────────────────────────────────

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

    # ── Report dialog ─────────────────────────────────────────────────────────────

    def _show_report(self):
        now     = datetime.now()
        started = self.cycle_start or now
        elapsed = now - started
        total   = int(elapsed.total_seconds())
        dur     = f"{total // 60}m {total % 60}s"
        ts      = started.strftime("%Y-%m-%d  %H:%M:%S")

        counts = {S_DONE: 0, S_FAILED: 0, S_TIMEOUT: 0, S_SKIPPED: 0}
        lines  = []
        for serial in sorted(self.run_serials):
            dev = self.devices.get(serial)
            if not dev:
                continue
            state  = dev["state"]
            reason = dev["fail_reason"]
            if state in counts:
                counts[state] += 1
            suffix = f"  —  {reason}" if reason else ""
            lines.append(f"{serial:<22}  {state:<14}{suffix}")

        summary = (
            f"  DONE: {counts[S_DONE]}    FAILED: {counts[S_FAILED]}"
            f"    TIMEOUT: {counts[S_TIMEOUT]}    SKIPPED: {counts[S_SKIPPED]}"
        )
        report_text = (
            f"Cycle started : {ts}\n"
            f"Duration      : {dur}\n"
            f"Devices       : {len(self.run_serials)}\n"
            + summary + "\n"
            + "─" * 60 + "\n"
            + "\n".join(lines)
        )
        self._save_report(report_text, started)

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Session Report  —  {dur}")
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

        meta = QLabel(
            f"Started {ts}   ·   Duration {dur}   ·   {len(self.run_serials)} devices"
        )
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
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(report_text))
        btn_close = QPushButton("Close")
        btn_close.setStyleSheet(Styles.get_outlined_button_style(Colors.TEXT_SECONDARY))
        btn_close.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_copy)
        btn_row.addStretch()
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        dlg.finished.connect(self._auto_new_cycle)
        dlg.exec()

    def _save_report(self, text, started):
        try:
            os.makedirs(self.reports_dir, exist_ok=True)
            fname = f"cycle_{started.strftime('%Y%m%d_%H%M%S')}.txt"
            with open(os.path.join(self.reports_dir, fname), "w") as f:
                f.write(text + "\n")
        except Exception as e:
            print(f"[factory] could not save report: {e}")

    def _new_cycle(self):
        for serial in list(self.devices.keys()):
            if self.devices[serial]["state"] in TERMINAL:
                self._remove_row(serial)
        self.run_serials.clear()
        self._update_summary()
        self._update_start_btn()

    def _auto_new_cycle(self):
        self._new_cycle()
        self._show_replug_dialog()

    def _show_replug_dialog(self):
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

        instr = QLabel("Connect all devices in EDL mode, then press Start.")
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

        poll = QTimer(dlg)
        def _check():
            n = sum(1 for d in self.devices.values() if d["is_edl"])
            count_lbl.setText(
                f"{n} device{'s' if n != 1 else ''} in EDL — ready" if n
                else "Waiting for EDL devices…"
            )
            btn_start.setEnabled(bool(n))
        poll.timeout.connect(_check)
        poll.start(SCAN_INTERVAL_MS)

        result = dlg.exec()
        poll.stop()
        if result == QDialog.DialogCode.Accepted:
            QTimer.singleShot(100, self._start_run)

    # ── Header helpers ────────────────────────────────────────────────────────────

    def _update_start_btn(self):
        if self.run_active:
            return
        self.btn_start.setEnabled(
            any(d["is_edl"] for d in self.devices.values())
        )

    def _update_summary(self):
        if not self.run_serials:
            self.lbl_summary.setText("")
            return
        counts = {s: 0 for s in [S_DONE, S_FAILED, S_TIMEOUT, S_SKIPPED]}
        for serial in self.run_serials:
            dev = self.devices.get(serial)
            if dev and dev["state"] in counts:
                counts[dev["state"]] += 1
        total   = len(self.run_serials)
        done    = counts[S_DONE]
        failed  = counts[S_FAILED] + counts[S_TIMEOUT]
        skipped = counts[S_SKIPPED]
        self.lbl_summary.setText(
            f"{done}/{total} DONE   {failed} FAILED   {skipped} SKIPPED"
        )


if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    window = FactoryStation()
    window.show()
    sys.exit(app.exec())
