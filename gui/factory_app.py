"""Factory Assembly Flash Station — serial-keyed 3-stage pipeline.

The GUI drives a FactoryPipeline (pure state machine) via a QTimer.
All device logic lives in pipeline.py / device.py; this file only handles
Qt widgets, QProcess, and QTimer.
"""
import os
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QDialog, QTextEdit, QApplication,
)
from PyQt6.QtCore import QTimer, Qt, QProcess
from PyQt6.QtGui import QColor
from gui.base_station import BaseFlashStation

from config import (
    SCAN_INTERVAL_MS,
    FACTORY_FW_PATH_ENV, PROD_DEBUG_FW_PATH_ENV,
    BOOT_TIMEOUT_SEC_ENV, DEFAULT_BOOT_TIMEOUT_SEC,
    FACTORY_REPORTS_DIR_ENV, DEFAULT_REPORTS_DIR,
)
from gui.styles import Styles, Colors
from core.device import Device
from core.scanner import scan_edl, scan_adb
from core.pipeline import (
    FactoryPipeline,
    S_WAITING, S_SKIPPED, S_FLASH1, S_BOOTING,
    S_REBOOTING_EDL, S_FLASH3, S_DONE, S_FAILED, S_TIMEOUT,
    TERMINAL,
)

# ── UI-only mappings ──────────────────────────────────────────────────────────

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


