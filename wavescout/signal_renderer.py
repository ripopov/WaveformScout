"""Waveform signal renderer.

Purpose
- Provide concise, reusable drawing routines for different signal kinds used by the
  WaveScout viewer (digital, bus, analog, and event).
- Keep higher-level widgets thin: callers assemble inputs (sampling results and
  render params), this module turns them into QPainter primitives.

Key ideas
- X axis is time mapped to pixels by the caller. Each routine consumes pre-sampled
  drawing_data with samples laid out along the X axis as (x_px, sample) pairs.
- Y axis is the row allocated to the signal. Helper calculate_signal_bounds returns
  top/bottom/middle Y coordinates inside that row with small margins.
- params is a dict with, at minimum: width, start_time, end_time; optionally
  waveform_max_time (to clip drawing outside the recorded time range),
  signal_range_cache and waveform_db (for analog scaling).
- Rendering adapts to density: some routines switch to simplified strokes when many
  regions/transitions fall into the viewport to keep drawing fast and legible.

This module depends only on QPainter and small data types from the local data model
and sampling code; it contains no widget logic.
"""

from typing import Dict, Tuple, Optional, TypedDict, TYPE_CHECKING, Protocol
from dataclasses import dataclass
from PySide6.QtGui import QPainter, QPen, QColor, QFont, QPolygonF
from PySide6.QtCore import Qt, QPointF
from pyrox import SignalHandle

if TYPE_CHECKING:
    from pyrox import Signal, Var
    from .canvas_layout import CanvasLayout, GroupContentDescriptor

from .data_model import RenderType, Time, AnalogScalingMode, SignalNodeID, DisplayFormat, SignalNode, SignalRangeCache, DataFormat, GroupRenderMode
from .signal_sampling import SignalDrawingData, ValueKind
from . import config
from .timing_utils import tprint
RENDERING = config.RENDERING
import math
from .waveform_db import WaveformDB

# Type definitions for node_info and params dictionaries
class NodeInfo(TypedDict):
    name: str
    handle: Optional[SignalHandle]
    is_group: bool
    format: DisplayFormat
    render_type: Optional[RenderType]
    height_scaling: int
    instance_id: SignalNodeID
    is_selected: bool  # Whether this node is currently selected
    signal: Optional["Signal"]  # Cached Signal object from node.signal

class RenderParams(TypedDict, total=False):
    width: int
    height: int
    dpr: float
    start_time: Time
    end_time: Time
    cursor_time: Time
    scroll_value: int
    visible_nodes_info: list[NodeInfo]
    visible_nodes: list[SignalNode]  # SignalNode objects
    waveform_db: Optional[WaveformDB]
    generation: int
    base_row_height: int
    header_height: int
    waveform_max_time: Optional[Time]
    signal_range_cache: Dict[SignalNodeID, SignalRangeCache]
    draw_commands: Dict[SignalHandle, SignalDrawingData]  # Draw commands for signals
    highlight_selected: bool  # Whether to highlight selected signals
    layout: Optional['CanvasLayout']  # New layout information
    group_draw_data: Dict[SignalNodeID, 'GroupDrawingPayload']  # Group drawing data


@dataclass
class GroupDrawingPayload:
    """Data payload for group rendering."""
    descriptor: 'GroupContentDescriptor'
    child_drawings: Dict[SignalHandle, SignalDrawingData]
    range: SignalRangeCache  # global min/max for the group


class GroupRenderer(Protocol):
    """Protocol for group renderer functions."""
    def __call__(self, painter: QPainter, payload: GroupDrawingPayload,
                 y: int, row_height: int, params: RenderParams) -> None: ...


def get_signal_color(format_color: Optional[str]) -> str:
    """Get the effective signal color - either user-configured or theme default.
    
    Args:
        format_color: The color from DisplayFormat (None for theme default)
    
    Returns:
        The color string to use for rendering
    """
    if format_color is not None:
        # User-configured color
        return format_color
    else:
        # Use theme default
        return config.COLORS.DEFAULT_SIGNAL


def calculate_signal_bounds(y: int, row_height: int, margin_top: int = RENDERING.SIGNAL_MARGIN_TOP, 
                          margin_bottom: int = RENDERING.SIGNAL_MARGIN_BOTTOM) -> Tuple[int, int, int]:
    """Compute vertical drawing band inside a row.
    
    The returned values are used by all renderers to keep strokes away from row borders.
    
    Args:
        y: Top Y coordinate of the row in pixels.
        row_height: Row height in pixels.
        margin_top: Top inner margin.
        margin_bottom: Bottom inner margin.
    
    Returns:
        (y_top, y_bottom, y_middle): Y coordinates delimiting usable area and its center.
    """
    y_top = y + margin_top
    y_bottom = y + row_height - margin_bottom
    y_middle = y + row_height // 2
    return y_top, y_bottom, y_middle


