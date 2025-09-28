"""Test WaveScoutWidget with real VCD file."""

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QModelIndex
from PySide6.QtTest import QTest
from wavescout import (
    WaveScoutWidget,
    WaveformItemModel,
    TreeNode,
    GroupNode,
    SignalNode,
    DisplayFormat,
    GroupRenderMode,
)
from wavescout.waveform_db import AsyncLoadedSignal
from .test_utils import get_test_input_path, TestFiles


@pytest.fixture
def qt_app(qtbot):
    """Provide Qt application for testing."""
    return QApplication.instance()


@pytest.fixture
def wave_widget(widget_with_groups):
    """Create WaveScoutWidget with loaded VCD."""
    # Use the widget_with_groups fixture which already has signals loaded
    return widget_with_groups


def test_widget_creation(wave_widget):
    """Test that WaveScoutWidget is created successfully."""
    assert wave_widget is not None
    assert wave_widget.session is not None
    assert wave_widget.model is not None


def test_three_panels_exist(wave_widget):
    """Test that the three panels exist (names, values, canvas)."""
    # Check that all views exist
    assert hasattr(wave_widget, '_names_view')
    assert hasattr(wave_widget, '_values_view')
    assert hasattr(wave_widget, '_canvas')
    
    # Check they are visible
    assert wave_widget._names_view.isVisible()
    assert wave_widget._values_view.isVisible()
    assert wave_widget._canvas.isVisible()


def test_model_has_signals(wave_widget):
    """Test that the model contains signals."""
    model = wave_widget.model
    
    # Check root level has items
    root_count = model.rowCount()
    assert root_count > 0, "Model should have at least one root item"
    
    # Print signal information for debugging
    print(f"\nModel has {root_count} root items:")
    for i in range(min(root_count, 5)):  # Print first 5
        index = model.index(i, 0)
        name = model.data(index, Qt.DisplayRole)
        print(f"  - {name}")


def test_signal_names_panel(wave_widget):
    """Test that signal names are displayed in the names panel."""
    names_view = wave_widget._names_view
    model = wave_widget.model
    
    # Check that the view has the model
    assert names_view.model() == model
    
    # Check first column is visible
    assert not names_view.isColumnHidden(0)
    
    # Check other columns are hidden
    for col in range(1, 4):
        assert names_view.isColumnHidden(col)
    
    # Get some signal names
    signal_names = []
    for i in range(min(model.rowCount(), 5)):
        index = model.index(i, 0)
        name = model.data(index, Qt.DisplayRole)
        if name:
            signal_names.append(name)
    
    assert len(signal_names) > 0, "Should have at least one signal name"
    print(f"\nSignal names in panel: {signal_names}")


def test_values_panel(wave_widget):
    """Test that values are displayed in the values panel."""
    values_view = wave_widget._values_view
    model = wave_widget.model
    
    # Check that the view has the model
    assert values_view.model() == model
    
    # Check that columns 1 and 2 are visible (Value and Format)
    assert not values_view.isColumnHidden(1)  # Value column
    assert not values_view.isColumnHidden(2)  # Format column
    
    # Check other columns are hidden
    for col in [0, 3]:  # Signal, Waveform columns should be hidden
        assert values_view.isColumnHidden(col)
    
    # Get some values
    values = []
    for i in range(min(model.rowCount(), 5)):
        index = model.index(i, 1)
        value = model.data(index, Qt.DisplayRole)
        if value is not None:  # Changed from if value: to handle 0 or empty string values
            values.append(value)
    
    print(f"\nValues at cursor: {values}")
    # Values may be empty depending on the cursor position and data, that's OK




def test_shared_scrollbar(wave_widget):
    """Test that views share the same scrollbar (names and values)."""
    # Get scrollbars from each view
    names_scroll = wave_widget._names_view.verticalScrollBar()
    values_scroll = wave_widget._values_view.verticalScrollBar()
    
    # Check they are the same object
    assert names_scroll == values_scroll
    assert names_scroll == wave_widget._shared_scrollbar


