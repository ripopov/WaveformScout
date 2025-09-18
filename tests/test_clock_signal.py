"""Tests for clock signal functionality."""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from PySide6.QtWidgets import QApplication

from wavescout.data_model import WaveformSession, SignalNode, DataFormat, DisplayFormat, RenderType, Time
from wavescout.clock_utils import (
    is_valid_clock_signal,
    calculate_event_clock_period,
    calculate_digital_clock_period,
    calculate_counter_clock_period,
    calculate_clock_period
)
from wavescout.waveform_controller import WaveformController
from wavescout.time_grid_renderer import TimeGridRenderer, TimeRulerConfig
from wavescout.persistence import save_session, load_session
import tempfile

# Import test utilities for proper file path handling
from .test_utils import get_test_input_path, TestFiles


class TestClockUtils:
    """Test clock utility functions."""
    
    def test_is_valid_clock_signal(self):
        """Test signal type validation for clock signals."""
        # Mock WVar objects
        wire_var = Mock()
        wire_var.var_type.return_value = 'Wire'  # Proper case for wellen
        assert is_valid_clock_signal(wire_var) == True
        
        event_var = Mock()
        event_var.var_type.return_value = 'Event'  # Proper case for wellen
        assert is_valid_clock_signal(event_var) == True
        
        string_var = Mock()
        string_var.var_type.return_value = 'String'  # Proper case for wellen
        assert is_valid_clock_signal(string_var) == False
        
        real_var = Mock()
        real_var.var_type.return_value = 'Real'  # Proper case for wellen
        assert is_valid_clock_signal(real_var) == False
    
    def test_calculate_event_clock_period(self):
        """Test clock period calculation for event signals."""
        # Mock signal with changes at times 100, 200, 300
        signal = Mock()
        signal.all_changes.return_value = iter([
            (100, 1),
            (200, 1),
            (300, 1)
        ])
        
        result = calculate_event_clock_period(signal)
        assert result is not None
        period, phase = result
        assert period == 100  # 200 - 100
        assert phase == 100  # First event
    
    def test_calculate_event_clock_period_insufficient_changes(self):
        """Test event clock with insufficient changes."""
        signal = Mock()
        signal.all_changes.return_value = iter([
            (100, 1)  # Only one change
        ])
        
        result = calculate_event_clock_period(signal)
        assert result is None
    
    def test_calculate_digital_clock_period(self):
        """Test clock period calculation for 1-bit digital signals."""
        # Mock signal with positive edges at 100, 200, 300, 400
        signal = Mock()
        signal.all_changes.return_value = iter([
            (50, '0'),
            (100, '1'),  # Positive edge
            (150, '0'),
            (200, '1'),  # Positive edge
            (250, '0'),
            (300, '1'),  # Positive edge
            (350, '0'),
            (400, '1'),  # Positive edge
        ])
        
        result = calculate_digital_clock_period(signal)
        assert result is not None
        period, phase = result
        assert period == 100  # Minimum interval between positive edges
        assert phase == 100  # First positive edge
    
    def test_calculate_digital_clock_period_gated(self):
        """Test gated clock detection."""
        # Mock signal with irregular positive edges (gated clock)
        signal = Mock()
        signal.all_changes.return_value = iter([
            (100, '0'),
            (200, '1'),  # Positive edge
            (300, '0'),
            (400, '1'),  # Positive edge (gap of 200)
            (500, '0'),
            (600, '1'),  # Positive edge (gap of 200)
            (700, '0'),
            (1000, '1'),  # Positive edge (gap of 400 - gated)
        ])
        
        result = calculate_digital_clock_period(signal)
        assert result is not None
        period, phase = result
        assert period == 200  # Minimum interval (ignores gated period)
        assert phase == 200  # First positive edge
    
    def test_calculate_counter_clock_period(self):
        """Test clock period calculation for counter signals."""
        # Mock counter that increments by 1 every 100 time units
        signal = Mock()
        signal.all_changes.return_value = iter([
            (1000, '10'),  # Decimal 10
            (1500, '15'),  # Decimal 15
        ])
        
        result = calculate_counter_clock_period(signal, 8)
        assert result is not None
        period, phase = result
        assert period == 100  # (1500-1000) / (15-10) = 100
        assert phase == 0  # Counters start at 0 phase
    
    def test_calculate_counter_clock_period_hex(self):
        """Test counter with hex values."""
        signal = Mock()
        signal.all_changes.return_value = iter([
            (1000, 'hA'),   # Hex A = 10
            (2000, 'h14'),  # Hex 14 = 20
        ])
        
        result = calculate_counter_clock_period(signal, 8)
        assert result is not None
        period, phase = result
        assert period == 100  # (2000-1000) / (20-10) = 100
        assert phase == 0  # Counters start at 0 phase
    
    def test_calculate_clock_period_integration(self):
        """Test integrated clock period calculation."""
        # Test with event signal
        event_var = Mock()
        event_var.var_type.return_value = 'Event'  # Proper case
        event_signal = Mock()
        event_signal.all_changes.return_value = iter([(100, 1), (200, 1)])
        
        result = calculate_clock_period(event_signal, event_var)
        assert result is not None
        period, phase = result
        assert period == 100
        assert phase == 100  # First event
        
        # Test with 1-bit signal
        wire_var = Mock()
        wire_var.var_type.return_value = 'Wire'  # Proper case
        wire_var.bitwidth.return_value = 1  # Use bitwidth not width
        wire_signal = Mock()
        wire_signal.all_changes.return_value = iter([
            (0, '0'), (100, '1'), (200, '0'), (300, '1')
        ])
        
        result = calculate_clock_period(wire_signal, wire_var)
        assert result is not None
        period, phase = result
        assert period == 200  # Between positive edges
        assert phase == 100  # First positive edge
        
        # Test with invalid signal type
        string_var = Mock()
        string_var.var_type.return_value = 'String'  # Proper case
        
        result = calculate_clock_period(None, string_var)
        assert result is None


