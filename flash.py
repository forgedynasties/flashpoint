"""
Qualcomm Pro Flash Station - Main Entry Point

A modular PyQt6 application for flashing Qualcomm devices in EDL or debug mode.
"""
import logging
import os
import sys

from PyQt6.QtWidgets import QApplication

from app import FlashStation


LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "flasher.log")


def main():
    """Launch the application."""
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    file_handler = logging.FileHandler(LOG_FILE, mode="w")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.DEBUG)
    stream_handler.setFormatter(fmt)

    logging.basicConfig(level=logging.DEBUG, handlers=[file_handler, stream_handler])
    app = QApplication(sys.argv)
    window = FlashStation()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()