def test_cursor_interaction(wave_widget, qtbot):
    """Test cursor movement updates values."""
    canvas = wave_widget._canvas
    initial_cursor = wave_widget.session.cursor_time
    
    # Simulate click on canvas
    new_x = 100
    qtbot.mouseClick(canvas, Qt.LeftButton, pos=canvas.rect().center())
    
    # Check cursor changed
    assert wave_widget.session.cursor_time != initial_cursor


def test_signal_formats(wave_widget):
    """Test that signals have different display formats."""
    model = wave_widget.model
    formats_found = set()
    
    # Check formats of signals
    for i in range(model.rowCount()):
        index = model.index(i, 0)
        node = model.data(index, Qt.UserRole)
        if isinstance(node, TreeNode) and not node.is_group:
            formats_found.add(node.format.data_format)
    
    print(f"\nDisplay formats found: {formats_found}")
    assert len(formats_found) > 1, "Should have multiple display formats"


def test_group_handling(wave_widget):
    """Test that groups are handled correctly."""
    model = wave_widget.model
    
    # Find a group
    group_found = False
    for i in range(model.rowCount()):
        index = model.index(i, 0)
        node = model.data(index, Qt.UserRole)
        if isinstance(node, TreeNode) and node.is_group:
            group_found = True
            # Check group has children
            child_count = model.rowCount(index)
            assert child_count > 0, "Group should have children"
            print(f"\nFound group '{node.name}' with {child_count} children")
            break
    
    assert group_found, "Should have at least one group in the test data"


def test_expansion_sync(wave_widget, qtbot):
    """Test that expansion state is synchronized across views."""
    model = wave_widget.model
    
    # Find a group to expand
    group_index = None
    group_node = None
    for i in range(model.rowCount()):
        index = model.index(i, 0)
        node = model.data(index, Qt.UserRole)
        if isinstance(node, TreeNode) and node.is_group:
            group_index = index
            group_node = node
            break
    
    if group_index:
        # Initially should be expanded
        assert group_node.is_expanded == True
        
        # Collapse in names view
        wave_widget._names_view.collapse(group_index)
        
        # Check it's collapsed in values view
        assert not wave_widget._values_view.isExpanded(group_index)
        
        # Check data model is updated
        assert group_node.is_expanded == False
        
        # Expand in names view
        wave_widget._names_view.expand(group_index)
        
        # Check it's expanded in values view
        assert wave_widget._values_view.isExpanded(group_index)
        
        # Check data model is updated
        assert group_node.is_expanded == True


def test_canvas_collapsed_groups(wave_widget, qtbot):
    """Test that canvas correctly handles collapsed groups."""
    model = wave_widget.model
    canvas = wave_widget._canvas
    
    # Find a group
    group_index = None
    group_node = None
    for i in range(model.rowCount()):
        index = model.index(i, 0)
        node = model.data(index, Qt.UserRole)
        if isinstance(node, TreeNode) and node.is_group:
            group_index = index
            group_node = node
            break
    
    if group_index and group_node:
        # Count visible rows with group expanded
        expanded_count = len(canvas._layout.rows)

        # Collapse the group
        wave_widget._names_view.collapse(group_index)
        qtbot.wait(50)  # Let updates propagate

        # Count visible rows with group collapsed
        collapsed_count = len(canvas._layout.rows)

        # Should have fewer visible rows when collapsed
        assert collapsed_count < expanded_count, f"Expected fewer rows when collapsed: {collapsed_count} >= {expanded_count}"

        # Children of the group should not be in visible rows
        child_sources = [row.source for row in canvas._layout.rows]
        for child in group_node.children:
            assert child not in child_sources, f"Child {child.name} should not be visible when group is collapsed"

        # The group itself should still be visible
        assert group_node in child_sources, "Group should still be visible when collapsed"
        
        print(f"\nExpanded nodes: {expanded_count}, Collapsed nodes: {collapsed_count}")


def test_headers_visible(wave_widget):
    """Test that headers are visible in all panels."""
    # Check headers
    assert not wave_widget._names_view.isHeaderHidden()
    assert not wave_widget._values_view.isHeaderHidden()
    
    # Get header text
    model = wave_widget.model
    headers = []
    # The model has 4 columns: Signal, Value, Format, Waveform
    for col in range(4):
        header = model.headerData(col, Qt.Horizontal, Qt.DisplayRole)
        headers.append(header)
    
    assert headers == ["Signal", "Value", "Format", "Waveform"]
    print(f"\nHeaders: {headers}")


