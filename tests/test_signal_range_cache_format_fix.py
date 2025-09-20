"""Test for signal range cache invalidation when data format changes.

This test verifies that the signal range cache is properly invalidated when
switching between signed and unsigned data formats, ensuring that cached
min/max values are recomputed with the correct interpretation.
"""

import pytest
import math
from typing import Dict, Optional

from pyrox import SignalHandle

from wavescout.data_model import (
    SignalNodeID, AnalogScalingMode, DataFormat, 
    SignalRangeCache, DisplayFormat
)
from wavescout.signal_renderer import get_signal_range, compute_global_signal_range
from wavescout.signal_sampling import SignalDrawingData, SignalSample, ValueKind
from wavescout.protocols import WaveformDBProtocol


class MockQueryResult:
    """Mock query result from waveform database."""
    def __init__(self, value):
        self.value = value


class MockSignal:
    """Mock signal object for testing."""
    def __init__(self, values):
        self.values = values  # Dict of time -> value
    
    def query_signal(self, time: int):
        if time in self.values:
            return MockQueryResult(self.values[time])
        return None


class MockWaveformDB:
    """Mock waveform database for testing."""
    def __init__(self):
        self.signals = {}
        self.time_table = [0, 100, 200, 300, 400, 500]
        self.hierarchy = None  # Mock hierarchy - tests will use 32-bit default
    
    def add_signal(self, handle: SignalHandle, values: Dict[int, int]):
        self.signals[handle] = MockSignal(values)
    
    def get_signal(self, handle: SignalHandle):
        return self.signals.get(handle)
    
    def get_time_table(self):
        return self.time_table


def create_test_drawing_data(values: list[int]) -> SignalDrawingData:
    """Create test drawing data with the given values."""
    samples = []
    for i, value in enumerate(values):
        sample = SignalSample(
            value_kind=ValueKind.NORMAL,
            value_str=str(value),
            value_float=float(value),
            value_bool=value != 0,
            has_multiple_transitions=False
        )
        samples.append((i * 10, sample))  # x position, sample
    
    return SignalDrawingData(samples=samples)


def test_signal_range_cache_format_invalidation():
    """Test that cache is invalidated when data format changes."""
    instance_id: SignalNodeID = 1
    handle: SignalHandle = 42
    cache: Dict[SignalNodeID, SignalRangeCache] = {}
    
    # Create mock database with large value that differs in signed vs unsigned 32-bit  
    mock_db = MockWaveformDB()
    large_value = 2147483648  # 2^31 - this will be negative in signed 32-bit
    mock_db.add_signal(handle, {0: large_value, 100: large_value, 200: large_value})
    
    # Create test drawing data (this is just for fallback, not used in global scaling)
    drawing_data = create_test_drawing_data([255])  # This value differs in signed vs unsigned
    
    # First call with UNSIGNED format - using SCALE_TO_ALL_DATA to trigger global range computation
    min_val, max_val = get_signal_range(
        instance_id=instance_id,
        handle=handle,
        drawing_data=drawing_data,
        scaling_mode=AnalogScalingMode.SCALE_TO_ALL_DATA,
        signal_range_cache=cache,
        data_format=DataFormat.UNSIGNED,
        waveform_db=mock_db
    )
    
    # Should be cached now
    assert instance_id in cache
    assert cache[instance_id].data_format == DataFormat.UNSIGNED
    cached_unsigned_min = cache[instance_id].min
    cached_unsigned_max = cache[instance_id].max
    
    # For 2147483648 as unsigned: should be 2147483648.0 + 10% margin
    expected_max_unsigned = 2147483648.0 + (2147483648.0 * 0.1)
    assert abs(max_val - expected_max_unsigned) < 1e-6
    
    # Second call with SIGNED format - should invalidate cache
    min_val, max_val = get_signal_range(
        instance_id=instance_id,
        handle=handle, 
        drawing_data=drawing_data,
        scaling_mode=AnalogScalingMode.SCALE_TO_ALL_DATA,
        signal_range_cache=cache,
        data_format=DataFormat.SIGNED,
        waveform_db=mock_db
    )
    
    # Cache should have been updated
    assert cache[instance_id].data_format == DataFormat.SIGNED
    cached_signed_min = cache[instance_id].min
    cached_signed_max = cache[instance_id].max
    
    # For 2147483648 as signed 32-bit: should be -2147483648.0 + 10% margin
    # margin = abs(-2147483648) * 0.1 = 214748364.8
    # max = -2147483648 + 214748364.8 = -1932735283.2
    expected_max_signed = -2147483648.0 + (abs(-2147483648.0) * 0.1)
    assert abs(max_val - expected_max_signed) < 1e-6
    
    # Cached values should be different
    assert cached_unsigned_max != cached_signed_max
    assert cached_unsigned_min != cached_signed_min


