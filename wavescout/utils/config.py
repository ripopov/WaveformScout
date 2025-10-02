"""Centralized configuration for WaveScout.

This module contains all configuration constants, colors, and magic numbers
used throughout the application to improve maintainability and consistency.
"""

from dataclasses import dataclass
from typing import Optional, List, TypeAlias

# Type alias for RGBA tuples
RGBA: TypeAlias = tuple[int, int, int, int]

# Marker labels
MARKER_LABELS: List[str] = ["A", "B", "C", "D", "E", "F", "G", "H", "I"]


@dataclass(frozen=True)
class RenderingConfig:
    """Configuration for signal rendering."""
    SIGNAL_MARGIN_TOP: int = 3
    SIGNAL_MARGIN_BOTTOM: int = 3
    BUS_TRANSITION_MAX_WIDTH: int = 3  # Maximum width for diagonal transitions (3px for >, 3px for <)
    BUS_TRANSITION_SLOPE_FACTOR: float = 0.125  # Controls transition steepening rate
    MIN_BUS_TEXT_WIDTH: int = 30
    DEFAULT_ROW_HEIGHT: int = 22
    DEFAULT_HEADER_HEIGHT: int = 35
    
    # Font settings
    FONT_FAMILY: str = "Consolas"
    FONT_SIZE_SMALL: int = 8
    FONT_SIZE_NORMAL: int = 9
    FONT_SIZE_LARGE: int = 10
    FONT_FAMILY_MONO: str = "Monospace"
    
    # Canvas settings
    MIN_CANVAS_WIDTH: int = 400
    DEFAULT_CANVAS_WIDTH: int = 1000  # Default width for calculations when canvas not yet initialized
    UPDATE_TIMER_DELAY: int = 100  # milliseconds
    MAX_ITERATIONS_SAFETY: int = 10  # multiplier for canvas width
    
    # Cache settings
    TRANSITION_CACHE_MAX_ENTRIES: int = 1000
    
    # Cursor settings
    CURSOR_WIDTH: int = 2
    CURSOR_PADDING: int = 2
    
    # Marker settings
    MARKER_WIDTH: int = 1
    MAX_MARKERS: int = 9
    MARKER_NAVIGATION_OFFSET: int = 10  # Pixels from left edge when navigating to marker
    
    # ROI overlay settings
    ROI_GUIDE_LINE_WIDTH: int = 1
    
    # Debug display settings
    DEBUG_FONT_FAMILY: str = "Consolas"
    DEBUG_FONT_SIZE: int = 10
    DEBUG_BG_ALPHA: int = 200
    DEBUG_TEXT_PADDING: int = 10
    DEBUG_TEXT_MARGIN: int = 10
    
    # Value tooltip settings
    VALUE_TOOLTIP_PADDING: int = 4  # Internal padding
    VALUE_TOOLTIP_MARGIN: int = 8  # Distance from cursor
    VALUE_TOOLTIP_BORDER_RADIUS: int = 4  # Rounded corner radius
    VALUE_TOOLTIP_MIN_WIDTH: int = 40  # Minimum tooltip width
    VALUE_TOOLTIP_FONT_SIZE: int = 9  # Font size for values


