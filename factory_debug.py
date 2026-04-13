"""Debug-only Factory Flash Station.

Pipeline:
  1. Poll qdl list → flash all in parallel with debug firmware
  2. Done
"""
import json
import logging
import os
import re
import struct
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import datetime

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QProgressBar, QTextEdit, QApplication,
    QDialog,
)
from PyQt6.QtCore import QTimer, Qt, QProcess
from PyQt6.QtNetwork import QLocalServer

from config import (
    SCAN_INTERVAL_MS,
    PROD_DEBUG_FW_PATH_ENV,
    QDL_BIN, QDL_PROGRESS_SOCK_PREFIX,
)
from styles import Styles, Colors
from utils_flash_manager import FlashManager

log = logging.getLogger(__name__)


def _fmt_elapsed(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m}m {s:02d}s" if m else f"{s}s"


# ── Sparse image helpers ─────────────────────────────────────────────────────

_SPARSE_MAGIC      = 0xED26FF3A
_CHUNK_TYPE_RAW    = 0xCAC1
_CHUNK_TYPE_FILL   = 0xCAC2
_CHUNK_TYPE_DONT_CARE = 0xCAC3
_SPARSE_HDR_FMT    = "<IHHHHIIIi"   # 28 bytes
_CHUNK_HDR_FMT     = "<HHII"        # 12 bytes


def _sparse_write_chunks(filepath):
    """Return list of byte sizes for each write op qdl will perform on this sparse image."""
    hdr_size   = struct.calcsize(_SPARSE_HDR_FMT)
    chunk_size = struct.calcsize(_CHUNK_HDR_FMT)
    ops = []
    try:
        with open(filepath, "rb") as f:
            raw = f.read(hdr_size)
            if len(raw) < hdr_size:
                return None
            magic, major, _minor, file_hdr_sz, chunk_hdr_sz, blk_sz, _total_blks, total_chunks, _crc = \
                struct.unpack(_SPARSE_HDR_FMT, raw)
            if magic != _SPARSE_MAGIC or major != 1:
                return None
            if file_hdr_sz > hdr_size:
                f.seek(file_hdr_sz - hdr_size, 1)
            for _ in range(total_chunks):
                raw_chunk = f.read(chunk_size)
                if len(raw_chunk) < chunk_size:
                    break
                chunk_type, _res, chunk_sz, _total_sz = struct.unpack(_CHUNK_HDR_FMT, raw_chunk)
                data_bytes = chunk_sz * blk_sz
                if chunk_hdr_sz > chunk_size:
                    f.seek(chunk_hdr_sz - chunk_size, 1)
                if chunk_type == _CHUNK_TYPE_RAW:
                    ops.append(data_bytes)
                    f.seek(data_bytes, 1)
                elif chunk_type == _CHUNK_TYPE_FILL:
                    ops.append(data_bytes)
                    f.seek(4, 1)
                elif chunk_type == _CHUNK_TYPE_DONT_CARE:
                    pass
    except Exception:
        return None
    return ops or None


def _scan_flash_ops(raw_xml_path, fw_dir):
    """Parse rawprogram.xml and return the exact ordered list of (label, bytes) that qdl will execute."""
    ops = []
    try:
        tree = ET.parse(raw_xml_path)
        for p in tree.findall(".//program"):
            filename = (p.get("filename") or "").strip()
            if not filename:
                continue
            label = (p.get("label") or p.get("LABEL") or "").strip() or filename
            is_sparse = (p.get("sparse") or "").lower() == "true"
            sector_size = int(p.get("SECTOR_SIZE_IN_BYTES") or 4096)
            num_sectors = int(p.get("num_partition_sectors") or 0)

            filepath = os.path.join(fw_dir, os.path.basename(filename))

            if is_sparse:
                chunks = _sparse_write_chunks(filepath)
                if chunks:
                    for b in chunks:
                        ops.append((label, b))
                    continue

            if num_sectors:
                ops.append((label, num_sectors * sector_size))
    except Exception as exc:
        log.warning("Could not scan flash ops: %s", exc)

    total_bytes = sum(b for _, b in ops)
    return ops, total_bytes


