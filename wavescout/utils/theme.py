"""Theme management for WaveScout.

This module provides runtime theme switching capabilities with predefined color palettes.
"""

from enum import Enum
from typing import Dict

from PySide6.QtCore import QObject, Signal, QSettings

from .config import ColorScheme


class ThemeName(Enum):
    """Available theme names."""
    DEFAULT = "Default"
    DARKONE = "DarkOne"
    DRACULA = "Dracula"


# Theme palette definitions
THEMES: Dict[ThemeName, ColorScheme] = {
    ThemeName.DEFAULT: ColorScheme(
        # Backgrounds - Classic dark gray like GTKWave
        BACKGROUND="#1e1e1e",
        BACKGROUND_DARK="#1a1a1a",
        BACKGROUND_INVALID="#1a1a1a",
        HEADER_BACKGROUND="#2d2d30",
        ALTERNATE_ROW="#2d2d30",
        # Borders and lines
        BORDER="#3e3e42",
        GRID="#3e3e42",
        RULER_LINE="#808080",
        BOUNDARY_LINE="#606060",
        # Text
        TEXT="#cccccc",
        TEXT_MUTED="#808080",
        BUS_TEXT="#ffff00",  # Yellow text for bus values (classic, stands out from green lines)
        # Selections and highlights
        SELECTION="#094771",
        SELECTION_BACKGROUND="#2E0F5B",  # Solid dark purple selection
        CURSOR="#ff0000",
        MARKER_DEFAULT_COLOR="#00e676",  # Match the signal color
        # ROI selection colors
        ROI_SELECTION_COLOR="#4A90E2",
        ROI_GUIDE_LINE_COLOR="#4A90E2",
        ROI_SELECTION_OPACITY=0.20,
        # Debug colors
        DEBUG_TEXT="#ffff00",
        DEBUG_BACKGROUND=(0, 0, 0, 200),
        # Default signal color - Blue-tinted green, less harsh than pure bright green
        DEFAULT_SIGNAL="#00e676",  # Softer blue-green for waveforms
        # Event signal arrow color
        EVENT_ARROW="#FFB84D",  # Orange for event arrows
        # Analog signal overlays
        ANALOG_UNDEFINED_FILL=(255, 0, 0, 100),
        ANALOG_HIGHZ_FILL=(255, 255, 0, 100),
        # Splitter
        SPLITTER_HANDLE="#3e3e42",
        # Value tooltips
        VALUE_TOOLTIP_BACKGROUND=(20, 20, 20, 200),
        VALUE_TOOLTIP_TEXT="#FFFFFF",
        VALUE_TOOLTIP_BORDER="#404040",
    ),
    
    ThemeName.DARKONE: ColorScheme(  # DarkOne theme
        # Backgrounds
        BACKGROUND="#282C34",
        BACKGROUND_DARK="#1F2329",
        BACKGROUND_INVALID="#1F2329",
        HEADER_BACKGROUND="#21252B",
        ALTERNATE_ROW="#2F333D",
        # Borders and lines
        BORDER="#3E4451",
        GRID="#3E4451",
        RULER_LINE="#5C6370",
        BOUNDARY_LINE="#5A5F6A",
        # Text
        TEXT="#ABB2BF",
        TEXT_MUTED="#5C6370",
        BUS_TEXT="#E5C07B",  # Orange/yellow text for bus values (distinct from cyan lines)
        # Selections and highlights
        SELECTION="#2C313C",
        SELECTION_BACKGROUND="#2E0F5B",  # Solid dark purple selection
        CURSOR="#E06C75",  # Red accent for clear visibility
        MARKER_DEFAULT_COLOR="#98C379",  # Green accent
        # ROI selection colors
        ROI_SELECTION_COLOR="#61AFEF",  # Blue accent
        ROI_GUIDE_LINE_COLOR="#61AFEF",
        ROI_SELECTION_OPACITY=0.22,
        # Debug colors
        DEBUG_TEXT="#E5C07B",  # Yellow/orange for legibility
        DEBUG_BACKGROUND=(0, 0, 0, 200),
        # Default signal color
        DEFAULT_SIGNAL="#56B6C2",
        # Event signal arrow color
        EVENT_ARROW="#D19A66",  # Orange accent for event arrows
        # Analog signal overlays
        ANALOG_UNDEFINED_FILL=(224, 108, 117, 100),  # E06C75 at ~40% alpha
        ANALOG_HIGHZ_FILL=(229, 192, 123, 100),  # E5C07B at ~40% alpha
        # Splitter
        SPLITTER_HANDLE="#3E4451",
        # Value tooltips
        VALUE_TOOLTIP_BACKGROUND=(40, 44, 52, 200),
        VALUE_TOOLTIP_TEXT="#E5C07B",
        VALUE_TOOLTIP_BORDER="#5C6370",
    ),
    
    ThemeName.DRACULA: ColorScheme(
        # Backgrounds
        BACKGROUND="#282A36",
        BACKGROUND_DARK="#1E2029",
        BACKGROUND_INVALID="#1E2029",
        HEADER_BACKGROUND="#343746",
        ALTERNATE_ROW="#2F3140",
        # Borders and lines
        BORDER="#44475A",
        GRID="#44475A",
        RULER_LINE="#6272A4",
        BOUNDARY_LINE="#6C7391",
        # Text
        TEXT="#F8F8F2",
        TEXT_MUTED="#6272A4",
        BUS_TEXT="#F1FA8C",  # Yellow text for bus values (distinct from cyan lines)
        # Selections and highlights
        SELECTION="#44475A",
        SELECTION_BACKGROUND="#2E0F5B",  # Solid dark purple selection
        CURSOR="#FF79C6",  # Pink accent for high contrast
        MARKER_DEFAULT_COLOR="#50FA7B",  # Green
        # ROI selection colors
        ROI_SELECTION_COLOR="#BD93F9",  # Purple accent
        ROI_GUIDE_LINE_COLOR="#BD93F9",
        ROI_SELECTION_OPACITY=0.22,
        # Debug colors
        DEBUG_TEXT="#F1FA8C",  # Yellow
        DEBUG_BACKGROUND=(0, 0, 0, 200),
        # Default signal color
        DEFAULT_SIGNAL="#8BE9FD",
        # Event signal arrow color
        EVENT_ARROW="#FFB86C",  # Orange for event arrows
        # Analog signal overlays
        ANALOG_UNDEFINED_FILL=(255, 85, 85, 100),  # FF5555
        ANALOG_HIGHZ_FILL=(241, 250, 140, 100),  # F1FA8C
        # Splitter
        SPLITTER_HANDLE="#44475A",
        # Value tooltips
        VALUE_TOOLTIP_BACKGROUND=(40, 42, 54, 200),
        VALUE_TOOLTIP_TEXT="#F1FA8C",
        VALUE_TOOLTIP_BORDER="#6272A4",
    ),
}


