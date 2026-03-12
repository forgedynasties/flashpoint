"""Firmware flashing utilities."""
import os
import subprocess
from config import QDL_BIN


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
    def build_flash_command(serial, prog, raw, patch):
        """Build the QDL flash command.
        
        Args:
            serial: Device serial number
            prog: Path to prog file
            raw: Path to raw file  
            patch: Path to patch file
            
        Returns:
            list: Command arguments for subprocess
        """
        return [
            "sudo",
            QDL_BIN,
            "-S",
            serial,
            "-s",
            "emmc",
            os.path.basename(prog),
            os.path.basename(raw),
            os.path.basename(patch),
            "-u",
            "1048576",
        ]
    
    @staticmethod
    def get_working_directory(raw_path):
        """Get working directory for flash operation."""
        return os.path.dirname(raw_path)


