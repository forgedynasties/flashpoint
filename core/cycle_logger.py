"""Cycle logger — records USB/ADB snapshots and per-device events for a factory cycle."""
import subprocess
from datetime import datetime
from pathlib import Path


class CycleLogger:
    """Writes a timestamped .log file alongside the cycle report.

    Usage:
        log = CycleLogger(reports_dir, started)
        log.snapshot("start")           # capture lsusb + adb at cycle start
        log.event(serial, "FLASH 1/3")  # called from on_state_change / on_log
        log.snapshot("end")             # capture final USB/ADB state
        log.close(summary_text)         # flush and close
    """

    def __init__(self, reports_dir: str, started: datetime) -> None:
        Path(reports_dir).mkdir(parents=True, exist_ok=True)
        fname = f"cycle_{started.strftime('%Y%m%d_%H%M%S')}.log"
        self._path = Path(reports_dir) / fname
        self._f = open(self._path, "w", buffering=1)  # line-buffered
        self._write(f"cycle started : {started.isoformat()}\n\n")

    # ── Public API ────────────────────────────────────────────────────────────

    def snapshot(self, label: str = "") -> None:
        """Capture and log lsusb + adb devices output."""
        ts = self._ts()
        heading = f"=== snapshot{': ' + label if label else ''} @ {ts} ==="
        self._write(f"{heading}\n")

        self._write("-- lsusb --\n")
        try:
            self._write(
                subprocess.check_output(["lsusb"], stderr=subprocess.DEVNULL).decode()
            )
        except Exception as e:
            self._write(f"[lsusb error: {e}]\n")

        self._write("\n-- adb devices -l --\n")
        try:
            self._write(
                subprocess.check_output(
                    ["adb", "devices", "-l"], stderr=subprocess.DEVNULL
                ).decode()
            )
        except Exception as e:
            self._write(f"[adb error: {e}]\n")

        self._write("\n")

    def event(self, serial: str, text: str) -> None:
        """Log a single per-device event line."""
        self._write(f"[{self._ts()}] {serial}: {text}\n")

    def close(self, summary: str = "") -> None:
        """Optionally append a summary block, then close the file."""
        if summary:
            self._write(f"\n=== summary ===\n{summary}\n")
        try:
            self._f.close()
        except Exception:
            pass

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _ts() -> str:
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    def _write(self, text: str) -> None:
        try:
            self._f.write(text)
        except Exception:
            pass
