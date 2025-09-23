"""Common test fixtures and utilities for WaveScout tests."""

import pytest
from pathlib import Path
from PySide6.QtWidgets import QApplication
from wavescout import create_sample_session, WaveScoutWidget
from wavescout.waveform_loader import create_signal_node_from_var
from wavescout.data_model import SignalNodeGroup
from .test_utils import get_test_input_path, TestFiles


@pytest.fixture(scope="session")
def qapp():
    """Create QApplication for tests that need Qt context."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def vcd_file():
    """Path to test VCD file."""
    return get_test_input_path(TestFiles.SWERV1_VCD)


@pytest.fixture
def vcd_session(vcd_file):
    """Create a session with VCD file loaded."""
    return create_sample_session(str(vcd_file))


def add_signals_from_vcd(session, count=10, include_groups=True):
    """Helper to add signals from the VCD file to the session."""
    if not session.waveform_db:
        return

    db = session.waveform_db
    hierarchy = db.hierarchy

    # Get actual signal handles from the database
    all_handles = list(db.get_all_handles())
    if not all_handles:
        return

    # Sort handles for consistent ordering
    all_handles.sort()

    # Add individual signals
    signals_added = 0
    for handle in all_handles[:count]:
        var = db.get_var(handle)
        if var:
            node = create_signal_node_from_var(var, hierarchy, handle)
            session.root_nodes.append(node)
            signals_added += 1

    # Add a group with some children if requested
    if include_groups and len(all_handles) > count:
        group = SignalNodeGroup(name="Test Group", is_expanded=True)

        # Add 3 children to the group
        for handle in all_handles[count:count + 3]:
            var = db.get_var(handle)
            if var:
                child = create_signal_node_from_var(var, hierarchy, handle)
                child.parent = group
                group.children.append(child)

        if group.children:
            session.root_nodes.append(group)


@pytest.fixture
def widget_with_signals(qtbot, vcd_session):
    """Create widget with VCD session and signals loaded."""
    widget = WaveScoutWidget()
    add_signals_from_vcd(vcd_session, count=10, include_groups=False)
    widget.setSession(vcd_session)
    
    # Show widget for testing
    widget.resize(800, 600)
    widget.show()
    qtbot.addWidget(widget)
    qtbot.waitExposed(widget)
    
    return widget


@pytest.fixture
def widget_with_groups(qtbot, vcd_session):
    """Create widget with VCD session including groups."""
    widget = WaveScoutWidget()
    add_signals_from_vcd(vcd_session, count=5, include_groups=True)
    widget.setSession(vcd_session)
    
    # Show widget for testing
    widget.resize(800, 600)
    widget.show()
    qtbot.addWidget(widget)
    qtbot.waitExposed(widget)
    
    return widget