class TestWaveformController:
    """Test WaveformController clock signal management."""
    
    def test_set_clock_signal(self):
        """Test setting a clock signal."""
        # Create controller with mock session and database
        controller = WaveformController()
        session = WaveformSession()
        db = Mock()
        session.waveform_db = db
        controller.set_session(session)
        
        # Create a signal node
        node = SignalNode(
            name="clk",
            handle=1,
            format=DisplayFormat()
        )
        
        # Mock database methods
        var = Mock()
        var.var_type.return_value = 'Wire'  # Proper case
        var.bitwidth.return_value = 1  # Use bitwidth not width
        db.var_from_handle.return_value = var
        
        signal = Mock()
        signal.all_changes.return_value = iter([
            (0, '0'), (100, '1'), (200, '0'), (300, '1')
        ])
        db.signal_from_handle.return_value = signal
        
        # Set clock signal
        controller.set_clock_signal(node)
        
        # Verify clock signal was set
        assert session.clock_signal is not None
        clock_period, clock_phase, clock_node = session.clock_signal
        assert clock_period == 200  # Period between positive edges
        assert clock_phase == 100  # First positive edge at 100
        assert clock_node == node
    
    def test_clear_clock_signal(self):
        """Test clearing clock signal."""
        controller = WaveformController()
        session = WaveformSession()
        
        # Set a clock signal
        node = SignalNode(name="clk", handle=1, format=DisplayFormat())
        session.clock_signal = (100, 0, node)  # period, phase, node
        controller.set_session(session)
        
        # Clear clock signal
        controller.clear_clock_signal()
        
        # Verify it was cleared
        assert session.clock_signal is None
    
    def test_is_clock_signal(self):
        """Test checking if a node is the clock signal."""
        controller = WaveformController()
        session = WaveformSession()
        
        # Create two nodes
        clock_node = SignalNode(name="clk", handle=1, format=DisplayFormat())
        other_node = SignalNode(name="data", handle=2, format=DisplayFormat())
        
        # Set clock signal
        session.clock_signal = (100, 0, clock_node)  # period, phase, node
        controller.set_session(session)
        
        # Check
        assert controller.is_clock_signal(clock_node) == True
        assert controller.is_clock_signal(other_node) == False


class TestTimeGridRenderer:
    """Test TimeGridRenderer clock mode functionality."""
    
    def test_set_clock_signal(self):
        """Test setting clock parameters."""
        renderer = TimeGridRenderer()
        
        # Initially no clock
        assert renderer._clock_period is None
        assert renderer._clock_offset == 0
        
        # Set clock signal
        renderer.set_clock_signal(100, 10)
        assert renderer._clock_period == 100
        assert renderer._clock_offset == 10
        
        # Clear clock signal
        renderer.set_clock_signal(None)
        assert renderer._clock_period is None
    
    def test_calculate_clock_ticks(self, qapp):
        """Test tick calculation in clock mode.
        
        Args:
            qapp: QApplication fixture provided by pytest-qt
        """
        renderer = TimeGridRenderer()
        renderer.set_clock_signal(100, 0)  # 100 time units per clock, phase 0
        
        # Calculate ticks for viewport
        tick_infos, step_size = renderer._calculate_clock_ticks(
            viewport_start=0,
            viewport_end=1000,
            canvas_width=800
        )
        
        # Should have ticks at clock edges
        assert len(tick_infos) > 0
        
        # Check that ticks have both time and clock labels
        for tick in tick_infos:
            assert 'clock_label' in tick
            assert 'label' in tick
            assert tick['clock_label'] is not None
    
    def test_ruler_background_colors(self):
        """Test background color calculation for dual-row display."""
        renderer = TimeGridRenderer()
        
        # Test dark mode
        dark_base = "#1e1e1e"
        clock_bg, time_bg = renderer._get_ruler_background_colors(dark_base)
        assert clock_bg.lightness() > time_bg.lightness()  # Clock row lighter
        
        # Test light mode  
        light_base = "#f0f0f0"
        clock_bg, time_bg = renderer._get_ruler_background_colors(light_base)
        assert clock_bg.lightness() < time_bg.lightness()  # Clock row darker


