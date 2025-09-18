"""
Centralized application settings management using QSettings.
"""

from typing import Optional, cast, Any
from PySide6.QtCore import QObject, QSettings, Signal


class SettingsManager(QObject):
    """
    Singleton manager for application-level settings.
    
    Provides type-safe access to application preferences stored in QSettings.
    """
    
    # Signals emitted when settings change
    hierarchy_levels_changed = Signal(int)
    ui_scale_changed = Signal(float)
    fst_backend_changed = Signal(str)
    value_tooltips_changed = Signal(bool)
    highlight_selected_changed = Signal(bool)
    style_changed = Signal(str, str)  # style_name, style_type
    panel_state_changed = Signal()
    
    _instance: Optional['SettingsManager'] = None
    
    def __new__(cls) -> 'SettingsManager':
        """Ensure singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self) -> None:
        """Initialize the settings manager."""
        if not hasattr(self, '_initialized'):
            super().__init__()
            # Use consistent organization name "WaveScout" 
            self._settings = QSettings("WaveScout", "Scout")
            self._initialized = True
            
            # Cache for frequently accessed settings
            self._hierarchy_levels_cache: Optional[int] = None
            self._ui_scale_cache: Optional[float] = None
            self._fst_backend_cache: Optional[str] = None
            self._value_tooltips_cache: Optional[bool] = None
            self._highlight_selected_cache: Optional[bool] = None
    
    def get_hierarchy_levels(self) -> int:
        """
        Get the number of hierarchical name levels to display.
        
        Returns:
            Number of levels (0 = show full hierarchy, N = show last N levels)
        """
        if self._hierarchy_levels_cache is None:
            # Default to 0 (show full hierarchy)
            value: Any = self._settings.value("SignalDisplay/HierarchyLevels", 0, type=int)
            # Ensure we have an int (QSettings.value can return None even with type=int)
            self._hierarchy_levels_cache = int(value) if value is not None else 0
        return self._hierarchy_levels_cache
    
    def set_hierarchy_levels(self, levels: int) -> None:
        """
        Set the number of hierarchical name levels to display.
        
        Args:
            levels: Number of levels (0 = show full hierarchy, N = show last N levels)
        """
        # Validate input
        if levels < 0:
            levels = 0
        elif levels > 999:
            levels = 999
            
        # Only update if changed
        if self._hierarchy_levels_cache != levels:
            self._hierarchy_levels_cache = levels
            self._settings.setValue("SignalDisplay/HierarchyLevels", levels)
            self._settings.sync()  # Ensure immediate persistence
            
            # Notify listeners
            self.hierarchy_levels_changed.emit(levels)
    
    # UI Scale settings
    def get_ui_scale(self) -> float:
        """Get the UI scale factor."""
        if self._ui_scale_cache is None:
            value: Any = self._settings.value("ui_scale", 1.0, type=float)
            self._ui_scale_cache = float(value) if value is not None else 1.0
        return self._ui_scale_cache
    
    def set_ui_scale(self, scale: float) -> None:
        """Set the UI scale factor."""
        scale = max(0.5, min(3.0, scale))  # Clamp to reasonable range
        if self._ui_scale_cache != scale:
            self._ui_scale_cache = scale
            self._settings.setValue("ui_scale", scale)
            self._settings.sync()
            self.ui_scale_changed.emit(scale)
    
    # FST Backend settings
    def get_fst_backend(self) -> str:
        """Get the FST backend preference ('pyrox' or 'pylibfst')."""
        if self._fst_backend_cache is None:
            value: Any = self._settings.value("fst_backend", "pyrox", type=str)
            self._fst_backend_cache = str(value) if value else "pyrox"
        return self._fst_backend_cache
    
    def set_fst_backend(self, backend: str) -> None:
        """Set the FST backend preference."""
        if backend not in ["pyrox", "pylibfst"]:
            backend = "pyrox"
        if self._fst_backend_cache != backend:
            self._fst_backend_cache = backend
            self._settings.setValue("fst_backend", backend)
            self._settings.sync()
            self.fst_backend_changed.emit(backend)
    
    # Value Tooltips settings
    def get_value_tooltips_enabled(self) -> bool:
        """Get whether value tooltips are enabled."""
        if self._value_tooltips_cache is None:
            value: Any = self._settings.value("view/value_tooltips_enabled", False, type=bool)
            self._value_tooltips_cache = bool(value) if value is not None else False
        return self._value_tooltips_cache
    
    def set_value_tooltips_enabled(self, enabled: bool) -> None:
        """Set whether value tooltips are enabled."""
        if self._value_tooltips_cache != enabled:
            self._value_tooltips_cache = enabled
            self._settings.setValue("view/value_tooltips_enabled", enabled)
            self._settings.sync()
            self.value_tooltips_changed.emit(enabled)
    
    # Highlight Selected settings
    def get_highlight_selected(self) -> bool:
        """Get whether selected signal highlighting is enabled."""
        if self._highlight_selected_cache is None:
            value: Any = self._settings.value("view/highlight_selected", False, type=bool)
            self._highlight_selected_cache = bool(value) if value is not None else False
        return self._highlight_selected_cache
    
    def set_highlight_selected(self, enabled: bool) -> None:
        """Set whether selected signal highlighting is enabled."""
        if self._highlight_selected_cache != enabled:
            self._highlight_selected_cache = enabled
            self._settings.setValue("view/highlight_selected", enabled)
            self._settings.sync()
            self.highlight_selected_changed.emit(enabled)
    
    # Style settings
    def get_style_type(self) -> str:
        """Get the current style type ('default', 'qdarkstyle_dark', 'qdarkstyle_light')."""
        value: Any = self._settings.value("style_type", "default", type=str)
        return str(value) if value else "default"
    
    def set_style_type(self, style_type: str) -> None:
        """Set the style type."""
        self._settings.setValue("style_type", style_type)
        self._settings.sync()
        # Get ui_style for complete signal
        ui_style: Any = self._settings.value("ui_style", "", type=str)
        self.style_changed.emit(str(ui_style) if ui_style else "", style_type)
    
    def get_ui_style(self) -> str:
        """Get the UI style name (e.g., 'Fusion', 'Windows', etc.)."""
        value: Any = self._settings.value("ui_style", "", type=str)
        return str(value) if value else ""
    
    def set_ui_style(self, style_name: str) -> None:
        """Set the UI style name."""
        self._settings.setValue("ui_style", style_name)
        self._settings.setValue("style_type", "default")
        self._settings.sync()
        self.style_changed.emit(style_name, "default")
    
    # Panel settings
    def get_panel_visible(self, panel: str) -> bool:
        """Get whether a panel is visible ('left', 'right', 'bottom')."""
        value: Any = self._settings.value(f"panels/{panel}_visible", True, type=bool)
        return bool(value) if value is not None else True
    
    def set_panel_visible(self, panel: str, visible: bool) -> None:
        """Set whether a panel is visible."""
        self._settings.setValue(f"panels/{panel}_visible", visible)
        self._settings.sync()
        self.panel_state_changed.emit()
    
    def get_panel_size(self, panel: str) -> int:
        """Get the size of a panel ('left_width', 'right_width', 'bottom_height')."""
        default_sizes = {"left_width": 420, "right_width": 250, "bottom_height": 200}
        default = default_sizes.get(panel, 200)
        value: Any = self._settings.value(f"panels/{panel}", default, type=int)
        return int(value) if value is not None else default
    
    def set_panel_size(self, panel: str, size: int) -> None:
        """Set the size of a panel."""
        self._settings.setValue(f"panels/{panel}", size)
        self._settings.sync()
    
    def get_splitter_sizes(self, splitter: str) -> list[int]:
        """Get splitter sizes ('horizontal' or 'vertical')."""
        value = self._settings.value(f"panels/{splitter}_sizes", type=list)
        return value if isinstance(value, list) else []
    
    def set_splitter_sizes(self, splitter: str, sizes: list[int]) -> None:
        """Set splitter sizes."""
        self._settings.setValue(f"panels/{splitter}_sizes", sizes)
        self._settings.sync()
    
    def has_panel_settings(self) -> bool:
        """Check if panel settings have been saved."""
        return self._settings.contains("panels/left_visible")
    
    # Note: Design Tree View mode settings removed - split mode is now the only mode
    
    def get_settings(self) -> QSettings:
        """
        Get the underlying QSettings object for direct access if needed.
        
        Returns:
            The QSettings instance
        """
        return self._settings