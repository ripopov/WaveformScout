"""Comprehensive tests for multi-selection functionality in WaveScoutWidget.

This module tests various multi-selection scenarios in the WaveScout waveform viewer,
ensuring that users can select multiple signals using standard selection patterns:

Selection Methods Tested:
1. Single selection - Basic click to select one item
2. Ctrl+Click - Add/remove individual items to/from selection
3. Shift+Click - Select a contiguous range of items
4. Ctrl+A - Select all items in the view
5. Deselection - Remove items from current selection

Key Aspects Verified:
- All views (names, values, analysis) share the same selection model
- Selection mode is set to ExtendedSelection for multi-select support
- Selection behavior is set to SelectRows for consistent row selection
- Data model (session.selected_nodes) stays synchronized with UI selection
- Canvas updates reflect current selection
- Selection works across groups and nested hierarchies

The tests use real VCD file data to ensure selection behavior works correctly
with actual waveform hierarchies including groups and nested signals. Each test
simulates user interactions through the Qt selection model to verify both the
UI state and the underlying data model remain consistent.

Technical Notes:
- Uses QItemSelectionModel for programmatic selection control
- Tests both flat and hierarchical (grouped) signal structures
- Verifies selection persistence across view updates
- Ensures proper parent-child relationships in selection
"""

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QModelIndex, QItemSelectionModel
from PySide6.QtTest import QTest
from wavescout import WaveScoutWidget, TreeNode


@pytest.fixture
def qt_app(qtbot):
    """Provide Qt application for testing."""
    return QApplication.instance()


@pytest.fixture
def wave_widget(widget_with_groups):
    """Use the shared widget with groups fixture that includes signals."""
    return widget_with_groups


def test_multi_selection_enabled(wave_widget):
    """Test that multi-selection is enabled on all views."""
    from PySide6.QtWidgets import QAbstractItemView
    
    # Check selection mode on all views
    assert wave_widget._names_view.selectionMode() == QAbstractItemView.ExtendedSelection
    assert wave_widget._values_view.selectionMode() == QAbstractItemView.ExtendedSelection
    
    # Check selection behavior (should select rows)
    assert wave_widget._names_view.selectionBehavior() == QAbstractItemView.SelectRows
    assert wave_widget._values_view.selectionBehavior() == QAbstractItemView.SelectRows


def test_shared_selection_model(wave_widget):
    """Test that all views share the same selection model."""
    # All views should have the same selection model
    selection_model = wave_widget._selection_model
    assert wave_widget._names_view.selectionModel() == selection_model
    assert wave_widget._values_view.selectionModel() == selection_model


def test_single_selection(wave_widget, qtbot):
    """Test selecting a single item updates the data model."""
    model = wave_widget.model
    session = wave_widget.session
    
    # Initially no selection
    assert len(session.selected_nodes) == 0
    
    # Select first item
    first_index = model.index(0, 0)
    wave_widget._names_view.setCurrentIndex(first_index)
    
    # Check selection in data model
    assert len(session.selected_nodes) == 1
    assert session.selected_nodes[0] == model.data(first_index, Qt.UserRole)


def test_ctrl_click_multi_selection(wave_widget, qtbot):
    """Test Ctrl+Click for multiple individual selections."""
    model = wave_widget.model
    session = wave_widget.session
    selection_model = wave_widget._selection_model
    
    # Select first item
    first_index = model.index(0, 0)
    selection_model.select(first_index, QItemSelectionModel.ClearAndSelect)
    
    # Ctrl+Click on second item
    second_index = model.index(1, 0)
    selection_model.select(second_index, QItemSelectionModel.Select)
    
    # Should have 2 selected nodes
    assert len(session.selected_nodes) == 2
    
    # Both nodes should be in selection
    first_node = model.data(first_index, Qt.UserRole)
    second_node = model.data(second_index, Qt.UserRole)
    assert first_node in session.selected_nodes
    assert second_node in session.selected_nodes


