"""Shared base class for flash station windows.

Provides reusable building blocks used by both FlashStation (app.py) and
FactoryStation (factory_app.py):
  - Scan timer setup
  - QProcess flash runner with output/progress parsing
  - QProcess build_id check
  - Progress bar and log label widget factories
"""
from __future__ import annotations

import re
from typing import Callable, Optional

from PyQt6.QtCore import QTimer, QProcess
from PyQt6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QProgressBar, QLabel

from config import SCAN_INTERVAL_MS
from gui.styles import Styles


class BaseFlashStation(QMainWindow):
    """Base class with shared flash station utilities."""

    # ── Scan timer ────────────────────────────────────────────────────────────

    def _setup_scanning(self) -> None:
        """Wire up the periodic scan timer. Subclass must implement _scan()."""
        self.timer = QTimer()
        self.timer.timeout.connect(self._scan)
        self.timer.start(SCAN_INTERVAL_MS)

    def _scan(self) -> None:
        raise NotImplementedError

    # ── Widget factories ──────────────────────────────────────────────────────

    @staticmethod
    def _make_progress_widget() -> tuple[QWidget, QProgressBar]:
        """Return (container_widget, progress_bar) ready to embed in a table cell."""
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
        return pw, progress

    @staticmethod
    def _make_log_label() -> QLabel:
        """Return a styled single-line log label for a table cell."""
        lbl = QLabel()
        lbl.setStyleSheet(Styles.get_log_box_style())
        lbl.setContentsMargins(6, 0, 6, 0)
        return lbl

    # ── QProcess runners ──────────────────────────────────────────────────────

    def _launch_flash_process(
        self,
        args: list[str],
        cwd: str,
        on_log: Callable[[str], None],
        on_progress: Callable[[int], None],
        on_done: Callable[[int], None],
    ) -> QProcess:
        """Start a QProcess for a flash command. Returns the process.

        Args:
            args:        Full command + arguments list.
            cwd:         Working directory for the process.
            on_log:      Called with each non-empty output line.
            on_progress: Called with a 0-100 integer whenever a "X.X%" is found.
            on_done:     Called with the exit code when the process finishes.
        """
        process = QProcess()
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)

        def _handle_output() -> None:
            data = process.readAllStandardOutput().data().decode()
            for line in data.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                on_log(stripped)
                m = re.search(r"(\d+\.\d+)%", stripped)
                if m:
                    on_progress(min(int(float(m.group(1))), 100))

        process.readyReadStandardOutput.connect(_handle_output)
        process.finished.connect(lambda code, _: on_done(code))
        process.setWorkingDirectory(cwd)
        process.start(args[0], args[1:])
        return process

    def _launch_build_id_check(
        self,
        transport_id: str,
        on_result: Callable[[str], None],
    ) -> QProcess:
        """Start an async adb getprop for ro.build.id. Returns the process.

        Args:
            transport_id: ADB transport ID string.
            on_result:    Called with the build_id string (empty if ADB not ready).
        """
        proc = QProcess()
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.finished.connect(
            lambda _code, _status: on_result(
                proc.readAllStandardOutput().data().decode().strip()
            )
        )
        proc.start("adb", ["-t", transport_id, "shell", "getprop", "ro.build.id"])
        return proc
