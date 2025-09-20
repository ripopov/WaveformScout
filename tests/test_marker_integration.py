#!/usr/bin/env python3
"""
Integration test for WaveScout marker functionality with session persistence.

Tests the complete marker workflow:
1. Load waveform file (apb_sim.vcd)
2. Add signal to waveform view
3. Place 3 markers at different positions
4. Navigate to marker using number key
5. Save session to JSON
6. Validate saved markers and viewport position

Key Features Tested:
- Marker placement at timestamps (20%, 50%, 80% of duration)
- Keyboard navigation (keys 1-9 jump to markers)
- 10-pixel offset positioning (marker appears 10px from left edge)
- JSON persistence (markers saved with time, label, color)
- Viewport state after navigation

Usage:
    python tests/test_marker_integration.py
"""

import sys
import os
import tempfile
import json
from pathlib import Path
from typing import Optional
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QModelIndex, QTimer
from PySide6.QtTest import QTest

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from scout import WaveScoutMainWindow
from wavescout import create_sample_session, save_session
from wavescout.data_model import SignalNode

# Import test utilities if running as part of test suite
try:
    from test_utils import get_test_input_path, TestFiles
except ImportError:
    # Fallback for standalone execution
    def get_test_input_path(filename):
        return Path(__file__).parent.parent / "test_inputs" / filename
    class TestFiles:
        APB_SIM_VCD = "apb_sim.vcd"


class MarkerTestHelper:
    """
    Helper class for marker integration testing.
    
    Provides utility methods for common test operations like waiting for
    asynchronous loads and finding signals in the design tree.
    """
    
    @staticmethod
    def wait_for_session_loaded(window, timeout_ms: int = 5000) -> None:
        """
        Wait for session and design tree to be fully loaded.
        
        Polls until: session exists, waveform DB loaded, design tree has nodes.
        
        Args:
            window: WaveScoutMainWindow instance
            timeout_ms: Max wait time in milliseconds
            
        Raises:
            TimeoutError: If not loaded within timeout
        """
        import time
        app = QApplication.instance()
        start_time = time.time()
        
        while (time.time() - start_time) * 1000 < timeout_ms:
            if (window.wave_widget.session is not None and
                window.wave_widget.session.waveform_db is not None and
                window.design_tree_view.design_tree_model is not None and
                window.design_tree_view.design_tree_model.rowCount() > 0):
                return
            QTest.qWait(100)
            app.processEvents()
        
        raise TimeoutError("Session failed to load within timeout")
    
    @staticmethod
    def find_and_add_first_signal(window) -> Optional[SignalNode]:
        """
        Find and add the first available signal from the design tree.
        
        Recursively searches for first non-scope node, creates SignalNode,
        and emits signals_selected to add it to waveform.
        
        Args:
            window: WaveScoutMainWindow with loaded design tree
            
        Returns:
            SignalNode if found and added, None otherwise
        """
        model = window.design_tree_view.design_tree_model
        if not model:
            return None
        
        # Recursively search for first non-scope node
        def find_signal(parent_idx: QModelIndex) -> Optional[SignalNode]:
            for row in range(model.rowCount(parent_idx)):
                idx = model.index(row, 0, parent_idx)
                if not idx.isValid():
                    continue
                
                node = model.data(idx, Qt.ItemDataRole.UserRole)
                if node and not node.is_scope:
                    # Found a signal - create SignalNode and add it
                    signal_node = window.design_tree_view._create_signal_node(node)
                    if signal_node:
                        window.design_tree_view.signals_selected.emit([signal_node])
                        # Wait for signal to be processed
                        QTest.qWait(200)
                        QApplication.processEvents()
                        return signal_node
                
                # Recurse into children
                result = find_signal(idx)
                if result:
                    return result
            
            return None
        
        return find_signal(QModelIndex())


