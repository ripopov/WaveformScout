"""Test data format conversion functionality."""

import pytest
import math
import struct
import os
from pathlib import Path
from wavescout.signal_sampling import parse_signal_value
from wavescout.data_model import DataFormat
from wavescout.waveform_db import WaveformDB
from .test_utils import get_test_input_path, TestFiles
from wavescout.waveform_loader import create_signal_node_from_var


def test_parse_signal_value_unsigned():
    """Test unsigned integer formatting."""
    # 8-bit unsigned
    value_str, value_float, value_bool = parse_signal_value(255, DataFormat.UNSIGNED, 8)
    assert value_str == "255"
    assert value_float == 255.0
    assert value_bool == True
    
    # Zero value
    value_str, value_float, value_bool = parse_signal_value(0, DataFormat.UNSIGNED, 8)
    assert value_str == "0"
    assert value_float == 0.0
    assert value_bool == False
    
    # 32-bit unsigned
    value_str, value_float, value_bool = parse_signal_value(4294967295, DataFormat.UNSIGNED, 32)
    assert value_str == "4294967295"
    assert value_float == 4294967295.0
    assert value_bool == True


def test_parse_signal_value_signed():
    """Test signed integer formatting with 2's complement."""
    # Positive 8-bit value
    value_str, value_float, value_bool = parse_signal_value(127, DataFormat.SIGNED, 8)
    assert value_str == "127"
    assert value_float == 127.0
    assert value_bool == True
    
    # Negative 8-bit value (128 = -128 in 8-bit 2's complement)
    value_str, value_float, value_bool = parse_signal_value(128, DataFormat.SIGNED, 8)
    assert value_str == "-128"
    assert value_float == -128.0
    assert value_bool == True
    
    # -1 in 8-bit (255 = -1)
    value_str, value_float, value_bool = parse_signal_value(255, DataFormat.SIGNED, 8)
    assert value_str == "-1"
    assert value_float == -1.0
    assert value_bool == True
    
    # 16-bit signed
    value_str, value_float, value_bool = parse_signal_value(32768, DataFormat.SIGNED, 16)
    assert value_str == "-32768"
    assert value_float == -32768.0
    
    # 32-bit signed
    value_str, value_float, value_bool = parse_signal_value(2147483648, DataFormat.SIGNED, 32)
    assert value_str == "-2147483648"
    assert value_float == -2147483648.0


def test_parse_signal_value_hex():
    """Test hexadecimal formatting."""
    # 8-bit hex
    value_str, value_float, value_bool = parse_signal_value(255, DataFormat.HEX, 8)
    assert value_str == "FF"
    assert value_float == 255.0
    assert value_bool == True
    
    # 16-bit hex
    value_str, value_float, value_bool = parse_signal_value(0x1234, DataFormat.HEX, 16)
    assert value_str == "1234"
    assert value_float == 0x1234
    
    # 32-bit hex
    value_str, value_float, value_bool = parse_signal_value(0xDEADBEEF, DataFormat.HEX, 32)
    assert value_str == "DEADBEEF"
    assert value_float == 0xDEADBEEF
    
    # Zero in hex
    value_str, value_float, value_bool = parse_signal_value(0, DataFormat.HEX, 8)
    assert value_str == "00"
    assert value_float == 0.0
    assert value_bool == False


def test_parse_signal_value_binary():
    """Test binary formatting."""
    # 8-bit binary
    value_str, value_float, value_bool = parse_signal_value(0b10101010, DataFormat.BIN, 8)
    assert value_str == "0b10101010"
    assert value_float == 170.0
    assert value_bool == True
    
    # 4-bit binary with leading zeros
    value_str, value_float, value_bool = parse_signal_value(0b0101, DataFormat.BIN, 4)
    assert value_str == "0b0101"
    assert value_float == 5.0
    
    # 1-bit binary
    value_str, value_float, value_bool = parse_signal_value(1, DataFormat.BIN, 1)
    assert value_str == "0b1"
    assert value_bool == True
    
    value_str, value_float, value_bool = parse_signal_value(0, DataFormat.BIN, 1)
    assert value_str == "0b0"
    assert value_bool == False