# ── Phase constants ──────────────────────────────────────────────────────────
P_IDLE   = "IDLE"
P_FLASH  = "FLASHING"
P_DONE   = "DONE"
P_FAILED = "FAILED"

_PHASE_COLOR = {
    P_IDLE:   Colors.TEXT_SECONDARY,
    P_FLASH:  Colors.WARNING,
    P_DONE:   Colors.SUCCESS,
    P_FAILED: Colors.ERROR,
}


# ── Count-only helpers ───────────────────────────────────────────────────────

def _edl_serials():
    """Return list of QDL serials by running `qdl list`."""
    try:
        out = subprocess.check_output(
            ["sudo", QDL_BIN, "list"], stderr=subprocess.DEVNULL, timeout=5
        ).decode()
        serials = []
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and ":" in parts[0]:
                serials.append(parts[1])
        return serials
    except Exception as exc:
        log.debug("qdl list: %s", exc)
        return []


# ── Main window ──────────────────────────────────────────────────────────────

class DebugFlashStation(QMainWindow):
    """Single-stage debug flash station — flashes debug firmware only."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Debug Flash Station")
        self.setMinimumSize(700, 500)
        self.setGeometry(100, 100, 860, 580)

        self.debug_fw = os.getenv(PROD_DEBUG_FW_PATH_ENV, "")

        # Run state
        self._phase        = P_IDLE
        self._device_count = 0
        self._processes    = []
        self._done_count   = 0
        self._failed_count = 0
        self._cycle_t0     = 0.0
        self._ops          = []
        self._total_bytes  = 0
        self._stage_t0     = 0.0
        self._dev_progress = {}

        self._setup_ui()

        log.info("=== Debug Flash Station startup ===")
        log.info("  QDL_BIN            = %s", QDL_BIN)
        log.info("  PROD_DEBUG_FW_PATH = %s", self.debug_fw or "(not set)")

        self._idle_timer = QTimer()
        self._idle_timer.timeout.connect(self._idle_tick)
        self._idle_timer.start(1000)

    def closeEvent(self, event):
        super().closeEvent(event)

    # ── UI setup ─────────────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        root.setStyleSheet(Styles.get_main_window_style())
        vbox = QVBoxLayout(root)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)
        self._build_header(vbox)
        self._build_body(vbox)
        self._build_log(vbox)

    def _build_header(self, parent):
        hdr = QWidget()
        hdr.setStyleSheet(Styles.get_header_group_style())
        row = QHBoxLayout(hdr)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(12)

        lbl = QLabel("DEBUG FIRMWARE")
        lbl.setStyleSheet(
            f"color:{Colors.TEXT_SECONDARY};font-size:10px;"
            "font-weight:700;letter-spacing:.8px;"
        )
        val = QLabel(self.debug_fw or "NOT SET — check env var")
        val.setStyleSheet(
            f"color:{Colors.TEXT_PRIMARY if self.debug_fw else Colors.ERROR};"
            "font-size:11px;"
        )
        box = QVBoxLayout()
        box.setSpacing(2)
        box.addWidget(lbl)
        box.addWidget(val)
        row.addLayout(box)
        row.addStretch()

        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setStyleSheet(Styles.get_outlined_button_style(Colors.ERROR))
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop)
        row.addWidget(self.btn_stop)

        self.btn_start = QPushButton("Start")
        self.btn_start.setStyleSheet(Styles.get_action_button_style(Colors.SUCCESS))
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self._start)
        row.addWidget(self.btn_start)

        parent.addWidget(hdr)

    def _build_body(self, parent):
        body = QWidget()
        body.setMinimumHeight(190)
        body.setStyleSheet(f"background:{Colors.BG_BASE};")
        vbox = QVBoxLayout(body)
        vbox.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_phase = QLabel(P_IDLE)
        self.lbl_phase.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_phase.setStyleSheet(
            f"color:{_PHASE_COLOR[P_IDLE]};font-size:28px;font-weight:700;"
        )

        pw = QWidget()
        pl = QHBoxLayout(pw)
        pl.setContentsMargins(80, 0, 80, 0)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFixedHeight(30)
        self.progress.setStyleSheet(Styles.get_progress_bar_style())
        pl.addWidget(self.progress)

        self.lbl_detail = QLabel("Waiting for EDL devices…")
        self.lbl_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_detail.setStyleSheet(
            f"color:{Colors.WHITE};font-size:16px;font-weight:700;"
        )

        self.lbl_eta = QLabel("")
        self.lbl_eta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_eta.setStyleSheet(
            f"color:{Colors.TEXT_SECONDARY};font-size:13px;"
        )

        vbox.addSpacing(18)
        vbox.addWidget(self.lbl_phase)
        vbox.addSpacing(14)
        vbox.addWidget(pw)
        vbox.addSpacing(6)
        vbox.addWidget(self.lbl_detail)
        vbox.addSpacing(2)
        vbox.addWidget(self.lbl_eta)
        vbox.addSpacing(14)
        parent.addWidget(body)

    def _build_log(self, parent):
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setStyleSheet(
            f"background:{Colors.BG_SURFACE};color:{Colors.TEXT_PRIMARY};"
            "font-family:'JetBrains Mono','Fira Code',monospace;font-size:10px;"
            "border:none;padding:8px;"
        )
        parent.addWidget(self.log_box)

    # ── UI helpers ────────────────────────────────────────────────────────────

    def _set_phase(self, phase):
        self._phase = phase
        self.lbl_phase.setText(phase)
        color = _PHASE_COLOR.get(phase, Colors.TEXT_PRIMARY)
        self.lbl_phase.setStyleSheet(
            f"color:{color};font-size:28px;font-weight:700;"
        )

    def _set_detail(self, text):
        self.lbl_detail.setText(text)

    def _set_eta(self, text):
        self.lbl_eta.setText(text)

    def _set_progress(self, value, *, spin=False, color=None):
        if spin:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(max(0, min(100, value)))
        style = Styles.get_progress_bar_style(color) if color else Styles.get_progress_bar_style()
        self.progress.setStyleSheet(style)

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_box.append(f"{ts}  {msg}")
        log.info(msg)

    # ── Idle polling ─────────────────────────────────────────────────────────

    def _idle_tick(self):
        if self._phase not in (P_IDLE, P_DONE, P_FAILED):
            return
        serials = _edl_serials()
        n = len(serials)
        if n:
            self._set_detail(f"{n} device{'s' if n != 1 else ''} in EDL — ready")
            self.btn_start.setEnabled(True)
        else:
            self._set_detail("Waiting for EDL devices…")
            self.btn_start.setEnabled(False)

    # ── Run control ───────────────────────────────────────────────────────────

    def _start(self):
        serials = _edl_serials()
        if not serials:
            return
        self._device_count = len(serials)
        self._idle_timer.stop()
        self.btn_start.setEnabled(False)
        self.btn_start.setText("Running…")
        self.btn_stop.setEnabled(True)
        self._cycle_t0 = time.monotonic()
        self._log(f"Run started — {self._device_count} device(s) in EDL")
        self._flash_stage(serials)

    def _stop(self):
        self._log("Stopped by operator")
        for p in self._processes:
            if p.state() != QProcess.ProcessState.NotRunning:
                p.kill()
        self._processes.clear()
        self._set_phase(P_FAILED)
        self._set_progress(0, color=Colors.ERROR)
        self._set_eta("")
        self._set_detail("Stopped by operator")
        self._reset_to_idle()

    def _set_failed(self, reason):
        for p in self._processes:
            if p.state() != QProcess.ProcessState.NotRunning:
                p.kill()
        self._processes.clear()
        self._set_phase(P_FAILED)
        self._set_progress(0, color=Colors.ERROR)
        self._set_eta("")
        self._set_detail(reason)
        self._log(f"FAILED: {reason}")
        self._reset_to_idle()

    def _reset_to_idle(self):
        self.btn_stop.setEnabled(False)
        self.btn_start.setEnabled(True)
        self.btn_start.setText("Start")
        self._idle_timer.start(SCAN_INTERVAL_MS)

    # ── Flash stage ───────────────────────────────────────────────────────────

    def _flash_stage(self, serials):
        fw_path = self.debug_fw

        prog, raw, patch = FlashManager.find_firmware_files(fw_path)
        if not (prog and raw and patch):
            self._set_failed(f"Debug firmware not found in: {fw_path!r}")
            return

        wdir = FlashManager.get_working_directory(raw)
        self._ops, self._total_bytes = _scan_flash_ops(raw, wdir)
        self._stage_t0 = time.monotonic()
        log.info("Debug flash: %d ops, %.0f MB total",
                 len(self._ops), self._total_bytes / 1e6)

        n = len(serials)
        self._set_phase(P_FLASH)
        self._set_progress(0)
        self._set_detail(f"Flashing {n} device(s)…")
        self._log(f"Flashing {n} device(s) with debug firmware")

        self._done_count   = 0
        self._failed_count = 0
        self._processes    = []
        self._dev_progress = {
            i: {"serial": serials[i], "bytes_done": 0, "op_cursor": 0, "cur_pct": 0.0}
            for i in range(n)
        }

        for idx, serial in enumerate(serials):
            if idx == 0:
                self._launch_one(serial, idx, n, prog, raw, patch, wdir)
            else:
                QTimer.singleShot(
                    idx * 3000,
                    lambda s=serial, i=idx, t=n, p=prog, r=raw, pa=patch, w=wdir:
                        self._launch_one(s, i, t, p, r, pa, w),
                )

    def _launch_one(self, serial, idx, total, prog, raw, patch, wdir):
        proc = QProcess()
        self._processes.append(proc)

        sock_name = f"{QDL_PROGRESS_SOCK_PREFIX}debug-{idx}"
        QLocalServer.removeServer(sock_name)
        ps = QLocalServer()
        ps.listen(sock_name)

        def on_new_conn():
            sock = ps.nextPendingConnection()
            if sock:
                sock.readyRead.connect(lambda: self._on_progress(sock, idx))

        def on_done(code, _status=None):
            ps.close()
            QLocalServer.removeServer(sock_name)
            self._on_flash_done(code, serial, total, idx)

        ps.newConnection.connect(on_new_conn)
        proc.finished.connect(on_done)
        proc.readyReadStandardOutput.connect(lambda: proc.readAllStandardOutput())

        args = FlashManager.build_flash_command(
            serial, prog, raw, patch,
            progress_socket=ps.fullServerName(),
            allow_fusing=True,
        )
        proc.setWorkingDirectory(wdir)
        proc.start(args[0], args[1:])
        log.info("Debug flash: qdl started for serial=%s", serial)

    _FLASHED_RE = re.compile(r'^flashed "(.+?)" successfully')

    def _on_progress(self, sock, dev_idx):
        data = bytes(sock.readAll()).decode(errors="replace")
        for line in data.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            event   = msg.get("event")
            message = msg.get("message", "").strip()

            if event == "info":
                self._log(f"  [qdl] {message}")
                m = self._FLASHED_RE.match(message)
                if m and dev_idx in self._dev_progress:
                    label = m.group(1)
                    dev   = self._dev_progress[dev_idx]
                    cursor = dev["op_cursor"]
                    while cursor < len(self._ops) and self._ops[cursor][0] != label:
                        cursor += 1
                    if cursor < len(self._ops):
                        dev["bytes_done"] += self._ops[cursor][1]
                        dev["op_cursor"]   = cursor + 1
                    dev["cur_pct"] = 0.0
                    self._update_overall_progress()
            elif event == "error":
                self._log(f"  [qdl ERR] {message}")
            elif event == "progress" and dev_idx in self._dev_progress:
                dev = self._dev_progress[dev_idx]
                dev["cur_pct"] = min(float(msg.get("percent", 0.0)), 100.0)
                self._update_overall_progress()

    def _update_overall_progress(self):
        if not self._total_bytes or not self._dev_progress:
            return

        def _live_bytes(dev):
            done   = dev["bytes_done"]
            cursor = dev["op_cursor"]
            if cursor < len(self._ops):
                done += self._ops[cursor][1] * dev["cur_pct"] / 100.0
            return done

        def _fmt_mb(b):
            return f"{b / 1e6:.0f} MB" if b < 1e9 else f"{b / 1e9:.2f} GB"

        def _fmt_eta(sec):
            sec = int(sec)
            if sec < 60:
                return f"ETA {sec}s"
            m, s = divmod(sec, 60)
            return f"ETA {m}m {s:02d}s"

        n        = len(self._dev_progress)
        avg_live = sum(_live_bytes(d) for d in self._dev_progress.values()) / n
        pct      = int(avg_live / self._total_bytes * 100)

        elapsed = time.monotonic() - self._stage_t0
        if elapsed >= 2.0 and avg_live > 0:
            rate        = avg_live / elapsed
            remaining   = self._total_bytes - avg_live
            eta_text    = _fmt_eta(remaining / rate) if remaining > 0 else ""
        else:
            eta_text = ""

        total_fmt = _fmt_mb(self._total_bytes)
        parts = []
        for d in self._dev_progress.values():
            if d.get("failed"):
                parts.append(f"{d['serial']}: FAILED")
            else:
                parts.append(f"{d['serial']}: {_fmt_mb(_live_bytes(d))}/{total_fmt}")
        self._set_detail("  |  ".join(parts))
        self._set_eta(eta_text)
        self._set_progress(min(pct, 99))

    def _on_flash_done(self, code, serial, total, idx):
        if idx in self._dev_progress:
            self._dev_progress[idx]["bytes_done"] = self._total_bytes
            if code != 0:
                self._dev_progress[idx]["failed"] = True
        self._update_overall_progress()

        self._done_count += 1
        if code != 0:
            self._failed_count += 1
            self._log(f"  ✗ FAILED  serial={serial}")
        else:
            self._log(f"  ✓ OK  serial={serial}")

        if self._done_count < total:
            return

        if self._failed_count:
            self._set_failed(
                f"{self._failed_count}/{total} device(s) failed"
            )
        else:
            self._enter_done()

    # ── Done ─────────────────────────────────────────────────────────────────

    def _enter_done(self):
        self._set_phase(P_DONE)
        self._set_progress(100, color=Colors.SUCCESS)
        self._set_eta("")
        self._set_detail(f"All {self._device_count} device(s) complete")
        elapsed = time.monotonic() - self._cycle_t0
        self._log(f"Run complete — {self._device_count} device(s) DONE in {_fmt_elapsed(elapsed)}")
        self._reset_to_idle()
        self._show_done_dialog(elapsed)

    def _show_done_dialog(self, elapsed_sec: float):
        m, s = divmod(int(elapsed_sec), 60)
        time_str = f"{m}m {s:02d}s" if m else f"{s}s"

        dlg = QDialog(self)
        dlg.setWindowTitle("Flash Complete")
        dlg.setModal(True)
        dlg.setMinimumWidth(340)
        dlg.setStyleSheet(
            f"background:{Colors.BG_SURFACE};"
            f"color:{Colors.TEXT_PRIMARY};"
        )

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(16)

        icon = QLabel("✓")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(f"color:{Colors.SUCCESS};font-size:48px;font-weight:700;")

        title = QLabel(f"{self._device_count} device{'s' if self._device_count != 1 else ''} flashed successfully")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        title.setStyleSheet(f"color:{Colors.WHITE};font-size:15px;font-weight:700;")

        time_lbl = QLabel(f"Total time: {time_str}")
        time_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        time_lbl.setStyleSheet(f"color:{Colors.TEXT_SECONDARY};font-size:13px;")

        btn = QPushButton("Start New Cycle")
        btn.setStyleSheet(Styles.get_action_button_style(Colors.SUCCESS))
        btn.setFixedHeight(38)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(dlg.accept)

        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addWidget(time_lbl)
        layout.addSpacing(8)
        layout.addWidget(btn)

        dlg.exec()
        self.log_box.clear()
        self._set_phase(P_IDLE)
        self._set_progress(0)
        self._set_eta("")
        self._set_detail("Waiting for EDL devices…")


def main():
    import sys
    if "--env" in sys.argv:
        print(f"QDL_BIN              = {QDL_BIN}")
        print(f"PROD_DEBUG_FW_PATH   = {os.getenv(PROD_DEBUG_FW_PATH_ENV) or '(not set)'}")
        return

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    sh  = logging.StreamHandler()
    sh.setFormatter(fmt)
    logging.basicConfig(level=logging.DEBUG, handlers=[sh])

    app = QApplication(sys.argv)
    win = DebugFlashStation()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
