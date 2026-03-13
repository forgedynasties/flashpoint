"""Factory Flash Station — Main Entry Point"""
import subprocess
import sys
from PyQt6.QtWidgets import QApplication, QMessageBox

from config import QDL_BIN
from gui.factory_app import FactoryStation


def _check_sudo_nopasswd() -> bool:
    """Return True if qdl can be run with sudo without a password."""
    result = subprocess.run(
        ["sudo", "-n", "-l", QDL_BIN],
        capture_output=True,
    )
    return result.returncode == 0


def main():
    app = QApplication(sys.argv)

    if not _check_sudo_nopasswd():
        msg = QMessageBox()
        msg.setWindowTitle("Missing sudo permission")
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setText(
            f"<b>sudo NOPASSWD not configured for qdl.</b><br><br>"
            f"Flashing requires passwordless sudo access to:<br>"
            f"<code>{QDL_BIN}</code><br><br>"
            f"Add the following line via <code>sudo visudo -f /etc/sudoers.d/qdl</code>:<br>"
            f"<code>flasher02 ALL=(ALL) NOPASSWD: {QDL_BIN}</code>"
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()
        sys.exit(1)

    window = FactoryStation()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