def test_compute_global_signal_range_with_format():
    """Test that compute_global_signal_range respects data format."""
    # Create mock database with test signal
    mock_db = MockWaveformDB()
    handle: SignalHandle = 1
    
    # Add signal with large value that differs in signed vs unsigned 32-bit
    large_value = 2147483648  # 2^31 - this will be negative in signed 32-bit
    mock_db.add_signal(handle, {0: large_value, 100: large_value, 200: large_value})
    
    # Test unsigned interpretation
    min_unsigned, max_unsigned = compute_global_signal_range(
        handle, mock_db, DataFormat.UNSIGNED
    )
    # For 2147483648 unsigned, with 10% margin added
    expected_max_unsigned = 2147483648.0 + (2147483648.0 * 0.1) 
    expected_min_unsigned = 2147483648.0 - (2147483648.0 * 0.1)
    assert abs(max_unsigned - expected_max_unsigned) < 1e-6
    assert abs(min_unsigned - expected_min_unsigned) < 1e-6
    
    # Test signed interpretation (32-bit width)
    min_signed, max_signed = compute_global_signal_range(
        handle, mock_db, DataFormat.SIGNED
    )
    # For 32-bit signed: 2147483648 becomes -2147483648
    # With 10% margin: margin = abs(-2147483648) * 0.1
    expected_max_signed = -2147483648.0 + (abs(-2147483648.0) * 0.1)
    expected_min_signed = -2147483648.0 - (abs(-2147483648.0) * 0.1)
    assert abs(max_signed - expected_max_signed) < 1e-6
    assert abs(min_signed - expected_min_signed) < 1e-6
    
    # Values should be different
    assert max_unsigned != max_signed
    assert min_unsigned != min_signed


def test_cache_preserved_for_same_format():
    """Test that cache is preserved when format doesn't change."""
    instance_id: SignalNodeID = 2
    handle: SignalHandle = 43
    cache: Dict[SignalNodeID, SignalRangeCache] = {}
    
    drawing_data = create_test_drawing_data([100, 200])
    
    # First call
    get_signal_range(
        instance_id=instance_id,
        handle=handle,
        drawing_data=drawing_data,
        scaling_mode=AnalogScalingMode.SCALE_TO_VISIBLE_DATA,
        signal_range_cache=cache,
        data_format=DataFormat.UNSIGNED
    )
    
    # Store cache reference 
    original_cache_obj = cache[instance_id]
    
    # Second call with same format
    get_signal_range(
        instance_id=instance_id,
        handle=handle,
        drawing_data=drawing_data,
        scaling_mode=AnalogScalingMode.SCALE_TO_VISIBLE_DATA, 
        signal_range_cache=cache,
        data_format=DataFormat.UNSIGNED
    )
    
    # Should be same cache object (not recreated)
    assert cache[instance_id] is original_cache_obj
    assert cache[instance_id].data_format == DataFormat.UNSIGNED


