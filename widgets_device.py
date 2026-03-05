"""Device widget component for displaying and managing individual devices."""
import re
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QProgressBar, QPushButton
)
from PyQt6.QtCore import QTimer, QProcess, Qt
from PyQt6.QtGui import QFont

from styles import Styles, Colors
from config import EDL_REBOOT_TIMEOUT_MS


class DeviceFlashWidget(QWidget):
    """Widget representing a single flashable device."""
    
    def __init__(self, serial, remove_callback, reboot_callback):
        """Initialize device widget.
        
        Args:
            serial: Device serial number
            remove_callback: Callback function for removing device
            reboot_callback: Callback function for rebooting to EDL
        """
        super().__init__()
        self.serial = serial
        self.remove_callback = remove_callback
        self.reboot_callback = reboot_callback
        self.is_flashing = False
        
        self.setup_ui()
        self.setup_process()
    
    def setup_ui(self):
        """Set up the user interface."""
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(8, 8, 8, 8)
        self.layout.setSpacing(12)
        
        # Serial label
        self.label = QLabel(f"<b>{self.serial}</b>")
        self.label.setFixedWidth(150)
        font = self.label.font()
        font.setPointSize(10)
        self.label.setFont(font)
        
        # Status label
        self.status = QLabel("Ready")
        self.status.setFixedWidth(120)
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setStyleSheet(Styles.get_ready_status_style())
        
        # ADB tag
        self.adb_tag = QLabel("ADB ✓")
        self.adb_tag.setFixedWidth(70)
        self.adb_tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.adb_tag.setStyleSheet(Styles.get_adb_tag_style())
        self.adb_tag.hide()
        
        # Progress bar
        self.progress = QProgressBar()
        self.progress.setFixedWidth(150)
        self.progress.setValue(0)
        self.progress.setStyleSheet(Styles.get_progress_bar_style())
        
        # Log preview
        self.log_preview = QLabel("Waiting...")
        self.log_preview.setStyleSheet(Styles.get_log_preview_style())
        self.log_preview.setMinimumHeight(24)
        
        # Action buttons
        self.btn_edl = QPushButton("EDL")
        self.btn_edl.setFixedWidth(60)
        self.btn_edl.setStyleSheet(Styles.get_edl_button_style())
        self.btn_edl.hide()
        
        self.btn_flash = QPushButton("Flash")
        self.btn_flash.setFixedWidth(70)
        self.btn_flash.setStyleSheet(Styles.get_action_button_style(Colors.PRIMARY))
        
        self.btn_remove = QPushButton("✕")
        self.btn_remove.setFixedWidth(35)
        self.btn_remove.setFixedHeight(35)
        self.btn_remove.setStyleSheet(Styles.get_remove_button_style())
        
        # Add widgets to layout
        self.layout.addWidget(self.label)
        self.layout.addWidget(self.status)
        self.layout.addWidget(self.adb_tag)
        self.layout.addWidget(self.progress)
        self.layout.addWidget(self.log_preview, 1)
        self.layout.addWidget(self.btn_edl)
        self.layout.addWidget(self.btn_flash)
        self.layout.addWidget(self.btn_remove)
        
        # Connect signals
        self.btn_remove.clicked.connect(lambda: self.remove_callback(self.serial))
        self.btn_edl.clicked.connect(self.trigger_edl_reboot)
    
    def setup_process(self):
        """Set up the QProcess for flashing."""
        self.process = QProcess()
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.handle_output)
        self.process.finished.connect(self.handle_finished)
    
    def trigger_edl_reboot(self):
        """Trigger reboot to EDL mode."""
        self.btn_edl.setText("...")
        self.btn_edl.setEnabled(False)
        self.reboot_callback(self.serial)
        QTimer.singleShot(EDL_REBOOT_TIMEOUT_MS, lambda: self.restore_edl_button())
    
    def restore_edl_button(self):
        """Restore EDL button to normal state."""
        if self.btn_edl.isVisible():
            self.btn_edl.setText("EDL")
            self.btn_edl.setEnabled(True)
    
    def set_boot_mode(self, mode_type, has_adb=False):
        """Update device boot mode display.
        
        Args:
            mode_type: Boot mode string (e.g., "USER BOOTED", "DEBUG BOOTED")
            has_adb: Whether device has ADB available
        """
        if not self.is_flashing:
            self.status.setText(mode_type)
            
            if "USER" in mode_type:
                self.status.setStyleSheet(Styles.get_user_mode_status_style())
            else:
                self.status.setStyleSheet(Styles.get_edl_mode_status_style())
            
            self.btn_flash.setEnabled(False)
            self.btn_edl.show()
            self.btn_edl.setEnabled(has_adb)
            self.adb_tag.setVisible(has_adb)
    
    def reset_to_ready(self):
        """Reset device to ready state."""
        if not self.is_flashing:
            self.status.setText("Ready")
            self.status.setStyleSheet(Styles.get_ready_status_style())
            self.btn_flash.setEnabled(True)
            self.btn_edl.hide()
            self.adb_tag.hide()
            self.progress.setValue(0)
            self.log_preview.setText("Waiting...")
    
    def start_flash(self, prog, raw, patch):
        """Start firmware flash operation.
        
        Args:
            prog: Path to prog file
            raw: Path to raw file
            patch: Path to patch file
        """
        if self.is_flashing:
            return
        
        self.is_flashing = True
        self.btn_flash.setEnabled(False)
        self.btn_edl.setEnabled(False)
        self.btn_remove.setEnabled(False)
        self.progress.setValue(0)
        
        self.status.setText("FLASHING")
        self.status.setStyleSheet(Styles.get_flashing_status_style())
        
        # Build and start flash process
        from utils_flash_manager import FlashManager
        
        firmware_dir = FlashManager.get_working_directory(raw)
        args = FlashManager.build_flash_command(self.serial, prog, raw, patch)
        
        self.process.setWorkingDirectory(firmware_dir)
        self.process.start(args[0], args[1:])
    
    def handle_output(self):
        """Handle output from flashing process."""
        data = self.process.readAllStandardOutput().data().decode()
        for line in data.splitlines():
            stripped = line.strip()
            self.log_preview.setText(stripped[-60:] if len(stripped) > 60 else stripped)
            
            # Extract progress percentage
            match = re.search(r"(\d+\.\d+)%", line)
            if match:
                self.progress.setValue(int(float(match.group(1))))
    
    def handle_finished(self):
        """Handle completion of flash process."""
        self.is_flashing = False
        self.btn_remove.setEnabled(True)
        self.btn_flash.setEnabled(True)
        
        if self.process.exitCode() == 0:
            self.status.setText("SUCCESS ✓")
            self.status.setStyleSheet(Styles.get_success_status_style())
            self.progress.setValue(100)
        else:
            self.status.setText("FAILED ✗")
            self.status.setStyleSheet(Styles.get_failed_status_style())
