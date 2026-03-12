"""Factory 3-stage flash pipeline — pure state machine, no I/O, no Qt.

The driver (GUI or CLI) is responsible for:
  - Calling tick() on a regular interval with fresh scan results.
  - Running flash processes and calling flash_done() when they finish.
  - Running build_id checks and calling build_id_result() when done.
  - Setting on_state_change / on_progress / on_log callbacks for UI updates.

Typical driver loop (CLI):

    pipeline = FactoryPipeline(devices, factory_fw, prod_fw)
    pipeline.on_log = lambda serial, text: print(f"[{serial}] {text}")
    pipeline.start()

    while not pipeline.is_complete:
        edl  = set(scan_edl())
        adb  = scan_adb()
        pipeline.tick(edl, adb)

        for serial, stage in pipeline.drain_flash_requests():
            exit_code = run_flash_subprocess(*pipeline.flash_command_for(serial, stage))
            pipeline.flash_done(serial, stage, exit_code)

        for serial in pipeline.drain_build_id_requests():
            build_id = get_build_id_subprocess(pipeline.device(serial).transport_id)
            pipeline.build_id_result(serial, build_id)

        time.sleep(SCAN_INTERVAL_SEC)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from core.device import Device

# ── Pipeline states ───────────────────────────────────────────────────────────

S_WAITING       = "WAITING"
S_SKIPPED       = "SKIPPED"
S_FLASH1        = "FLASH 1/3"
S_BOOTING       = "BOOTING"
S_REBOOTING_EDL = "TO EDL"
S_FLASH3        = "FLASH 3/3"
S_DONE          = "DONE"
S_FAILED        = "FAILED"
S_TIMEOUT       = "TIMEOUT"

TERMINAL = frozenset({S_DONE, S_FAILED, S_TIMEOUT, S_SKIPPED})


@dataclass
class _Job:
    """Internal per-device state for one pipeline run."""

    state: str = S_WAITING
    fail_reason: str = ""
    boot_deadline: Optional[float] = None  # time.monotonic() deadline


class FactoryPipeline:
    """Pure state machine for the 3-stage factory flash pipeline."""

    def __init__(
        self,
        devices: list[Device],
        factory_fw: str,
        prod_fw: str,
        boot_timeout_sec: int = 120,
    ) -> None:
        self.factory_fw = factory_fw
        self.prod_fw = prod_fw
        self.boot_timeout_sec = boot_timeout_sec

        self._devices: dict[str, Device] = {d.serial: d for d in devices}
        self._jobs: dict[str, _Job] = {d.serial: _Job() for d in devices}

        # Pending action queues — driver drains these each tick
        self._pending_flashes: list[tuple[str, int]] = []    # [(serial, stage)]
        self._pending_build_checks: list[str] = []           # [serial]

        # Callbacks — set by driver before calling start()
        self.on_state_change: Callable[[str, str, str], None] = lambda s, st, r: None
        self.on_progress: Callable[[str, int], None] = lambda s, p: None
        self.on_log: Callable[[str, str], None] = lambda s, t: None

    # ── Driver interface ──────────────────────────────────────────────────────

    def start(self) -> None:
        """Kick off the pipeline. Call once after setting callbacks."""
        for serial, job in self._jobs.items():
            dev = self._devices[serial]
            if dev.is_edl:
                self._set_state(serial, S_FLASH1)
                self._pending_flashes.append((serial, 1))
            else:
                self._set_state(serial, S_SKIPPED)

    def tick(self, edl_serials: set[str], adb_map: dict[str, str]) -> None:
        """Advance state machine based on current scan results.

        Call this periodically (e.g. every SCAN_INTERVAL_MS from a QTimer or
        from a sleep loop in the CLI).
        """
        now = time.monotonic()
        for serial, job in self._jobs.items():
            if job.state in TERMINAL:
                continue

            if job.state == S_BOOTING:
                # Boot timeout
                if job.boot_deadline and now > job.boot_deadline:
                    self._set_failed(serial, f"No boot within {self.boot_timeout_sec}s")
                    continue
                # ADB appeared — queue a build_id check (deduplicated)
                if serial in adb_map and serial not in self._pending_build_checks:
                    self._devices[serial].transport_id = adb_map[serial]
                    self._pending_build_checks.append(serial)

            elif job.state == S_REBOOTING_EDL:
                if serial in edl_serials:
                    self._set_state(serial, S_FLASH3)
                    self._pending_flashes.append((serial, 3))

    def flash_done(self, serial: str, stage: int, exit_code: int) -> None:
        """Notify the pipeline that a flash process has finished."""
        if serial not in self._jobs:
            return
        if exit_code == 0:
            if stage == 1:
                self._set_state(serial, S_BOOTING)
                self._jobs[serial].boot_deadline = (
                    time.monotonic() + self.boot_timeout_sec
                )
                self.on_log(serial, "Waiting for device to boot…")
            else:
                self._set_state(serial, S_DONE)
                self.on_log(serial, "Complete")
        else:
            self._set_failed(serial, f"Stage {stage} flash failed (exit {exit_code})")

    def build_id_result(self, serial: str, build_id: str) -> None:
        """Notify the pipeline of a completed build_id check.

        Passing an empty string means ADB wasn't ready yet — the pipeline will
        re-queue the check on the next tick().
        """
        if serial not in self._jobs:
            return
        if self._jobs[serial].state != S_BOOTING:
            return
        if not build_id:
            return  # ADB not ready yet — will retry next tick

        from config import EXPECTED_BUILD_ID

        if build_id == EXPECTED_BUILD_ID:
            self._devices[serial].reboot_to_edl()
            self._set_state(serial, S_REBOOTING_EDL)
            self.on_log(serial, "Rebooting to EDL…")
        else:
            self._set_failed(serial, f"Build ID mismatch: {build_id!r}")

    # ── Queue draining helpers ────────────────────────────────────────────────

    def drain_flash_requests(self) -> list[tuple[str, int]]:
        """Return and clear all pending flash requests as [(serial, stage)]."""
        items, self._pending_flashes = self._pending_flashes, []
        return items

    def drain_build_id_requests(self) -> list[str]:
        """Return and clear all pending build_id check requests as [serial]."""
        items, self._pending_build_checks = self._pending_build_checks, []
        return items

    # ── Queries ───────────────────────────────────────────────────────────────

    def device(self, serial: str) -> Device:
        return self._devices[serial]

    def state_of(self, serial: str) -> str:
        return self._jobs[serial].state

    def fail_reason_of(self, serial: str) -> str:
        return self._jobs[serial].fail_reason

    def flash_command_for(self, serial: str, stage: int) -> tuple[list[str], str]:
        """Return (args, cwd) for a flash stage."""
        fw = self.factory_fw if stage == 1 else self.prod_fw
        return self._devices[serial].flash_command(fw)

    @property
    def serials(self) -> list[str]:
        return list(self._jobs.keys())

    @property
    def is_complete(self) -> bool:
        return all(j.state in TERMINAL for j in self._jobs.values())

    def results(self) -> dict[str, tuple[str, str]]:
        """Return {serial: (state, fail_reason)} for report generation."""
        return {s: (j.state, j.fail_reason) for s, j in self._jobs.items()}

    # ── Internal ──────────────────────────────────────────────────────────────

    def _set_state(self, serial: str, state: str, reason: str = "") -> None:
        job = self._jobs[serial]
        job.state = state
        job.fail_reason = reason
        self.on_state_change(serial, state, reason)

    def _set_failed(self, serial: str, reason: str) -> None:
        self._set_state(serial, S_FAILED, reason)