def test_create_group_from_selected(wave_widget, monkeypatch):
    """Test creating a group from selected nodes."""
    from PySide6.QtWidgets import QInputDialog
    
    model = wave_widget.model
    session = wave_widget.session
    
    # Find two signals to select
    signal_nodes = []
    for i in range(model.rowCount()):
        index = model.index(i, 0)
        node = model.data(index, Qt.UserRole)
        if isinstance(node, TreeNode) and not node.is_group:
            signal_nodes.append(node)
            if len(signal_nodes) >= 2:
                break
    
    assert len(signal_nodes) >= 2, "Need at least 2 signals for test"
    
    # Select the signals
    session.selected_nodes = signal_nodes.copy()
    initial_root_count = len(session.root_nodes)
    
    # Mock the QInputDialog to return a test group name
    monkeypatch.setattr(QInputDialog, 'getText', lambda *args, **kwargs: ("TestGroup", True))
    
    # Create group
    wave_widget._create_group_from_selected()
    
    # Check a new group was created
    assert len(session.root_nodes) == initial_root_count - len(signal_nodes) + 1
    
    # Find the new group
    new_group = None
    for node in session.root_nodes:
        if node.is_group and node.name == "TestGroup":
            new_group = node
            break
    
    assert new_group is not None, "New group should be created"
    assert len(new_group.children) == 2, "Group should contain 2 children"
    assert all(child in signal_nodes for child in new_group.children), "Group should contain selected signals"


def test_create_group_of_groups_preserves_hierarchy(wave_widget, monkeypatch):
    """Test creating a group from groups preserves the hierarchy."""
    from PySide6.QtWidgets import QInputDialog

    session = wave_widget.session

    # Get real signals from the loaded VCD file
    # The session should already have some signals loaded
    existing_signals = []
    for node in session.root_nodes:
        if not node.is_group:
            existing_signals.append(node)

    # Make sure we have enough signals for the test
    assert len(existing_signals) >= 5, f"Need at least 5 signals, got {len(existing_signals)}"

    # Create two groups with children using real signals
    # Group 1: G1 with first two signals
    g1 = GroupNode(name="G1", is_expanded=True, group_render_mode=GroupRenderMode.SEPARATE_ROWS)
    signal1 = existing_signals[0]
    signal2 = existing_signals[1]
    signal1.parent = g1
    signal2.parent = g1
    g1.children = [signal1, signal2]

    # Group 2: G2 with next three signals
    g2 = GroupNode(name="G2", is_expanded=True, group_render_mode=GroupRenderMode.SEPARATE_ROWS)
    signal3 = existing_signals[2]
    signal4 = existing_signals[3]
    signal5 = existing_signals[4]
    signal3.parent = g2
    signal4.parent = g2
    signal5.parent = g2
    g2.children = [signal3, signal4, signal5]

    # Clear existing nodes and set up our test scenario
    session.root_nodes = [g1, g2]
    wave_widget.model.layoutChanged.emit()
    
    # Select all nodes (simulating Ctrl+A)
    # This will select G1, signal1, signal2, G2, signal3, signal4, signal5
    all_nodes = [g1, signal1, signal2, g2, signal3, signal4, signal5]
    session.selected_nodes = all_nodes.copy()

    # Mock the QInputDialog to return a test group name
    monkeypatch.setattr(QInputDialog, 'getText', lambda *args, **kwargs: ("ParentGroup", True))

    # Create group (simulating 'g' key)
    wave_widget._create_group_from_selected()

    # Verify the structure
    assert len(session.root_nodes) == 1, "Should have only one root node (the new group)"

    new_group = session.root_nodes[0]
    assert new_group.is_group, "Root should be a group"
    assert new_group.name == "ParentGroup", "New group should have the specified name"

    # The new group should contain only G1 and G2 (not their children)
    assert len(new_group.children) == 2, "New group should contain only the two original groups"
    assert g1 in new_group.children, "G1 should be in new group"
    assert g2 in new_group.children, "G2 should be in new group"

    # G1 and G2 should still have their original children
    assert len(g1.children) == 2, "G1 should still have 2 children"
    assert signal1 in g1.children, "signal1 should still be in G1"
    assert signal2 in g1.children, "signal2 should still be in G1"

    assert len(g2.children) == 3, "G2 should still have 3 children"
    assert signal3 in g2.children, "signal3 should still be in G2"
    assert signal4 in g2.children, "signal4 should still be in G2"
    assert signal5 in g2.children, "signal5 should still be in G2"

    # Verify parent relationships
    assert g1.parent == new_group, "G1's parent should be the new group"
    assert g2.parent == new_group, "G2's parent should be the new group"
    assert signal1.parent == g1, "signal1's parent should still be G1"
    assert signal2.parent == g1, "signal2's parent should still be G1"


