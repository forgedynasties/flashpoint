"""factory2.py — Simplified 2-stage factory flash station.

Flow:
  1. Scan for QDL devices → N serials captured
  2. Flash factory firmware to all N in parallel
  3. Poll `adb devices` until count >= N
  4. Reboot all ADB devices to EDL
  5. Wait until N QDL devices appear
  6. Flash debug firmware to all N in parallel
  7. Done

Env vars: FACTORY, DEBUG, QDL_BIN
"""
import os
import re
import subprocess
import sys

from PyQt6.QtCore import Qt, QProcess, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication, QHeaderView, QLabel, QMainWindow,
    QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from config import SCAN_INTERVAL_MS
from core.device import Device
from core.scanner import scan_edl
from gui.styles import Colors, Styles

# ── Phases ────────────────────────────────────────────────────────────────────

P_IDLE       = "idle"
P_FLASH1     = "flash1"     # flashing factory fw
P_WAIT_ADB   = "wait_adb"   # waiting for N ADB devices
P_REBOOT     = "reboot"     # sending reboot edl
P_WAIT_EDL   = "wait_edl"   # waiting for N QDL devices
P_FLASH2     = "flash2"     # flashing debug fw
P_DONE       = "done"

# ── Per-device states ─────────────────────────────────────────────────────────

DS_WAIT   = "—"
DS_FLASH  = "flashing"
DS_OK     = "done"
DS_FAIL   = "FAILED"

DS_COLORS = {
    DS_WAIT:  Colors.TEXT_DIM,
    DS_FLASH: Colors.WARNING,
    DS_OK:    Colors.SUCCESS,
    DS_FAIL:  Colors.ERROR,
}

# ── Table columns ─────────────────────────────────────────────────────────────

COL_SN      = 0
COL_FLASH1  = 1
COL_FLASH2  = 2
COL_STATUS  = 3
COL_COUNT   = 4

