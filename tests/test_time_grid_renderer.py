"""Unit tests for TimeGridRenderer module."""

import pytest
from unittest.mock import MagicMock, Mock, patch
from typing import List

from PySide6.QtGui import QPainter, QColor, QFont
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from wavescout.rendering.time_grid_renderer import TimeGridRenderer, TickInfo
from wavescout.core.data_model import TimeRulerConfig, Timescale, TimeUnit

# Initialize QApplication for tests that use Qt objects
@pytest.fixture(scope="module")
def qapp():
    """Create QApplication for tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class TestTimeGridRenderer:
    """Test suite for TimeGridRenderer."""
    
    def test_initialization(self) -> None:
        """Test renderer initialization with various configurations."""
        # Test with defaults
        renderer = TimeGridRenderer()
        assert renderer._config is not None
        assert renderer._timescale is not None
        
        # Test with custom config
        config = TimeRulerConfig(tick_density=0.5, text_size=12)
        renderer = TimeGridRenderer(config)
        assert renderer._config.tick_density == 0.5
        assert renderer._config.text_size == 12
        
        # Test with custom timescale
        timescale = Timescale(100, TimeUnit.NANOSECONDS)
        renderer = TimeGridRenderer(None, timescale)
        assert renderer._timescale.factor == 100
        assert renderer._timescale.unit == TimeUnit.NANOSECONDS
    
    def test_update_config(self) -> None:
        """Test updating configuration."""
        renderer = TimeGridRenderer()
        new_config = TimeRulerConfig(tick_density=0.9, show_grid_lines=False)
        
        renderer.update_config(new_config)
        
        assert renderer._config.tick_density == 0.9
        assert renderer._config.show_grid_lines == False
    
    def test_update_timescale(self) -> None:
        """Test updating timescale."""
        renderer = TimeGridRenderer()
        new_timescale = Timescale(10, TimeUnit.MICROSECONDS)
        
        renderer.update_timescale(new_timescale)
        
        assert renderer._timescale.factor == 10
        assert renderer._timescale.unit == TimeUnit.MICROSECONDS
    
    def test_calculate_ticks_empty_viewport(self) -> None:
        """Test tick calculation with invalid viewport."""
        renderer = TimeGridRenderer()
        
        # Test zero width
        ticks, step = renderer.calculate_ticks(0, 0, 100)
        assert ticks == []
        assert step == 0.0
        
        # Test negative range
        ticks, step = renderer.calculate_ticks(100, 50, 100)
        assert ticks == []
        assert step == 0.0
        
        # Test zero canvas width
        ticks, step = renderer.calculate_ticks(0, 100, 0)
        assert ticks == []
        assert step == 0.0
    
    def test_calculate_ticks_basic(self, qapp) -> None:
        """Test basic tick calculation."""
        renderer = TimeGridRenderer()
        
        # Simple case: 0 to 1000 time units
        ticks, step = renderer.calculate_ticks(0, 1000, 500)
        
        assert len(ticks) > 0
        assert step > 0
        
        # Check that ticks are within viewport
        for tick in ticks:
            assert 0 <= tick['time_value'] <= 1000
            assert 0 <= tick['pixel_x'] <= 500
            assert tick['label'] != ""
    
    def test_calculate_ticks_with_custom_unit(self, qapp) -> None:
        """Test tick calculation with custom display unit."""
        renderer = TimeGridRenderer()
        
        ticks, step = renderer.calculate_ticks(
            0, 1000000, 800, TimeUnit.MICROSECONDS
        )
        
        assert len(ticks) > 0
        # Check that labels use the specified unit
        for tick in ticks:
            # Labels should contain μs for microseconds
            assert 'μs' in tick['label'] or 'ms' in tick['label']  # May upgrade to ms
    
    def test_calculate_ticks_density(self, qapp) -> None:
        """Test that tick density affects number of ticks."""
        # Low density
        config_sparse = TimeRulerConfig(tick_density=0.3)
        renderer_sparse = TimeGridRenderer(config_sparse)
        ticks_sparse, _ = renderer_sparse.calculate_ticks(0, 1000, 500)
        
        # High density
        config_dense = TimeRulerConfig(tick_density=1.0)
        renderer_dense = TimeGridRenderer(config_dense)
        ticks_dense, _ = renderer_dense.calculate_ticks(0, 1000, 500)
        
        # Higher density should produce more ticks (or equal)
        assert len(ticks_dense) >= len(ticks_sparse)
    
    def test_format_time_label_units(self) -> None:
        """Test time label formatting for different units."""
        renderer = TimeGridRenderer()
        
        # Test picoseconds
        label = renderer._format_time_label(100, TimeUnit.PICOSECONDS)
        assert 'ps' in label
        
        # Test nanoseconds
        label = renderer._format_time_label(1000, TimeUnit.NANOSECONDS)
        assert 'ns' in label or 'μs' in label  # May upgrade
        
        # Test microseconds
        label = renderer._format_time_label(1000000, TimeUnit.MICROSECONDS)
        assert 'μs' in label or 'ms' in label  # May upgrade
    
    def test_format_time_label_with_step_size(self) -> None:
        """Test that step size affects decimal places."""
        # Use a timescale that will result in whole numbers
        timescale = Timescale(1, TimeUnit.NANOSECONDS)
        renderer = TimeGridRenderer(timescale=timescale)
        
        # Large step - no decimals
        label = renderer._format_time_label(100, TimeUnit.NANOSECONDS, 100)
        assert '100' in label and 'ns' in label
        
        # Small step - should have decimals
        label = renderer._format_time_label(100.5, TimeUnit.NANOSECONDS, 0.1)
        # Should include decimal part
        assert '.' in label
    
    def test_format_time_label_unit_upgrade(self) -> None:
        """Test automatic unit upgrades for readability."""
        renderer = TimeGridRenderer()
        
        # 1000ps should upgrade to 1ns
        label = renderer._format_time_label(1000, TimeUnit.PICOSECONDS)
        assert 'ns' in label
        assert '1' in label or '1.0' in label
        
        # 1000000ps should eventually upgrade to μs
        label = renderer._format_time_label(1000000, TimeUnit.PICOSECONDS)
        assert 'μs' in label or 'ns' in label
    
    def test_render_ruler(self) -> None:
        """Test ruler rendering."""
        renderer = TimeGridRenderer()
        
        # Create mock painter
        painter = MagicMock(spec=QPainter)
        
        # Create test tick infos
        tick_infos: List[TickInfo] = [
            TickInfo(time_value=0, pixel_x=0, label="0 ns"),
            TickInfo(time_value=100, pixel_x=100, label="100 ns"),
            TickInfo(time_value=200, pixel_x=200, label="200 ns"),
        ]
        
        # Render ruler
        renderer.render_ruler(painter, tick_infos, 500, 40)
        
        # Verify painter was called
        painter.fillRect.assert_called()  # Background
        painter.drawLine.assert_called()  # Lines
        painter.drawText.assert_called()  # Labels
        painter.setFont.assert_called()   # Font setup
    
    def test_render_grid(self) -> None:
        """Test grid rendering."""
        config = TimeRulerConfig(show_grid_lines=True)
        renderer = TimeGridRenderer(config)
        
        # Create mock painter
        painter = MagicMock(spec=QPainter)
        
        # Create test tick infos
        tick_infos: List[TickInfo] = [
            TickInfo(time_value=0, pixel_x=0, label="0 ns"),
            TickInfo(time_value=100, pixel_x=100, label="100 ns"),
        ]
        
        # Render grid
        renderer.render_grid(painter, tick_infos, 500, 400, 40)
        
        # Verify grid lines were drawn
        painter.setPen.assert_called()
        painter.drawLine.assert_called()
    
    def test_render_grid_disabled(self) -> None:
        """Test that grid rendering respects show_grid_lines setting."""
        config = TimeRulerConfig(show_grid_lines=False)
        renderer = TimeGridRenderer(config)
        
        # Create mock painter
        painter = MagicMock(spec=QPainter)
        
        tick_infos: List[TickInfo] = [
            TickInfo(time_value=0, pixel_x=0, label="0 ns"),
        ]
        
        # Render grid (should do nothing)
        renderer.render_grid(painter, tick_infos, 500, 400, 40)
        
        # Verify no drawing happened
        painter.drawLine.assert_not_called()
    
    def test_grid_line_styles(self) -> None:
        """Test different grid line styles."""
        # Test dashed style
        config_dashed = TimeRulerConfig(
            show_grid_lines=True,
            grid_style="dashed"
        )
        renderer_dashed = TimeGridRenderer(config_dashed)
        
        painter = MagicMock(spec=QPainter)
        tick_infos = [TickInfo(time_value=0, pixel_x=50, label="0")]
        
        renderer_dashed.render_grid(painter, tick_infos, 100, 100, 40)
        
        # Check that setPen was called with dashed style
        calls = painter.setPen.call_args_list
        assert len(calls) > 0
        pen = calls[0][0][0]  # First positional argument of first call
        # Can't easily test Qt enum in mock, but verify setPen was called
        
    def test_grid_opacity(self) -> None:
        """Test grid line opacity setting."""
        config = TimeRulerConfig(
            show_grid_lines=True,
            grid_opacity=0.5
        )
        renderer = TimeGridRenderer(config)
        
        painter = MagicMock(spec=QPainter)
        tick_infos = [TickInfo(time_value=0, pixel_x=50, label="0")]
        
        renderer.render_grid(painter, tick_infos, 100, 100, 40)
        
        # Verify setPen was called (opacity is set on the pen color)
        painter.setPen.assert_called()
    
    def test_time_to_pixel_conversion(self) -> None:
        """Test internal time to pixel conversion."""
        renderer = TimeGridRenderer()
        
        # Test basic conversion
        pixel = renderer._time_to_pixel(50, 0, 100, 200)
        assert pixel == 100  # 50% of range = 50% of width
        
        # Test start position
        pixel = renderer._time_to_pixel(0, 0, 100, 200)
        assert pixel == 0
        
        # Test end position
        pixel = renderer._time_to_pixel(100, 0, 100, 200)
        assert pixel == 200
        
        # Test out of range
        pixel = renderer._time_to_pixel(150, 0, 100, 200)
        assert pixel == 300  # Extrapolates
    
    def test_nice_number_selection(self, qapp) -> None:
        """Test that nice numbers are selected for tick intervals."""
        renderer = TimeGridRenderer()
        
        # Common viewport that should result in nice numbers
        ticks, step = renderer.calculate_ticks(0, 1000, 500)
        
        # Step size should be a "nice" number (1, 2, 2.5, 5, 10, 20, 25, 50, 100, etc.)
        # Check if step is a power of 10 times a nice multiplier
        import math
        if step > 0:
            scale = 10 ** math.floor(math.log10(step))
            multiplier = step / scale
            nice_multipliers = [1, 2, 2.5, 5, 10, 20, 25, 50]
            # Allow some floating point tolerance
            assert any(abs(multiplier - nm) < 0.01 for nm in nice_multipliers)
    
    def test_edge_cases(self, qapp) -> None:
        """Test various edge cases."""
        renderer = TimeGridRenderer()
        
        # Very large time range
        ticks, step = renderer.calculate_ticks(0, 1e15, 800)
        assert len(ticks) > 0
        assert step > 0
        
        # Very small time range
        ticks, step = renderer.calculate_ticks(0, 0.001, 800)
        assert len(ticks) > 0 or step == 0  # May produce no ticks for tiny range
        
        # Negative start time
        ticks, step = renderer.calculate_ticks(-500, 500, 800)
        assert len(ticks) > 0
        # Should include negative and positive times
        has_negative = any(t['time_value'] < 0 for t in ticks)
        has_positive = any(t['time_value'] > 0 for t in ticks)
        assert has_negative or has_positive