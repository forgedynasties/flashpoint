"""Device widget component - currently not used with table-based UI.

This module is kept for reference. The current UI uses QTableWidget
to display devices. This class can be refactored or removed in the future.
"""
import re
from PyQt6.QtCore import QProcess, Qt


class DeviceFlashWidget:
    """Legacy device widget - not used with current table-based UI."""
    
    def __init__(self, serial):
        """Initialize device widget (legacy).
        
        Args:
            serial: Device serial number
        """
        self.serial = serial
        self.is_flashing = False
        self.process = QProcess()
    
    def start_flash(self, prog, raw, patch):
        """Start flashing (legacy method).
        
        Args:
            prog: Path to prog file
            raw: Path to raw file
            patch: Path to patch file
        """
        pass
    
    def handle_output(self):
        """Handle flash output (legacy method)."""
        pass
    
    def handle_finished(self):
        """Handle flash completion (legacy method)."""
        pass