PHASE_LABEL = {
    P_IDLE:     "Connect devices in QDL mode",
    P_FLASH1:   "Flashing factory firmware…",
    P_WAIT_ADB: "Waiting for devices to boot…",
    P_REBOOT:   "Rebooting to EDL…",
    P_WAIT_EDL: "Waiting for QDL devices…",
    P_FLASH2:   "Flashing debug firmware…",
    P_DONE:     "Done",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _adb_transport_ids() -> list[str]:
    try:
        out = subprocess.check_output(["adb", "devices", "-l"]).decode()
        return [
            m.group(1)
            for line in out.splitlines()
            if (m := re.search(r"transport_id:(\d+)", line))
        ]
    except Exception:
        return []


# ── Main window ───────────────────────────────────────────────────────────────

class Factory2(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Factory Flash v2")
        self.setMinimumSize(780, 460)
        self.setGeometry(100, 100, 900, 520)

        self.factory_fw = os.getenv("FACTORY", "")
        self.debug_fw   = os.getenv("DEBUG", "")

        self._phase      = P_IDLE
        self._n          = 0                    # target device count
        self._serials:   list[str]    = []      # QDL serials captured at start
        self._rows:      dict[str, int] = {}    # serial → table row
        self._procs:     list[QProcess] = []    # active flash QProcesses
        self._done = self._fail = 0

        self._setup_ui()

        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)
        self._timer.start(SCAN_INTERVAL_MS)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        root.setStyleSheet(Styles.get_main_window_style())

        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        hdr = QWidget()
        hdr.setStyleSheet(Styles.get_header_group_style())
        hdr_row = QHBoxLayout(hdr)
        hdr_row.setContentsMargins(14, 10, 14, 10)
        hdr_row.setSpacing(12)

        def _fw_label(prefix, path):
            w = QLabel(
                f"<span style='color:{Colors.TEXT_SECONDARY};font-size:10px;"
                f"font-weight:700'>{prefix}</span>  "
                f"<span style='color:{Colors.TEXT_PRIMARY if path else Colors.ERROR};"
                f"font-size:11px'>{path or 'NOT SET'}</span>"
            )
            w.setTextFormat(Qt.TextFormat.RichText)
            return w

        hdr_row.addWidget(_fw_label("FACTORY", self.factory_fw))
        hdr_row.addSpacing(20)
        hdr_row.addWidget(_fw_label("DEBUG", self.debug_fw))
        hdr_row.addStretch()

        self.lbl_phase = QLabel(PHASE_LABEL[P_IDLE])
        self.lbl_phase.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; font-size: 11px; letter-spacing: 0.3px;"
        )
        hdr_row.addWidget(self.lbl_phase)
        hdr_row.addSpacing(16)

        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setStyleSheet(Styles.get_outlined_button_style(Colors.ERROR))
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop)
        hdr_row.addWidget(self.btn_stop)

        self.btn_start = QPushButton("Start")
        self.btn_start.setStyleSheet(Styles.get_action_button_style(Colors.SUCCESS))
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self._start)
        hdr_row.addWidget(self.btn_start)

        layout.addWidget(hdr)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(COL_COUNT)
        self.table.setHorizontalHeaderLabels(["Serial", "Flash 1", "Flash 2", "Status"])
        self.table.setStyleSheet(Styles.get_table_style())
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        hdr_h = self.table.horizontalHeader()
        hdr_h.setStretchLastSection(True)
        R = hdr_h.ResizeMode
        hdr_h.setSectionResizeMode(COL_SN,     R.Fixed);  self.table.setColumnWidth(COL_SN,     160)
        hdr_h.setSectionResizeMode(COL_FLASH1, R.Fixed);  self.table.setColumnWidth(COL_FLASH1, 200)
        hdr_h.setSectionResizeMode(COL_FLASH2, R.Fixed);  self.table.setColumnWidth(COL_FLASH2, 200)
        hdr_h.setSectionResizeMode(COL_STATUS, R.Stretch)

        vh = self.table.verticalHeader()
        vh.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vh.setDefaultSectionSize(36)
        vh.setVisible(False)

        layout.addWidget(self.table)

    # ── Polling ───────────────────────────────────────────────────────────────

    def _tick(self):
        if self._phase == P_IDLE:
            edl = scan_edl()
            n = len(edl)
            ok = bool(n) and bool(self.factory_fw) and bool(self.debug_fw)
            self.btn_start.setEnabled(ok)
            self.lbl_phase.setText(
                f"{n} device{'s' if n != 1 else ''} in QDL"
                + (" — ready" if ok else " — waiting…")
            )

        elif self._phase == P_WAIT_ADB:
            tids = _adb_transport_ids()
            n = len(tids)
            self.lbl_phase.setText(f"Waiting for boot: {n}/{self._n}")
            if n >= self._n:
                self._phase = P_REBOOT
                self.lbl_phase.setText(PHASE_LABEL[P_REBOOT])
                for tid in tids:
                    subprocess.Popen(["adb", "-t", tid, "reboot", "edl"])
                self._phase = P_WAIT_EDL

        elif self._phase == P_WAIT_EDL:
            edl = scan_edl()
            n = len(edl)
            self.lbl_phase.setText(f"Waiting for QDL: {n}/{self._n}")
            if n >= self._n:
                self._flash_all(list(edl.keys()), self.debug_fw, stage=2)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _start(self):
        edl = scan_edl()
        if not edl:
            return

        self._serials = list(edl.keys())
        self._n = len(self._serials)
        self._rows.clear()
        self.table.setRowCount(0)

        for sn in self._serials:
            self._add_row(sn)

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

        self._flash_all(self._serials, self.factory_fw, stage=1)

    def _stop(self):
        for proc in self._procs:
            if proc.state() != QProcess.ProcessState.NotRunning:
                proc.kill()
        self._procs.clear()
        self._phase = P_IDLE
        self.lbl_phase.setText("Stopped")
        self.btn_stop.setEnabled(False)
        self.btn_start.setEnabled(True)

    # ── Flash ─────────────────────────────────────────────────────────────────

    def _flash_all(self, serials: list[str], fw: str, stage: int):
        next_phase = P_WAIT_ADB if stage == 1 else P_DONE
        col        = COL_FLASH1  if stage == 1 else COL_FLASH2

        self._phase = P_FLASH1 if stage == 1 else P_FLASH2
        self.lbl_phase.setText(PHASE_LABEL[self._phase])
        self._done = self._fail = 0
        self._procs.clear()

        total = len(serials)

        for sn in serials:
            # Ensure row exists (stage 2 may have new/different serials)
            if sn not in self._rows:
                self._add_row(sn)
            self._set_cell(sn, col, DS_FLASH)

            try:
                dev = Device(serial=sn, mode="edl")
                args, cwd = dev.flash_command(fw)
            except Exception as e:
                self._set_cell(sn, col, DS_FAIL)
                self._set_status(sn, str(e))
                self._fail += 1
                self._on_flash_done(total, next_phase)
                continue

            proc = QProcess()
            proc.setWorkingDirectory(cwd)

            # Capture progress from qdl stdout lines like "modem_a 22.18%"
            proc.readyReadStandardOutput.connect(
                lambda sn=sn, col=col, proc=proc: self._on_stdout(sn, col, proc)
            )

            proc.finished.connect(
                lambda code, _sig, sn=sn, col=col, n=total, np=next_phase:
                    self._on_proc_finished(sn, col, code, n, np)
            )

            proc.start(args[0], args[1:])
            self._procs.append(proc)

    def _on_stdout(self, sn: str, col: int, proc: QProcess):
        raw = bytes(proc.readAllStandardOutput()).decode(errors="replace")
        for line in raw.splitlines():
            # pick up "partition N.NN%" or "flashed "X" successfully"
            m = re.search(r"(\d+\.\d+)%", line)
            if m:
                pct = float(m.group(1))
                self._set_cell(sn, col, f"{pct:.0f}%")
            elif "successfully" in line:
                part = re.search(r'"([^"]+)"', line)
                if part:
                    self._set_cell(sn, col, part.group(1))

    def _on_proc_finished(self, sn: str, col: int, code: int, total: int, next_phase: str):
        if code == 0:
            self._done += 1
            self._set_cell(sn, col, DS_OK)
            self._set_status(sn, "✓")
        else:
            self._fail += 1
            self._set_cell(sn, col, DS_FAIL)
            self._set_status(sn, f"exit {code}")
        self._on_flash_done(total, next_phase)

    def _on_flash_done(self, total: int, next_phase: str):
        finished = self._done + self._fail
        if finished < total:
            return
        if next_phase == P_DONE:
            self._phase = P_DONE
            self.lbl_phase.setText(
                f"Done — {self._done}/{total} succeeded"
                + (f", {self._fail} failed" if self._fail else "")
            )
            self.btn_stop.setEnabled(False)
            self.btn_start.setEnabled(True)
            self.btn_start.setText("Start")
        else:
            self._phase = next_phase

    # ── Table helpers ─────────────────────────────────────────────────────────

    def _add_row(self, sn: str):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._rows[sn] = row

        center = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter

        sn_item = QTableWidgetItem(sn)
        sn_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        sn_item.setForeground(QColor(Colors.EDL_MODE))
        self.table.setItem(row, COL_SN, sn_item)

        for col in (COL_FLASH1, COL_FLASH2, COL_STATUS):
            it = QTableWidgetItem(DS_WAIT)
            it.setTextAlignment(center)
            it.setForeground(QColor(DS_COLORS[DS_WAIT]))
            self.table.setItem(row, col, it)

    def _set_cell(self, sn: str, col: int, text: str):
        row = self._rows.get(sn)
        if row is None:
            return
        it = self.table.item(row, col)
        if it is None:
            it = QTableWidgetItem()
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, col, it)
        it.setText(text)
        color = DS_COLORS.get(text, Colors.TEXT_PRIMARY)
        it.setForeground(QColor(color))

    def _set_status(self, sn: str, text: str):
        self._set_cell(sn, COL_STATUS, text)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    win = Factory2()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