class TestSessionPersistence:
    """Test clock signal persistence in session files."""
    
    def test_save_load_clock_signal(self):
        """Test saving and loading session with clock signal."""
        # Create session with clock signal
        session = WaveformSession()
        clock_node = SignalNode(
            name="clk",
            handle=1,
            format=DisplayFormat()
        )
        session.root_nodes = [clock_node]
        session.clock_signal = (100, 0, clock_node)  # period, phase, node
        
        # Save to temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = Path(f.name)
        
        try:
            save_session(session, temp_path)  # Correct parameter order
            
            # Load session
            loaded_session = load_session(temp_path)
            
            # Verify clock signal was restored
            assert loaded_session.clock_signal is not None
            clock_period, clock_phase, loaded_clock_node = loaded_session.clock_signal
            assert clock_period == 100
            assert clock_phase == 0  # Default phase
            assert loaded_clock_node.name == "clk"
            assert loaded_clock_node.instance_id == clock_node.instance_id
        finally:
            temp_path.unlink()  # Clean up
    
    def test_load_session_without_clock(self):
        """Test loading session without clock signal (backward compatibility)."""
        # Create session without clock signal
        session = WaveformSession()
        session.root_nodes = [
            SignalNode(name="data", handle=1, format=DisplayFormat())
        ]
        
        # Save to temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = Path(f.name)
        
        try:
            save_session(session, temp_path)  # Correct parameter order
            
            # Load session
            loaded_session = load_session(temp_path)
            
            # Verify no clock signal
            assert loaded_session.clock_signal is None
        finally:
            temp_path.unlink()  # Clean up


class TestRealWaveform:
    """Test clock signal functionality with real waveform files."""
    
    def test_apb_sim_clock_detection(self):
        """Test clock period detection on apb_sim.vcd file."""
        from wavescout.waveform_db import WaveformDB
        from wavescout.clock_utils import calculate_clock_period
        
        # Load the waveform using proper test utilities
        db = WaveformDB()
        test_file = get_test_input_path(TestFiles.APB_SIM_VCD)
        db.open(str(test_file))
        
        # Find the clock signal apb_testbench.pclk
        clock_handle = db.find_handle_by_path('apb_testbench.pclk')
        assert clock_handle is not None, "Clock signal apb_testbench.pclk not found"
        
        # Get the signal and variable
        signal = db.signal_from_handle(clock_handle)
        var = db.var_from_handle(clock_handle)
        
        assert signal is not None, "Could not get signal from handle"
        assert var is not None, "Could not get variable from handle"
        
        # Calculate clock period
        result = calculate_clock_period(signal, var)
        assert result is not None, "Clock period calculation failed"
        
        period, phase_offset = result
        
        # Verify the period is 100000 ps (100 ns)
        assert period == 100000, f"Expected period 100000, got {period}"
        
        # Verify the phase offset is 50000 ps (first positive edge)
        assert phase_offset == 50000, f"Expected phase offset 50000, got {phase_offset}"
        
        print(f"✓ Clock period: {period} ps")
        print(f"✓ Phase offset: {phase_offset} ps")
    
    def test_apb_sim_controller_integration(self):
        """Test setting apb_testbench.pclk as clock signal through controller."""
        from wavescout.waveform_db import WaveformDB
        from wavescout.waveform_controller import WaveformController
        from wavescout.data_model import WaveformSession, SignalNode, DisplayFormat
        
        # Create controller and session
        controller = WaveformController()
        session = WaveformSession()
        
        # Load the waveform using proper test utilities
        db = WaveformDB()
        test_file = get_test_input_path(TestFiles.APB_SIM_VCD)
        db.open(str(test_file))
        session.waveform_db = db
        controller.set_session(session)
        
        # Find the clock signal handle
        clock_handle = db.find_handle_by_path('apb_testbench.pclk')
        assert clock_handle is not None
        
        # Create a signal node for the clock
        clock_node = SignalNode(
            name="apb_testbench.pclk",
            handle=clock_handle,
            format=DisplayFormat()
        )
        
        # Set as clock signal
        controller.set_clock_signal(clock_node)
        
        # Verify it was set correctly
        assert session.clock_signal is not None, "Clock signal not set"
        clock_period, clock_phase, stored_node = session.clock_signal
        
        assert clock_period == 100000, f"Expected period 100000, got {clock_period}"
        assert clock_phase == 50000, f"Expected phase 50000, got {clock_phase}"
        assert stored_node == clock_node, "Clock node not stored correctly"
        
        # Test is_clock_signal method
        assert controller.is_clock_signal(clock_node) == True
        
        # Test clearing
        controller.clear_clock_signal()
        assert session.clock_signal is None, "Clock signal not cleared"


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])