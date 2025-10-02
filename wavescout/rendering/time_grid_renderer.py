"""Time ruler and grid rendering module for WaveformCanvas.

This module encapsulates all time ruler and grid rendering logic,
providing a clean, type-safe interface for the WaveformCanvas.
"""

import math
from typing import List, Tuple, Optional, TypedDict

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPen, QColor, QFont, QFontMetrics

from ..utils import config
from ..core.data_model import Time, TimeUnit, TimeRulerConfig, Timescale

RENDERING = config.RENDERING


class TickInfo(TypedDict):
    """Information about a single tick position."""
    time_value: float  # Time value in Timescale units
    pixel_x: int      # X coordinate in pixels
    label: str        # Formatted label for this tick
    clock_label: Optional[str]  # Optional clock cycle label (for dual-row display)


class ViewportParams(TypedDict):
    """Parameters describing the current viewport."""
    start_time: Time     # Viewport start in Timescale units
    end_time: Time       # Viewport end in Timescale units
    canvas_width: int    # Canvas width in pixels
    canvas_height: int   # Canvas height in pixels


class RenderContext(TypedDict):
    """Context for rendering operations."""
    header_height: int   # Height of the ruler header
    background_color: str  # Background color for ruler
    ruler_line_color: str  # Color for ruler lines
    text_color: str       # Color for text labels