def test_multiple_format_switches():
    """Test cache behavior through multiple format switches."""
    instance_id: SignalNodeID = 3
    handle: SignalHandle = 44
    cache: Dict[SignalNodeID, SignalRangeCache] = {}
    
    # Test data: value that has different signed/unsigned interpretation
    drawing_data = create_test_drawing_data([128])  # 128 unsigned, -128 signed (8-bit)
    
    formats_to_test = [
        DataFormat.UNSIGNED,
        DataFormat.SIGNED, 
        DataFormat.UNSIGNED,  # Back to unsigned
        DataFormat.SIGNED,    # Back to signed
    ]
    
    cache_objects = []
    
    for data_format in formats_to_test:
        get_signal_range(
            instance_id=instance_id,
            handle=handle,
            drawing_data=drawing_data,
            scaling_mode=AnalogScalingMode.SCALE_TO_VISIBLE_DATA,
            signal_range_cache=cache,
            data_format=data_format
        )
        
        # Verify format is correct
        assert cache[instance_id].data_format == data_format
        
        # Store cache object reference
        cache_objects.append(id(cache[instance_id]))
    
    # Each format change should create new cache object
    # unsigned -> signed: new object
    assert cache_objects[0] != cache_objects[1]
    # signed -> unsigned: new object  
    assert cache_objects[1] != cache_objects[2]
    # unsigned -> signed: new object
    assert cache_objects[2] != cache_objects[3]


def test_global_vs_viewport_cache_format_invalidation():
    """Test that both global and viewport caches respect format changes."""
    instance_id: SignalNodeID = 4
    handle: SignalHandle = 45
    cache: Dict[SignalNodeID, SignalRangeCache] = {}
    
    drawing_data = create_test_drawing_data([200])
    mock_db = MockWaveformDB()
    mock_db.add_signal(handle, {0: 200, 100: 200})
    
    # First: SCALE_TO_ALL_DATA with unsigned
    get_signal_range(
        instance_id=instance_id,
        handle=handle,
        drawing_data=drawing_data,
        scaling_mode=AnalogScalingMode.SCALE_TO_ALL_DATA,
        signal_range_cache=cache,
        data_format=DataFormat.UNSIGNED,
        waveform_db=mock_db
    )
    
    assert cache[instance_id].data_format == DataFormat.UNSIGNED
    # 200.0 with 10% margin = 200.0 + 20.0 = 220.0
    assert cache[instance_id].max == 220.0
    
    # Second: SCALE_TO_VISIBLE_DATA with unsigned (same format)
    get_signal_range(
        instance_id=instance_id,
        handle=handle,
        drawing_data=drawing_data,
        scaling_mode=AnalogScalingMode.SCALE_TO_VISIBLE_DATA,
        signal_range_cache=cache,
        data_format=DataFormat.UNSIGNED,
        waveform_db=mock_db,
        start_time=0,
        end_time=100
    )
    
    # Should have viewport cache now
    assert len(cache[instance_id].viewport_ranges) > 0
    
    # Third: Change to signed format
    get_signal_range(
        instance_id=instance_id,
        handle=handle,
        drawing_data=drawing_data,
        scaling_mode=AnalogScalingMode.SCALE_TO_ALL_DATA,
        signal_range_cache=cache,
        data_format=DataFormat.SIGNED,
        waveform_db=mock_db
    )
    
    # Cache should be invalidated and recreated
    assert cache[instance_id].data_format == DataFormat.SIGNED
    # For 32-bit signed: 200 stays 200 (it's within range)
    # With 10% margin: 200 + 20 = 220
    assert cache[instance_id].max == 220.0
    # Viewport cache should be empty for new cache
    assert len(cache[instance_id].viewport_ranges) == 0


if __name__ == "__main__":
    # Run tests individually for debugging
    test_signal_range_cache_format_invalidation()
    test_compute_global_signal_range_with_format() 
    test_cache_preserved_for_same_format()
    test_multiple_format_switches()
    test_global_vs_viewport_cache_format_invalidation()
    print("All tests passed!")
