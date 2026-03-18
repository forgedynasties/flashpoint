"""Count-based Factory Flash Station.

Tracks devices by count only — no USB-path or serial mapping across stages.

Pipeline:
  1. Get serial list from qdl list → flash all in parallel
  2. Poll `adb devices` until count == N and all have the expected build ID
  3. `adb reboot edl` on all transport IDs
  4. Poll `qdl list` until count >= N (3 s initial delay for USB stability)
  5. Flash all again
  6. Done
"""
import json
import logging
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import datetime

from flash_timing import FlashTimingLog

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
    QDL_BIN, QDL_LIST_SOCKET, QDL_PROGRESS_SOCK_PREFIX,
)
from styles import Styles, Colors
from utils_device_manager import DeviceScanner
from utils_flash_manager import FlashManager, RebootManager

log = logging.getLogger(__name__)

EDL_RETURN_TIMEOUT_MS = 60_000   # 60 s for devices to return to EDL after reboot

def _parse_flash_tasks(raw_xml_path):
    """Return ordered list of task labels for actual flash ops in rawprogram.xml.

    Only <program> tags with a non-empty filename are executed by qdl.
    The label attribute is what qdl reports as "task" in progress events.
    """
    try:
        tree = ET.parse(raw_xml_path)
        tasks = []
        for p in tree.findall(".//program"):
            fn = (p.get("filename") or "").strip()
            if fn:
                label = (p.get("label") or p.get("LABEL") or "").strip() or fn
                tasks.append(label)
        return tasks if tasks else ["unknown"]
    except Exception as exc:
        log.warning("Could not parse flash tasks in %s: %s", raw_xml_path, exc)
        return ["unknown"]