def calculate_valid_pixel_range(start_time: Time, end_time: Time, width: int, 
                               waveform_max_time: Optional[Time]) -> Tuple[float, float]:
    """Map waveform time bounds to X-pixel clipping boundaries.
    
    This prevents drawing outside recorded data (before time 0 or after last timestamp)
    while still allowing partial segments at the edges.
    
    Args:
        start_time: Viewport start time (inclusive) in waveform time units.
        end_time: Viewport end time (exclusive) in waveform time units.
        width: Current canvas width in pixels.
        waveform_max_time: Last valid sample time in the waveform, or None if unknown.
    
    Returns:
        (min_valid_pixel, max_valid_pixel): Float X bounds used to clip strokes.
    """
    time_per_pixel = (end_time - start_time) / width if width > 0 else 1
    min_valid_pixel = -1.0  # Default: draw everything
    max_valid_pixel = width + 1.0
    
    if waveform_max_time is not None:
        # Calculate pixel position for time 0
        if start_time < 0:
            min_valid_pixel = (0 - start_time) / time_per_pixel
        
        # Calculate pixel position for max_time + 1
        max_time_boundary = waveform_max_time + 1
        if max_time_boundary < end_time:
            max_valid_pixel = (max_time_boundary - start_time) / time_per_pixel
    
    return min_valid_pixel, max_valid_pixel


def draw_special_value_region(painter: QPainter, value_kind: ValueKind, x_start: float, x_end: float,
                             y_top: int, height: int) -> None:
    """Draw a colored rectangle for UNDEFINED or HIGH_IMPEDANCE regions.
    
    Args:
        painter: Active QPainter
        value_kind: Type of special value (UNDEFINED or HIGH_IMPEDANCE)
        x_start: Start x position
        x_end: End x position  
        y_top: Top y position
        height: Height of the region
    """
    old_pen = painter.pen()
    old_brush = painter.brush()
    
    if value_kind == ValueKind.UNDEFINED:
        # Use red color for undefined
        r, g, b, a = config.COLORS.ANALOG_UNDEFINED_FILL
        fill_color = QColor(r, g, b, a)
    elif value_kind == ValueKind.HIGH_IMPEDANCE:
        # Use yellow color for high impedance
        r, g, b, a = config.COLORS.ANALOG_HIGHZ_FILL
        fill_color = QColor(r, g, b, a)
    else:
        return  # Nothing to draw for normal values
    
    painter.fillRect(int(x_start), y_top, int(x_end - x_start), height, fill_color)
    painter.setPen(old_pen)
    painter.setBrush(old_brush)


def draw_digital_signal(painter: QPainter, node_info: NodeInfo, drawing_data: SignalDrawingData, 
                       y: int, row_height: int, params: RenderParams) -> None:
    """Render a boolean waveform as step lines.
    
    Logic overview
    - Samples are (x_px, sample). Each region is drawn as a horizontal run at y_high (1),
      y_low (0), or y_middle (X/unknown). Vertical lines mark transitions at region starts.
    - Drawing is clipped to valid pixel range computed from start/end time and
      waveform_max_time to avoid strokes past recorded data.
    - If a sample indicates has_multiple_transitions, draw a double vertical marker to
      signal aliasing within that pixel column.
    
    Args:
        painter: Active QPainter to draw into.
        node_info: Dict with at least format.color.
        drawing_data: Pre-sampled waveform data along X.
        y: Row top Y in pixels.
        row_height: Row height in pixels.
        params: Dict with width, start_time, end_time, optional waveform_max_time.
    """
    effective_color = get_signal_color(node_info['format'].color)
    color = QColor(effective_color)
    # Force fully opaque color for crisp lines
    if color.alpha() != 255:
        color.setAlpha(255)
    pen = QPen(color)
    pen.setWidth(0)  # cosmetic 1 device-pixel for crisp HiDPI lines
    painter.setPen(pen)
    
    # Calculate signal bounds
    y_high, y_low, y_middle = calculate_signal_bounds(y, row_height)
    
    # Get waveform max time from params
    waveform_max_time = params.get('waveform_max_time')
    
    # Calculate pixel boundaries for valid time range
    min_valid_pixel, max_valid_pixel = calculate_valid_pixel_range(
        params['start_time'], params['end_time'], params['width'], waveform_max_time
    )
    
    for i in range(len(drawing_data.samples)):
        current_x, current_sample = drawing_data.samples[i]
        
        # Don't skip regions based on min_valid_pixel for the starting edge
        if current_x > max_valid_pixel:
            break  # All subsequent regions will also be outside
        
        if i + 1 < len(drawing_data.samples):
            next_x, _ = drawing_data.samples[i + 1]
        else:
            next_x = params['width']
        
        # Clip next_x to valid range
        next_x = min(next_x, max_valid_pixel)
        
        # Check for special values (UNDEFINED or HIGH_IMPEDANCE)
        if current_sample.value_kind in (ValueKind.UNDEFINED, ValueKind.HIGH_IMPEDANCE):
            # Draw colored rectangle for special values
            draw_start_x = max(current_x, min_valid_pixel) if min_valid_pixel > 0 else current_x
            draw_end_x = min(next_x, max_valid_pixel)
            if draw_start_x < draw_end_x:
                signal_height = y_low - y_high
                draw_special_value_region(painter, current_sample.value_kind, 
                                        draw_start_x, draw_end_x, y_high, signal_height)
            current_y = y_middle  # For transition drawing
        else:
            # Normal values - get y position based on value
            value_str = current_sample.value_str or ""
            if value_str == "1" or current_sample.value_bool == True:
                current_y = y_high
            elif value_str == "0" or current_sample.value_bool == False:
                current_y = y_low
            else:
                current_y = y_middle
            
            # Draw horizontal line for the current value
            draw_start_x = max(current_x, min_valid_pixel) if min_valid_pixel > 0 else current_x
            draw_end_x = min(next_x, max_valid_pixel)
            if draw_start_x < draw_end_x:
                painter.drawLine(int(draw_start_x), current_y, int(draw_end_x), current_y)
        
        # Draw transition from previous value if needed
        if i > 0:
            # Find the last drawn region
            prev_sample = None
            for j in range(i-1, -1, -1):
                prev_x, prev_smp = drawing_data.samples[j]
                if prev_x >= min_valid_pixel:
                    prev_sample = prev_smp
                    break
            
            if prev_sample:
                # Determine previous y position
                if prev_sample.value_kind in (ValueKind.UNDEFINED, ValueKind.HIGH_IMPEDANCE):
                    prev_y = y_middle
                else:
                    prev_value_str = prev_sample.value_str or ""
                    prev_y = y_high if prev_value_str == "1" or prev_sample.value_bool == True else y_low if prev_value_str == "0" or prev_sample.value_bool == False else y_middle
                
                # Only draw transition if it's within the valid range and not between special regions
                # Skip transitions for special value regions as they're drawn as filled rectangles
                if (prev_y != current_y and current_x >= min_valid_pixel and current_x <= max_valid_pixel
                    and not (prev_sample.value_kind in (ValueKind.UNDEFINED, ValueKind.HIGH_IMPEDANCE))
                    and not (current_sample.value_kind in (ValueKind.UNDEFINED, ValueKind.HIGH_IMPEDANCE))):
                    painter.drawLine(int(current_x), prev_y, int(current_x), current_y)
        
        # If this region has multiple transitions, draw additional vertical lines
        if current_sample.has_multiple_transitions:
            # Draw a vertical line to indicate multiple transitions
            painter.drawLine(int(current_x), y_low, int(current_x), y_high)
            # Also draw to the next pixel to make it more visible
            if current_x + 1 < next_x:
                painter.drawLine(int(current_x + 1), y_low, int(current_x + 1), y_high)


