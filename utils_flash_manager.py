"""Firmware flashing utilities."""
import logging
import os
import subprocess

from config import QDL_BIN

log = logging.getLogger(__name__)


class FlashManager:
    """Handles firmware flashing operations."""
    
    @staticmethod
    def find_firmware_files(path):
        """Find required firmware files in directory.
        
        Returns:
            tuple: (prog_path, raw_path, patch_path) or (None, None, None) if incomplete
        """
        try:
            files = os.listdir(path)
            prog = next(f for f in files if "prog" in f and f.endswith(".elf"))
            raw = next(f for f in files if "rawprogram" in f and f.endswith(".xml"))
            patch = next(f for f in files if "patch" in f and f.endswith(".xml"))
            return (
                os.path.join(path, prog),
                os.path.join(path, raw),
                os.path.join(path, patch),
            )
        except:
            return None, None, None
    
    @staticmethod
    def validate_firmware_folder(path):
        """Check if directory contains valid firmware files."""
        try:
            files = os.listdir(path)
            has_elf = any(f.endswith(".elf") for f in files)
            has_raw = any("rawprogram" in f for f in files)
            return has_elf and has_raw
        except:
            return False
    
    @staticmethod
    def build_flash_command(serial, prog, raw, patch, progress_socket=None):
        """Build the QDL flash command.

        Args:
            serial: Device serial number
            prog: Path to prog file
            raw: Path to raw file
            patch: Path to patch file
            progress_socket: Optional Unix socket path for JSON progress events

        Returns:
            list: Command arguments for subprocess
        """
        cmd = [
            "sudo",
            QDL_BIN,
            "--json",
            "-S", serial,
            "-s", "emmc",
            os.path.basename(prog),
            os.path.basename(raw),
            os.path.basename(patch),
            "-u", "1048576",
        ]
        if progress_socket:
            cmd.extend(["--progress-socket", progress_socket])
            log.debug("Flash command includes progress socket: %s", progress_socket)
        return cmd
    
    @staticmethod
    def get_working_directory(raw_path):
        """Get working directory for flash operation."""
        return os.path.dirname(raw_path)


class RebootManager:
    """Handles device rebooting operations."""
    
    @staticmethod
    def reboot_to_edl(transport_id):
        """Reboot device to EDL mode via ADB.
        
        Args:
            transport_id: ADB transport ID
        """
        try:
            subprocess.Popen(["adb", "-t", transport_id, "reboot", "edl"])
        except:
            pass
