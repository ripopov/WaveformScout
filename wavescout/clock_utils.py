"""Clock signal utilities for calculating clock periods from various signal types."""

from typing import Optional
from wavescout.backend_types import WSignal, WVar
from wavescout.data_model import Time


def is_valid_clock_signal(var: WVar) -> bool:
    """Check if a signal type is valid for use as a clock.
    
    Valid types:
    - 1-bit signals: Wire, Reg, Logic, Bit, etc. (width = 1)
    - Event type signals
    - Multi-bit buses: Wire, Reg, Integer (treated as clock counters)
    
    Invalid types:
    - String type variables
    - Real/Float type variables
    """
    var_type = var.var_type()
    
    # Invalid types (use proper capitalization for wellen)
    if var_type in ('String', 'Real', 'RealTime'):
        return False
    
    # Event types are always valid
    if var_type == 'Event':  # Capital E for wellen enum
        return True
    
    # All other digital types are valid (wire, reg, logic, bit, integer, etc.)
    return True


def calculate_event_clock_period(signal: WSignal) -> Optional[tuple[Time, Time]]:
    """Calculate clock period and phase offset for Event type signals.
    
    Algorithm:
    1. Iterate through first 2 signal changes
    2. Calculate time difference between consecutive changes
    3. Use this difference as clock period
    4. Use first event time as phase offset
    
    Returns:
        Tuple of (period, phase_offset) or None if calculation fails
    """
    changes = []
    change_iter = signal.all_changes()
    
    # Collect first 2 changes
    for _ in range(2):
        try:
            change = next(change_iter)
            changes.append(change)
        except StopIteration:
            break
    
    # Need at least 2 changes
    if len(changes) < 2:
        return None
    
    # Calculate period and phase
    period = changes[1][0] - changes[0][0]
    if period > 0:
        # Phase offset is the time of the first event
        phase_offset = changes[0][0]
        return (period, phase_offset)
    return None


def calculate_digital_clock_period(signal: WSignal) -> Optional[tuple[Time, Time]]:
    """Calculate clock period and phase offset for 1-bit digital signals.
    
    Algorithm:
    1. Find first 4 positive edges (0→1 transitions)
    2. Calculate intervals between consecutive positive edges
    3. Use shortest interval as clock period (handles gated clocks)
    4. Return both period and phase (time of first positive edge)
    5. If fewer than 2 edges found, fall back to any 2 transitions
    
    Returns:
        Tuple of (period, phase_offset) or None if calculation fails
    """
    positive_edges = []
    all_changes = []
    prev_value = None
    
    change_iter = signal.all_changes()
    
    # Look for positive edges
    for _ in range(100):  # Limit iterations for performance
        try:
            time, value = next(change_iter)
            all_changes.append((time, value))
            
            # Check for positive edge (0→1 or X→1)
            if prev_value is not None:
                prev_str = str(prev_value).lower()
                curr_str = str(value).lower()
                
                # Positive edge detection
                if (prev_str in ('0', 'x', 'z') and curr_str == '1'):
                    positive_edges.append(time)
                    if len(positive_edges) >= 4:
                        break
            
            prev_value = value
        except StopIteration:
            break
    
    # Calculate period from positive edges
    if len(positive_edges) >= 2:
        intervals = []
        for i in range(1, len(positive_edges)):
            interval = positive_edges[i] - positive_edges[i-1]
            if interval > 0:
                intervals.append(interval)
        
        if intervals:
            # Use minimum interval (handles gated clocks)
            period = min(intervals)
            # Phase offset is the time of the first positive edge
            phase_offset = positive_edges[0]
            return (period, phase_offset)
    
    # Fall back to any 2 transitions if not enough positive edges
    if len(all_changes) >= 2:
        period = all_changes[1][0] - all_changes[0][0]
        # For fallback, use first transition as phase
        phase_offset = all_changes[0][0]
        return (period, phase_offset) if period > 0 else None
    
    return None


def calculate_counter_clock_period(signal: WSignal, bit_width: int) -> Optional[tuple[Time, Time]]:
    """Calculate clock period and phase offset for bus/counter signals.
    
    Algorithm:
    1. Get first 2 signal changes with values
    2. Calculate: value_diff = value2 - value1, time_diff = time2 - time1
    3. Clock period = time_diff / value_diff (assumes monotonic counter)
    4. Validate result is positive integer
    5. Phase offset is 0 (counters start from 0)
    
    Returns:
        Tuple of (period, phase_offset) or None if calculation fails
    """
    changes = []
    change_iter = signal.all_changes()
    
    # Collect first 2 changes
    for _ in range(2):
        try:
            change = next(change_iter)
            changes.append(change)
        except StopIteration:
            break
    
    # Need at least 2 changes
    if len(changes) < 2:
        return None
    
    time1, value1 = changes[0]
    time2, value2 = changes[1]
    
    # Try to parse values as integers
    try:
        # Handle various value formats (binary, hex, decimal)
        val1_str = str(value1)
        val2_str = str(value2)
        
        # Remove format prefixes if present
        if val1_str.startswith(('b', 'B')):
            int1 = int(val1_str[1:], 2)
        elif val1_str.startswith(('h', 'H', 'x', 'X')):
            int1 = int(val1_str[1:], 16)
        else:
            int1 = int(val1_str)
        
        if val2_str.startswith(('b', 'B')):
            int2 = int(val2_str[1:], 2)
        elif val2_str.startswith(('h', 'H', 'x', 'X')):
            int2 = int(val2_str[1:], 16)
        else:
            int2 = int(val2_str)
    except (ValueError, TypeError):
        return None
    
    # Calculate differences
    value_diff = int2 - int1
    time_diff = time2 - time1
    
    # Handle counter wraparound
    if value_diff < 0:
        max_value = (1 << bit_width) - 1
        value_diff = (int2 + max_value + 1) - int1
    
    # Calculate period
    if value_diff > 0 and time_diff > 0:
        period = time_diff // value_diff
        if period > 0:
            # Counters typically start from 0, so phase offset is 0
            return (period, 0)
    
    return None


def calculate_clock_period(signal: WSignal, var: WVar) -> Optional[tuple[Time, Time]]:
    """Calculate clock period and phase offset for any valid clock signal type.
    
    Determines the signal type and applies the appropriate algorithm.
    
    Returns:
        Tuple of (period, phase_offset) or None if calculation fails.
        For non-digital clocks, phase_offset is 0.
    """
    if not is_valid_clock_signal(var):
        return None
    
    var_type = var.var_type()
    
    # Event type signals
    if var_type == 'Event':  # Capital E for wellen enum
        return calculate_event_clock_period(signal)
    
    # Check bit width for digital signals
    bit_width = var.bitwidth()
    
    if bit_width is not None:
        if bit_width == 1:
            # 1-bit digital signal - returns (period, phase_offset)
            return calculate_digital_clock_period(signal)
        else:
            # Multi-bit bus/counter
            return calculate_counter_clock_period(signal, bit_width)
    
    # Default to digital clock if bitwidth not available
    return calculate_digital_clock_period(signal)