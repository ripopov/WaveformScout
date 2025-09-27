"""Signal analysis engine for computing statistical measurements on waveform signals."""

import math
from typing import List, Optional, Tuple, Any
from dataclasses import dataclass

from .data_model import SignalNodeSignal, Time
from .signal_sampling import parse_signal_value


@dataclass
class SignalStatistics:
    """Statistical measurements for a signal."""
    signal_name: str
    min_value: float
    max_value: float
    sum_value: float
    average_value: float
    sample_count: int


def compute_signal_statistics(
    waveform_db: Any,  # WaveformDB instance
    signal_node: SignalNodeSignal,
    sampling_times: List[Time],
    start_time: Time,
    end_time: Time
) -> SignalStatistics:
    """
    Compute statistical measurements for a signal.
    
    Args:
        waveform_db: The waveform database instance
        signal_node: The signal to analyze
        sampling_times: List of times at which to sample the signal
        start_time: Start of analysis interval
        end_time: End of analysis interval
    
    Returns:
        SignalStatistics with min, max, sum, average values
    """
    # Filter sampling times to be within the analysis interval
    valid_times = [t for t in sampling_times if start_time <= t <= end_time]
    
    if not valid_times:
        # No valid sampling points
        return SignalStatistics(
            signal_name=signal_node.name,
            min_value=0.0,
            max_value=0.0,
            sum_value=0.0,
            average_value=0.0,
            sample_count=0
        )
    
    # Get signal bit width for parsing
    var = signal_node.var
    if var:
        if hasattr(var, 'width'):
            bit_width = var.width()
        elif hasattr(var, 'bitwidth'):
            bit_width = var.bitwidth()
        else:
            bit_width = 1
    else:
        bit_width = 1
    
    # Sample signal at each valid time and collect statistics
    min_val = float('inf')
    max_val = float('-inf')
    sum_val = 0.0
    valid_count = 0
    
    for time in valid_times:
        # Get signal value at this time
        sig = signal_node.signal.get_signal_blocking()

        if sig is None:
            value = None
        else:
            qr = sig.query_signal(max(0, time))
            value = qr.value if qr.value is not None else None
        
        # Convert string numeric values to appropriate type
        if isinstance(value, str):
            # Try to convert to numeric type
            try:
                # Check if it's a float
                if '.' in value or 'e' in value.lower():
                    value = float(value)
                else:
                    # Integer value
                    value = int(value)
            except (ValueError, AttributeError):
                # Not a numeric string, keep as is (will be handled by parse_signal_value)
                pass
        
        # Parse the value using the signal's format
        _, value_float, _ = parse_signal_value(
            value, 
            signal_node.format.data_format,
            bit_width
        )
        
        # Skip NaN values (undefined/high-impedance)
        if value_float is not None and not math.isnan(value_float):
            min_val = min(min_val, value_float)
            max_val = max(max_val, value_float)
            sum_val += value_float
            valid_count += 1
    
    # Calculate average
    if valid_count > 0:
        avg_val = sum_val / valid_count
    else:
        # No valid samples found
        min_val = max_val = sum_val = avg_val = 0.0
    
    return SignalStatistics(
        signal_name=signal_node.name,
        min_value=min_val,
        max_value=max_val,
        sum_value=sum_val,
        average_value=avg_val,
        sample_count=valid_count
    )


def generate_sampling_times_period(
    start_time: Time,
    end_time: Time,
    period: Time
) -> List[Time]:
    """
    Generate regular sampling times based on a fixed period.
    
    Args:
        start_time: Start of interval
        end_time: End of interval
        period: Sampling period
    
    Returns:
        List of sampling times
    """
    if period <= 0:
        return []
    
    times = []
    current_time = start_time
    while current_time <= end_time:
        times.append(current_time)
        current_time += period
    
    return times


def generate_sampling_times_signal(
    waveform_db: Any,  # WaveformDB instance
    sampling_signal: SignalNodeSignal,
    start_time: Time,
    end_time: Time
) -> List[Time]:
    """
    Generate sampling times based on a signal's transitions.
    
    For 1-bit wire signals: Sample only on positive edges (0→1)
    For bus signals: Sample on every value change
    For event signals: Sample on every event occurrence
    
    Args:
        waveform_db: The waveform database instance
        sampling_signal: The signal to use for sampling
        start_time: Start of interval
        end_time: End of interval
    
    Returns:
        List of sampling times
    """
    # Get signal information
    if not sampling_signal.var:
        return []

    # Get bit width
    var = sampling_signal.var
    if hasattr(var, 'width'):
        bit_width = var.width()
    elif hasattr(var, 'bitwidth'):
        bit_width = var.bitwidth()
    else:
        bit_width = 1
    
    # Get all transitions in the interval
    transitions = waveform_db.transitions(sampling_signal.handle, start_time, end_time)
    
    if bit_width == 1:
        # For 1-bit signals, only use positive edges (0→1 transitions)
        sampling_times = []
        prev_value = None
        
        for time, value in transitions:
            if prev_value == '0' and value == '1':
                sampling_times.append(time)
            prev_value = value
        
        return sampling_times
    else:
        # For buses and event signals, use all transitions
        return [time for time, _ in transitions]


def sample_signal_value(
    waveform_db: Any,  # WaveformDB instance
    signal_node: SignalNodeSignal,
    time: Time
) -> Tuple[Optional[str], Optional[float], Optional[bool]]:
    """
    Sample a signal's value at a specific time.
    
    Args:
        waveform_db: The waveform database instance
        signal_node: The signal to sample
        time: The time at which to sample
    
    Returns:
        Tuple of (value_str, value_float, value_bool) from parse_signal_value
    """
    # Get signal value at the specified time
    sig = signal_node.signal.get_signal_blocking()

    if sig is None:
        value = None
    else:
        qr = sig.query_signal(max(0, time))
        value = qr.value if qr.value is not None else None
    
    # Convert string numeric values to appropriate type
    if isinstance(value, str):
        # Try to convert to numeric type
        try:
            # Check if it's a float
            if '.' in value or 'e' in value.lower():
                value = float(value)
            else:
                # Integer value
                value = int(value)
        except (ValueError, AttributeError):
            # Not a numeric string, keep as is (will be handled by parse_signal_value)
            pass
    
    # Get signal bit width for parsing
    var = signal_node.var
    if var:
        if hasattr(var, 'width'):
            bit_width = var.width()
        elif hasattr(var, 'bitwidth'):
            bit_width = var.bitwidth()
        else:
            bit_width = 1
    else:
        bit_width = 1
    
    # Parse and return the value
    return parse_signal_value(
        value,
        signal_node.format.data_format,
        bit_width
    )
