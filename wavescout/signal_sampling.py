"""Signal sampling module for converting waveform data to drawing commands.

This module handles the core logic of sampling digital signals at different
zoom levels and generating optimized drawing commands for rendering.
"""

from enum import Enum
from dataclasses import dataclass
from typing import List, Tuple, Optional, Any
from .protocols import WaveformDBProtocol
import math

from .data_model import SignalNode, Time, DataFormat
from .config import RENDERING
import struct


# Core data structures
class ValueKind(Enum):
    """Represents the kind of signal value."""
    NORMAL = "normal"          # Regular defined value
    UNDEFINED = "undefined"    # Unknown/uninitialized (X)
    HIGH_IMPEDANCE = "highz"   # High impedance (Z)


@dataclass
class SignalSample:
    """Represents a sampled signal value at a specific pixel position."""
    value_kind: ValueKind
    value_str: Optional[str] = None      # For BUS rendering mode
    value_float: Optional[float] = None  # For ANALOG rendering mode
    value_bool: Optional[bool] = None    # For BOOL rendering mode
    has_multiple_transitions: bool = False    # Indicates pulse/glitch within pixel


@dataclass
class SignalDrawingData:
    """Sampled signal data ready for rendering."""
    samples: List[Tuple[float, SignalSample]]  # (pixel_x, sample) pairs


def determine_value_kind(value: str) -> ValueKind:
    """Determine the value kind from the string value."""
    value_upper = value.upper()
    if value_upper == 'UNDEFINED' or value_upper == 'X' or 'X' in value_upper:
        return ValueKind.UNDEFINED
    elif value_upper == 'Z' or 'Z' in value_upper:
        return ValueKind.HIGH_IMPEDANCE
    return ValueKind.NORMAL


def parse_signal_value(value: Any, data_format: DataFormat = DataFormat.UNSIGNED, bit_width: int = 32) -> Tuple[Optional[str], Optional[float], Optional[bool]]:
    """Parse wellen signal value to appropriate types based on data format.
    
    Pyrox returns values in their native types:
    - int for raw binary data
    - float for real signals
    - str for string signals
    - None for undefined values
    
    Args:
        value: The raw value from pyrox
        data_format: How to interpret integer values
        bit_width: Bit width of the signal (for signed/float conversion)
    
    Returns:
        Tuple of (value_str, value_float, value_bool)
    """
    # Handle None value
    if value is None:
        return "UNDEFINED", math.nan, False
    
    # Handle string values (DataFormat ignored)
    if isinstance(value, str):
        return value, math.nan, value == '1'
    
    # Handle float values (DataFormat ignored)
    if isinstance(value, float):
        return str(value), value, value != 0.0
    
    # Handle integer values based on DataFormat
    if isinstance(value, int):
        # Boolean interpretation (same for all formats)
        value_bool = value != 0
        
        if data_format == DataFormat.UNSIGNED:
            # Unsigned decimal
            value_str = str(value)
            value_float = float(value)
            
        elif data_format == DataFormat.SIGNED:
            # Signed (2's complement)
            max_val = 1 << (bit_width - 1)
            if value >= max_val:
                signed_value = value - (1 << bit_width)
            else:
                signed_value = value
            value_str = str(signed_value)
            value_float = float(signed_value)
            
        elif data_format == DataFormat.HEX:
            # Hexadecimal (without 0x prefix)
            # Calculate appropriate width for hex display
            hex_width = (bit_width + 3) // 4  # Round up to nearest nibble
            value_str = f"{value:0{hex_width}X}"
            value_float = float(value)  # Use unsigned interpretation
            
        elif data_format == DataFormat.BIN:
            # Binary
            value_str = f"0b{value:0{bit_width}b}"
            value_float = float(value)  # Use unsigned interpretation
            
        elif data_format == DataFormat.FLOAT:
            # IEEE 754 float32
            if bit_width == 32:
                # Mask to 32 bits and interpret as float
                masked_value = value & 0xFFFFFFFF
                # Convert to bytes and interpret as float32
                try:
                    bytes_val = masked_value.to_bytes(4, byteorder='little')
                    float_val = struct.unpack('<f', bytes_val)[0]
                    value_str = str(float_val)
                    value_float = float_val
                except (OverflowError, struct.error):
                    # Fallback if conversion fails
                    value_str = str(value)
                    value_float = float(value)
            else:
                # For non-32-bit signals, just use unsigned
                value_str = str(value)
                value_float = float(value)
        else:
            # Default to unsigned
            value_str = str(value)
            value_float = float(value)
            
        return value_str, value_float, value_bool
    
    # Fallback for other types
    return str(value), float(value) if isinstance(value, (int, float)) else math.nan, bool(value)