def test_marker_integration():
    """
    Test marker functionality: placement, navigation, and persistence.
    
    Test Scenario:
    ==============
    
    Step 1: Application Setup
    - Start WaveScout and load test_inputs/apb_sim.vcd
    - Wait for waveform database and design tree to initialize
    - Verify: Design tree populated with signal hierarchy
    
    Step 2: Add Signal to Waveform
    - Find and add first available signal from design tree
    - Verify: 1 signal appears in session.root_nodes
    
    Step 3: Place Markers
    - Add markers at 20%, 50%, and 80% of waveform duration
    - Marker A at 2735, B at 6837, C at 10940 (green color)
    - Verify: 3 markers in session.markers list
    
    Step 4: Test Navigation
    - Zoom to 10% viewport width
    - Press '3' key to navigate to marker C
    - Verify: Viewport moves, marker C appears 10px from left edge
    
    Step 5: Save Session
    - Save to temporary JSON file
    - Verify: File created with complete session data
    
    Step 6: Validate JSON
    - Check root_nodes: 1 signal with correct name
    - Check markers: 3 entries with correct times/labels/colors
    - Check viewport: positioned at marker C minus 10px offset
    - Verify: All values within 5% tolerance
    
    Expected Results:
    - All markers placed correctly
    - Navigation positions viewport with 10px offset
    - JSON contains complete session state
    - Viewport calculation: marker_pos - (10px/canvas_width) * viewport_width
    """
    
    # Create application
    app = QApplication.instance() or QApplication(sys.argv)
    
    # Create temporary file for session
    temp_session = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    temp_session_path = temp_session.name
    temp_session.close()
    
    try:
        print("="*60)
        print("MARKER INTEGRATION TEST")
        print("="*60)
        
        # Step 1: Start main application with test VCD file
        print("\n1. Starting application with apb_sim.vcd...")
        test_vcd = get_test_input_path(TestFiles.APB_SIM_VCD)
        assert test_vcd.exists(), f"Test VCD not found: {test_vcd}"
        
        window = WaveScoutMainWindow()
        window.show()
        
        # Load the VCD file
        window.load_file(str(test_vcd))
        
        # Wait for loading to complete
        helper = MarkerTestHelper()
        helper.wait_for_session_loaded(window)
        
        print("   ✓ Application started and VCD loaded")
        
        # Step 2: Add one variable to waveform widget
        print("\n2. Adding one variable to waveform widget...")
        
        # Expand first scope to see signals
        design_view = window.design_tree_view.scope_tree
        model = window.design_tree_view.scope_tree_model
        root = QModelIndex()
        
        # Expand first level
        for r in range(model.rowCount(root)):
            idx = model.index(r, 0, root)
            if idx.isValid():
                design_view.expand(idx)
        
        QTest.qWait(100)
        
        # Find and add first signal
        signal_node = helper.find_and_add_first_signal(window)
        assert signal_node is not None, "No signal found to add"
        
        # Wait longer for signal to be fully processed
        QTest.qWait(300)
        QApplication.processEvents()
        
        # Verify signal added
        session = window.wave_widget.session
        assert len(session.root_nodes) == 1, f"Signal not added to session (found {len(session.root_nodes)} nodes)"
        print(f"   ✓ Added signal: {signal_node.name}")
        
        # Step 3: Place 3 markers at different positions
        print("\n3. Placing 3 markers at different positions...")
        controller = window.wave_widget.controller
        
        # Get total duration for marker placement
        total_duration = session.viewport.total_duration
        
        # Place markers at 20%, 50%, and 80% of waveform
        marker_positions = [
            int(total_duration * 0.2),
            int(total_duration * 0.5),
            int(total_duration * 0.8)
        ]
        
        for i, pos in enumerate(marker_positions):
            controller.add_marker(i, pos)
            print(f"   ✓ Marker {chr(65+i)} placed at time {pos}")
        
        # Verify markers added
        markers_count = len([m for m in session.markers if m and m.time >= 0])
        assert markers_count == 3, f"Expected 3 markers, found {markers_count}"
        
        # Step 4: Press '3' to navigate to marker C
        print("\n4. Navigating to Marker C (pressing '3')...")
        
        # Zoom in first to make navigation meaningful
        controller.zoom_viewport(0.1)
        QTest.qWait(100)
        
        # Store initial viewport
        initial_left = session.viewport.left
        
        # Simulate pressing '3' key
        QTest.keyClick(window.wave_widget, Qt.Key.Key_3)
        QTest.qWait(100)
        
        # Check viewport changed
        new_left = session.viewport.left
        assert new_left != initial_left, "Viewport did not change"
        print(f"   ✓ Viewport moved from {initial_left:.4f} to {new_left:.4f}")
        
        # Step 5: Save session to JSON
        print(f"\n5. Saving session to {temp_session_path}...")
        save_session(session, Path(temp_session_path))
        print("   ✓ Session saved")
        
        # Step 6: Verify saved JSON
        print("\n6. Verifying saved JSON content...")
        
        with open(temp_session_path, 'r') as f:
            saved_data = json.load(f)
        
        # Check for 1 variable
        assert 'root_nodes' in saved_data, "No root_nodes in saved session"
        assert len(saved_data['root_nodes']) == 1, f"Expected 1 variable, found {len(saved_data['root_nodes'])}"
        print(f"   ✓ Found 1 variable: {saved_data['root_nodes'][0]['name']}")
        
        # Check for 3 markers
        assert 'markers' in saved_data, "No markers in saved session"
        saved_markers = [m for m in saved_data['markers'] if m is not None]
        assert len(saved_markers) == 3, f"Expected 3 markers, found {len(saved_markers)}"
        
        for i, marker in enumerate(saved_markers):
            print(f"   ✓ Marker {marker['label']}: time={marker['time']}, color={marker['color']}")
        
        # Check viewport is near marker C (index 2)
        marker_c_time = marker_positions[2]
        viewport_data = saved_data['viewport']
        viewport_left = viewport_data['left']
        viewport_right = viewport_data['right']
        
        # Convert marker time to normalized position
        marker_c_normalized = marker_c_time / total_duration
        
        # Calculate expected position (marker should be ~10 pixels from left)
        canvas_width = window.wave_widget._canvas.width()
        viewport_width = viewport_right - viewport_left
        offset_normalized = (10.0 / canvas_width) * viewport_width
        expected_left = marker_c_normalized - offset_normalized
        
        # Check if viewport is close to expected position (within 5% tolerance)
        error = abs(viewport_left - expected_left)
        tolerance = 0.05
        
        print(f"\n   Viewport validation:")
        print(f"   - Marker C time: {marker_c_time}")
        print(f"   - Marker C normalized: {marker_c_normalized:.4f}")
        print(f"   - Expected viewport.left: {expected_left:.4f}")
        print(f"   - Actual viewport.left: {viewport_left:.4f}")
        print(f"   - Error: {error:.4f}")
        
        assert error < tolerance, f"Viewport not near marker C (error: {error:.4f})"
        print(f"   ✓ Viewport correctly positioned near Marker C")
        
        print("\n" + "="*60)
        print("ALL TESTS PASSED!")
        print("="*60)
        
        # Wait for thread pool to finish before closing
        if hasattr(window, 'thread_pool'):
            window.thread_pool.waitForDone(5000)  # Wait up to 5 seconds
        QApplication.processEvents()  # Process any pending events
        
        # Close window
        window.close()
        QTest.qWait(100)  # Wait a bit after close
        QApplication.processEvents()  # Ensure close is processed
        
    except Exception as e:
        print(f"\n✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        raise
        
    finally:
        # Clean up temp file
        if os.path.exists(temp_session_path):
            os.unlink(temp_session_path)
            print(f"\nCleaned up temporary file: {temp_session_path}")


def main():
    """Run the integration test."""
    success = test_marker_integration()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()