"""Device widget component for displaying and managing individual devices."""
import re
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QProgressBar, QPushButton
)
from PyQt6.QtCore import QTimer, QProcess, Qt, QSize
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
        
        self.setStyleSheet(Styles.get_device_row_style())
        self.setup_ui()
        self.setup_process()
    
    def setup_ui(self):
        """Set up the user interface."""
        self.setMinimumHeight(90)
        
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(12)
        
        # Serial label
        self.label = QLabel(self.serial)
        self.label.setFixedWidth(120)
        font = self.label.font()
        font.setPointSize(10)
        font.setBold(True)
        self.label.setFont(font)
        self.label.setStyleSheet("color: #1F2937;")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        
        # Status label
        self.status = QLabel("Ready")
        self.status.setFixedWidth(100)
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setStyleSheet(Styles.get_ready_status_style())
        
        # ADB tag
        self.adb_tag = QLabel("ADB ✓")
        self.adb_tag.setFixedWidth(55)
        self.adb_tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.adb_tag.setStyleSheet(Styles.get_adb_tag_style())
        self.adb_tag.hide()
        
        # Progress bar and log preview in vertical layout
        progress_log_layout = QVBoxLayout()
        progress_log_layout.setContentsMargins(0, 4, 0, 4)
        progress_log_layout.setSpacing(6)
        
        self.progress = QProgressBar()
        self.progress.setFixedHeight(12)
        self.progress.setValue(0)
        self.progress.setStyleSheet(Styles.get_progress_bar_style())
        
        self.log_preview = QLabel("Waiting...")
        self.log_preview.setStyleSheet(Styles.get_log_preview_style())
        self.log_preview.setMinimumHeight(28)
        self.log_preview.setWordWrap(False)
        
        progress_log_layout.addWidget(self.progress)
        progress_log_layout.addWidget(self.log_preview)
        
        # Action buttons layout
        buttons_layout = QHBoxLayout()
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(6)
        
        self.btn_edl = QPushButton("EDL")
        self.btn_edl.setFixedSize(50, 32)
        self.btn_edl.setStyleSheet(Styles.get_edl_button_style())
        self.btn_edl.hide()
        
        self.btn_flash = QPushButton("Flash")
        self.btn_flash.setFixedSize(60, 32)
        self.btn_flash.setStyleSheet(Styles.get_action_button_style(Colors.PRIMARY))
        
        self.btn_remove = QPushButton("✕")
        self.btn_remove.setFixedSize(32, 32)
        self.btn_remove.setStyleSheet(Styles.get_remove_button_style())
        
        buttons_layout.addWidget(self.btn_edl)
        buttons_layout.addWidget(self.btn_flash)
        buttons_layout.addWidget(self.btn_remove)
        
        # Add all widgets to main layout
        main_layout.addWidget(self.label)
        main_layout.addWidget(self.status)
        main_layout.addWidget(self.adb_tag)
        main_layout.addLayout(progress_log_layout, 1)
        main_layout.addLayout(buttons_layout)
        
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
        
        self.status.setText("Flashing...")
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
            if stripped:
                # Show last 55 characters to fit nicely
                self.log_preview.setText(stripped[-55:])
            
            # Extract progress percentage
            match = re.search(r"(\d+\.\d+)%", line)
            if match:
                progress_val = int(float(match.group(1)))
                self.progress.setValue(min(progress_val, 100))
    
    def handle_finished(self):
        """Handle completion of flash process."""
        self.is_flashing = False
        self.btn_remove.setEnabled(True)
        self.btn_flash.setEnabled(True)
        
        if self.process.exitCode() == 0:
            self.status.setText("Success ✓")
            self.status.setStyleSheet(Styles.get_success_status_style())
            self.progress.setValue(100)
        else:
            self.status.setText("Failed ✗")
            self.status.setStyleSheet(Styles.get_failed_status_style())
