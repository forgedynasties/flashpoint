"""UI Styling and theme management — dark pro theme."""


class Colors:
    # Base surfaces
    BG_BASE      = "#0D0F14"
    BG_SURFACE   = "#13151C"
    BG_ELEVATED  = "#1A1D27"

    # Borders
    BORDER       = "#252836"

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
    def get_progress_bar_style(color=Colors.PRIMARY):
        return f"""
            QProgressBar {{
                background-color: {Colors.BG_ELEVATED};
                border: none;
                border-radius: 4px;
                text-align: center;
                color: {Colors.WHITE};
                font-size: 13px;
                font-weight: 700;
            }}
            QProgressBar:disabled {{
                background-color: {Colors.BG_ELEVATED};
                color: {Colors.WHITE};
            }}
            QProgressBar::chunk {{
                background-color: {color};
                border-radius: 4px;
            }}
            QProgressBar::chunk:disabled {{
                background-color: {color};
            }}
        """
