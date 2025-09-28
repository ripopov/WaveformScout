"""Unit tests for the reload waveform feature."""

import pytest
import tempfile
import os
from pathlib import Path
from typing import List, Dict, Any
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QModelIndex, Qt, QTimer
from PySide6.QtTest import QTest

from scout import WaveScoutMainWindow
from wavescout.data_model import SignalNode, SignalNodeSignal, DisplayFormat, RenderType, DataFormat
from wavescout.waveform_db import WaveformDB
from .test_utils import get_test_input_path, TestFiles, MockVar
from wavescout.waveform_loader import create_signal_node_from_var


class TestReloadFeature:
    """Test suite for waveform reload functionality with session preservation."""
    
    @pytest.fixture
    def app(self, qapp):
        """Provide QApplication instance."""
        return qapp
    
    def _wait_for_reload(self, window: WaveScoutMainWindow, timeout_ms: int = 2000) -> bool:
        """Wait for reload to complete by checking for session restoration.
        
        Returns True if reload completed successfully, False if timeout.
        """
        elapsed = 0
        interval = 50  # Check every 50ms
        
        # First wait for any existing session to be cleared (if applicable)
        QTest.qWait(100)
        
        # Then wait for new session to be loaded
        while elapsed < timeout_ms:
            if window.wave_widget.session is not None:
                # Session exists, check if it has been populated
                if window._loading_state.temp_reload_path is not None:
                    # Still loading
                    QTest.qWait(interval)
                    elapsed += interval
                else:
                    # Reload complete, give a small buffer for UI update
                    QTest.qWait(100)
                    return True
            else:
                QTest.qWait(interval)
                elapsed += interval
        
        return False
    
    @pytest.fixture
    def main_window(self, app):
        """Create main window with test waveform loaded."""
        test_file = str(get_test_input_path(TestFiles.APB_SIM_VCD))
        window = WaveScoutMainWindow(wave_file=test_file)
        
        # Wait for session to be created with shorter initial wait
        max_wait = 3000  # 3 seconds max (reduced from 7 seconds total)
        elapsed = 0
        while window.wave_widget.session is None and elapsed < max_wait:
            QTest.qWait(50)  # Check more frequently
            elapsed += 50
        
        # Give a small buffer for UI to stabilize
        if window.wave_widget.session:
            QTest.qWait(100)
        
        yield window
        
        # Cleanup
        window.close()
    
    def _add_signals_to_session(self, window: WaveScoutMainWindow, count: int = 3) -> List[str]:
        """Helper to add signals to the session.

        Returns list of signal names that were added.
        """
        # Get the waveform database
        if not window.wave_widget.session or not window.wave_widget.session.waveform_db:
            return []

        waveform_db = window.wave_widget.session.waveform_db
        hierarchy = waveform_db.hierarchy
        added_signals = []

        # Get signals through hierarchy
        if hierarchy:
            signal_vars = []

            def collect_vars(scope):
                for var in scope.vars(hierarchy):
                    signal_vars.append(var)
                for child_scope in scope.scopes(hierarchy):
                    collect_vars(child_scope)

            for top_scope in hierarchy.top_scopes():
                collect_vars(top_scope)

            # Add the first 'count' signals
            for i, var in enumerate(signal_vars):
                if i >= count:
                    break

                full_name = var.full_name(hierarchy)
                # Get handle for this signal
                handle = waveform_db.find_handle_by_path(full_name)
                if handle is not None:
                    # Create a SignalNode using the proper helper function
                    signal_node = create_signal_node_from_var(var, hierarchy, handle, waveform_db)

                    # Add to session
                    window.wave_widget.session.root_nodes.append(signal_node)
                    added_signals.append(full_name)

        # Force UI update
        if added_signals and window.wave_widget:
            window.wave_widget.update()
            QTest.qWait(20)  # Minimal wait for UI update

        return added_signals
    
    def _get_signal_properties(self, node: SignalNode) -> Dict[str, Any]:
        """Extract all relevant properties from a SignalNode for comparison."""
        from wavescout import SignalNodeSignal, SignalNodeGroup

        props = {
            'name': node.name,
            'nickname': node.nickname,
            'is_group': isinstance(node, SignalNodeGroup),
            'height_scaling': node.height_scaling,
            'instance_id': node.instance_id,
        }

        # Add signal-specific properties
        if isinstance(node, SignalNodeSignal):
            props['handle'] = node.handle
            props['is_multi_bit'] = node.is_multi_bit
            # Add format properties
            if node.format:
                props['format'] = {
                    'data_format': node.format.data_format,
                    'render_type': node.format.render_type,
                    'color': node.format.color,
                    'analog_scaling_mode': node.format.analog_scaling_mode,
                }
                # Add analog properties if they exist
                if hasattr(node.format, 'analog_min'):
                    props['format']['analog_min'] = node.format.analog_min
                if hasattr(node.format, 'analog_max'):
                    props['format']['analog_max'] = node.format.analog_max
            else:
                props['format'] = None

        # Add group-specific properties
        if isinstance(node, SignalNodeGroup):
            props['is_expanded'] = node.is_expanded
            props['group_render_mode'] = node.group_render_mode

        return props
    
    def _compare_signal_nodes(self, nodes_before: List[SignalNode], nodes_after: List[SignalNode]) -> bool:
        """Compare two lists of SignalNodes for equality of all properties."""
        if len(nodes_before) != len(nodes_after):
            print(f"Node count mismatch: {len(nodes_before)} vs {len(nodes_after)}")
            return False
        
        for i, (before, after) in enumerate(zip(nodes_before, nodes_after)):
            props_before = self._get_signal_properties(before)
            props_after = self._get_signal_properties(after)
            
            # Compare all properties except instance_id (which may change)
            for key in props_before:
                if key == 'instance_id':
                    continue  # Skip instance_id comparison
                
                if props_before[key] != props_after[key]:
                    print(f"Signal {i} property mismatch for '{key}':")
                    print(f"  Before: {props_before[key]}")
                    print(f"  After: {props_after[key]}")
                    return False
        
        return True
    
    def test_reload_preserves_signal_properties(self, main_window):
        """Test that reload preserves all signal properties through multiple cycles."""
        window = main_window
        
        # Verify file is loaded
        assert window.current_wave_file is not None
        assert window.wave_widget.session is not None
        
        # Add signals to session
        signal_names = self._add_signals_to_session(window, count=3)
        assert len(signal_names) >= 3, "Failed to add enough signals"
        
        QTest.qWait(50)  # Reduced from 200ms
        
        # Verify signals were added
        session = window.wave_widget.session
        assert len(session.root_nodes) >= 3
        
        # Modify signal properties
        # Signal 0: Change height scaling
        session.root_nodes[0].height_scaling = 2.5
        
        # Signal 1: Set to analog render mode
        session.root_nodes[1].format.render_type = RenderType.ANALOG
        session.root_nodes[1].height_scaling = 1.5
        
        # Signal 2: Change data format and height
        session.root_nodes[2].format.data_format = DataFormat.HEX
        session.root_nodes[2].height_scaling = 0.75
        session.root_nodes[2].nickname = "TestSignal"
        
        # Store initial state
        initial_nodes = [self._get_signal_properties(node) for node in session.root_nodes]
        
        # Perform multiple reload cycles
        for cycle in range(3):
            print(f"\nReload cycle {cycle + 1}")
            
            # Store state before reload
            nodes_before = [self._get_signal_properties(node) for node in session.root_nodes]
            
            # Trigger reload
            window.reload_waveform()
            
            # Wait for reload to complete with smart wait
            assert self._wait_for_reload(window, timeout_ms=2000), f"Reload timeout in cycle {cycle + 1}"
            
            # Verify session still exists
            assert window.wave_widget.session is not None, f"Session lost after reload {cycle + 1}"
            
            # Get state after reload
            session_after = window.wave_widget.session
            nodes_after = [self._get_signal_properties(node) for node in session_after.root_nodes]
            
            # Compare with state before reload
            assert len(nodes_after) == len(nodes_before), f"Signal count changed in cycle {cycle + 1}"
            
            # Verify all properties are preserved
            for i, (before, after) in enumerate(zip(nodes_before, nodes_after)):
                # Check name
                assert before['name'] == after['name'], f"Signal {i} name mismatch in cycle {cycle + 1}"
                
                # Check height scaling
                assert before['height_scaling'] == after['height_scaling'], \
                    f"Signal {i} height_scaling mismatch in cycle {cycle + 1}: {before['height_scaling']} != {after['height_scaling']}"
                
                # Check nickname
                assert before['nickname'] == after['nickname'], \
                    f"Signal {i} nickname mismatch in cycle {cycle + 1}"
                
                # Check format properties
                if before['format'] and after['format']:
                    assert before['format']['render_type'] == after['format']['render_type'], \
                        f"Signal {i} render_type mismatch in cycle {cycle + 1}"
                    assert before['format']['data_format'] == after['format']['data_format'], \
                        f"Signal {i} data_format mismatch in cycle {cycle + 1}"
                    
        
        # Final verification against initial state
        final_nodes = [self._get_signal_properties(node) for node in window.wave_widget.session.root_nodes]
        
        print("\nFinal verification against initial state:")
        for i, (initial, final) in enumerate(zip(initial_nodes, final_nodes)):
            print(f"Signal {i} ({initial['name']}):")
            print(f"  Height scaling: {initial['height_scaling']} -> {final['height_scaling']}")
            if initial['format'] and final['format']:
                print(f"  Render type: {initial['format']['render_type']} -> {final['format']['render_type']}")
                print(f"  Data format: {initial['format']['data_format']} -> {final['format']['data_format']}")
            if initial['nickname']:
                print(f"  Nickname: {initial['nickname']} -> {final['nickname']}")
        
        # Verify specific modifications are still present
        assert window.wave_widget.session.root_nodes[0].height_scaling == 2.5, \
            "Signal 0 height_scaling not preserved"
        assert window.wave_widget.session.root_nodes[1].format.render_type == RenderType.ANALOG, \
            "Signal 1 analog render mode not preserved"
        assert window.wave_widget.session.root_nodes[2].format.data_format == DataFormat.HEX, \
            "Signal 2 hex format not preserved"
        assert window.wave_widget.session.root_nodes[2].nickname == "TestSignal", \
            "Signal 2 nickname not preserved"
        
        print("\nAll signal properties preserved through 3 reload cycles!")
    
    def test_reload_with_empty_session(self, main_window):
        """Test that reload works correctly with no signals in session."""
        window = main_window
        
        # Verify file is loaded but no signals added
        assert window.current_wave_file is not None
        assert window.wave_widget.session is not None
        assert len(window.wave_widget.session.root_nodes) == 0
        
        # Trigger reload
        window.reload_waveform()
        
        # Wait for reload with smart wait
        assert self._wait_for_reload(window, timeout_ms=1500), "Reload timeout"
        
        # Verify session still exists and is empty
        assert window.wave_widget.session is not None
        assert len(window.wave_widget.session.root_nodes) == 0
        
        print("Empty session reload successful!")
    
    def test_reload_with_markers_and_cursor(self, main_window):
        """Test that reload preserves markers and cursor position."""
        from wavescout.data_model import Marker
        
        window = main_window
        session = window.wave_widget.session
        
        # Add some signals
        self._add_signals_to_session(window, count=2)
        QTest.qWait(50)  # Reduced wait
        
        # Add markers
        session.markers = [
            Marker(time=150, label="Start"),
            Marker(time=750, label="End"),
            Marker(time=400, label="Middle")
        ]
        
        # Set cursor position
        session.cursor_time = 500
        
        # Store initial state
        initial_markers = [(m.time, m.label) for m in session.markers]
        initial_cursor = session.cursor_time
        
        # Perform reload
        window.reload_waveform()
        assert self._wait_for_reload(window, timeout_ms=1500), "Reload timeout"
        
        # Verify markers and cursor preserved
        session_after = window.wave_widget.session
        assert session_after is not None
        
        markers_after = [(m.time, m.label) for m in session_after.markers]
        cursor_after = session_after.cursor_time
        
        assert markers_after == initial_markers, "Markers not preserved"
        assert cursor_after == initial_cursor, "Cursor position not preserved"
        
        print("Markers and cursor position preserved!")