class FactoryStation(BaseFlashStation):
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

        # {serial: Device} — populated by scanner before run starts
        self._devices: dict[str, Device] = {}
        # {serial: dict}  — Qt widget refs (row, stage_item, status_item, progress, log_lbl)
        self._widgets: dict[str, dict] = {}
        # {serial: dict}  — async process handles (process, build_id_proc)
        self._procs: dict[str, dict] = {}
        # Set of serials whose build_id QProcess is currently in flight
        self._build_id_in_flight: set[str] = set()

        self._pipeline: FactoryPipeline | None = None
        self.run_active  = False
        self.run_serials: set[str] = set()
        self.cycle_start: datetime | None = None

        self._setup_ui()
        self._setup_scanning()

    # ── UI setup ─────────────────────────────────────────────────────────────

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
        super()._setup_scanning()

    # ── Scanning ──────────────────────────────────────────────────────────────

    def _scan(self):
        edl_devices = scan_edl()   # {serial: Device}
        adb_map     = scan_adb()   # {serial: tid}

        if not self.run_active:
            # Pre-run: track EDL devices, allow row addition/removal
            for serial, device in edl_devices.items():
                if serial not in self._widgets:
                    self._devices[serial] = device
                    self._add_row(serial)
            for serial in list(self._widgets.keys()):
                if serial not in edl_devices:
                    self._remove_row(serial)
        else:
            # During run: update transport IDs for booted devices
            for serial, tid in adb_map.items():
                if serial in self._devices:
                    self._devices[serial].transport_id = tid
            # Advance pipeline and drain queued actions
            self._pipeline.tick(set(edl_devices.keys()), adb_map)
            self._drain_pending_actions()

        self._update_start_btn()
        self._update_summary()

    def _drain_pending_actions(self):
        if not self._pipeline:
            return
        for serial, stage in self._pipeline.drain_flash_requests():
            self._start_flash_process(serial, stage)
        for serial in self._pipeline.drain_build_id_requests():
            self._start_build_id_check(serial)

    # ── Row management ────────────────────────────────────────────────────────

    def _add_row(self, serial: str):
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

        self.table.setItem(row, COL_SERIAL, serial_item)
        self.table.setItem(row, COL_STAGE,  stage_item)
        self.table.setItem(row, COL_STATUS, status_item)

        pw, progress = self._make_progress_widget()
        self.table.setCellWidget(row, COL_PROGRESS, pw)

        log_lbl = self._make_log_label()
        self.table.setCellWidget(row, COL_LOG, log_lbl)

        self._widgets[serial] = {
            "row":         row,
            "stage_item":  stage_item,
            "status_item": status_item,
            "progress":    progress,
            "log_lbl":     log_lbl,
        }
        self._procs[serial] = {"process": None, "build_id_proc": None}

    def _remove_row(self, serial: str):
        w = self._widgets.pop(serial, None)
        if not w:
            return
        self._devices.pop(serial, None)
        self._procs.pop(serial, None)
        self.table.removeRow(w["row"])
        for d in self._widgets.values():
            if d["row"] > w["row"]:
                d["row"] -= 1

    # ── State updates (called via pipeline callbacks) ─────────────────────────

    def _on_state_change(self, serial: str, state: str, reason: str):
        w = self._widgets.get(serial)
        if not w:
            return
        w["status_item"].setText(state)
        w["status_item"].setForeground(
            QColor(STATE_COLORS.get(state, Colors.TEXT_SECONDARY))
        )
        w["stage_item"].setText(STAGE_LABEL.get(state, "—"))

        progress = w["progress"]
        if state in (S_BOOTING, S_REBOOTING_EDL):
            progress.setRange(0, 0)
        elif state == S_DONE:
            progress.setRange(0, 100)
            progress.setValue(100)
            progress.setStyleSheet(Styles.get_progress_bar_style(Colors.SUCCESS))
        elif state in (S_FAILED, S_TIMEOUT):
            progress.setRange(0, 100)
            progress.setValue(0)
            progress.setStyleSheet(Styles.get_progress_bar_style(Colors.ERROR))
            if reason:
                w["log_lbl"].setText(reason)
        elif state in (S_FLASH1, S_FLASH3):
            progress.setRange(0, 100)
            progress.setValue(0)
            progress.setStyleSheet(Styles.get_progress_bar_style(Colors.WARNING))
        else:
            progress.setRange(0, 100)
            progress.setValue(0)
            progress.setStyleSheet(Styles.get_progress_bar_style())

        if state in TERMINAL:
            self._check_complete()

    def _on_progress(self, serial: str, pct: int):
        w = self._widgets.get(serial)
        if w:
            w["progress"].setValue(pct)

    def _on_log(self, serial: str, text: str):
        w = self._widgets.get(serial)
        if w:
            w["log_lbl"].setText(text)

    # ── Run control ───────────────────────────────────────────────────────────

    def _start_run(self):
        if self.run_active:
            return

        edl_devices = {s: d for s, d in self._devices.items() if d.is_edl}
        if not edl_devices:
            return

        self.run_active  = True
        self.run_serials = set(edl_devices.keys())
        self.cycle_start = datetime.now()

        self.btn_start.setEnabled(False)
        self.btn_start.setText("Running...")
        self.btn_stop.setEnabled(True)

        self._pipeline = FactoryPipeline(
            devices=list(edl_devices.values()),
            factory_fw=self.factory_fw,
            prod_fw=self.prod_fw,
            boot_timeout_sec=self.boot_timeout_ms // 1000,
        )
        self._pipeline.on_state_change = self._on_state_change
        self._pipeline.on_progress     = self._on_progress
        self._pipeline.on_log          = self._on_log
        self._pipeline.start()
        self._drain_pending_actions()
        self._check_complete()

    def _stop_run(self):
        # Kill any in-flight processes
        for serial, procs in self._procs.items():
            for key in ("process", "build_id_proc"):
                p = procs.get(key)
                if p and p.state() != QProcess.ProcessState.NotRunning:
                    p.kill()
            procs["process"] = None
            procs["build_id_proc"] = None
        self._build_id_in_flight.clear()

        # Mark unfinished jobs as failed
        if self._pipeline:
            for serial in self.run_serials:
                if self._pipeline.state_of(serial) not in TERMINAL:
                    # Force state change via callback (pipeline is being abandoned)
                    self._on_state_change(serial, S_FAILED, "Stopped by operator")

        self.run_active = False
        self.run_serials.clear()
        self._pipeline = None
        self.btn_stop.setEnabled(False)
        self.btn_start.setEnabled(True)
        self.btn_start.setText("Start")
        self._update_summary()

    # ── Flash process ─────────────────────────────────────────────────────────

    def _start_flash_process(self, serial: str, stage: int):
        procs = self._procs.get(serial)
        if not procs or procs.get("process"):
            return  # guard re-entry

        try:
            args, cwd = self._pipeline.flash_command_for(serial, stage)
        except FileNotFoundError as e:
            self._pipeline.flash_done(serial, stage, 1)
            self._on_log(serial, str(e))
            return

        w = self._widgets.get(serial, {})

        def on_done(code: int) -> None:
            procs["process"] = None
            if self._pipeline is None:
                return
            if code == 0 and w:
                w["progress"].setValue(100)
            self._pipeline.flash_done(serial, stage, code)
            self._drain_pending_actions()

        procs["process"] = self._launch_flash_process(
            args, cwd,
            on_log=lambda text: self._on_log(serial, text),
            on_progress=lambda pct: self._on_progress(serial, pct),
            on_done=on_done,
        )

    # ── Build ID check ────────────────────────────────────────────────────────

    def _start_build_id_check(self, serial: str):
        if serial in self._build_id_in_flight:
            return
        procs = self._procs.get(serial)
        if not procs:
            return

        device = self._devices.get(serial)
        if not device or not device.transport_id:
            return

        self._build_id_in_flight.add(serial)

        def on_result(output: str) -> None:
            self._build_id_in_flight.discard(serial)
            procs["build_id_proc"] = None
            if self._pipeline is None or serial not in self._devices:
                return
            self._pipeline.build_id_result(serial, output)

        procs["build_id_proc"] = self._launch_build_id_check(
            device.transport_id, on_result
        )

    # ── Session complete ───────────────────────────────────────────────────────

    def _check_complete(self):
        if not self.run_active or not self._pipeline:
            return
        if self._pipeline.is_complete:
            self.run_active = False
            self.btn_stop.setEnabled(False)
            self.btn_start.setText("Start")
            self.btn_start.setEnabled(True)
            self._update_summary()
            QTimer.singleShot(400, self._show_report)

    # ── Report dialog ──────────────────────────────────────────────────────────

    def _show_report(self):
        now     = datetime.now()
        started = self.cycle_start or now
        elapsed = now - started
        total   = int(elapsed.total_seconds())
        dur     = f"{total // 60}m {total % 60}s"
        ts      = started.strftime("%Y-%m-%d  %H:%M:%S")

        results = self._pipeline.results() if self._pipeline else {}
        counts  = {S_DONE: 0, S_FAILED: 0, S_TIMEOUT: 0, S_SKIPPED: 0}
        lines   = []
        for serial in sorted(self.run_serials):
            state, reason = results.get(serial, (S_FAILED, ""))
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

    def _save_report(self, text: str, started: datetime):
        try:
            os.makedirs(self.reports_dir, exist_ok=True)
            fname = f"cycle_{started.strftime('%Y%m%d_%H%M%S')}.txt"
            with open(os.path.join(self.reports_dir, fname), "w") as f:
                f.write(text + "\n")
        except Exception as e:
            print(f"[factory] could not save report: {e}")

    def _new_cycle(self):
        for serial in list(self._widgets.keys()):
            if self._pipeline and self._pipeline.state_of(serial) in TERMINAL:
                self._remove_row(serial)
            elif not self._pipeline:
                self._remove_row(serial)
        self.run_serials.clear()
        self._pipeline = None
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
            n = sum(1 for d in self._devices.values() if d.is_edl)
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

    # ── Header helpers ─────────────────────────────────────────────────────────

    def _update_start_btn(self):
        if self.run_active:
            return
        self.btn_start.setEnabled(
            any(d.is_edl for d in self._devices.values())
        )

    def _update_summary(self):
        if not self.run_serials or not self._pipeline:
            self.lbl_summary.setText("")
            return
        counts = {S_DONE: 0, S_FAILED: 0, S_TIMEOUT: 0, S_SKIPPED: 0}
        for serial in self.run_serials:
            state = self._pipeline.state_of(serial)
            if state in counts:
                counts[state] += 1
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