def test_create_group_cancel_dialog(wave_widget, monkeypatch):
    """Test canceling the group creation dialog."""
    from PySide6.QtWidgets import QInputDialog
    
    model = wave_widget.model
    session = wave_widget.session
    
    # Find two signals to select
    signal_nodes = []
    for i in range(model.rowCount()):
        index = model.index(i, 0)
        node = model.data(index, Qt.UserRole)
        if isinstance(node, TreeNode) and not node.is_group:
            signal_nodes.append(node)
            if len(signal_nodes) >= 2:
                break
    
    assert len(signal_nodes) >= 2, "Need at least 2 signals for test"
    
    # Select the signals
    session.selected_nodes = signal_nodes.copy()
    initial_root_count = len(session.root_nodes)
    initial_root_nodes = session.root_nodes.copy()
    
    # Mock the QInputDialog to simulate user canceling
    monkeypatch.setattr(QInputDialog, 'getText', lambda *args, **kwargs: ("", False))
    
    # Try to create group (should be cancelled)
    wave_widget._create_group_from_selected()
    
    # Check that no group was created
    assert len(session.root_nodes) == initial_root_count, "No new nodes should be created"
    assert session.root_nodes == initial_root_nodes, "Root nodes should remain unchanged"
    
    # Selected signals should still be selected
    assert session.selected_nodes == signal_nodes, "Selection should remain unchanged"


def test_create_group_empty_name_uses_default(wave_widget, monkeypatch):
    """Test that empty name in dialog still creates group with default name."""
    from PySide6.QtWidgets import QInputDialog
    
    model = wave_widget.model
    session = wave_widget.session
    
    # Find two signals to select
    signal_nodes = []
    for i in range(model.rowCount()):
        index = model.index(i, 0)
        node = model.data(index, Qt.UserRole)
        if isinstance(node, TreeNode) and not node.is_group:
            signal_nodes.append(node)
            if len(signal_nodes) >= 2:
                break
    
    assert len(signal_nodes) >= 2, "Need at least 2 signals for test"
    
    # Select the signals
    session.selected_nodes = signal_nodes.copy()
    initial_root_count = len(session.root_nodes)
    
    # Mock the QInputDialog to return empty string but OK clicked
    monkeypatch.setattr(QInputDialog, 'getText', lambda *args, **kwargs: ("", True))
    
    # Create group with empty name
    wave_widget._create_group_from_selected()
    
    # Check a new group was created with default name
    assert len(session.root_nodes) == initial_root_count - len(signal_nodes) + 1
    
    # Find the new group
    new_group = None
    for node in session.root_nodes:
        if node.is_group and node.name.startswith("Group"):
            new_group = node
            break
    
    assert new_group is not None, "New group should be created with default name"
    assert len(new_group.children) == 2, "Group should contain 2 children"
    assert all(child in signal_nodes for child in new_group.children), "Group should contain selected signals"


if __name__ == "__main__":
    # For manual testing
    from pathlib import Path
    from wavescout import create_sample_session
    
    app = QApplication([])
    
    vcd_file = get_test_input_path(TestFiles.SWERV1_VCD)
    session = create_sample_session(str(vcd_file))
    
    widget = WaveScoutWidget()
    widget.setSession(session)
    widget.resize(1200, 800)
    widget.show()
    
    app.exec()
