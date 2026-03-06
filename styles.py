"""UI Styling and theme management."""

# Color Palette
class Colors:
    """Minimal, clean color palette."""
    # Primary
    PRIMARY = "#2563EB"
    PRIMARY_LIGHT = "#DBEAFE"
    PRIMARY_DARK = "#1D4ED8"
    
    # Status colors
    READY = "#6B7280"
    FLASHING = "#F59E0B"
    SUCCESS = "#10B981"
    FAILED = "#EF4444"
    EDL_MODE = "#8B5CF6"
    USER_MODE = "#06B6D4"
    
    # Utility
    WHITE = "#FFFFFF"
    DARK_TEXT = "#1F2937"
    LIGHT_TEXT = "#6B7280"
    BORDER = "#E5E7EB"
    BG_LIGHT = "#F9FAFB"
    BG_LIGHTER = "#F3F4F6"
    
    # Tags
    TAG_SUCCESS = "#ECFDF5"
    TAG_SUCCESS_TEXT = "#065F46"
    TAG_PURPLE = "#F3E8FF"
    TAG_PURPLE_TEXT = "#6D28D9"


class Styles:
    """Minimal, clean style definitions for all UI components."""
    
    @staticmethod
    def get_main_window_style():
        return f"""
            QMainWindow {{
                background-color: {Colors.BG_LIGHT};
            }}
        """
    
    @staticmethod
    def get_status_label_style(color):
        """Return style for status labels."""
        return f"""
            QLabel {{
                font-weight: 600;
                font-size: 12px;
                color: {color};
                padding: 4px 8px;
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
                color: {Colors.TAG_SUCCESS_TEXT};
                font-weight: 600;
                font-size: 11px;
                padding: 3px 8px;
                border-radius: 4px;
            }}
        """
    
    @staticmethod
    def get_primary_button_style():
        return f"""
            QPushButton {{
                background-color: {Colors.PRIMARY};
                color: {Colors.WHITE};
                font-weight: 600;
                border: none;
                border-radius: 6px;
                padding: 8px 14px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {Colors.PRIMARY_DARK};
            }}
            QPushButton:pressed {{
                background-color: #1E40AF;
            }}
            QPushButton:disabled {{
                background-color: #D1D5DB;
                color: #9CA3AF;
            }}
        """
    
    @staticmethod
    def get_action_button_style(color=Colors.PRIMARY):
        # Map colors to their darker hover versions
        hover_colors = {
            Colors.PRIMARY: "#1D4ED8",
            Colors.SUCCESS: "#059669",
            Colors.EDL_MODE: "#A78BFA",
            Colors.FAILED: "#DC2626",
        }
        hover_color = hover_colors.get(color, color)
        
        return f"""
            QPushButton {{
                background-color: {color};
                color: {Colors.WHITE};
                font-weight: 600;
                border: none;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
            }}
            QPushButton:pressed {{
                background-color: {hover_color};
            }}
            QPushButton:disabled {{
                background-color: #D1D5DB;
                color: #9CA3AF;
            }}
        """
    
    @staticmethod
    def get_edl_button_style():
        return f"""
            QPushButton {{
                background-color: {Colors.EDL_MODE};
                color: {Colors.WHITE};
                font-weight: 600;
                border: none;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: #A78BFA;
            }}
            QPushButton:pressed {{
                background-color: #7C3AED;
            }}
            QPushButton:disabled {{
                background-color: #D1D5DB;
                color: #9CA3AF;
            }}
        """
    
    @staticmethod
    def get_remove_button_style():
        return f"""
            QPushButton {{
                background-color: {Colors.BG_LIGHTER};
                color: {Colors.FAILED};
                font-weight: 600;
                border: 1px solid #FCA5A5;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: #FEE2E2;
                color: {Colors.FAILED};
            }}
            QPushButton:pressed {{
                background-color: #FECACA;
            }}
        """
    
    @staticmethod
    def get_progress_bar_style():
        return f"""
            QProgressBar {{
                border: none;
                border-radius: 4px;
                background-color: {Colors.BG_LIGHTER};
                text-align: center;
                height: 6px;
                margin: 0px;
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
                font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
                font-size: 10px;
                background-color: {Colors.WHITE};
                padding: 6px 8px;
                border-radius: 4px;
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
                background-color: #BFDBFE;
            }}
        """
    
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
                border-radius: 8px;
                padding: 0px;
            }}
        """
    
    @staticmethod
    def get_section_label_style():
        return f"""
            QLabel {{
                font-weight: 600;
                font-size: 12px;
                color: {Colors.DARK_TEXT};
                background-color: transparent;
            }}
        """
    
    @staticmethod
    def get_combobox_style():
        return f"""
            QComboBox {{
                padding: 6px 10px;
                border: 1px solid {Colors.BORDER};
                border-radius: 6px;
                background-color: {Colors.WHITE};
                color: {Colors.DARK_TEXT};
                font-size: 12px;
            }}
            QComboBox:focus {{
                border: 2px solid {Colors.PRIMARY};
            }}
            QComboBox::drop-down {{
                border: none;
            }}
        """