def draw_bus_signal(painter: QPainter, node_info: NodeInfo, drawing_data: SignalDrawingData, 
                   y: int, row_height: int, params: RenderParams) -> None:
    """Render a multi-bit bus with smooth dynamic transitions.
    
    Logic overview:
    - All transitions are rendered as "><" style across all zoom levels
    - Transition slopes steepen smoothly as density increases
    - When transitions occur on every pixel, they collapse to vertical lines
    - No abrupt visual switch between rendering modes
    - Slopes are symmetric on both sides of transitions
    
    Args:
        painter: Active QPainter.
        node_info: Dict with format.color.
        drawing_data: Pre-sampled bus regions with value_str for captions.
        y: Row top Y in pixels.
        row_height: Row height in pixels.
        params: Dict with width, start_time, end_time, optional waveform_max_time.
    """
    effective_color = get_signal_color(node_info['format'].color)
    color = QColor(effective_color)
    # Force fully opaque color for crisp lines
    if color.alpha() != 255:
        color.setAlpha(255)
    
    # Get waveform max time from params
    waveform_max_time = params.get('waveform_max_time')
    
    # Calculate pixel boundaries for valid time range
    min_valid_pixel, max_valid_pixel = calculate_valid_pixel_range(
        params['start_time'], params['end_time'], params['width'], waveform_max_time
    )
    
    # Calculate signal bounds
    y_top, y_bottom, y_middle = calculate_signal_bounds(y, row_height)
    height = y_bottom - y_top
    
    num_regions = len(drawing_data.samples)
    
    # Calculate transition density (average pixels per transition)
    viewport_width = max_valid_pixel - min_valid_pixel
    density = viewport_width / num_regions if num_regions > 0 else float('inf')
    
    # Calculate dynamic transition width based on density
    # Starts at max width for low density, decreases smoothly to near-zero for high density
    transition_width = min(RENDERING.BUS_TRANSITION_MAX_WIDTH, 
                          density * RENDERING.BUS_TRANSITION_SLOPE_FACTOR)
    
    # Set up font for text rendering
    font = QFont(RENDERING.FONT_FAMILY, RENDERING.FONT_SIZE_NORMAL)
    painter.setFont(font)
    fm = painter.fontMetrics()
    
    pen = QPen(color)
    pen.setWidth(0)  # cosmetic 1 device-pixel
    painter.setPen(pen)
    
    # Unified rendering loop - handles all density levels
    for i in range(num_regions):
        current_x, current_sample = drawing_data.samples[i]
        
        # Check value kind and use appropriate color
        if current_sample.value_kind == ValueKind.UNDEFINED:
            # Use red color for undefined values
            special_color = QColor(config.COLORS.BUS_UNDEFINED)
            pen = QPen(special_color)
            pen.setWidth(0)
            painter.setPen(pen)
        elif current_sample.value_kind == ValueKind.HIGH_IMPEDANCE:
            # Use yellow color for high impedance values
            special_color = QColor(config.COLORS.BUS_HIGH_IMPEDANCE)
            pen = QPen(special_color)
            pen.setWidth(0)
            painter.setPen(pen)
        else:
            # Use normal color for defined values
            pen = QPen(color)
            pen.setWidth(0)
            painter.setPen(pen)
        
        if current_x < min_valid_pixel:
            continue
        if current_x > max_valid_pixel:
            break
        
        if i + 1 < len(drawing_data.samples):
            next_x, _ = drawing_data.samples[i + 1]
        else:
            next_x = params['width']
        
        next_x = min(next_x, max_valid_pixel)
        
        region_width = next_x - current_x
        
        x_start = int(current_x)
        x_end = int(next_x)
        
        # Determine if THIS specific region should be drawn as high density (vertical line only)
        # A region is high density if it's very narrow, regardless of overall density
        is_high_density_region = (region_width < 2)
        
        # When this specific region is too narrow, just draw vertical line
        if is_high_density_region:
            painter.drawLine(x_start, y_top, x_start, y_bottom)
            # For very narrow regions, also draw the end line
            if region_width < 2 and i == num_regions - 1:
                painter.drawLine(x_end, y_top, x_end, y_bottom)
        else:
            # This is a low-density region - draw as a box with transitions
            # Calculate actual transition width, capped by region width
            actual_trans_width = min(transition_width, region_width / 2)
            
            # Check if we need to skip transitions
            skip_left_transition = (i == 0)
            skip_right_transition = (i == num_regions - 1)
            
            # Check if next region will be drawn as vertical lines only
            next_is_vertical = False
            if i + 1 < num_regions:
                if i + 1 < len(drawing_data.samples):
                    _, _ = drawing_data.samples[i + 1]
                    if i + 2 < len(drawing_data.samples):
                        next_next_x, _ = drawing_data.samples[i + 2]
                    else:
                        next_next_x = params['width']
                    next_region_width = next_next_x - next_x
                    # Next region is vertical-only if it's very narrow OR overall density is very high
                    next_is_vertical = (next_region_width < 2) or (transition_width < 1.0 and next_region_width < 4)
            
            # Force vertical close if next region is high density or overall density is very high
            force_vertical_close = next_is_vertical or (transition_width < 0.5)
            
            if region_width < actual_trans_width * 2:
                # Region too narrow for transitions - draw simple box
                painter.drawLine(x_start, y_top, x_end, y_top)
                painter.drawLine(x_end, y_top, x_end, y_bottom)
                painter.drawLine(x_end, y_bottom, x_start, y_bottom)
                painter.drawLine(x_start, y_bottom, x_start, y_top)
            else:
                x_left_trans = x_start + actual_trans_width
                x_right_trans = x_end - actual_trans_width
                
                # Draw left transition (symmetric slopes)
                # If previous region was vertical-only (very narrow), force vertical transition here
                prev_is_vertical = False
                if i > 0:
                    prev_x, _ = drawing_data.samples[i - 1]
                    if i - 2 >= 0:
                        prev_prev_x, _ = drawing_data.samples[i - 2]
                    else:
                        prev_prev_x = max(min_valid_pixel, 0)
                    prev_region_width = current_x - prev_x
                    # Previous region is considered vertical-only if it's very narrow
                    # or overall transition width is tiny and previous is narrow
                    prev_is_vertical = (prev_region_width < 2) or (transition_width < 1.0 and prev_region_width < 4)
                if skip_left_transition or prev_is_vertical:
                    painter.drawLine(x_start, y_top, x_start, y_bottom)
                    x_left_trans = x_start
                else:
                    painter.drawLine(int(x_start), y_middle, int(x_left_trans), y_top)
                    painter.drawLine(int(x_start), y_middle, int(x_left_trans), y_bottom)
                
                # Draw right transition (symmetric slopes)
                # Force vertical line if we're in high-density mode overall
                if skip_right_transition or force_vertical_close:
                    painter.drawLine(x_end, y_top, x_end, y_bottom)
                    x_right_trans = x_end
                else:
                    painter.drawLine(int(x_right_trans), y_top, int(x_end), y_middle)
                    painter.drawLine(int(x_right_trans), y_bottom, int(x_end), y_middle)
                
                # Top and bottom horizontal lines
                painter.drawLine(int(x_left_trans), y_top, int(x_right_trans), y_top)
                painter.drawLine(int(x_left_trans), y_bottom, int(x_right_trans), y_bottom)
            
            # Interior width for text calculation (accounting for dynamic transitions)
            interior_width = region_width - (actual_trans_width * 2) if region_width > actual_trans_width * 2 else 0
            
            # Get value text
            value_text = current_sample.value_str or ""
            if interior_width > RENDERING.MIN_BUS_TEXT_WIDTH and value_text:
                text = value_text
                text_width = fm.horizontalAdvance(text)
                if text_width < interior_width - 10:
                    # Save current pen and set bus text color
                    old_pen = painter.pen()
                    text_pen = QPen(QColor(config.COLORS.BUS_TEXT))
                    painter.setPen(text_pen)
                    
                    text_x_start = int(current_x + actual_trans_width + 5)
                    text_width_available = int(interior_width - 10)
                    painter.drawText(text_x_start, y_top + 1, 
                                   text_width_available, height,
                                   Qt.AlignmentFlag.AlignCenter, text)
                    
                    # Restore original pen for drawing lines
                    painter.setPen(old_pen)


