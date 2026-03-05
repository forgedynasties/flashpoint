"""
Qualcomm Pro Flash Station - Main Entry Point

A modular PyQt6 application for flashing Qualcomm devices in EDL or debug mode.
"""
import sys
from PyQt6.QtWidgets import QApplication

from app import FlashStation


def main():
    """Launch the application."""
    app = QApplication(sys.argv)
    window = FlashStation()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()