"""
Qualcomm Pro Flash Station - Main Entry Point

A modular PyQt6 application for flashing Qualcomm devices in EDL or debug mode.
"""
import logging
import sys

from PyQt6.QtWidgets import QApplication

from app import FlashStation


def main():
    """Launch the application."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    app = QApplication(sys.argv)
    window = FlashStation()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()