def compute_signal_range(drawing_data: SignalDrawingData, start_time: Optional[Time] = None, end_time: Optional[Time] = None) -> Tuple[float, float]:
    """Compute min/max of numeric sample values for analog rendering.
    
    Notes
    - Scans drawing_data.samples and considers sample.value_float values, ignoring NaN/None.
    - Optional start_time/end_time are placeholders; drawing_data is already pixel-sampled,
      so we currently use all provided samples.
    - If no valid values exist, returns (0.0, 1.0). If min==max, expand by a small margin.
    
    Args:
        drawing_data: Samples prepared for drawing.
        start_time: Optional viewport start (unused at the moment).
        end_time: Optional viewport end (unused at the moment).
    
    Returns:
        (min_val, max_val) suitable for mapping to Y coordinates.
    """
    min_val = float('inf')
    max_val = float('-inf')
    
    for pixel_x, sample in drawing_data.samples:
        # Filter by time range if specified
        if start_time is not None and end_time is not None:
            # Convert pixel position back to time if needed
            # For now, use all samples in drawing_data
            pass
            
        if sample.value_float is not None and not math.isnan(sample.value_float):
            min_val = min(min_val, sample.value_float)
            max_val = max(max_val, sample.value_float)
    
    # Handle case where no valid values found
    if min_val == float('inf') or max_val == float('-inf'):
        return 0.0, 1.0
    
    # Add some margin if range is zero
    if min_val == max_val:
        margin = abs(min_val) * 0.1 if min_val != 0 else 1.0
        min_val -= margin
        max_val += margin
    
    return min_val, max_val


