"""Count-based Factory Flash Station.

Pipeline:
  1. Poll qdl list → flash all in parallel
  2. Poll `adb devices` until count == N
  3. `adb reboot edl` on all transport IDs
  4. Poll `qdl list` until count >= N
  5. Flash all again
  6. Done
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
    FACTORY_FW_PATH_ENV, PROD_DEBUG_FW_PATH_ENV,
    BOOT_TIMEOUT_SEC_ENV, DEFAULT_BOOT_TIMEOUT_SEC,
    EXPECTED_BUILD_ID,
    QDL_BIN, QDL_PROGRESS_SOCK_PREFIX,
)
from styles import Styles, Colors
from utils_device_manager import DeviceScanner
from utils_flash_manager import FlashManager, RebootManager

log = logging.getLogger(__name__)

EDL_RETURN_TIMEOUT_MS = 60_000   # 60 s for devices to return to EDL after reboot


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
    """Return list of byte sizes for each write op qdl will perform on this sparse image.

    RAW and FILL chunks each become one write op. DONT_CARE are skipped.
    Returns None if the file is not a valid sparse image.
    """
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
    """Parse rawprogram.xml and return the exact ordered list of (label, bytes) that qdl will execute.

    Sparse images are expanded into their individual RAW/FILL chunk ops.
    Returns (ops_list, total_bytes). ops_list is [(label, bytes), ...].
    """
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

            # Non-sparse (or sparse parse failed): one op, size from XML
            if num_sectors:
                ops.append((label, num_sectors * sector_size))
    except Exception as exc:
        log.warning("Could not scan flash ops: %s", exc)

    total_bytes = sum(b for _, b in ops)
    return ops, total_bytes


# ── Phase constants ──────────────────────────────────────────────────────────
P_IDLE    = "IDLE"
P_FLASH1  = "FLASH 1/3"
P_BOOTING = "BOOTING"
P_TO_EDL  = "TO EDL"
P_FLASH3  = "FLASH 3/3"
P_DONE    = "DONE"
P_FAILED  = "FAILED"

_PHASE_COLOR = {
    P_IDLE:    Colors.TEXT_SECONDARY,
    P_FLASH1:  Colors.WARNING,
    P_BOOTING: Colors.USER_MODE,
    P_TO_EDL:  Colors.EDL_MODE,
    P_FLASH3:  Colors.WARNING,
    P_DONE:    Colors.SUCCESS,
    P_FAILED:  Colors.ERROR,
}


# ── Count-only helpers ───────────────────────────────────────────────────────

def _edl_serials():
    """Return list of QDL serials by running `qdl list`.

    Output format: <vid>:<pid>\t<serial>  (one device per line, no header)
    Lines not matching that format (e.g. "No devices found") are ignored.
    """
    try:
        out = subprocess.check_output(
            ["sudo", QDL_BIN, "list"], stderr=subprocess.DEVNULL, timeout=5
        ).decode()
        serials = []
        for line in out.splitlines():
            parts = line.split()
            # Valid device line: parts[0] is "XXXX:XXXX" (vid:pid)
            if len(parts) >= 2 and ":" in parts[0]:
                serials.append(parts[1])
        return serials
    except Exception as exc:
        log.debug("qdl list: %s", exc)
        return []


def _adb_transport_ids():
    """Return list of all ADB transport IDs from `adb devices`."""
    try:
        out = subprocess.check_output(
            ["adb", "devices", "-l"], stderr=subprocess.DEVNULL
        ).decode()
        return re.findall(r'transport_id:(\d+)', out)
    except Exception as exc:
        log.debug("adb devices: %s", exc)
        return []


# ── Main window ──────────────────────────────────────────────────────────────

class CountFactoryStation(QMainWindow):
    """Count-based factory station — no per-device path or serial mapping."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Factory Flash Station")
        self.setMinimumSize(700, 500)
        self.setGeometry(100, 100, 860, 580)

        self.factory_fw = os.getenv(FACTORY_FW_PATH_ENV, "")
        self.prod_fw    = os.getenv(PROD_DEBUG_FW_PATH_ENV, "")
        self.boot_timeout_ms = int(
            os.getenv(BOOT_TIMEOUT_SEC_ENV, DEFAULT_BOOT_TIMEOUT_SEC)
        ) * 1000

        # Run state
        self._phase        = P_IDLE
        self._device_count = 0    # locked in when Start is pressed
        self._processes    = []   # active QProcess instances this stage
        self._done_count   = 0    # flash completions this stage
        self._failed_count = 0
        self._cycle_t0     = 0.0  # monotonic time when Start was pressed
        self._poll_timer   = None
        self._timeout_timer = None
        # Per-device byte-accurate progress (shared across all devices in a stage)
        self._ops          = []   # [(label, bytes)] ordered list for current stage
        self._total_bytes  = 0    # sum of all op bytes for current stage
        # Per-device progress state: idx → {op_idx, bytes_done, cur_pct, prev_pct, prev_task}
        self._dev_progress = {}

        self._setup_ui()

        log.info("=== Factory Flash Station startup ===")
        log.info("  QDL_BIN            = %s", QDL_BIN)
        log.info("  FACTORY_FW_PATH    = %s", self.factory_fw or "(not set)")
        log.info("  PROD_DEBUG_FW_PATH = %s", self.prod_fw or "(not set)")
        log.info("  BOOT_TIMEOUT_SEC   = %d", self.boot_timeout_ms // 1000)

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

        def fw_block(label, path):
            lbl = QLabel(label)
            lbl.setStyleSheet(
                f"color:{Colors.TEXT_SECONDARY};font-size:10px;"
                "font-weight:700;letter-spacing:.8px;"
            )
            val = QLabel(path or "NOT SET — check env var")
            val.setStyleSheet(
                f"color:{Colors.TEXT_PRIMARY if path else Colors.ERROR};"
                "font-size:11px;"
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

        vbox.addSpacing(18)
        vbox.addWidget(self.lbl_phase)
        vbox.addSpacing(14)
        vbox.addWidget(pw)
        vbox.addSpacing(6)
        vbox.addWidget(self.lbl_detail)
        vbox.addSpacing(18)
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

    def _stop_phase_timers(self):
        for attr in ("_poll_timer", "_timeout_timer"):
            t = getattr(self, attr, None)
            if t:
                t.stop()
                setattr(self, attr, None)

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
        self._flash_stage(serials, stage=1)

    def _stop(self):
        self._log("Stopped by operator")
        self._stop_phase_timers()
        for p in self._processes:
            if p.state() != QProcess.ProcessState.NotRunning:
                p.kill()
        self._processes.clear()
        self._set_phase(P_FAILED)
        self._set_progress(0, color=Colors.ERROR)
        self._set_detail("Stopped by operator")
        self._reset_to_idle()

    def _set_failed(self, reason):
        self._stop_phase_timers()
        for p in self._processes:
            if p.state() != QProcess.ProcessState.NotRunning:
                p.kill()
        self._processes.clear()
        self._set_phase(P_FAILED)
        self._set_progress(0, color=Colors.ERROR)
        self._set_detail(reason)
        self._log(f"FAILED: {reason}")
        self._reset_to_idle()

    def _reset_to_idle(self):
        self.btn_stop.setEnabled(False)
        self.btn_start.setEnabled(True)
        self.btn_start.setText("Start")
        # _phase stays as DONE/FAILED so operator sees it;
        # _idle_tick runs (it allows DONE/FAILED) and updates detail + Start btn
        self._idle_timer.start(SCAN_INTERVAL_MS)

    # ── Flash stage ───────────────────────────────────────────────────────────

    def _flash_stage(self, serials, stage: int):
        fw_path = self.factory_fw if stage == 1 else self.prod_fw
        phase   = P_FLASH1 if stage == 1 else P_FLASH3

        prog, raw, patch = FlashManager.find_firmware_files(fw_path)
        if not (prog and raw and patch):
            self._set_failed(f"Stage {stage} firmware not found in: {fw_path!r}")
            return

        wdir = FlashManager.get_working_directory(raw)
        self._ops, self._total_bytes = _scan_flash_ops(raw, wdir)
        log.info("Stage %d: %d ops, %d MB total",
                 stage, len(self._ops), self._total_bytes // 1_000_000)

        n = len(serials)
        self._set_phase(phase)
        self._set_progress(0)
        self._set_detail(f"Flashing {n} device(s)…")
        self._log(f"Stage {stage}: flashing {n} device(s)")

        self._done_count   = 0
        self._failed_count = 0
        self._processes    = []
        # Per-device progress state
        self._dev_progress = {
            i: {"op_idx": 0, "bytes_done": 0, "cur_pct": 0.0, "prev_pct": 0.0, "prev_task": ""}
            for i in range(n)
        }

        for idx, serial in enumerate(serials):
            self._launch_one(serial, stage, idx, n, prog, raw, patch, wdir)

    def _launch_one(self, serial, stage, idx, total, prog, raw, patch, wdir):
        proc = QProcess()
        self._processes.append(proc)

        sock_name = f"{QDL_PROGRESS_SOCK_PREFIX}f{stage}-{idx}"
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
            self._on_flash_done(code, stage, serial, total, idx)

        ps.newConnection.connect(on_new_conn)
        proc.finished.connect(on_done)
        proc.readyReadStandardOutput.connect(lambda: proc.readAllStandardOutput())

        args = FlashManager.build_flash_command(
            serial, prog, raw, patch,
            progress_socket=ps.fullServerName(),
            allow_fusing=(stage == 3),
        )
        proc.setWorkingDirectory(wdir)
        proc.start(args[0], args[1:])
        log.info("Stage %d: qdl started for serial=%s", stage, serial)

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
            event = msg.get("event")

            if event == "info":
                self._log(f"  [qdl] {msg.get('message', '').strip()}")
                continue
            if event == "error":
                self._log(f"  [qdl ERR] {msg.get('message', '').strip()}")
                continue
            if event != "progress":
                continue

            task = msg.get("task", "")
            pct  = min(float(msg.get("percent", 0)), 100.0)

            if dev_idx not in self._dev_progress or not self._ops:
                continue

            dev = self._dev_progress[dev_idx]
            op_idx     = dev["op_idx"]
            prev_pct   = dev["prev_pct"]
            prev_task  = dev["prev_task"]

            # Detect op boundary:
            #   1. Task label changed        → previous op finished
            #   2. Same label, pct regressed significantly → sparse chunk boundary
            op_done = (
                (prev_task and task != prev_task) or
                (prev_task and task == prev_task and pct < 10.0 and prev_pct > 80.0)
            )
            if op_done and op_idx < len(self._ops):
                dev["bytes_done"] += self._ops[op_idx][1]
                op_idx += 1
                dev["op_idx"] = op_idx

            dev["prev_task"] = task
            dev["prev_pct"]  = pct
            dev["cur_pct"]   = pct

            self._update_overall_progress()

    def _update_overall_progress(self):
        if not self._total_bytes or not self._dev_progress:
            return
        total_done = 0
        for dev in self._dev_progress.values():
            op_idx = dev["op_idx"]
            if op_idx < len(self._ops):
                total_done += dev["bytes_done"] + self._ops[op_idx][1] * dev["cur_pct"] / 100.0
            else:
                total_done += dev["bytes_done"]
        # Average across all devices
        avg_done = total_done / len(self._dev_progress)
        pct = int(avg_done / self._total_bytes * 100)
        self._set_progress(min(pct, 99))  # hold at 99 until fully done

    def _on_flash_done(self, code, stage, serial, total, idx):
        # Mark this device's progress as complete
        if idx in self._dev_progress:
            dev = self._dev_progress[idx]
            dev["bytes_done"] = self._total_bytes
            dev["op_idx"]     = len(self._ops)
            dev["cur_pct"]    = 100.0
        self._update_overall_progress()

        self._done_count += 1
        if code != 0:
            self._failed_count += 1
            self._log(f"  ✗ stage {stage} exit {code}  serial={serial}")
        else:
            self._log(f"  ✓ stage {stage} OK  serial={serial}")
        self._set_detail(f"{self._done_count} / {total} complete")

        if self._done_count < total:
            return

        if self._failed_count:
            self._set_failed(
                f"Stage {stage}: {self._failed_count}/{total} device(s) failed"
            )
        elif stage == 1:
            self._enter_booting()
        else:
            self._enter_done()

    # ── Boot detection ────────────────────────────────────────────────────────

    def _enter_booting(self):
        self._log(
            f"Stage 1 complete — waiting for {self._device_count} device(s) in ADB"
        )
        self._set_phase(P_BOOTING)
        self._set_progress(0, spin=True)
        self._set_detail(f"0 / {self._device_count} in ADB")

        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._check_adb)
        self._poll_timer.start(SCAN_INTERVAL_MS)

        self._timeout_timer = QTimer()
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._boot_timeout)
        self._timeout_timer.start(self.boot_timeout_ms)

    def _boot_timeout(self):
        n = len(_adb_transport_ids())
        self._set_failed(
            f"Boot timeout: only {n}/{self._device_count} device(s) returned to ADB"
        )

    def _check_adb(self):
        tids = _adb_transport_ids()
        self._set_detail(f"{len(tids)} / {self._device_count} in ADB")
        if len(tids) < self._device_count:
            return

        # Enough devices in ADB — stop the poll timer while doing build-ID checks
        # (each adb shell call blocks briefly; prevents timer re-entrancy)
        self._poll_timer.stop()
        self._log("Checking build IDs…")

        correct_tids = []
        for tid in tids:
            bid = DeviceScanner.get_build_id(tid)
            if bid == EXPECTED_BUILD_ID:
                correct_tids.append(tid)
            elif bid:
                self._log(f"  build mismatch transport={tid}: {bid!r}")

        if len(correct_tids) >= self._device_count:
            self._stop_phase_timers()
            self._log(
                f"All {self._device_count} device(s) have correct build — rebooting to EDL"
            )
            self._enter_rebooting(correct_tids[: self._device_count])
        else:
            self._set_detail(
                f"{len(tids)} in ADB — "
                f"{len(correct_tids)}/{self._device_count} correct build"
            )
            self._poll_timer.start(SCAN_INTERVAL_MS)

    # ── Reboot to EDL ─────────────────────────────────────────────────────────

    def _enter_rebooting(self, tids):
        self._set_phase(P_TO_EDL)
        self._set_progress(0, spin=True)
        self._set_detail(f"Rebooting {len(tids)} device(s) to EDL…")
        for tid in tids:
            RebootManager.reboot_to_edl(tid)
        # 3 s initial delay so devices fully disconnect before polling qdl list
        QTimer.singleShot(3000, self._start_edl_poll)

    def _start_edl_poll(self):
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._check_edl_count)
        self._poll_timer.start(SCAN_INTERVAL_MS)

        self._timeout_timer = QTimer()
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(
            lambda: self._set_failed("Timeout waiting for devices to return to EDL")
        )
        self._timeout_timer.start(EDL_RETURN_TIMEOUT_MS)

    def _check_edl_count(self):
        serials = _edl_serials()
        self._set_detail(f"{len(serials)} / {self._device_count} in EDL")
        if len(serials) >= self._device_count:
            self._stop_phase_timers()
            self._log(f"{len(serials)} device(s) in EDL — starting stage 3")
            self._flash_stage(serials[: self._device_count], stage=3)

    # ── Done ─────────────────────────────────────────────────────────────────

    def _enter_done(self):
        self._set_phase(P_DONE)
        self._set_progress(100, color=Colors.SUCCESS)
        self._set_detail(f"All {self._device_count} device(s) complete")
        elapsed = time.monotonic() - self._cycle_t0
        self._log(f"Run complete — {self._device_count} device(s) DONE in {_fmt_elapsed(elapsed)}")
        self._reset_to_idle()
        self._show_done_dialog(elapsed)

    def _show_done_dialog(self, elapsed_sec: float):
        m, s = divmod(int(elapsed_sec), 60)
        time_str = f"{m}m {s:02d}s" if m else f"{s}s"

        dlg = QDialog(self)
        dlg.setWindowTitle("Cycle Complete")
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
        self._set_detail("Waiting for EDL devices…")


def main():
    import sys
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    sh  = logging.StreamHandler()
    sh.setFormatter(fmt)
    logging.basicConfig(level=logging.DEBUG, handlers=[sh])

    app = QApplication(sys.argv)
    win = CountFactoryStation()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