class TimeGridRenderer:
    """Renderer for time ruler and grid lines.
    
    This class encapsulates all logic for calculating tick positions,
    formatting time labels, and rendering the time ruler and grid lines.
    """
    
    def __init__(self, 
                 config: Optional[TimeRulerConfig] = None,
                 timescale: Optional[Timescale] = None) -> None:
        """Initialize the renderer with configuration and timescale.
        
        Args:
            config: Time ruler configuration. Uses defaults if None.
            timescale: Waveform timescale. Defaults to 1ps if None.
        """
        self._config: TimeRulerConfig = config or TimeRulerConfig()
        self._timescale: Timescale = timescale or Timescale(1, TimeUnit.PICOSECONDS)
        self._clock_period: Optional[Time] = None  # Clock period in Timescale units
        self._clock_offset: Time = 0  # Clock phase offset
    
    def update_config(self, config: TimeRulerConfig) -> None:
        """Update the ruler configuration.
        
        Args:
            config: New configuration to use
        """
        self._config = config
    
    def update_timescale(self, timescale: Timescale) -> None:
        """Update the timescale.
        
        Args:
            timescale: New timescale to use
        """
        self._timescale = timescale
    
    def set_clock_signal(self, period: Optional[Time], offset: Time = 0) -> None:
        """Set clock signal parameters for clock-based grid display.
        
        Args:
            period: Clock period in Timescale units (None to disable clock mode)
            offset: Clock phase offset in Timescale units
        """
        self._clock_period = period
        self._clock_offset = offset
    
    def calculate_ticks(self,
                       viewport_start: Time,
                       viewport_end: Time,
                       canvas_width: int,
                       display_unit: Optional[TimeUnit] = None,
                       clock_mode: bool = False) -> Tuple[List[TickInfo], float]:
        """Calculate optimal tick positions for the viewport.
        
        Args:
            viewport_start: Start time of viewport in Timescale units
            viewport_end: End time of viewport in Timescale units
            canvas_width: Width of canvas in pixels
            display_unit: Override display unit (uses config if None)
            
        Returns:
            Tuple of (tick_infos, step_size) where tick_infos contains
            position and label information for each tick
        """
        if viewport_end <= viewport_start or canvas_width <= 0:
            return [], 0.0
        
        # Use clock-based calculation if clock mode is active
        if clock_mode and self._clock_period is not None:
            return self._calculate_clock_ticks(viewport_start, viewport_end, canvas_width, display_unit)
        
        # Use provided unit or fall back to config
        unit = display_unit or self._config.time_unit
        
        # Step 1: Estimate label width requirements
        # Use the larger of start/end time for estimation
        sample_time = max(abs(viewport_start), abs(viewport_end))
        # For estimation, use a reasonable step size guess
        estimated_step = (viewport_end - viewport_start) / 10
        sample_label = self._format_time_label(sample_time, unit, estimated_step)
        
        # Get font metrics for accurate width calculation
        font = QFont(RENDERING.FONT_FAMILY_MONO, self._config.text_size)
        fm = QFontMetrics(font)
        
        # Add some padding between labels
        label_width = fm.horizontalAdvance(sample_label) + RENDERING.DEBUG_TEXT_PADDING
        
        # Step 2: Calculate maximum number of labels that fit
        available_space = canvas_width * self._config.tick_density
        max_labels = int(available_space / label_width) + 2
        
        # Step 3: Determine base scale
        viewport_duration = viewport_end - viewport_start
        if max_labels > 0:
            raw_step = viewport_duration / max_labels
        else:
            raw_step = viewport_duration
            
        if raw_step > 0:
            scale = 10 ** math.floor(math.log10(raw_step))
        else:
            scale = 1
        
        # Step 4: Find optimal step multiplier
        nice_multipliers = [1, 2, 2.5, 5, 10, 20, 25, 50]
        step_size = scale  # Default
        
        for multiplier in nice_multipliers:
            test_step = scale * multiplier
            
            # Calculate first tick position (aligned to step)
            first_tick = math.floor(viewport_start / test_step) * test_step
            
            # Count how many ticks would be generated
            num_ticks = math.ceil((viewport_end - first_tick) / test_step) + 1
            
            if num_ticks <= max_labels:
                step_size = test_step
                break
        
        # Step 5: Generate tick positions
        tick_infos: List[TickInfo] = []
        first_tick = math.floor(viewport_start / step_size) * step_size
        
        tick_time = first_tick
        while tick_time <= viewport_end:
            # Calculate pixel position (caller must provide conversion)
            pixel_x = self._time_to_pixel(tick_time, viewport_start, viewport_end, canvas_width)
            
            # Format label
            label = self._format_time_label(tick_time, unit, step_size)
            
            tick_infos.append(TickInfo(
                time_value=tick_time,
                pixel_x=pixel_x,
                label=label,
                clock_label=None
            ))
            
            tick_time += step_size
            
        return tick_infos, step_size
    
    def render_ruler(self,
                    painter: QPainter,
                    tick_infos: List[TickInfo],
                    canvas_width: int,
                    header_height: int,
                    clock_mode: bool = False) -> None:
        """Render the time ruler.
        
        Args:
            painter: QPainter to render with
            tick_infos: List of tick information
            canvas_width: Width of canvas in pixels
            header_height: Height of ruler header in pixels
            clock_mode: Whether to render in clock mode with dual rows
        """
        if clock_mode and any(tick.get('clock_label') for tick in tick_infos):
            # Clock mode with dual-row display
            half_height = header_height // 2
            
            # Get background colors
            clock_bg, time_bg = self._get_ruler_background_colors(config.COLORS.HEADER_BACKGROUND)
            
            # Draw backgrounds for each row
            painter.fillRect(0, 0, canvas_width, half_height, clock_bg)
            painter.fillRect(0, half_height, canvas_width, half_height, time_bg)
            
            # Draw divider line between rows
            pen = QPen(QColor(config.COLORS.RULER_LINE))
            pen.setWidth(0)
            painter.setPen(pen)
            painter.drawLine(0, half_height, canvas_width, half_height)
        else:
            # Normal mode - single background
            painter.fillRect(0, 0, canvas_width, header_height, 
                            QColor(config.COLORS.HEADER_BACKGROUND))
        
        # Draw bottom line of ruler
        pen = QPen(QColor(config.COLORS.RULER_LINE))
        pen.setWidth(0)  # cosmetic 1 device-pixel
        painter.setPen(pen)
        painter.drawLine(0, header_height - 1, canvas_width, header_height - 1)
        
        # Set font for labels
        if clock_mode and any(tick.get('clock_label') for tick in tick_infos):
            # Smaller font for dual-row display
            font = QFont(RENDERING.FONT_FAMILY_MONO, self._config.text_size - 1)
        else:
            font = QFont(RENDERING.FONT_FAMILY_MONO, self._config.text_size)
        painter.setFont(font)
        fm = QFontMetrics(font)
        
        # Draw ticks and labels
        for tick_info in tick_infos:
            pixel_x = tick_info['pixel_x']
            if 0 <= pixel_x <= canvas_width:
                # Draw tick mark
                tick_pen = QPen(QColor(config.COLORS.RULER_LINE))
                tick_pen.setWidth(0)
                painter.setPen(tick_pen)
                painter.drawLine(pixel_x, header_height - 6, pixel_x, header_height - 1)
                
                if clock_mode and tick_info.get('clock_label'):
                    # Dual-row mode: clock count above, time below
                    half_height = header_height // 2
                    
                    # Draw clock label
                    clock_label = tick_info['clock_label']
                    if clock_label is not None:  # Type guard for mypy
                        clock_rect = fm.boundingRect(clock_label)
                        clock_x = pixel_x - clock_rect.width() // 2
                        clock_y = 2  # Small margin from top
                        
                        painter.setPen(QColor(config.COLORS.TEXT))
                        painter.drawText(clock_x, clock_y + fm.ascent(), clock_label)
                    
                    # Draw time label
                    time_label = tick_info['label']
                    time_rect = fm.boundingRect(time_label)
                    time_x = pixel_x - time_rect.width() // 2
                    time_y = half_height + 2  # Small margin from divider
                    
                    painter.drawText(time_x, time_y + fm.ascent(), time_label)
                else:
                    # Normal mode: single label
                    label = tick_info['label']
                    text_rect = fm.boundingRect(label)
                    text_width = text_rect.width()
                    
                    # Calculate position to center text above tick
                    text_x = pixel_x - text_width // 2
                    text_y = 5  # Margin from top
                    
                    # Draw label
                    painter.setPen(QColor(config.COLORS.TEXT))
                    painter.drawText(text_x, text_y + fm.ascent(), label)
    
    def render_grid(self,
                   painter: QPainter,
                   tick_infos: List[TickInfo],
                   canvas_width: int,
                   canvas_height: int,
                   header_height: int) -> None:
        """Render vertical grid lines.
        
        Args:
            painter: QPainter to render with
            tick_infos: List of tick information
            canvas_width: Width of canvas in pixels
            canvas_height: Height of canvas in pixels
            header_height: Height of ruler header in pixels
        """
        if not self._config.show_grid_lines:
            return
        
        # Set up grid line style
        grid_color = QColor(self._config.grid_color)
        grid_color.setAlpha(int(self._config.grid_opacity * 255))
        pen = QPen(grid_color)
        pen.setWidth(0)  # cosmetic 1 device-pixel
        
        # Apply line style
        if self._config.grid_style == "dashed":
            pen.setStyle(Qt.PenStyle.DashLine)
        elif self._config.grid_style == "dotted":
            pen.setStyle(Qt.PenStyle.DotLine)
        
        painter.setPen(pen)
        
        # Draw vertical lines from below ruler to bottom
        for tick_info in tick_infos:
            pixel_x = tick_info['pixel_x']
            if 0 <= pixel_x <= canvas_width:
                painter.drawLine(pixel_x, header_height, pixel_x, canvas_height)
    
    def _time_to_pixel(self, time: Time, viewport_start: Time, viewport_end: Time, canvas_width: int) -> int:
        """Convert time to pixel coordinate.
        
        Args:
            time: Time value in Timescale units
            viewport_start: Start of viewport in Timescale units
            viewport_end: End of viewport in Timescale units
            canvas_width: Canvas width in pixels
            
        Returns:
            X coordinate in pixels
        """
        if viewport_end <= viewport_start:
            return 0
        
        viewport_duration = viewport_end - viewport_start
        relative_position = (time - viewport_start) / viewport_duration
        return int(relative_position * canvas_width)
    
    def _format_time_label(self, time: float, unit: TimeUnit, step_size: Optional[float] = None) -> str:
        """Format time value according to preferred unit.
        
        Args:
            time: Time value in Timescale units
            unit: The preferred time unit for display
            step_size: The step size between ticks (used to determine decimal places)
            
        Returns:
            Formatted time label string
        """
        # Convert from timescale units to seconds first
        time_in_seconds = time * self._timescale.factor * (10 ** self._timescale.unit.to_exponent())
        
        # Convert seconds to the target unit
        conversions = {
            TimeUnit.ZEPTOSECONDS: (time_in_seconds * 1e21, "zs"),    # s to zs
            TimeUnit.ATTOSECONDS: (time_in_seconds * 1e18, "as"),     # s to as
            TimeUnit.FEMTOSECONDS: (time_in_seconds * 1e15, "fs"),    # s to fs
            TimeUnit.PICOSECONDS: (time_in_seconds * 1e12, "ps"),     # s to ps
            TimeUnit.NANOSECONDS: (time_in_seconds * 1e9, "ns"),      # s to ns
            TimeUnit.MICROSECONDS: (time_in_seconds * 1e6, "μs"),     # s to μs
            TimeUnit.MILLISECONDS: (time_in_seconds * 1e3, "ms"),     # s to ms
            TimeUnit.SECONDS: (time_in_seconds, "s")                  # s to s
        }
        
        value, suffix = conversions[unit]
        
        # Determine decimal places based on step size
        if step_size is not None:
            # Convert step size from timescale units to seconds
            step_in_seconds = step_size * self._timescale.factor * (10 ** self._timescale.unit.to_exponent())
            
            # Convert step size to the current display unit
            step_in_unit = step_in_seconds * (10 ** -unit.to_exponent())
            
            # Special handling for units with different factors
            if unit == TimeUnit.MICROSECONDS:
                step_in_unit = step_in_seconds * 1e6
            elif unit == TimeUnit.MILLISECONDS:
                step_in_unit = step_in_seconds * 1e3
            
            # Determine decimal places needed
            if step_in_unit >= 1:
                decimal_places = 0
            elif step_in_unit >= 0.1:
                decimal_places = 1
            elif step_in_unit >= 0.01:
                decimal_places = 2
            elif step_in_unit >= 0.001:
                decimal_places = 3
            else:
                decimal_places = 4  # Maximum precision
        else:
            # Default decimal places when step size is not provided
            decimal_places = 0
        
        # Format with appropriate decimal places
        if decimal_places == 0:
            formatted_value = f"{value:.0f}"
        else:
            formatted_value = f"{value:.{decimal_places}f}"
            # Remove trailing zeros after decimal point
            if '.' in formatted_value:
                formatted_value = formatted_value.rstrip('0').rstrip('.')
        
        # Handle unit upgrades for readability
        if unit == TimeUnit.PICOSECONDS and value >= 1000:
            return self._format_time_label(time, TimeUnit.NANOSECONDS, step_size)
        elif unit == TimeUnit.NANOSECONDS and value >= 1000:
            return self._format_time_label(time, TimeUnit.MICROSECONDS, step_size)
        elif unit == TimeUnit.MICROSECONDS and value >= 1000:
            return self._format_time_label(time, TimeUnit.MILLISECONDS, step_size)
        elif unit == TimeUnit.MILLISECONDS and value >= 1000:
            return self._format_time_label(time, TimeUnit.SECONDS, step_size)
        
        return f"{formatted_value} {suffix}"
    
    def _calculate_clock_ticks(self,
                              viewport_start: Time,
                              viewport_end: Time,
                              canvas_width: int,
                              display_unit: Optional[TimeUnit] = None) -> Tuple[List[TickInfo], float]:
        """Calculate tick positions aligned to clock edges.
        
        Args:
            viewport_start: Start time of viewport in Timescale units
            viewport_end: End time of viewport in Timescale units
            canvas_width: Width of canvas in pixels
            display_unit: Override display unit (uses config if None)
            
        Returns:
            Tuple of (tick_infos, step_size) with dual labels for clock mode
        """
        if self._clock_period is None or self._clock_period <= 0:
            return [], 0.0
        
        unit = display_unit or self._config.time_unit
        
        # Calculate visible clock cycles
        start_cycle = math.floor((viewport_start - self._clock_offset) / self._clock_period)
        end_cycle = math.ceil((viewport_end - self._clock_offset) / self._clock_period)
        visible_cycles = end_cycle - start_cycle
        
        # Determine clock cycle step (powers of 10)
        if visible_cycles <= 0:
            return [], 0.0
        
        # Estimate how many labels can fit
        font = QFont(RENDERING.FONT_FAMILY_MONO, self._config.text_size - 1)  # Smaller font for dual-row
        fm = QFontMetrics(font)
        
        # Estimate label width for clock counts
        sample_cycle = max(abs(start_cycle), abs(end_cycle))
        sample_label = str(sample_cycle)
        label_width = fm.horizontalAdvance(sample_label) + RENDERING.DEBUG_TEXT_PADDING
        
        # Calculate maximum number of labels
        available_space = canvas_width * self._config.tick_density
        max_labels = int(available_space / label_width) + 2
        
        # Also limit based on minimum spacing between ticks (avoid overcrowding)
        min_tick_spacing = 30  # Minimum pixels between ticks
        max_labels_by_spacing = canvas_width // min_tick_spacing
        max_labels = min(max_labels, max_labels_by_spacing)
        
        # Find appropriate step size (always integer clock cycles)
        raw_step = visible_cycles / max_labels if max_labels > 0 else visible_cycles
        
        # Ensure minimum step is 1 (never show fractional clock cycles)
        if raw_step < 1:
            cycle_step = 1
        else:
            # Use powers of 10 for larger steps
            if raw_step > 0:
                scale = 10 ** math.floor(math.log10(raw_step))
            else:
                scale = 1
            
            # Choose nice multiplier
            nice_multipliers = [1, 2, 5, 10, 20, 50]
            cycle_step = scale
            
            for multiplier in nice_multipliers:
                test_step = scale * multiplier
                num_ticks = math.ceil(visible_cycles / test_step) + 1
                if num_ticks <= max_labels:
                    cycle_step = test_step
                    break
        
        # Ensure cycle_step is always an integer (should already be, but be explicit)
        cycle_step = int(cycle_step)
        
        # Generate tick positions
        tick_infos: List[TickInfo] = []
        
        # Always align to integer clock cycles
        if cycle_step == 1:
            # When showing every clock, start from the first visible integer cycle
            first_cycle = int(math.floor(start_cycle))
            if first_cycle < start_cycle:
                first_cycle += 1
        else:
            # For larger steps, align to the step size
            first_cycle = math.floor(start_cycle / cycle_step) * cycle_step
            # But ensure it's an integer
            first_cycle = int(first_cycle)
        
        cycle = first_cycle
        while cycle <= end_cycle:
            # Calculate time for this clock cycle
            tick_time = self._clock_offset + cycle * self._clock_period
            
            # Skip if outside viewport
            if tick_time < viewport_start or tick_time > viewport_end:
                cycle += cycle_step
                continue
            
            # Calculate pixel position
            pixel_x = self._time_to_pixel(tick_time, viewport_start, viewport_end, canvas_width)
            
            # Format labels
            clock_label = str(int(cycle))  # Clock cycle count
            time_label = self._format_time_label(tick_time, unit, cycle_step * self._clock_period)
            
            tick_infos.append(TickInfo(
                time_value=tick_time,
                pixel_x=pixel_x,
                label=time_label,
                clock_label=clock_label
            ))
            
            cycle += cycle_step
        
        return tick_infos, cycle_step * self._clock_period
    
    def _get_ruler_background_colors(self, base_color: str) -> Tuple[QColor, QColor]:
        """Calculate background colors for clock and time rows.
        
        Args:
            base_color: Base background color
            
        Returns:
            Tuple of (clock_bg_color, time_bg_color)
        """
        base = QColor(base_color)
        
        # Determine if we're in light or dark mode
        is_dark = base.lightness() < 128
        
        if is_dark:
            # Dark mode: make clock row slightly lighter
            clock_bg = base.lighter(110)  # 10% lighter
            time_bg = base.lighter(105)   # 5% lighter
        else:
            # Light mode: make clock row slightly darker
            clock_bg = base.darker(110)   # 10% darker
            time_bg = base.darker(105)    # 5% darker
        
        return clock_bg, time_bg