def generate_signal_draw_commands(
    signal: SignalNode,
    start_time: Time,
    end_time: Time,
    canvas_width: int,
    waveform_db: WaveformDBProtocol,
    waveform_max_time: Optional[Time] = None
) -> Optional[SignalDrawingData]:
    """Generate drawing commands for a single signal.

    Uses a unified algorithm that works for all zoom levels by following
    signal transitions and marking pixels with multiple transitions.

    Args:
        signal: The signal node to generate commands for
        start_time: Start of the visible time range
        end_time: End of the visible time range
        canvas_width: Width of the canvas in pixels
        waveform_db: Waveform database instance
        waveform_max_time: Maximum valid time in the waveform (optional)

    Returns:
        SignalDrawingData with samples ready for rendering, or None if unable to generate
    """
    if not waveform_db:
        return None

    # Skip if entire range is outside valid bounds
    if waveform_max_time is not None and (end_time < 0 or start_time > waveform_max_time + 1):
        return None

    try:
        if signal.handle is None:
            return None

        signal_obj = waveform_db.get_signal(signal.handle)
        if not signal_obj:
            return None
        
        # Get signal bit width for data format conversion
        # We need to get it from the variable, not the signal object
        bit_width = waveform_db.get_var_bitwidth(signal.handle)
        
        drawing_data = SignalDrawingData(samples=[])
        time_per_pixel = (end_time - start_time) / canvas_width if canvas_width > 0 else 1
        
        # Calculate initial pixel position
        initial_pixel = 0.0
        if start_time < 0:
            initial_pixel = -start_time / time_per_pixel
        
        # Start from time 0 or start_time, whichever is greater
        current_time = max(0, start_time)
        prev_value = None
        prev_pixel = -1.0
        
        # Safety limit
        max_iterations = canvas_width * RENDERING.MAX_ITERATIONS_SAFETY
        iterations = 0

        while iterations < max_iterations:
            iterations += 1
            
            # Query signal at current time
            query_result = signal_obj.query_signal(int(current_time))

            # Parse the signal value with data format
            # None values are handled by parse_signal_value and become UNDEFINED
            value_str, value_float, value_bool = parse_signal_value(
                query_result.value,
                signal.format.data_format,
                bit_width
            )
            value_kind = determine_value_kind(value_str) if value_str else ValueKind.UNDEFINED
            
            # Calculate pixel position for current time
            current_pixel = (current_time - start_time) / time_per_pixel
            
            # Add initial sample OR samples when value changes OR when we've jumped to a new pixel
            if prev_value is None or value_str != prev_value or (prev_pixel >= 0 and int(current_pixel) > int(prev_pixel)):
                # Add the new sample
                sample = SignalSample(
                    value_kind=value_kind,
                    value_str=value_str,
                    value_float=value_float,
                    value_bool=value_bool,
                    has_multiple_transitions=False
                )
                drawing_data.samples.append((current_pixel, sample))
                prev_value = value_str
                prev_pixel = current_pixel
            
            # Check for next transition
            if query_result.next_time is None:
                break
            
            # Check bounds
            if waveform_max_time is not None and query_result.next_time > waveform_max_time:
                break
            if query_result.next_time > end_time:
                break
            
            # Calculate pixel for next transition
            next_pixel = (query_result.next_time - start_time) / time_per_pixel
            
            # Stop if we're past the canvas
            if next_pixel > canvas_width:
                break
            
            # Check if next transition is in the same pixel
            if int(next_pixel) == int(current_pixel) and drawing_data.samples:
                # Mark the last sample as having multiple transitions
                _, last_sample = drawing_data.samples[-1]
                last_sample.has_multiple_transitions = True
                
                # Skip to the middle of the next pixel to avoid iterating through
                # thousands of transitions that all map to the same pixel
                next_pixel_boundary = int(current_pixel) + 1.5  # Middle of next pixel
                next_pixel_time = start_time + (next_pixel_boundary * time_per_pixel)
                
                # Jump directly to the next pixel time
                current_time = int(next_pixel_time)
            else:
                # Move to next transition
                current_time = query_result.next_time

        return drawing_data if drawing_data.samples else None
                
    except Exception:
        return None


