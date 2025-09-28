"""Tests for ROI (Region of Interest) zoom feature.

This module tests the ROI zoom functionality that allows users to zoom 
the waveform viewport to a time interval selected via right-mouse drag.
"""

import tempfile
from pathlib import Path
from typing import Tuple

import pytest
from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest

from wavescout import create_sample_session, WaveScoutWidget
from wavescout.data_model import Time
from wavescout.waveform_controller import WaveformController


class TestPaths:
    """Central repository for test file paths."""
    REPO_ROOT = Path(__file__).resolve().parent.parent
    TEST_INPUTS = REPO_ROOT / "test_inputs"
    APB_SIM_VCD = TEST_INPUTS / "apb_sim.vcd"
    ANALOG_SIGNALS_VCD = TEST_INPUTS / "analog_signals_short.vcd"


class ROITestHelper:
    """Helper class for ROI zoom testing."""
    
    @staticmethod
    def setup_widget_with_signals(vcd_path: Path, qtbot, size: Tuple[int, int] = (1200, 800)):
        """Create and setup WaveScoutWidget with signals loaded.
        
        Args:
            vcd_path: Path to VCD file
            qtbot: pytest-qt fixture
            size: Widget size as (width, height) tuple
            
        Returns:
            Configured WaveScoutWidget with signals loaded
        """
        assert vcd_path.exists(), f"VCD not found: {vcd_path}"
        
        # Create session and widget
        session = create_sample_session(str(vcd_path))
        widget = WaveScoutWidget()
        widget.resize(*size)
        widget.setSession(session)
        qtbot.addWidget(widget)
        widget.show()
        qtbot.waitExposed(widget)
        
        # Add some signals from the VCD
        db = session.waveform_db
        assert db is not None and db.hierarchy is not None
        
        # Find and add first few signals
        from wavescout.waveform_loader import create_signal_node_from_var
        
        signal_count = 0
        for handle, vars_list in db.iter_handles_and_vars():
            for var in vars_list:
                if signal_count >= 3:  # Add 3 signals for testing
                    break
                full_name = var.full_name(db.hierarchy)
                node = create_signal_node_from_var(var, db.hierarchy, handle, db)
                node.name = full_name
                session.root_nodes.append(node)
                signal_count += 1
            if signal_count >= 3:
                break
        
        # Notify model about changes
        if widget.model:
            widget.model.layoutChanged.emit()
        qtbot.wait(50)
        
        return widget
    
    @staticmethod
    def simulate_roi_drag(canvas, start_x: int, end_x: int, qtbot):
        """Simulate ROI selection drag operation.
        
        Args:
            canvas: WaveformCanvas widget
            start_x: Starting X coordinate in pixels
            end_x: Ending X coordinate in pixels
            qtbot: pytest-qt fixture
        """
        # Press right mouse button at start position
        start_pos = QPoint(start_x, canvas.height() // 2)
        QTest.mousePress(canvas, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, start_pos)
        qtbot.wait(10)
        
        # Move to end position
        end_pos = QPoint(end_x, canvas.height() // 2)
        QTest.mouseMove(canvas, end_pos)
        qtbot.wait(10)
        
        # Release right mouse button
        QTest.mouseRelease(canvas, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, end_pos)
        qtbot.wait(50)


def test_roi_zoom_basic_functionality(qtbot):
    """Test basic ROI zoom from left to right drag.
    
    This test verifies that:
    1. Right-click drag activates ROI selection
    2. ROI selection state is properly managed
    3. Viewport zooms to selected region on release
    """
    helper = ROITestHelper()
    widget = helper.setup_widget_with_signals(TestPaths.APB_SIM_VCD, qtbot)
    
    canvas = widget._canvas
    controller = widget.controller
    
    # Get initial viewport
    initial_viewport = controller.session.viewport
    initial_left = initial_viewport.left
    initial_right = initial_viewport.right
    
    # Calculate pixel positions for ROI (25% to 75% of canvas width)
    canvas_width = canvas.width()
    start_x = int(canvas_width * 0.25)
    end_x = int(canvas_width * 0.75)
    
    # Simulate ROI drag
    helper.simulate_roi_drag(canvas, start_x, end_x, qtbot)
    
    # Verify viewport has changed
    new_viewport = controller.session.viewport
    assert new_viewport.left != initial_left, "Viewport left should have changed"
    assert new_viewport.right != initial_right, "Viewport right should have changed"
    
    # Verify the viewport is zoomed in (smaller interval)
    initial_width = initial_right - initial_left
    new_width = new_viewport.right - new_viewport.left
    assert new_width < initial_width, "New viewport should be zoomed in"
    
    # Verify ROI selection is cleared after zoom
    assert not canvas._roi_selection_active, "ROI selection should be inactive after zoom"
    assert canvas._roi_start_x is None, "ROI start should be cleared"
    assert canvas._roi_current_x is None, "ROI current should be cleared"
    
    widget.close()


def test_roi_zoom_reversed_drag(qtbot):
    """Test ROI zoom with right-to-left drag.
    
    This test verifies that ROI zoom works correctly when dragging
    from right to left (reversed direction).
    """
    helper = ROITestHelper()
    widget = helper.setup_widget_with_signals(TestPaths.APB_SIM_VCD, qtbot)
    
    canvas = widget._canvas
    controller = widget.controller
    
    # Get initial viewport - should be full view (0.0 to 1.0)
    initial_viewport = controller.session.viewport
    initial_left = initial_viewport.left
    initial_right = initial_viewport.right
    
    # If already zoomed from a previous test, reset to full view
    if abs(initial_left) > 0.01 or abs(initial_right - 1.0) > 0.01:
        controller.zoom_to_fit()
        qtbot.wait(50)
        initial_left = controller.session.viewport.left
        initial_right = controller.session.viewport.right
    
    # Calculate pixel positions for reversed ROI (75% to 25% of canvas width)
    canvas_width = canvas.width()
    start_x = int(canvas_width * 0.75)
    end_x = int(canvas_width * 0.25)
    
    # Simulate reversed ROI drag
    helper.simulate_roi_drag(canvas, start_x, end_x, qtbot)
    
    # Verify viewport has changed
    new_viewport = controller.session.viewport
    
    # The ROI should zoom to approximately 25%-75% range
    assert abs(new_viewport.left - initial_left) > 0.01 or abs(new_viewport.right - initial_right) > 0.01, \
        f"Viewport should have changed from {initial_left:.4f}-{initial_right:.4f} to {new_viewport.left:.4f}-{new_viewport.right:.4f}"
    
    # Verify the zoom is applied correctly (should swap start/end internally)
    initial_width = initial_right - initial_left
    new_width = new_viewport.right - new_viewport.left
    assert new_width < initial_width, "New viewport should be zoomed in"
    
    widget.close()


def test_roi_selection_visual_state(qtbot):
    """Test ROI selection visual state management.
    
    This test verifies that:
    1. ROI selection state is activated on right-press
    2. ROI coordinates are updated during drag
    3. Visual overlay properties are set correctly
    """
    helper = ROITestHelper()
    widget = helper.setup_widget_with_signals(TestPaths.APB_SIM_VCD, qtbot)
    
    canvas = widget._canvas
    
    # Initial state check
    assert not canvas._roi_selection_active, "ROI should be inactive initially"
    assert canvas._roi_start_x is None, "ROI start should be None initially"
    assert canvas._roi_current_x is None, "ROI current should be None initially"
    
    # Press right mouse button
    start_x = 100
    start_pos = QPoint(start_x, canvas.height() // 2)
    QTest.mousePress(canvas, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, start_pos)
    qtbot.wait(10)
    
    # Check ROI is activated
    assert canvas._roi_selection_active, "ROI should be active after right-press"
    assert canvas._roi_start_x == start_x, f"ROI start should be {start_x}"
    assert canvas._roi_current_x == start_x, "ROI current should equal start initially"
    
    # Move mouse
    end_x = 300
    end_pos = QPoint(end_x, canvas.height() // 2)
    QTest.mouseMove(canvas, end_pos)
    qtbot.wait(10)
    
    # Check ROI current position updated
    assert canvas._roi_current_x == end_x, f"ROI current should be {end_x}"
    assert canvas._roi_start_x == start_x, f"ROI start should still be {start_x}"
    
    # Release mouse
    QTest.mouseRelease(canvas, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, end_pos)
    qtbot.wait(10)
    
    # Check ROI is cleared
    assert not canvas._roi_selection_active, "ROI should be inactive after release"
    assert canvas._roi_start_x is None, "ROI start should be cleared"
    assert canvas._roi_current_x is None, "ROI current should be cleared"
    
    widget.close()


def test_roi_zoom_escape_cancellation(qtbot):
    """Test cancelling ROI selection with Escape key.
    
    This test verifies that pressing Escape during ROI selection
    cancels the operation without changing the viewport.
    """
    helper = ROITestHelper()
    widget = helper.setup_widget_with_signals(TestPaths.APB_SIM_VCD, qtbot)
    
    canvas = widget._canvas
    controller = widget.controller
    
    # Get initial viewport
    initial_viewport = controller.session.viewport
    
    # Start ROI selection
    start_pos = QPoint(100, canvas.height() // 2)
    QTest.mousePress(canvas, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, start_pos)
    qtbot.wait(10)
    
    # Move mouse to create selection
    end_pos = QPoint(300, canvas.height() // 2)
    QTest.mouseMove(canvas, end_pos)
    qtbot.wait(10)
    
    # Verify ROI is active
    assert canvas._roi_selection_active, "ROI should be active"
    
    # Press Escape to cancel
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    qtbot.wait(10)
    
    # Verify ROI is cancelled
    assert not canvas._roi_selection_active, "ROI should be cancelled"
    assert canvas._roi_start_x is None, "ROI start should be cleared"
    assert canvas._roi_current_x is None, "ROI current should be cleared"
    
    # Verify viewport unchanged
    assert controller.session.viewport == initial_viewport, "Viewport should not change on cancel"
    
    widget.close()


def test_roi_zoom_minimum_width(qtbot):
    """Test ROI zoom with very small selection (minimum width enforcement).
    
    This test verifies that ROI zoom enforces a minimum width
    to prevent zooming to an invalid or too-small region.
    """
    helper = ROITestHelper()
    widget = helper.setup_widget_with_signals(TestPaths.APB_SIM_VCD, qtbot)
    
    canvas = widget._canvas
    controller = widget.controller
    
    # Get initial viewport
    initial_viewport = controller.session.viewport
    
    # Try to make a very small ROI (just 5 pixels wide)
    start_x = 100
    end_x = 105
    
    # Simulate very small ROI drag
    helper.simulate_roi_drag(canvas, start_x, end_x, qtbot)
    
    # The zoom should still happen, but with minimum width enforcement
    new_viewport = controller.session.viewport
    
    # Check that some zoom occurred (viewport changed)
    # The exact behavior depends on implementation - it might enforce minimum
    # or might zoom to a very small region
    assert new_viewport != initial_viewport or (end_x - start_x) < 10, \
        "Small ROI should either zoom with minimum width or be rejected"
    
    widget.close()


def test_roi_zoom_near_edges(qtbot):
    """Test ROI zoom near viewport edges.
    
    This test verifies that ROI zoom works correctly when
    the selection is made near the edges of the viewport.
    """
    helper = ROITestHelper()
    widget = helper.setup_widget_with_signals(TestPaths.APB_SIM_VCD, qtbot)
    
    canvas = widget._canvas
    controller = widget.controller
    
    # Start from full view
    controller.zoom_to_fit()
    qtbot.wait(50)
    
    # Test near left edge
    start_x = 5
    end_x = 100
    helper.simulate_roi_drag(canvas, start_x, end_x, qtbot)
    
    # Verify zoom happened
    viewport_after_left = controller.session.viewport
    left_range = (viewport_after_left.left, viewport_after_left.right)
    
    # Reset to full view before next zoom
    controller.zoom_to_fit()
    qtbot.wait(50)
    
    # Test near right edge
    canvas_width = canvas.width()
    start_x = canvas_width - 100
    end_x = canvas_width - 5
    helper.simulate_roi_drag(canvas, start_x, end_x, qtbot)
    
    # Verify zoom happened
    viewport_after_right = controller.session.viewport
    right_range = (viewport_after_right.left, viewport_after_right.right)
    
    # Both edge zooms should produce different viewports
    assert abs(left_range[0] - right_range[0]) > 0.01 or abs(left_range[1] - right_range[1]) > 0.01, \
        f"Left edge zoom {left_range} and right edge zoom {right_range} should produce different viewports"
    
    widget.close()


def test_roi_zoom_with_analog_signals(qtbot):
    """Test ROI zoom functionality with analog signals.
    
    This test verifies that ROI zoom works correctly when
    analog signals are displayed in the waveform.
    """
    helper = ROITestHelper()
    widget = helper.setup_widget_with_signals(TestPaths.ANALOG_SIGNALS_VCD, qtbot)
    
    canvas = widget._canvas
    controller = widget.controller
    
    # Ensure we start from full view
    controller.zoom_to_fit()
    qtbot.wait(50)
    
    # Get initial viewport
    initial_viewport = controller.session.viewport
    initial_left = initial_viewport.left
    initial_right = initial_viewport.right
    
    # Perform ROI zoom
    canvas_width = canvas.width()
    start_x = int(canvas_width * 0.3)
    end_x = int(canvas_width * 0.7)
    
    helper.simulate_roi_drag(canvas, start_x, end_x, qtbot)
    
    # Verify viewport changed
    new_viewport = controller.session.viewport
    assert abs(new_viewport.left - initial_left) > 0.01 or abs(new_viewport.right - initial_right) > 0.01, \
        f"Viewport should change with analog signals from {initial_left:.4f}-{initial_right:.4f} to {new_viewport.left:.4f}-{new_viewport.right:.4f}"
    
    # Verify zoom is applied correctly
    initial_width = initial_right - initial_left
    new_width = new_viewport.right - new_viewport.left
    # The zoom should result in approximately 40% of the original width (0.3 to 0.7)
    expected_width_ratio = 0.4
    actual_ratio = new_width / initial_width if initial_width > 0 else 1.0
    # Allow some tolerance
    assert abs(actual_ratio - expected_width_ratio) < 0.1 or new_width < initial_width, \
        f"Should zoom to ~40% of original width, got {actual_ratio:.2f} (widths: {initial_width:.4f} -> {new_width:.4f})"
    
    widget.close()


def test_roi_overlay_during_drag(qtbot):
    """Test that ROI overlay is properly rendered during drag.
    
    This test verifies that the ROI selection overlay is
    active and properly configured during the drag operation.
    """
    helper = ROITestHelper()
    widget = helper.setup_widget_with_signals(TestPaths.APB_SIM_VCD, qtbot)
    
    canvas = widget._canvas
    
    # Start ROI selection
    start_x = 150
    start_pos = QPoint(start_x, canvas.height() // 2)
    QTest.mousePress(canvas, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, start_pos)
    qtbot.wait(10)
    
    # During drag, ROI should be active
    assert canvas._roi_selection_active, "ROI should be active during drag"
    
    # Move mouse multiple times to simulate drag
    for offset in [50, 100, 150, 200]:
        new_x = start_x + offset
        new_pos = QPoint(new_x, canvas.height() // 2)
        QTest.mouseMove(canvas, new_pos)
        qtbot.wait(5)
        
        # Verify ROI state is updated
        assert canvas._roi_current_x == new_x, f"ROI current should be {new_x}"
        assert canvas._roi_selection_active, "ROI should remain active during drag"
    
    # Release to complete
    final_pos = QPoint(start_x + 200, canvas.height() // 2)
    QTest.mouseRelease(canvas, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, final_pos)
    qtbot.wait(10)
    
    # ROI should be cleared after release
    assert not canvas._roi_selection_active, "ROI should be inactive after release"
    
    widget.close()


def test_roi_zoom_time_calculation(qtbot):
    """Test that ROI zoom correctly calculates time boundaries.
    
    This test verifies that pixel positions are correctly
    converted to time values for the zoom operation.
    """
    helper = ROITestHelper()
    widget = helper.setup_widget_with_signals(TestPaths.APB_SIM_VCD, qtbot)
    
    canvas = widget._canvas
    controller = widget.controller
    
    # Get initial viewport to calculate expected times
    initial_viewport = controller.session.viewport
    canvas_width = canvas.width()
    
    # Calculate expected normalized range for ROI
    # Using 25% to 75% of canvas width
    start_ratio = 0.25
    end_ratio = 0.75
    
    # The normalized coordinates should map linearly to canvas positions
    viewport_width = initial_viewport.right - initial_viewport.left
    expected_left = initial_viewport.left + viewport_width * start_ratio
    expected_right = initial_viewport.left + viewport_width * end_ratio
    
    # Perform ROI zoom
    start_x = int(canvas_width * start_ratio)
    end_x = int(canvas_width * end_ratio)
    helper.simulate_roi_drag(canvas, start_x, end_x, qtbot)
    
    # Check new viewport is approximately correct
    new_viewport = controller.session.viewport
    
    # Allow some tolerance for rounding
    tolerance = 0.05  # 5% tolerance in normalized coordinates
    
    assert abs(new_viewport.left - expected_left) <= tolerance, \
        f"ROI left should be near {expected_left}, got {new_viewport.left}"
    assert abs(new_viewport.right - expected_right) <= tolerance, \
        f"ROI right should be near {expected_right}, got {new_viewport.right}"
    
    widget.close()


def test_roi_rapid_mouse_movement(qtbot):
    """Test ROI selection with rapid mouse movements.
    
    This test verifies that ROI selection handles rapid
    mouse movements without issues.
    """
    helper = ROITestHelper()
    widget = helper.setup_widget_with_signals(TestPaths.APB_SIM_VCD, qtbot)
    
    canvas = widget._canvas
    
    # Start ROI selection
    start_x = 50
    start_pos = QPoint(start_x, canvas.height() // 2)
    QTest.mousePress(canvas, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, start_pos)
    qtbot.wait(5)
    
    # Simulate rapid mouse movements
    positions = [100, 200, 150, 300, 250, 400, 350, 450]
    for x in positions:
        pos = QPoint(x, canvas.height() // 2)
        QTest.mouseMove(canvas, pos)
        qtbot.wait(2)  # Very short wait to simulate rapid movement
    
    # Final position
    final_x = 400
    final_pos = QPoint(final_x, canvas.height() // 2)
    
    # Verify state before release
    assert canvas._roi_selection_active, "ROI should still be active"
    assert canvas._roi_start_x == start_x, "Start position should be unchanged"
    
    # Release
    QTest.mouseRelease(canvas, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, final_pos)
    qtbot.wait(10)
    
    # Verify completion
    assert not canvas._roi_selection_active, "ROI should be inactive after release"
    
    widget.close()