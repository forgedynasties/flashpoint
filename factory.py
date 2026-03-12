"""Factory Flash Station — Main Entry Point"""
import sys
from PyQt6.QtWidgets import QApplication

from gui.factory_app import FactoryStation


def main():
    app = QApplication(sys.argv)
    window = FactoryStation()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
