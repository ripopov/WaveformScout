"""Tests for waveform theme functionality."""

import pytest
from unittest.mock import MagicMock, patch
from PySide6.QtCore import QSettings

from wavescout.utils.theme import ThemeName, THEMES, ThemeManager, theme_manager
from wavescout.utils.config import RGBA


class TestThemeRegistry:
    """Test the theme registry and color definitions."""
    
    def test_all_themes_have_required_fields(self):
        """Verify all themes have all required ColorScheme fields."""
        # Get all field names from any theme (they should all have the same fields)
        default_theme = THEMES[ThemeName.DEFAULT]
        required_fields = set(default_theme.__dataclass_fields__.keys())
        
        for theme_name, theme in THEMES.items():
            theme_fields = set(theme.__dataclass_fields__.keys())
            assert theme_fields == required_fields, f"Theme {theme_name} missing fields"
    
    def test_color_formats_valid(self):
        """Verify all color values are in valid formats."""
        for theme_name, theme in THEMES.items():
            # Check hex color format
            hex_fields = [
                'BACKGROUND', 'BACKGROUND_DARK', 'BACKGROUND_INVALID',
                'HEADER_BACKGROUND', 'ALTERNATE_ROW', 'BORDER', 'GRID',
                'RULER_LINE', 'BOUNDARY_LINE', 'TEXT', 'TEXT_MUTED',
                'SELECTION', 'CURSOR', 'MARKER_DEFAULT_COLOR',
                'ROI_SELECTION_COLOR', 'ROI_GUIDE_LINE_COLOR',
                'DEBUG_TEXT', 'DEFAULT_SIGNAL', 'SPLITTER_HANDLE'
            ]
            
            for field in hex_fields:
                value = getattr(theme, field)
                assert isinstance(value, str), f"{theme_name}.{field} should be string"
                assert value.startswith('#'), f"{theme_name}.{field} should start with #"
                assert len(value) == 7, f"{theme_name}.{field} should be #RRGGBB format"
            
            # Check RGBA tuple format
            rgba_fields = ['DEBUG_BACKGROUND', 'ANALOG_UNDEFINED_FILL', 'ANALOG_HIGHZ_FILL']
            for field in rgba_fields:
                value = getattr(theme, field)
                assert isinstance(value, tuple), f"{theme_name}.{field} should be tuple"
                assert len(value) == 4, f"{theme_name}.{field} should have 4 components"
                for component in value:
                    assert isinstance(component, int), f"{theme_name}.{field} components should be int"
                    assert 0 <= component <= 255, f"{theme_name}.{field} components should be 0-255"
            
            # Check opacity
            assert isinstance(theme.ROI_SELECTION_OPACITY, float)
            assert 0.0 <= theme.ROI_SELECTION_OPACITY <= 1.0
    
    def test_three_themes_exist(self):
        """Verify the three required themes exist."""
        assert ThemeName.DEFAULT in THEMES
        assert ThemeName.DARKONE in THEMES
        assert ThemeName.DRACULA in THEMES
        assert len(THEMES) == 3


class TestThemeManager:
    """Test the ThemeManager functionality."""
    
    def test_initial_theme_is_default(self):
        """Verify initial theme is Default."""
        manager = ThemeManager()
        assert manager.current_theme_name() == ThemeName.DEFAULT
        assert manager.current() == THEMES[ThemeName.DEFAULT]
    
    def test_set_theme(self):
        """Test switching themes."""
        manager = ThemeManager()
        
        # Switch to DarkOne
        manager.set_theme(ThemeName.DARKONE)
        assert manager.current_theme_name() == ThemeName.DARKONE
        assert manager.current() == THEMES[ThemeName.DARKONE]
        
        # Switch to Dracula
        manager.set_theme(ThemeName.DRACULA)
        assert manager.current_theme_name() == ThemeName.DRACULA
        assert manager.current() == THEMES[ThemeName.DRACULA]
    
    def test_set_invalid_theme_raises(self):
        """Test that setting an invalid theme raises ValueError."""
        manager = ThemeManager()
        
        # Create a fake theme name that's not in THEMES
        with pytest.raises(ValueError):
            manager.set_theme("InvalidTheme")  # type: ignore
    
    def test_theme_changed_signal_emitted(self):
        """Test that themeChanged signal is emitted when theme changes."""
        manager = ThemeManager()
        
        # Mock the signal
        signal_mock = MagicMock()
        manager.themeChanged.connect(signal_mock)
        
        # Change theme
        manager.set_theme(ThemeName.DARKONE)
        
        # Verify signal was emitted with correct ColorScheme
        signal_mock.assert_called_once()
        # Note: PySide signals call with the argument directly
        assert signal_mock.call_args[0][0] == THEMES[ThemeName.DARKONE]
    
    def test_global_colors_updated(self):
        """Test that global COLORS reference is updated."""
        manager = ThemeManager()
        
        # Import config to check COLORS
        import wavescout.utils.config as config
        
        # Change theme
        manager.set_theme(ThemeName.DRACULA)
        
        # Verify COLORS was updated
        assert config.COLORS == THEMES[ThemeName.DRACULA]
    
    def test_save_to_settings(self):
        """Test saving theme preference to QSettings."""
        manager = ThemeManager()
        settings = MagicMock(spec=QSettings)
        
        manager.save_to_settings(settings, ThemeName.DARKONE)
        
        settings.setValue.assert_called_once_with("theme_name", "DarkOne")
    
    def test_load_from_settings(self):
        """Test loading theme preference from QSettings."""
        manager = ThemeManager()
        settings = MagicMock(spec=QSettings)
        
        # Test loading DarkOne
        settings.value.return_value = "DarkOne"
        result = manager.load_from_settings(settings)
        
        assert result == ThemeName.DARKONE
        assert manager.current_theme_name() == ThemeName.DARKONE
        
        # Test loading invalid theme defaults to Default
        settings.value.return_value = "InvalidTheme"
        result = manager.load_from_settings(settings)
        
        assert result == ThemeName.DEFAULT
        assert manager.current_theme_name() == ThemeName.DEFAULT
    
    def test_load_from_settings_default(self):
        """Test loading when no theme is saved."""
        manager = ThemeManager()
        settings = MagicMock(spec=QSettings)
        
        # Return default value (None becomes "Default")
        settings.value.return_value = "Default"
        result = manager.load_from_settings(settings)
        
        assert result == ThemeName.DEFAULT
        assert manager.current_theme_name() == ThemeName.DEFAULT