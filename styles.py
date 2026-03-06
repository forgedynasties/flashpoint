"""UI Styling and theme management."""

# Color Palette
class Colors:
    """Minimal, clean color palette."""
    # Primary
    PRIMARY = "#0066CC"
    
    # Status colors
    READY = "#666666"
    FLASHING = "#FF9900"
    SUCCESS = "#00AA00"
    FAILED = "#CC0000"
    EDL_MODE = "#6600CC"
    USER_MODE = "#0099CC"
    
    # Utility
    WHITE = "#FFFFFF"
    DARK_TEXT = "#000000"
    LIGHT_TEXT = "#666666"
    BORDER = "#CCCCCC"
    BG_LIGHT = "#F5F5F5"
    BG_LIGHTER = "#EEEEEE"


class Styles:
    """Minimal, clean style definitions for all UI components."""
    
    @staticmethod
    def get_main_window_style():
        return f"QMainWindow {{ background-color: {Colors.BG_LIGHT}; }}"
    
    @staticmethod
    def get_status_label_style(color):
        """Return style for status labels."""
        return f"QLabel {{ color: {color}; font-weight: bold; font-size: 11px; }}"
    
    @staticmethod
    def get_ready_status_style():
        return Styles.get_status_label_style(Colors.READY)
    
    @staticmethod
    def get_flashing_status_style():
        return Styles.get_status_label_style(Colors.FLASHING)
    
    @staticmethod
    def get_success_status_style():
        return Styles.get_status_label_style(Colors.SUCCESS)
    
    @staticmethod
    def get_failed_status_style():
        return Styles.get_status_label_style(Colors.FAILED)
    
    @staticmethod
    def get_edl_mode_status_style():
        return Styles.get_status_label_style(Colors.EDL_MODE)
    
    @staticmethod
    def get_user_mode_status_style():
        return Styles.get_status_label_style(Colors.USER_MODE)
    
    @staticmethod
    def get_simple_button_style(color=Colors.PRIMARY):
        return f"""
            QPushButton {{
                background-color: {color};
                color: {Colors.WHITE};
                font-weight: bold;
                border: none;
                padding: 5px 10px;
                font-size: 11px;
            }}
            QPushButton:disabled {{
                background-color: #999999;
                color: #CCCCCC;
            }}
        """
    
    @staticmethod
    def get_action_button_style(color=Colors.PRIMARY):
        return Styles.get_simple_button_style(color)
    
    @staticmethod
    def get_edl_button_style():
        return Styles.get_simple_button_style(Colors.EDL_MODE)
    
    @staticmethod
    def get_remove_button_style():
        return f"""
            QPushButton {{
                background-color: #FF6666;
                color: {Colors.WHITE};
                font-weight: bold;
                border: none;
                padding: 5px 10px;
                font-size: 11px;
            }}
            QPushButton:disabled {{
                background-color: #999999;
                color: #CCCCCC;
            }}
        """
    
    @staticmethod
    def get_progress_bar_style():
        return f"""
            QProgressBar {{
                border: 1px solid {Colors.BORDER};
                background-color: {Colors.WHITE};
                text-align: center;
                height: 20px;
            }}
            QProgressBar::chunk {{
                background-color: {Colors.PRIMARY};
            }}
        """
    
    @staticmethod
    def get_log_preview_style():
        return f"QLabel {{ color: {Colors.LIGHT_TEXT}; font-size: 10px; }}"
    
    @staticmethod
    def get_header_group_style():
        return f"""
            QWidget {{
                background-color: {Colors.WHITE};
                border-bottom: 1px solid {Colors.BORDER};
            }}
        """
    
    @staticmethod
    def get_device_row_style():
        return f"""
            QWidget {{
                background-color: {Colors.WHITE};
                border: 1px solid {Colors.BORDER};
            }}
        """
    
    @staticmethod
    def get_combobox_style():
        return f"""
            QComboBox {{
                padding: 5px 8px;
                border: 1px solid {Colors.BORDER};
                background-color: {Colors.WHITE};
                color: {Colors.DARK_TEXT};
                font-size: 11px;
            }}
        """
    
    @staticmethod
    def get_table_style():
        return f"""
            QTableWidget {{
                background-color: {Colors.WHITE};
                alternate-background-color: {Colors.BG_LIGHT};
                border: 1px solid {Colors.BORDER};
                gridline-color: {Colors.BORDER};
            }}
            QTableWidget::item {{
                padding: 5px;
                border: none;
            }}
            QHeaderView::section {{
                background-color: {Colors.BG_LIGHTER};
                color: {Colors.DARK_TEXT};
                padding: 5px;
                border: 1px solid {Colors.BORDER};
                font-weight: bold;
                font-size: 11px;
            }}
            QScrollBar:vertical {{
                background-color: {Colors.BG_LIGHT};
                width: 10px;
                border: 1px solid {Colors.BORDER};
            }}
            QScrollBar::handle:vertical {{
                background-color: {Colors.BORDER};
            }}
        """