def test_parse_signal_value_float32():
    """Test IEEE 754 float32 interpretation."""
    # Test positive float (1.0)
    # 1.0 in IEEE 754: 0x3F800000
    value_str, value_float, value_bool = parse_signal_value(0x3F800000, DataFormat.FLOAT, 32)
    assert value_str == "1.0"
    assert value_float == 1.0
    assert value_bool == True
    
    # Test negative float (-1.0)
    # -1.0 in IEEE 754: 0xBF800000
    value_str, value_float, value_bool = parse_signal_value(0xBF800000, DataFormat.FLOAT, 32)
    assert value_str == "-1.0"
    assert value_float == -1.0
    assert value_bool == True
    
    # Test zero
    value_str, value_float, value_bool = parse_signal_value(0x00000000, DataFormat.FLOAT, 32)
    assert value_str == "0.0"
    assert value_float == 0.0
    assert value_bool == False
    
    # Test pi approximation
    # pi ≈ 3.14159265 in IEEE 754: 0x40490FDB
    value_str, value_float, value_bool = parse_signal_value(0x40490FDB, DataFormat.FLOAT, 32)
    assert abs(value_float - 3.14159265) < 0.00001
    
    # Test NaN
    # NaN in IEEE 754: 0x7FC00000
    value_str, value_float, value_bool = parse_signal_value(0x7FC00000, DataFormat.FLOAT, 32)
    assert math.isnan(value_float)
    
    # Test infinity
    # +Inf in IEEE 754: 0x7F800000
    value_str, value_float, value_bool = parse_signal_value(0x7F800000, DataFormat.FLOAT, 32)
    assert math.isinf(value_float) and value_float > 0
    
    # Non-32-bit should fallback to unsigned
    value_str, value_float, value_bool = parse_signal_value(100, DataFormat.FLOAT, 16)
    assert value_str == "100"
    assert value_float == 100.0


def test_parse_signal_value_float_input():
    """Test that float inputs ignore DataFormat."""
    # Float input should pass through unchanged
    value_str, value_float, value_bool = parse_signal_value(3.14159, DataFormat.HEX, 32)
    assert value_str == "3.14159"
    assert value_float == 3.14159
    assert value_bool == True
    
    value_str, value_float, value_bool = parse_signal_value(0.0, DataFormat.SIGNED, 32)
    assert value_str == "0.0"
    assert value_float == 0.0
    assert value_bool == False


def test_parse_signal_value_string_input():
    """Test that string inputs ignore DataFormat."""
    # String input should pass through unchanged
    value_str, value_float, value_bool = parse_signal_value("HIGH", DataFormat.HEX, 32)
    assert value_str == "HIGH"
    assert math.isnan(value_float)
    assert value_bool == False
    
    value_str, value_float, value_bool = parse_signal_value("1", DataFormat.SIGNED, 32)
    assert value_str == "1"
    assert math.isnan(value_float)
    assert value_bool == True


def test_parse_signal_value_none():
    """Test handling of None values."""
    value_str, value_float, value_bool = parse_signal_value(None, DataFormat.HEX, 32)
    assert value_str == "UNDEFINED"
    assert math.isnan(value_float)
    assert value_bool == False


def test_with_vcd_file():
    """Test data format with actual VCD file."""
    # Use test utilities to get proper path
    vcd_file = get_test_input_path(TestFiles.ANALOG_SIGNALS_SHORT_VCD)
    
    # Skip test if file doesn't exist (though get_test_input_path will raise FileNotFoundError)
    if not vcd_file.exists():
        pytest.skip(f"Test VCD file not found: {vcd_file}")
    
    db = WaveformDB()
    db.open(str(vcd_file))
    
    # Get hierarchy
    hierarchy = db.hierarchy
    
    # Get all variables using public API
    handles_and_vars = db.iter_handles_and_vars()
    
    # Test a few signals with different formats
    for handle, var_list in handles_and_vars:
        # Skip if empty list
        if not var_list:
            continue
            
        # Use first variable in the list
        var = var_list[0]
        
        # Create signal node
        signal_node = create_signal_node_from_var(var, hierarchy, handle)
        
        # Get signal object
        signal_obj = db.get_signal(handle)
        if not signal_obj:
            continue
            
        # Get bit width
        var = db.get_var(handle)
        bit_width = var.bitwidth() if var else 32
        
        # Sample at time 0
        sig = db.signal_from_handle(handle)
        if not sig:
            continue
        qr = sig.query_signal(0)
        value = qr.value if qr.value is not None else None
        
        # Test different formats if value is an integer
        if isinstance(value, int):
            # Test all formats
            for data_format in [DataFormat.UNSIGNED, DataFormat.SIGNED, DataFormat.HEX, 
                               DataFormat.BIN, DataFormat.FLOAT]:
                value_str, value_float, value_bool = parse_signal_value(value, data_format, bit_width)
                
                # Basic checks
                assert value_str is not None
                assert not (math.isnan(value_float) and data_format in [DataFormat.UNSIGNED, DataFormat.SIGNED])
                assert isinstance(value_bool, bool)
                
                # Format-specific checks
                if data_format == DataFormat.HEX:
                    # Accept both prefixed and non-prefixed uppercase hex strings
                    assert (
                        value_str.startswith("0x") or value_str.startswith("0X") or
                        all(ch in "0123456789ABCDEF" for ch in value_str.upper())
                    )
                elif data_format == DataFormat.BIN:
                    assert value_str.startswith("0b")
                elif data_format in [DataFormat.UNSIGNED, DataFormat.SIGNED]:
                    # Should be a decimal number
                    assert value_str.lstrip('-').isdigit()
        
        # Limit to testing a few signals
        if handle > 5:
            break


if __name__ == "__main__":
    pytest.main([__file__, "-v"])