def compute_global_signal_range(handle: SignalHandle, waveform_db: WaveformDB, data_format: DataFormat = DataFormat.UNSIGNED, signal_obj: Optional["Signal"] = None, var: Optional["Var"] = None) -> Tuple[float, float]:
    """Estimate global min/max from the waveform database.

    Rationale
    - Some scaling modes need the range across the entire recording. Since the backend
      may not expose all transitions directly, we sample the signal uniformly across the
      time table to approximate min/max.

    Args:
        handle: Signal handle used to query the DB.
        waveform_db: Waveform database facade providing get_time_table().
        signal_obj: Cached Signal object from node.signal (should be provided when handle exists).

    Returns:
        (min_val, max_val) over the full recording; defaults to (0.0, 1.0) on failure.
    """
    if not waveform_db:
        return 0.0, 1.0

    try:
        # Signal object should be provided from cached node.signal
        if not signal_obj:
            return 0.0, 1.0
            
        min_val = float('inf')
        max_val = float('-inf')
        
        # Get time table to know the full range
        time_table = waveform_db.get_time_table()
        if not time_table or len(time_table) == 0:
            return 0.0, 1.0
            
        # Query the entire signal range
        start_time = 0
        end_time = time_table[-1]
        
        # Get the signal's bit width for correct signed/unsigned interpretation
        bit_width = 32  # Default bit width
        if var:
            # Use the provided var object directly
            try:
                detected_width = var.bitwidth()
                bit_width = detected_width if detected_width is not None else 32
            except:
                bit_width = 32  # Fallback to 32-bit if bitwidth() fails
        elif waveform_db.hierarchy:
            # Fallback: Find the variable corresponding to this handle to get its bit width
            for v in waveform_db.hierarchy.all_vars():
                var_handle = waveform_db.find_handle_by_path(v.full_name(waveform_db.hierarchy))
                if var_handle == handle:
                    try:
                        detected_width = v.bitwidth()
                        bit_width = detected_width if detected_width is not None else 32
                    except:
                        bit_width = 32  # Fallback to 32-bit if bitwidth() fails
                    break
        
        # Sample the signal at various points to find min/max
        # We need to sample because wellen doesn't provide a direct way to get all transitions
        # Sample at a reasonable interval to capture the range
        num_samples = min(10000, end_time - start_time + 1)  # Limit samples for performance
        sample_interval = max(1, (end_time - start_time) // num_samples)
        
        from .signal_sampling import parse_signal_value
        
        current_time = start_time
        while current_time <= end_time:
            query_result = signal_obj.query_signal(int(current_time))
            if query_result and query_result.value is not None:
                # Parse the value to get numeric representation
                _, value_float, _ = parse_signal_value(query_result.value, data_format, bit_width)
                
                if value_float is not None and not math.isnan(value_float):
                    min_val = min(min_val, value_float)
                    max_val = max(max_val, value_float)
            
            current_time += sample_interval
        
        # Handle case where no valid values found
        if min_val == float('inf') or max_val == float('-inf'):
            return 0.0, 1.0
        
        # Add some margin if range is zero
        if min_val == max_val:
            margin = abs(min_val) * 0.1 if min_val != 0 else 1.0
            min_val -= margin
            max_val += margin
        
        return min_val, max_val
        
    except Exception as e:
        tprint(f"Error computing global signal range: {e}")
        return 0.0, 1.0


def get_signal_range(instance_id: SignalNodeID, handle: SignalHandle,
                    drawing_data: SignalDrawingData,
                    scaling_mode: AnalogScalingMode,
                    signal_range_cache: Dict[SignalNodeID, SignalRangeCache],
                    data_format: DataFormat = DataFormat.UNSIGNED,
                    waveform_db: Optional[WaveformDB] = None,
                    start_time: Optional[Time] = None, end_time: Optional[Time] = None,
                    signal_obj: Optional["Signal"] = None) -> Tuple[float, float]:
    """Return analog Y-range using a small cache keyed by signal instance.
    
    Behavior
    - SCALE_TO_ALL_DATA: compute once per instance across the full recording (via DB if
      available, otherwise from visible samples) and cache as cache.min/max.
    - Other scaling: compute per viewport (start_time, end_time) and memoize in
      cache.viewport_ranges.
    
    Args:
        instance_id: Unique SignalNode ID used as cache key.
        handle: DB handle used for global queries (may be None).
        drawing_data: Samples for the current paint pass.
        scaling_mode: AnalogScalingMode enum controlling how the range is chosen.
        signal_range_cache: Dict[SignalNodeID, SignalRangeCache] owned by the canvas.
        signal_obj: Cached Signal object from node.signal (should be provided when handle exists).
        waveform_db: Optional database facade for global-range computation.
        start_time: Viewport start time.
        end_time: Viewport end time.
    
    Returns:
        (min_val, max_val) range for mapping values to Y.
    """
    # Get or create cache entry for this signal instance
    # If cache exists but data format changed, invalidate it
    if instance_id not in signal_range_cache or signal_range_cache[instance_id].data_format != data_format:
        signal_range_cache[instance_id] = SignalRangeCache(
            min=float('inf'),
            max=float('-inf'),
            viewport_ranges={},
            data_format=data_format
        )
    
    cache = signal_range_cache[instance_id]
    
    if scaling_mode == AnalogScalingMode.SCALE_TO_ALL_DATA:
        # Use global range computed from entire waveform
        if cache.min == float('inf'):
            # Compute and cache global range from database
            if waveform_db and handle is not None:
                # Note: var is not available in this context, would need to be passed as parameter
                min_val, max_val = compute_global_signal_range(handle, waveform_db, data_format, signal_obj, None)
            else:
                # Fallback to viewport data if db not available
                min_val, max_val = compute_signal_range(drawing_data)
            cache.min = min_val
            cache.max = max_val
        return cache.min, cache.max
    else:
        # Use viewport range
        cache_key = (start_time, end_time) if start_time and end_time else (0, 0)
        if cache_key not in cache.viewport_ranges:
            # Compute and cache viewport range
            min_val, max_val = compute_signal_range(drawing_data, start_time, end_time)
            cache.viewport_ranges[cache_key] = (min_val, max_val)
        min_val, max_val = cache.viewport_ranges[cache_key]
        return min_val, max_val


def draw_analog_signal(painter: QPainter, node_info: NodeInfo, drawing_data: SignalDrawingData, 
                      y: int, row_height: int, params: RenderParams) -> None:
    """Render an analog waveform as a polyline with optional min/max labels.
    
    Logic overview
    - Determine vertical range from scaling mode via get_signal_range (uses cache and
      may consult the waveform DB). Add 10% headroom to avoid clamped tops/bottoms.
    - Map each sample.value_float to Y; break the polyline when values are undefined or
      high-impedance; draw aliasing markers (dashed verticals) where multiple transitions
      happened within the same pixel column.
    - Clip drawing to valid pixel range derived from viewport times and waveform_max_time.
    """
    effective_color = get_signal_color(node_info['format'].color)
    color = QColor(effective_color)
    if color.alpha() != 255:
        color.setAlpha(255)
    pen = QPen(color)
    pen.setWidth(0)  # cosmetic 1 device-pixel for crisp lines
    painter.setPen(pen)
    
    # Get waveform max time from params
    waveform_max_time = params.get('waveform_max_time')
    
    # Calculate pixel boundaries for valid time range
    min_valid_pixel, max_valid_pixel = calculate_valid_pixel_range(
        params['start_time'], params['end_time'], params['width'], waveform_max_time
    )
    
    # Calculate signal bounds
    y_top, y_bottom, _ = calculate_signal_bounds(y, row_height)
    signal_height = y_bottom - y_top
    
    # Get signal range based on scaling mode
    instance_id = node_info.get('instance_id')
    handle = node_info.get('handle')
    signal_range_cache = params.get('signal_range_cache', {})
    scaling_mode = node_info['format'].analog_scaling_mode
    waveform_db = params.get('waveform_db')

    # Get cached signal object directly from node_info
    signal_obj = node_info.get('signal')

    if instance_id is not None and handle is not None:
        min_val, max_val = get_signal_range(
            instance_id, handle, drawing_data, scaling_mode, signal_range_cache,
            node_info['format'].data_format, waveform_db, params['start_time'], params['end_time'],
            signal_obj
        )
    else:
        # Fallback to computing range from current data
        min_val, max_val = compute_signal_range(drawing_data)
    
    # Use the real signal range without added margins
    value_range = max_val - min_val
    if value_range == 0:
        value_range = 1.0
    
    # Draw min/max value labels only if there's enough vertical space
    height_scaling = node_info.get('height_scaling', 1)
    if height_scaling > 1:
        font = QFont("Monospace", 8)
        painter.setFont(font)
        text_color = QColor(config.COLORS.TEXT_MUTED)
        text_pen = QPen(text_color)
        text_pen.setWidth(0)
        painter.setPen(text_pen)
        
        # Format and draw max value at top
        max_text = f"{max_val:.2f}"
        painter.drawText(5, y_top + 10, max_text)
        
        # Format and draw min value at bottom
        min_text = f"{min_val:.2f}"
        painter.drawText(5, y_bottom - 2, min_text)
    
    # Reset pen for waveform drawing (cosmetic 1px, no AA)
    pen_wave = QPen(color)
    pen_wave.setWidth(0)
    painter.setPen(pen_wave)
    
    # Draw the waveform as a step diagram (staircase)
    aliasing_regions = []  # Track regions with multiple transitions
    prev_x = None
    prev_y = None
    
    for i in range(len(drawing_data.samples)):
        x, sample = drawing_data.samples[i]
        
        # Skip regions outside valid time range
        if x < min_valid_pixel:
            continue
        if x > max_valid_pixel:
            break
        
        # Check for aliasing (multiple transitions)
        if sample.has_multiple_transitions:
            aliasing_regions.append(x)
        
        # Handle different value kinds
        if sample.value_kind in (ValueKind.UNDEFINED, ValueKind.HIGH_IMPEDANCE):
            # Draw special value region using common helper
            # Determine the width of this region
            if i + 1 < len(drawing_data.samples):
                next_x, _ = drawing_data.samples[i + 1]
                region_end = min(next_x, max_valid_pixel)
            else:
                region_end = min(params['width'], max_valid_pixel)
            
            # Draw colored rectangle for special values
            draw_special_value_region(painter, sample.value_kind, x, region_end, y_top, signal_height)
            
            # Reset the staircase
            prev_x = None
            prev_y = None
            
        elif sample.value_float is not None and not math.isnan(sample.value_float):
            # Normal numeric value - draw as part of staircase
            # Map value to y coordinate
            normalized = (sample.value_float - min_val) / value_range
            # Clamp normalized value to [0, 1]
            normalized = max(0.0, min(1.0, normalized))
            y_pos = y_bottom - (normalized * signal_height)
            
            if prev_x is not None and prev_y is not None:
                # Draw horizontal line at previous value level until current x
                painter.drawLine(int(prev_x), int(prev_y), int(x), int(prev_y))
                # Draw vertical line at current x connecting previous and current value
                painter.drawLine(int(x), int(prev_y), int(x), int(y_pos))
            
            # Update previous values
            prev_x = x
            prev_y = y_pos
    
    # Draw the final horizontal line to the end of the viewport if we have a value
    if prev_x is not None and prev_y is not None:
        # Determine the end x position
        if len(drawing_data.samples) > 0:
            # Get the next sample's x position if available
            last_idx = len(drawing_data.samples) - 1
            for j in range(last_idx, -1, -1):
                last_x, last_sample = drawing_data.samples[j]
                if last_x <= max_valid_pixel:
                    # Draw horizontal line from last value to edge of viewport
                    end_x = min(params['width'], max_valid_pixel)
                    if prev_x < end_x:
                        painter.drawLine(int(prev_x), int(prev_y), int(end_x), int(prev_y))
                    break
    
    # Draw aliasing indicators as very subtle vertical dashed lines
    if aliasing_regions:
        # Create a semi-transparent version of the signal color
        # Very low opacity (20-30) to make it almost invisible
        aliasing_color = QColor(color)
        aliasing_color.setAlpha(40)  # Very low alpha for minimal visibility
        
        # Use dotted pen style with semi-transparent color
        aliasing_pen = QPen(aliasing_color, 1, Qt.PenStyle.DotLine)
        aliasing_pen.setCosmetic(True)
        painter.setPen(aliasing_pen)
        
        for x_pos in aliasing_regions:
            x_int = int(x_pos)
            # Draw single subtle vertical line
            painter.drawLine(x_int, y_top, x_int, y_bottom)


def draw_event_signal(painter: QPainter, node_info: NodeInfo, drawing_data: SignalDrawingData, 
                     y: int, row_height: int, params: RenderParams) -> None:
    """Render timestamped events as thin upward arrows.
    
    Logic overview
    - For each (x_px, sample) event, draw a 1px vertical shaft using full row height
      and a filled polygon arrow head at the top. Clip to valid pixel range like other renderers.
    
    Args:
        painter: Active QPainter.
        node_info: Dict with format.color.
        drawing_data: Event positions along X (values are not displayed).
        y: Row top Y in pixels.
        row_height: Row height in pixels (21 pixels).
        params: Dict with width, start_time, end_time, optional waveform_max_time.
    """
    # Use dedicated event arrow color from theme
    color = QColor(config.COLORS.EVENT_ARROW)
    if color.alpha() != 255:
        color.setAlpha(255)
    pen = QPen(color)
    pen.setWidth(0)  # cosmetic 1 device-pixel
    painter.setPen(pen)
    
    # Use full row height (21 pixels)
    y_top = y
    y_bottom = y + row_height - 1  # 21 pixels total height
    
    # Get valid pixel range for clipping
    waveform_max_time = params.get('waveform_max_time')
    min_valid_pixel, max_valid_pixel = calculate_valid_pixel_range(
        params['start_time'], params['end_time'], params['width'], waveform_max_time
    )
    
    # Draw each event
    for x, sample in drawing_data.samples:
        # Check if event is within valid range
        if x < min_valid_pixel or x > max_valid_pixel:
            continue
            
        x_pos = int(x)
        
        # Draw vertical line (arrow shaft) - 1 pixel wide, full height minus arrow head
        arrow_tip_y = y_top
        painter.drawLine(x_pos, y_bottom, x_pos, arrow_tip_y + 6)
        
        # Draw arrow head pixel by pixel for exact control
        # Pattern:
        #   .      (tip row 1 - 1 pixel)
        #   .      (tip row 2 - 1 pixel)
        #  ...     (middle row 1 - 3 pixels)
        #  ...     (middle row 2 - 3 pixels)
        # .....    (base row 1 - 5 pixels)
        # .....    (base row 2 - 5 pixels)
        
        # Tip row 1 (1 pixel)
        painter.drawPoint(x_pos, arrow_tip_y)
        
        # Tip row 2 (1 pixel)
        painter.drawPoint(x_pos, arrow_tip_y + 1)
        
        # Middle row 1 (3 pixels)
        painter.drawPoint(x_pos - 1, arrow_tip_y + 2)
        painter.drawPoint(x_pos, arrow_tip_y + 2)
        painter.drawPoint(x_pos + 1, arrow_tip_y + 2)
        
        # Middle row 2 (3 pixels)
        painter.drawPoint(x_pos - 1, arrow_tip_y + 3)
        painter.drawPoint(x_pos, arrow_tip_y + 3)
        painter.drawPoint(x_pos + 1, arrow_tip_y + 3)
        
        # Base row 1 (5 pixels)
        painter.drawPoint(x_pos - 2, arrow_tip_y + 4)
        painter.drawPoint(x_pos - 1, arrow_tip_y + 4)
        painter.drawPoint(x_pos, arrow_tip_y + 4)
        painter.drawPoint(x_pos + 1, arrow_tip_y + 4)
        painter.drawPoint(x_pos + 2, arrow_tip_y + 4)
        
        # Base row 2 (5 pixels)
        painter.drawPoint(x_pos - 2, arrow_tip_y + 5)
        painter.drawPoint(x_pos - 1, arrow_tip_y + 5)
        painter.drawPoint(x_pos, arrow_tip_y + 5)
        painter.drawPoint(x_pos + 1, arrow_tip_y + 5)
        painter.drawPoint(x_pos + 2, arrow_tip_y + 5)




def draw_overlapped_group(painter: QPainter, payload: GroupDrawingPayload,
                          y: int, row_height: int, params: RenderParams) -> None:
    """Draw multiple child signals overlapped in a single row.

    Behavior:
    - Forces analog-style rendering for all child signals.
    - Uses a single global Y-range across all children (SCALE_TO_ALL_DATA by spec).
    - Colors come from each child's DisplayFormat.color (fallback to default).
    - Renders polylines on top of each other with slight transparency.
    """
    # Extract data from payload
    descriptor = payload.descriptor
    group_id = descriptor.cache_key
    children = descriptor.children
    cache = payload.range
    # Bounds and clipping
    waveform_max_time = params.get('waveform_max_time')
    min_valid_px, max_valid_px = calculate_valid_pixel_range(
        params['start_time'], params['end_time'], params['width'], waveform_max_time
    )
    y_top, y_bottom, _ = calculate_signal_bounds(y, row_height)
    signal_height = y_bottom - y_top

    # Slight headroom
    min_val = cache.min
    max_val = cache.max
    if max_val <= min_val:
        max_val = min_val + 1.0
    headroom = (max_val - min_val) * 0.1
    min_val -= headroom
    max_val += headroom

    # Draw each child as analog, using its own color
    for child in children:
        if child.handle is None:
            continue
        drawing_data = payload.child_drawings.get(child.handle)
        if not drawing_data:
            continue
        color_str = get_signal_color(child.format.color)
        color = QColor(color_str)
        # Set some transparency for better overlap perception
        if color.alpha() > 200:
            color.setAlpha(200)
        pen = QPen(color)
        pen.setWidth(0)
        painter.setPen(pen)
        # Build polyline
        poly = QPolygonF()
        for px, sample in drawing_data.samples:
            if px < min_valid_px:
                continue
            if px > max_valid_px:
                break
            if sample.value_float is None or math.isnan(sample.value_float):
                # Break in case of undefined/high-Z: draw current poly and reset
                if poly and poly.size() > 1:
                    painter.drawPolyline(poly)
                poly = QPolygonF()
                continue
            # Map value to Y
            norm = (sample.value_float - min_val) / (max_val - min_val)
            # Flip vertically: higher value is lower Y (downwards axis)
            y_px = y_top + (1.0 - norm) * signal_height
            poly.append(QPointF(float(px), float(y_px)))
        if poly and poly.size() > 1:
            painter.drawPolyline(poly)


# Group renderer registry
GROUP_RENDERERS: Dict[GroupRenderMode, GroupRenderer] = {
    GroupRenderMode.OVERLAPPED: draw_overlapped_group,
    # Future modes go here:
    # GroupRenderMode.STACKED_AREA: draw_stacked_area_group,
    # GroupRenderMode.PIPELINE: draw_pipeline_group,
}