@dataclass(frozen=True)
class ColorScheme:
    """Color scheme for the application."""
    # Backgrounds
    BACKGROUND: str = "#1e1e1e"
    BACKGROUND_DARK: str = "#1a1a1a"
    BACKGROUND_INVALID: str = "#1a1a1a"  # For invalid time ranges
    ALTERNATE_ROW: str = "#2d2d30"
    HEADER_BACKGROUND: str = "#2d2d30"
    
    # Borders and lines
    BORDER: str = "#3e3e42"
    GRID: str = "#3e3e42"
    RULER_LINE: str = "#808080"
    BOUNDARY_LINE: str = "#606060"
    
    # Text
    TEXT: str = "#cccccc"
    TEXT_MUTED: str = "#808080"
    BUS_TEXT: str = "#ffffff"  # Text color for values inside bus signals
    BUS_UNDEFINED: str = "#ff4444"  # Color for undefined bus value regions (red)
    BUS_HIGH_IMPEDANCE: str = "#ffff44"  # Color for high impedance bus value regions (yellow)
    
    # Selections and highlights
    SELECTION: str = "#094771"
    SELECTION_BACKGROUND: str = "#5B3A8C"  # Solid dark purple selection
    CURSOR: str = "#ff0000"
    MARKER_DEFAULT_COLOR: str = "#00ff00"
    
    # ROI selection colors
    ROI_SELECTION_COLOR: str = "#4A90E2"  # Blue fill color (will apply opacity separately)
    ROI_GUIDE_LINE_COLOR: str = "#4A90E2"  # Guide line color
    ROI_SELECTION_OPACITY: float = 0.2      # Fill opacity 0..1
    
    # Debug colors
    DEBUG_TEXT: str = "#ffff00"  # Yellow
    DEBUG_BACKGROUND: RGBA = (0, 0, 0, 200)  # RGBA
    
    # Default signal color
    DEFAULT_SIGNAL: str = "#33C3F0"
    
    # Event signal arrow color
    EVENT_ARROW: str = "#FFB84D"  # Orange for event arrows
    
    # Analog signal overlays
    ANALOG_UNDEFINED_FILL: RGBA = (255, 0, 0, 100)  # Semi-transparent red for undefined regions
    ANALOG_HIGHZ_FILL: RGBA = (255, 255, 0, 100)  # Semi-transparent yellow for high-Z regions
    
    # Splitter
    SPLITTER_HANDLE: str = "#3e3e42"
    
    # Value tooltips
    VALUE_TOOLTIP_BACKGROUND: RGBA = (20, 20, 20, 200)  # Semi-transparent dark background
    VALUE_TOOLTIP_TEXT: str = "#FFFFFF"  # Bright text color
    VALUE_TOOLTIP_BORDER: str = "#404040"  # Optional border color


@dataclass(frozen=True)
class UIConfig:
    """UI-related configuration."""
    # Splitter settings
    SPLITTER_INITIAL_SIZES: Optional[List[int]] = None  # Will be set in __post_init__
    SPLITTER_HANDLE_WIDTH: int = 2
    
    # Tree view settings
    TREE_ROW_HEIGHT_BASE: int = 20
    TREE_ALTERNATING_ROWS: bool = True
    TREE_UNIFORM_ROW_HEIGHTS: bool = False
    
    # Info bar settings
    INFO_BAR_HEIGHT: int = 25
    
    # Scrolling settings
    SCROLL_SENSITIVITY: float = 0.05
    ZOOM_WHEEL_FACTOR: float = 1.1
    PAN_PERCENTAGE: float = 0.1
    
    # Selection
    SELECTION_MODE_EXTENDED: bool = True
    
    # Drag and drop
    DRAG_DROP_ENABLED: bool = True
    
    def __post_init__(self) -> None:
        if self.SPLITTER_INITIAL_SIZES is None:
            object.__setattr__(self, 'SPLITTER_INITIAL_SIZES', [200, 100, 600])


@dataclass(frozen=True)
class TimeRulerDefaults:
    """Default settings for time ruler."""
    TICK_DENSITY: float = 0.8
    TEXT_SIZE: int = 10
    SHOW_GRID_LINES: bool = True
    GRID_STYLE: str = "solid"
    NICE_NUMBERS: Optional[List[float]] = None  # Will be set in __post_init__
    
    # Ruler dimensions
    RULER_HEIGHT: int = 35
    TICK_HEIGHT: int = 5
    TICK_Y_START: int = 29
    TEXT_Y_OFFSET: int = 5
    
    def __post_init__(self) -> None:
        if self.NICE_NUMBERS is None:
            object.__setattr__(self, 'NICE_NUMBERS', [1, 2, 2.5, 5])


# Global instances for easy access
RENDERING = RenderingConfig()
COLORS = ColorScheme()
UI = UIConfig()
TIME_RULER = TimeRulerDefaults()