"""UI Styling and theme management."""

# Color Palette
class Colors:
    """Modern color palette."""
    # Primary
    PRIMARY = "#1976D2"
    PRIMARY_DARK = "#1565C0"
    
    # Status colors
    READY = "#1976D2"
    FLASHING = "#F57C00"
    SUCCESS = "#2E7D32"
    FAILED = "#C62828"
    EDL_MODE = "#7B1FA2"
    USER_MODE = "#00796B"
    
    # Utility
    WHITE = "#FFFFFF"
    DARK_TEXT = "#212121"
    LIGHT_TEXT = "#666666"
    BORDER = "#E0E0E0"
    BG_LIGHT = "#F5F5F5"
    
    # Tags
    TAG_SUCCESS = "#4CAF50"
    TAG_PURPLE = "#4527A0"


class Styles:
    """Centralized style definitions for all UI components."""
    
    @staticmethod
    def get_main_window_style():
        return """
            QMainWindow {
                background-color: #FAFAFA;
            }
        """
    
    @staticmethod
    def get_status_label_style(color, bg_color=None):
        """Return style for status labels."""
        if bg_color is None:
            bg_color = color
        return f"""
            QLabel {{
                font-weight: bold;
                color: {color};
                border: 1px solid {color};
                border-radius: 4px;
                padding: 4px 8px;
                background-color: {Colors.WHITE};
            }}
        """
    
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
    def get_adb_tag_style():
        return f"""
            QLabel {{
                background-color: {Colors.TAG_SUCCESS};
                color: {Colors.WHITE};
                font-weight: bold;
                border-radius: 3px;
                padding: 3px 6px;
                font-size: 10px;
            }}
        """
    
    @staticmethod
    def get_primary_button_style():
        return f"""
            QPushButton {{
                background-color: {Colors.PRIMARY};
                color: {Colors.WHITE};
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
            }}
            QPushButton:hover {{
                background-color: {Colors.PRIMARY_DARK};
            }}
            QPushButton:pressed {{
                background-color: #0D47A1;
            }}
            QPushButton:disabled {{
                background-color: #BDBDBD;
                color: #757575;
            }}
        """
    
    @staticmethod
    def get_action_button_style(color=Colors.PRIMARY):
        return f"""
            QPushButton {{
                background-color: {color};
                color: {Colors.WHITE};
                font-weight: bold;
                border: none;
                border-radius: 3px;
                padding: 5px 10px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: darker({color}, 120);
            }}
            QPushButton:pressed {{
                background-color: darker({color}, 140);
            }}
            QPushButton:disabled {{
                background-color: #BDBDBD;
                color: #757575;
            }}
        """
    
    @staticmethod
    def get_edl_button_style():
        return f"""
            QPushButton {{
                background-color: {Colors.TAG_PURPLE};
                color: {Colors.WHITE};
                font-weight: bold;
                border: none;
                border-radius: 3px;
                padding: 5px 10px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: #5E35B1;
            }}
            QPushButton:pressed {{
                background-color: #3E2723;
            }}
            QPushButton:disabled {{
                background-color: #BDBDBD;
                color: #757575;
            }}
        """
    
    @staticmethod
    def get_remove_button_style():
        return """
            QPushButton {
                background-color: #EEEEEE;
                color: #E57373;
                font-weight: bold;
                border: 1px solid #E57373;
                border-radius: 3px;
                padding: 5px;
            }
            QPushButton:hover {
                background-color: #FFEBEE;
                color: #E53935;
            }
            QPushButton:pressed {
                background-color: #FFCDD2;
                color: #C62828;
            }
        """
    
    @staticmethod
    def get_progress_bar_style():
        return f"""
            QProgressBar {{
                border: 1px solid {Colors.BORDER};
                border-radius: 4px;
                background-color: {Colors.BG_LIGHT};
                text-align: center;
            }}
            QProgressBar::chunk {{
                background-color: {Colors.PRIMARY};
                border-radius: 3px;
            }}
        """
    
    @staticmethod
    def get_log_preview_style():
        return f"""
            QLabel {{
                color: {Colors.LIGHT_TEXT};
                font-family: 'Courier New', monospace;
                font-size: 10px;
                background-color: {Colors.BG_LIGHT};
                padding: 4px;
                border-radius: 3px;
                border: 1px solid {Colors.BORDER};
            }}
        """
    
    @staticmethod
    def get_scroll_area_style():
        return f"""
            QScrollArea {{
                background-color: {Colors.BG_LIGHT};
                border: none;
            }}
            QScrollBar:vertical {{
                border: none;
                background-color: {Colors.BG_LIGHT};
                width: 8px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {Colors.BORDER};
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: #BDBDBD;
            }}
        """
    
    @staticmethod
    def get_header_group_style():
        return f"""
            QWidget {{
                background-color: {Colors.WHITE};
                border-bottom: 1px solid {Colors.BORDER};
                padding: 12px;
            }}
        """
    
    @staticmethod
    def get_device_row_style():
        return f"""
            QWidget {{
                background-color: {Colors.WHITE};
                border: 1px solid {Colors.BORDER};
                border-radius: 4px;
                margin: 4px;
                padding: 8px;
            }}
        """
    
    @staticmethod
    def get_section_label_style():
        return f"""
            QLabel {{
                font-weight: bold;
                font-size: 11px;
                color: {Colors.DARK_TEXT};
                background-color: transparent;
            }}
        """
