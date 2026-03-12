"""UI Styling and theme management — dark pro theme."""
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_CHECK_SVG = os.path.join(_HERE, "check.svg").replace("\\", "/")


class Colors:
    # Base surfaces
    BG_BASE      = "#0D0F14"
    BG_SURFACE   = "#13151C"
    BG_ELEVATED  = "#1A1D27"
    BG_ROW       = "#161920"
    BG_ROW_ALT   = "#12141A"

    # Borders
    BORDER       = "#252836"
    BORDER_LIGHT = "#2E3248"

    # Text
    TEXT_PRIMARY   = "#E2E8F0"
    TEXT_SECONDARY = "#64748B"
    TEXT_DIM       = "#3A3F55"

    # Accents
    PRIMARY   = "#3B82F6"
    EDL_MODE  = "#A855F7"
    SUCCESS   = "#22C55E"
    WARNING   = "#F59E0B"
    ERROR     = "#EF4444"
    USER_MODE = "#38BDF8"

    WHITE = "#FFFFFF"
    # compat aliases
    DARK_TEXT  = TEXT_PRIMARY
    LIGHT_TEXT = TEXT_SECONDARY


STATUS_COLORS = {
    "edl":      Colors.EDL_MODE,
    "debug":    Colors.USER_MODE,
    "user":     Colors.USER_MODE,
    "ready":    Colors.TEXT_SECONDARY,
    "flashing": Colors.WARNING,
    "success":  Colors.SUCCESS,
    "failed":   Colors.ERROR,
}


class Styles:

    @staticmethod
    def get_main_window_style():
        return f"background-color: {Colors.BG_BASE};"

    @staticmethod
    def get_header_group_style():
        return f"""
            QWidget {{
                background-color: {Colors.BG_SURFACE};
                border-bottom: 1px solid {Colors.BORDER};
            }}
        """

    @staticmethod
    def get_combobox_style():
        return f"""
            QComboBox {{
                background-color: {Colors.BG_ELEVATED};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER_LIGHT};
                padding: 5px 10px;
                font-size: 12px;
                min-height: 30px;
            }}
            QComboBox:hover {{
                border-color: {Colors.PRIMARY};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 24px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {Colors.BG_ELEVATED};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER_LIGHT};
                selection-background-color: {Colors.PRIMARY};
                outline: none;
            }}
        """

    @staticmethod
    def get_action_button_style(color=Colors.PRIMARY):
        return f"""
            QPushButton {{
                background-color: {color};
                color: {Colors.WHITE};
                font-weight: 600;
                font-size: 11px;
                border: none;
                padding: 5px 12px;
                letter-spacing: 0.3px;
            }}
            QPushButton:hover {{
                background-color: {color}CC;
            }}
            QPushButton:pressed {{
                background-color: {color}99;
            }}
            QPushButton:disabled {{
                background-color: {Colors.BG_ELEVATED};
                color: {Colors.TEXT_DIM};
            }}
        """

    @staticmethod
    def get_outlined_button_style(color=Colors.PRIMARY):
        return f"""
            QPushButton {{
                background-color: transparent;
                color: {color};
                font-weight: 600;
                font-size: 11px;
                border: 1.5px solid {color};
                padding: 3px 14px;
                letter-spacing: 0.3px;
            }}
            QPushButton:hover {{
                background-color: {color}22;
            }}
            QPushButton:pressed {{
                background-color: {color}44;
            }}
            QPushButton:disabled {{
                color: {Colors.TEXT_DIM};
                border-color: {Colors.TEXT_DIM};
            }}
        """

    @staticmethod
    def get_remove_button_style():
        return Styles.get_action_button_style(Colors.ERROR)

    @staticmethod
    def get_progress_bar_style(color=Colors.PRIMARY):
        return f"""
            QProgressBar {{
                background-color: {Colors.BG_ELEVATED};
                border: none;
                border-radius: 3px;
                text-align: center;
                color: {Colors.TEXT_SECONDARY};
                font-size: 10px;
            }}
            QProgressBar:disabled {{
                background-color: {Colors.BG_ELEVATED};
                color: {Colors.TEXT_SECONDARY};
            }}
            QProgressBar::chunk {{
                background-color: {color};
                border-radius: 3px;
            }}
            QProgressBar::chunk:disabled {{
                background-color: {color};
            }}
        """

    @staticmethod
    def get_checkbox_style():
        return f"""
            QCheckBox {{
                background: transparent;
                spacing: 0px;
            }}
            QCheckBox::indicator {{
                width: 12px;
                height: 12px;
                border: 1.5px solid {Colors.BORDER_LIGHT};
                border-radius: 2px;
                background-color: {Colors.BG_ELEVATED};
            }}
            QCheckBox::indicator:hover {{
                border-color: {Colors.PRIMARY};
            }}
            QCheckBox::indicator:checked {{
                background-color: {Colors.PRIMARY};
                border-color: {Colors.PRIMARY};
                image: url({_CHECK_SVG});
            }}
        """

    @staticmethod
    def get_table_style():
        return f"""
            QTableWidget {{
                background-color: {Colors.BG_ROW};
                alternate-background-color: {Colors.BG_ROW_ALT};
                border: none;
                gridline-color: {Colors.BORDER};
                outline: none;
                font-size: 12px;
                color: {Colors.TEXT_PRIMARY};
            }}
            QTableWidget::item {{
                padding: 4px 8px;
                border: none;
                color: {Colors.TEXT_PRIMARY};
            }}
            QTableWidget::item:selected {{
                background-color: transparent;
                color: {Colors.TEXT_PRIMARY};
            }}
            QHeaderView {{
                background-color: {Colors.BG_SURFACE};
            }}
            QHeaderView::section {{
                background-color: {Colors.BG_SURFACE};
                color: {Colors.TEXT_SECONDARY};
                padding: 6px 8px;
                border: none;
                border-right: 1px solid {Colors.BORDER};
                border-bottom: 1px solid {Colors.BORDER};
                font-weight: 700;
                font-size: 10px;
                letter-spacing: 0.8px;
                text-transform: uppercase;
            }}
            QScrollBar:vertical {{
                background-color: {Colors.BG_BASE};
                width: 6px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background-color: {Colors.BORDER_LIGHT};
                border-radius: 3px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {Colors.TEXT_SECONDARY};
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar:horizontal {{
                background-color: {Colors.BG_BASE};
                height: 6px;
                border: none;
            }}
            QScrollBar::handle:horizontal {{
                background-color: {Colors.BORDER_LIGHT};
                border-radius: 3px;
            }}
            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
        """

    @staticmethod
    def get_log_box_style():
        return (
            f"QLabel {{ color: {Colors.TEXT_SECONDARY}; background: transparent;"
            "font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;"
            "font-size: 10px; }"
            f"QLabel:disabled {{ color: {Colors.TEXT_SECONDARY}; background: transparent; }}"
        )

    # legacy compat stubs
    @staticmethod
    def get_status_label_style(color):
        return f"QLabel {{ color: {color}; font-weight: bold; font-size: 11px; }}"

    @staticmethod
    def get_simple_button_style(color=Colors.PRIMARY):
        return Styles.get_action_button_style(color)

    @staticmethod
    def get_edl_button_style():
        return Styles.get_action_button_style(Colors.EDL_MODE)

    @staticmethod
    def get_device_row_style():
        return f"QWidget {{ background-color: {Colors.BG_ROW}; }}"
