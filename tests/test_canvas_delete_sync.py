"""Test that WaveformCanvas properly syncs when nodes are deleted.

This module specifically tests the synchronization between the WaveformCanvas 
rendering component and the data model when nodes are deleted. Unlike the 
integration tests in test_delete_integration.py, these tests focus on the 
internal state of the canvas to ensure proper cleanup and rendering updates.

Key Testing Focus:
- Canvas's layout row maintenance
- Proper removal of deleted nodes from rendering pipeline
- Hierarchical deletion (groups with children)
- Canvas state consistency after deletion operations

Why This Matters:
The WaveformCanvas maintains its own list of visible nodes for efficient 
rendering. When nodes are deleted from the data model, the canvas must:
1. Remove the deleted nodes from its internal tracking
2. Update any cached rendering data
3. Ensure no stale references remain that could cause rendering errors

Test Scenarios:
1. Individual node deletion - Verify single nodes are removed from canvas
2. Group deletion - Ensure groups and all children are removed together

Technical Details:
- Directly calls widget._delete_selected_nodes() for focused testing
- Examines canvas._layout internal state
- Uses processEvents() to ensure signal propagation
- Complements integration tests by verifying implementation details

This is a white-box test that validates the canvas component's internal 
behavior, ensuring the rendering layer stays synchronized with the data model.
"""

import pytest
from pathlib import Path
from PySide6.QtCore import Qt, QCoreApplication, QItemSelectionModel
from PySide6.QtWidgets import QApplication
from wavescout import WaveScoutWidget, create_sample_session
from .test_utils import get_test_input_path, TestFiles


@pytest.fixture
def wave_widget(qtbot):
    """Create WaveScoutWidget with test data."""
    # Create widget
    widget = WaveScoutWidget()
    qtbot.addWidget(widget)
    
    # Create and set session
    # Use test utilities for proper path
    test_file = get_test_input_path(TestFiles.SWERV1_VCD)
    session = create_sample_session(str(test_file))
    widget.setSession(session)
    
    # Show widget
    widget.show()
    qtbot.waitExposed(widget)
    
    yield widget


def test_canvas_updates_on_node_deletion(wave_widget, qtbot):
    """Test that canvas properly updates when nodes are deleted."""
    canvas = wave_widget._canvas
    model = wave_widget.model
    
    # Get initial visible row count
    initial_count = len(canvas._layout.rows)
    print(f"\nInitial visible rows: {initial_count}")
    
    # Select first few nodes
    wave_widget._selection_model.clearSelection()
    nodes_to_delete = []
    
    for i in range(min(3, model.rowCount())):
        index = model.index(i, 0)
        node = model.data(index, Qt.UserRole)
        if node and not node.is_group:  # Don't delete groups for this test
            wave_widget._selection_model.select(index, QItemSelectionModel.Select)
            nodes_to_delete.append(node)
    
    delete_count = len(nodes_to_delete)
    print(f"Nodes to delete: {delete_count}")
    
    if delete_count > 0:
        # Delete the selected nodes
        wave_widget._delete_selected_nodes()
        
        # Let signals propagate
        qtbot.wait(50)
        QCoreApplication.processEvents()
        
        # Check that canvas visible nodes updated
        final_count = len(canvas._layout.rows)
        print(f"Final visible nodes: {final_count}")
        
        # Should have fewer visible nodes
        assert final_count == initial_count - delete_count, \
            f"Expected {initial_count - delete_count} nodes, got {final_count}"
        
        # Verify deleted nodes are not in canvas visible nodes
        for node in nodes_to_delete:
            row_sources = [row.source for row in canvas._layout.rows]
            assert node not in row_sources, \
                f"Deleted node {node.name} should not be in visible nodes"


def test_canvas_updates_on_group_deletion(wave_widget, qtbot):
    """Test that canvas updates when a group with children is deleted."""
    canvas = wave_widget._canvas
    model = wave_widget.model
    
    # Find a group to delete
    group_index = None
    group_node = None
    child_count = 0
    
    for i in range(model.rowCount()):
        index = model.index(i, 0)
        node = model.data(index, Qt.UserRole)
        if node and node.is_group and node.children:
            group_index = index
            group_node = node
            child_count = len(node.children)
            break
    
    if group_index and group_node:
        # Get initial count
        initial_count = len(canvas._layout.rows)
        print(f"\nInitial visible nodes: {initial_count}")
        print(f"Deleting group '{group_node.name}' with {child_count} children")
        
        # Select and delete the group
        wave_widget._selection_model.clearSelection()
        wave_widget._selection_model.select(group_index, QItemSelectionModel.Select)
        wave_widget._delete_selected_nodes()
        
        # Let signals propagate
        qtbot.wait(50)
        QCoreApplication.processEvents()
        
        # Check canvas updated
        final_count = len(canvas._layout.rows)
        print(f"Final visible nodes: {final_count}")
        
        # Should have removed group + all its children
        expected_removed = 1 + child_count
        assert final_count == initial_count - expected_removed, \
            f"Expected to remove {expected_removed} nodes, but count went from {initial_count} to {final_count}"
        
        # Verify group and children not in visible nodes
        row_sources = [row.source for row in canvas._layout.rows]
        assert group_node not in row_sources
        for child in group_node.children:
            assert child not in row_sources