def _fmt_eta(sec: float) -> str:
    if sec <= 0:
        return "ETA: finishing…"
    m, s = divmod(int(sec), 60)
    if m >= 60:
        h, m2 = divmod(m, 60)
        return f"ETA: {h}h {m2}m"
    if m:
        return f"ETA: {m}m {s:02d}s"
    return f"ETA: {s}s"


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
    """Return list of QDL serials visible on the list-server right now."""
    device_list = DeviceScanner._query_list_socket()
    if not device_list:
        return []
    return [d.get("serial", "").strip() for d in device_list
            if d.get("serial", "").strip()]


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
        self._phase         = P_IDLE
        self._device_count  = 0       # locked in when Start is pressed
        self._processes     = []      # active QProcess instances this stage
        self._done_count    = 0       # flash completions this stage
        self._failed_count  = 0
        self._total_ops          = 1    # flash ops per firmware (from rawprogram.xml)
        self._flash_tasks        = []   # task labels from rawprogram.xml (for op count)
        self._dev_progress       = {}   # idx → {completed, pct, task}
        self._stage_t0           = 0.0  # monotonic time when flash stage started
        self._cycle_t0           = 0.0  # monotonic time when Start was pressed
        self._stage_key          = ""   # "factory" or "prod"
        self._stage_expected_total = 0.0  # avg total duration from timing log
        self._poll_timer         = None
        self._timeout_timer      = None
        self._progress_timer     = None
        self._timing_log         = FlashTimingLog()

        self._setup_ui()
        self._start_list_server()
        self._idle_timer = QTimer()
        self._idle_timer.timeout.connect(self._idle_tick)
        self._idle_timer.start(SCAN_INTERVAL_MS)

    # ── List-server ──────────────────────────────────────────────────────────

    def _start_list_server(self):
        try:
            self._ls_proc = subprocess.Popen(
                ["sudo", QDL_BIN, "list-server", "--socket", QDL_LIST_SOCKET],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            log.info("qdl list-server started (pid=%d)", self._ls_proc.pid)
        except Exception as exc:
            log.warning("Could not start qdl list-server: %s", exc)
            self._ls_proc = None

    def closeEvent(self, event):
        if getattr(self, "_ls_proc", None):
            self._ls_proc.terminate()
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

        self.lbl_eta = QLabel("")
        self.lbl_eta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_eta.setStyleSheet(
            f"color:{Colors.WHITE};font-size:16px;font-weight:700;"
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

    def _set_progress(self, value, total=100, *, spin=False, color=None):
        if spin:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, total)
            self.progress.setValue(value)
        style = (Styles.get_progress_bar_style(color) if color
                 else Styles.get_progress_bar_style())
        self.progress.setStyleSheet(style)

    def _set_eta(self, text):
        self.lbl_eta.setText(text)

    def _recalc_progress(self):
        """Update progress bar and ETA. Time-based when history exists, else op-based."""
        elapsed = time.monotonic() - self._stage_t0

        if self._stage_expected_total > 0:
            # Time-based: linear by definition
            pct = min(elapsed / self._stage_expected_total * 100.0, 99.0)
            self._set_progress(int(pct))
            eta_sec = max(self._stage_expected_total - elapsed, 0.0)
            self._set_eta(_fmt_eta(eta_sec))
        else:
            # First run — no timing data yet; fall back to uniform per-op progress
            n_devs = len(self._dev_progress)
            total_work = self._total_ops * n_devs
            if total_work > 0:
                done_work = sum(
                    d["completed"] + d["pct"] / 100.0
                    for d in self._dev_progress.values()
                )
                pct = min(int(done_work / total_work * 100), 99)
                self._set_progress(pct)
            if elapsed > 3.0:
                self._set_eta("ETA: no data yet — will estimate after first run")

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_box.append(f"{ts}  {msg}")
        log.info(msg)

    def _stop_phase_timers(self):
        for attr in ("_poll_timer", "_timeout_timer", "_progress_timer"):
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
        self._set_progress(0)
        self._set_eta("")
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
        self._set_detail("Stopped by operator")
        self._set_progress(0, color=Colors.ERROR)
        self._reset_to_idle()

    def _set_failed(self, reason):
        self._stop_phase_timers()
        for p in self._processes:
            if p.state() != QProcess.ProcessState.NotRunning:
                p.kill()
        self._processes.clear()
        self._timing_log.save()
        self._set_phase(P_FAILED)
        self._set_detail(reason)
        self._set_eta("")
        self._set_progress(0, color=Colors.ERROR)
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

        n = len(serials)
        self._set_phase(phase)
        self._set_progress(0, n)
        self._set_detail(f"0 / {n} complete")
        self._log(f"Stage {stage}: flashing {n} device(s)")

        self._done_count    = 0
        self._failed_count  = 0
        self._flash_tasks   = _parse_flash_tasks(raw)
        self._total_ops     = len(self._flash_tasks)
        self._stage_key     = "factory" if stage == 1 else "prod"
        self._stage_expected_total = self._timing_log.avg_total(self._stage_key)
        self._stage_t0      = time.monotonic()
        self._dev_progress  = {
            i: {"completed": 0, "pct": 0.0, "task": ""}
            for i in range(n)
        }
        self._progress_timer = QTimer()
        self._progress_timer.timeout.connect(self._recalc_progress)
        self._progress_timer.start(500)
        self._processes    = []
        wdir = FlashManager.get_working_directory(raw)

        for idx, serial in enumerate(serials):
            self._launch_one(serial, stage, idx, n, prog, raw, patch, wdir)

    def _launch_one(self, serial, stage, idx, total, prog, raw, patch, wdir):
        proc = QProcess()
        self._processes.append(proc)

        sock_name = f"{QDL_PROGRESS_SOCK_PREFIX}f{stage}-{idx}"
        QLocalServer.removeServer(sock_name)
        ps = QLocalServer()
        ps.listen(sock_name)
        sock_path = ps.fullServerName()

        def on_new_conn():
            sock = ps.nextPendingConnection()
            if sock:
                sock.readyRead.connect(
                    lambda: self._on_progress(sock, idx, total)
                )

        def on_done(code, _status=None):
            ps.close()
            QLocalServer.removeServer(sock_name)
            self._on_flash_done(code, stage, serial, total, idx)

        ps.newConnection.connect(on_new_conn)
        proc.finished.connect(on_done)
        proc.readyReadStandardOutput.connect(lambda: proc.readAllStandardOutput())

        args = FlashManager.build_flash_command(
            serial, prog, raw, patch,
            progress_socket=sock_path,
            allow_fusing=(stage == 3),
        )
        proc.setWorkingDirectory(wdir)
        proc.start(args[0], args[1:])
        log.info("Stage %d: qdl started for serial=%s", stage, serial)

    def _on_progress(self, sock, idx, total):
        data = bytes(sock.readAll()).decode(errors="replace")
        for line in data.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if msg.get("event") != "progress":
                    continue
                task = msg.get("task", "")
                pct  = min(float(msg["percent"]), 100.0)
                dev  = self._dev_progress[idx]

                # qdl emits one 0→100 sequence per flash operation (per program
                # entry).  Two cases signal that the previous op completed and a
                # new one started:
                #
                #  1. Task name changed  — different partition label.
                #  2. Same task name but percent reset to near-zero after being
                #     near-complete — sparse images split into multiple chunks
                #     that all share the same label (firehose.c:607).
                prev_pct  = dev["pct"]
                prev_task = dev["task"]
                new_op = (
                    (task != prev_task and prev_task and prev_pct >= 50.0) or
                    (task == prev_task and prev_task and pct <= 5.0 and prev_pct >= 95.0)
                )
                if new_op:
                    dev["completed"] += 1

                dev["task"] = task
                dev["pct"]  = pct

                self._recalc_progress()
            except (json.JSONDecodeError, KeyError, ZeroDivisionError):
                pass

    def _on_flash_done(self, code, stage, serial, total, idx):
        self._done_count += 1
        if code != 0:
            self._failed_count += 1
            self._log(f"  ✗ stage {stage} exit {code}  serial={serial}")
        else:
            self._log(f"  ✓ stage {stage} OK  serial={serial}")
            if idx in self._dev_progress:
                d = self._dev_progress[idx]
                d["completed"] = self._total_ops
                d["pct"] = 100.0
        self._set_detail(f"{self._done_count} / {total} complete")
        self._recalc_progress()

        if self._done_count < total:
            return  # still waiting for other devices

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
        self._timing_log.record_total(self._stage_key, time.monotonic() - self._stage_t0)
        self._timing_log.save()
        if self._progress_timer:
            self._progress_timer.stop()
            self._progress_timer = None
        self._set_phase(P_BOOTING)
        self._set_progress(0, spin=True)
        self._set_eta("")
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
        self._timing_log.record_total(self._stage_key, time.monotonic() - self._stage_t0)
        self._timing_log.save()
        self._set_phase(P_DONE)
        self._set_progress(100, color=Colors.SUCCESS)
        self._set_eta("")
        self._set_detail(f"All {self._device_count} device(s) complete")
        elapsed = time.monotonic() - self._cycle_t0
        self._log(f"Run complete — {self._device_count} device(s) DONE in {_fmt_eta(elapsed).replace('ETA: ', '')}")
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
        # Reset view immediately after dialog is dismissed
        self.log_box.clear()
        self._set_phase(P_IDLE)
        self._set_progress(0)
        self._set_detail("Waiting for EDL devices…")
        self._set_eta("")


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