class ThemeManager(QObject):
    """Manages application theme and broadcasts changes."""
    
    themeChanged = Signal(ColorScheme)
    
    def __init__(self) -> None:
        super().__init__()
        self._current_theme_name = ThemeName.DEFAULT
        self._current_scheme = THEMES[ThemeName.DEFAULT]
    
    def current_theme_name(self) -> ThemeName:
        """Get the current theme name."""
        return self._current_theme_name
    
    def current(self) -> ColorScheme:
        """Get the current ColorScheme."""
        return self._current_scheme
    
    def set_theme(self, name: ThemeName) -> None:
        """Set the active theme and emit change signal."""
        if name not in THEMES:
            raise ValueError(f"Unknown theme: {name}")
        
        self._current_theme_name = name
        self._current_scheme = THEMES[name]
        
        # Update the global COLORS reference
        import wavescout.utils.config as config_module
        config_module.COLORS = self._current_scheme
        
        # Emit change signal
        self.themeChanged.emit(self._current_scheme)
    
    def load_from_settings(self, settings: QSettings) -> ThemeName:
        """Load theme preference from settings."""
        theme_str = settings.value("theme_name", ThemeName.DEFAULT.value)
        
        # Find matching theme by value
        for theme in ThemeName:
            if theme.value == theme_str:
                self.set_theme(theme)
                return theme
        
        # Default if not found
        self.set_theme(ThemeName.DEFAULT)
        return ThemeName.DEFAULT
    
    def save_to_settings(self, settings: QSettings, name: ThemeName) -> None:
        """Save theme preference to settings."""
        settings.setValue("theme_name", name.value)


# Global singleton instance
theme_manager = ThemeManager()


def apply_saved_theme(settings: QSettings) -> None:
    """Helper to apply saved theme from settings."""
    theme_manager.load_from_settings(settings)