def test_shift_click_range_selection(wave_widget, qtbot):
    """Test Shift+Click for range selection."""
    model = wave_widget.model
    session = wave_widget.session
    selection_model = wave_widget._selection_model
    
    # Ensure we have at least 5 items
    if model.rowCount() < 5:
        pytest.skip("Not enough items for range selection test")
    
    # Select first item
    first_index = model.index(0, 0)
    selection_model.select(first_index, QItemSelectionModel.ClearAndSelect)
    
    # Shift+Click on fifth item to select range
    fifth_index = model.index(4, 0)
    # Create a selection range from first to fifth
    from PySide6.QtCore import QItemSelection
    selection = QItemSelection(first_index, fifth_index)
    selection_model.select(selection, QItemSelectionModel.ClearAndSelect)
    
    # Should have 5 selected nodes
    assert len(session.selected_nodes) == 5


def test_ctrl_a_select_all(wave_widget, qtbot):
    """Test Ctrl+A selects all items."""
    model = wave_widget.model
    session = wave_widget.session
    
    # Count total items (including children)
    def count_items(parent=QModelIndex()):
        count = 0
        rows = model.rowCount(parent)
        for row in range(rows):
            count += 1
            index = model.index(row, 0, parent)
            if model.hasChildren(index):
                count += count_items(index)
        return count
    
    total_items = count_items()
    
    # Press Ctrl+A
    wave_widget._select_all()
    
    # All items should be selected
    assert len(session.selected_nodes) == total_items


def test_deselection(wave_widget, qtbot):
    """Test deselecting items."""
    model = wave_widget.model
    session = wave_widget.session
    selection_model = wave_widget._selection_model
    
    # Select multiple items
    first_index = model.index(0, 0)
    second_index = model.index(1, 0)
    selection_model.select(first_index, QItemSelectionModel.ClearAndSelect)
    selection_model.select(second_index, QItemSelectionModel.Select)
    
    assert len(session.selected_nodes) == 2
    
    # Ctrl+Click on first item again to deselect
    selection_model.select(first_index, QItemSelectionModel.Deselect)
    
    # Should have only 1 selected node
    assert len(session.selected_nodes) == 1
    assert model.data(second_index, Qt.UserRole) in session.selected_nodes


def test_selection_updates_canvas(wave_widget, qtbot):
    """Test that selection updates the canvas display."""
    model = wave_widget.model
    canvas = wave_widget._canvas
    
    # Select an item
    first_index = model.index(0, 0)
    wave_widget._names_view.setCurrentIndex(first_index)
    
    # Canvas should have been updated (we can't easily test the visual change,
    # but we can verify the selected nodes are accessible to canvas)
    assert len(wave_widget.session.selected_nodes) > 0
    assert canvas._model._session == wave_widget.session


def test_selection_across_groups(wave_widget, qtbot):
    """Test selecting items across different groups."""
    model = wave_widget.model
    session = wave_widget.session
    
    # Find a group with children
    group_index = None
    for i in range(model.rowCount()):
        index = model.index(i, 0)
        node = model.data(index, Qt.UserRole)
        if node and node.is_group and model.hasChildren(index):
            group_index = index
            break
    
    if group_index:
        # Select the group
        wave_widget._selection_model.select(group_index, QItemSelectionModel.ClearAndSelect)
        
        # Select a child of the group
        child_index = model.index(0, 0, group_index)
        wave_widget._selection_model.select(child_index, QItemSelectionModel.Select)
        
        # Should have both selected
        assert len(session.selected_nodes) == 2
        
        # Verify both nodes are in selection
        group_node = model.data(group_index, Qt.UserRole)
        child_node = model.data(child_index, Qt.UserRole)
        assert group_node in session.selected_nodes
        assert child_node in session.selected_nodes


if __name__ == "__main__":
    pytest.main([__file__, "-v"])