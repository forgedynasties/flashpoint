"""Device model — represents a single connected Qualcomm device."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Device:
    """A connected device, identified by its hardware serial number.

    Attributes:
        serial:       Hardware serial (used as QDL -S arg and ADB device serial).
        mode:         Current mode: "edl" | "debug" | "user".
        usb_path:     Sysfs USB path, e.g. "3-1". May be None.
        transport_id: ADB transport ID string. None when device has no ADB.
        build_id:     ro.build.id from ADB, if known. None otherwise.
    """

    serial: str
    mode: str
    usb_path: Optional[str] = None
    transport_id: Optional[str] = None
    build_id: Optional[str] = None

    # ── Convenience properties ────────────────────────────────────────────────

    @property
    def is_edl(self) -> bool:
        return self.mode == "edl"

    @property
    def has_adb(self) -> bool:
        return self.transport_id is not None

    # ── ADB operations ────────────────────────────────────────────────────────

    def adb(self, *args: str, timeout: Optional[float] = None) -> subprocess.CompletedProcess:
        """Run an adb command targeting this device by transport ID.

        Raises:
            RuntimeError: if device has no ADB transport.
        """
        if not self.transport_id:
            raise RuntimeError(f"Device {self.serial} has no ADB transport")
        return subprocess.run(
            ["adb", "-t", self.transport_id, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def refresh_build_id(self) -> str:
        """Fetch ro.build.id via ADB and update self.build_id. Returns the value."""
        try:
            result = self.adb("shell", "getprop", "ro.build.id", timeout=3)
            self.build_id = result.stdout.strip() or None
        except Exception:
            self.build_id = None
        return self.build_id or ""

    def reboot_to_edl(self) -> None:
        """Send 'adb reboot edl' to this device (fire-and-forget)."""
        if not self.transport_id:
            raise RuntimeError(f"Device {self.serial} has no ADB transport")
        subprocess.Popen(["adb", "-t", self.transport_id, "reboot", "edl"])

    # ── Flashing ──────────────────────────────────────────────────────────────

    def flash_command(self, fw_path: str) -> tuple[list[str], str]:
        """Return (args, cwd) needed to flash this device with firmware at fw_path.

        The caller is responsible for actually running the process (subprocess or
        QProcess). This keeps Device free of I/O concerns.

        Raises:
            FileNotFoundError: if firmware files are missing/incomplete.
        """
        from qdl_wrapper import FlashManager

        prog, raw, patch = FlashManager.find_firmware_files(fw_path)
        if not (prog and raw and patch):
            raise FileNotFoundError(f"Incomplete firmware in {fw_path!r}")
        args = FlashManager.build_flash_command(self.serial, prog, raw, patch)
        cwd = FlashManager.get_working_directory(raw)
        return args, cwd

    def __repr__(self) -> str:
        tid = f" tid={self.transport_id}" if self.transport_id else ""
        return f"Device({self.serial!r}, mode={self.mode!r}{tid})"
