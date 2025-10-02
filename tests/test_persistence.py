"""Test persistence functionality for saving and loading sessions."""

import pytest
import tempfile
import pathlib
from wavescout import save_session, load_session, create_sample_session
from wavescout.core.data_model import (
    WaveformSession,
    TreeNode,
    GroupNode,
    SignalNode,
    DisplayFormat,
    DataFormat,
    Viewport,
    Marker,
    AnalysisMode,
    GroupRenderMode,
)
from wavescout.core.waveform_db import WaveformDB
from wavescout.core.waveform_loader import create_signal_node_from_var
from .test_utils import get_test_input_path, TestFiles


def create_test_session():
    """Create a test session with various signal configurations using real waveform."""
    # Create session from a small test VCD file
    vcd_path = get_test_input_path(TestFiles.APB_SIM_VCD)
    session = create_sample_session(str(vcd_path))

    # Get waveform database and add signals
    primary_file = session.get_primary_file()
    if not primary_file or not primary_file.waveform_db:
        raise RuntimeError("Failed to open waveform database")
    db = primary_file.waveform_db

    hierarchy = db.hierarchy
    all_handles = list(db.get_all_handles())
    all_handles.sort()  # For consistency

    # Add first signal as a simple signal
    if len(all_handles) >= 1:
        var1 = db.get_var(all_handles[0])
        if var1:
            node1 = create_signal_node_from_var(var1, hierarchy, all_handles[0], db)
            # Customize format
            node1.format.data_format = DataFormat.BIN
            node1.format.color = "#33C3F0"
            session.root_nodes.append(node1)

    # Add group with children
    if len(all_handles) >= 3:
        group = GroupNode(
            name="CPU",
            group_render_mode=GroupRenderMode.OVERLAPPED,
            is_expanded=False
        )

        # Add two children to the group
        var2 = db.get_var(all_handles[1])
        if var2:
            child1 = create_signal_node_from_var(var2, hierarchy, all_handles[1], db)
            child1.format.data_format = DataFormat.HEX
            child1.format.color = "#FF0000"
            child1.parent = group
            child1.nickname = "Program Counter"
            group.children.append(child1)

        var3 = db.get_var(all_handles[2])
        if var3:
            child2 = create_signal_node_from_var(var3, hierarchy, all_handles[2], db)
            child2.format.data_format = DataFormat.HEX
            child2.format.color = "#00FF00"
            child2.parent = group
            group.children.append(child2)

        session.root_nodes.append(group)

    # Set up viewport and other session properties
    time_table = db.get_time_table()
    if time_table and len(time_table) > 1:
        total_duration = time_table[-1]
        session.viewport.total_duration = total_duration
        # Show the middle 10% of the waveform
        session.viewport.left = 0.45
        session.viewport.right = 0.55

        # Set markers and cursor within visible range
        visible_start = int(total_duration * 0.45)
        visible_end = int(total_duration * 0.55)
        visible_mid = (visible_start + visible_end) // 2

        session.markers = [
            Marker(time=visible_start + (visible_end - visible_start) // 4, label="A", color="#FF0000"),
            Marker(time=visible_start + 3 * (visible_end - visible_start) // 4, label="B", color="#00FF00")
        ]
        session.cursor_time = visible_mid
        session.analysis_mode = AnalysisMode(
            mode="max",
            range_start=visible_start,
            range_end=visible_end
        )

    return session


def test_save_and_load_session():
    """Test saving and loading a session preserves all data."""
    original_session = create_test_session()
    
    # Save to temporary file
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        temp_path = pathlib.Path(f.name)
    
    try:
        # Save session
        save_session(original_session, temp_path)
        
        # Load session
        loaded_session = load_session(temp_path)
        
        # Verify basic properties
        assert len(loaded_session.root_nodes) == 2
        # Viewport values are dynamic based on actual waveform
        assert 0.4 <= loaded_session.viewport.left <= 0.5
        assert 0.5 <= loaded_session.viewport.right <= 0.6
        assert loaded_session.viewport.total_duration > 0
        # Verify cursor is within the viewport range
        assert loaded_session.viewport.start_time <= loaded_session.cursor_time <= loaded_session.viewport.end_time
        
        # Verify markers
        assert len(loaded_session.markers) == 2
        assert loaded_session.markers[0].label == "A"
        assert loaded_session.markers[1].label == "B"
        # Markers should be within the viewport
        assert loaded_session.viewport.start_time <= loaded_session.markers[0].time <= loaded_session.viewport.end_time
        assert loaded_session.viewport.start_time <= loaded_session.markers[1].time <= loaded_session.viewport.end_time

        # Verify analysis mode
        assert loaded_session.analysis_mode.mode == "max"
        # Analysis range should be the viewport range
        assert loaded_session.analysis_mode.range_start == loaded_session.viewport.start_time
        assert loaded_session.analysis_mode.range_end == loaded_session.viewport.end_time
        
        # Verify first node (simple signal)
        node1 = loaded_session.root_nodes[0]
        assert node1.handle is not None
        assert node1.format.data_format == DataFormat.BIN
        assert node1.format.color == "#33C3F0"
        assert not node1.is_group
        
        # Verify group node
        group = loaded_session.root_nodes[1]
        assert group.name == "CPU"
        assert group.is_group
        assert group.group_render_mode == GroupRenderMode.OVERLAPPED
        assert not group.is_expanded
        assert len(group.children) == 2
        
        # Verify children
        child1 = group.children[0]
        assert child1.handle is not None
        assert child1.nickname == "Program Counter"
        assert child1.format.data_format == DataFormat.HEX
        assert child1.format.color == "#FF0000"
        assert child1.parent == group

        child2 = group.children[1]
        assert child2.handle is not None
        assert child2.format.data_format == DataFormat.HEX
        assert child2.format.color == "#00FF00"
        assert child2.parent == group
        
    finally:
        # Clean up
        temp_path.unlink(missing_ok=True)


def test_save_session_with_waveform_db():
    """Test saving a session that has a waveform database reference."""
    # Create session from VCD file
    vcd_path = get_test_input_path(TestFiles.SWERV1_VCD)
    session = create_sample_session(str(vcd_path))

    # Save to temporary file
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        temp_path = pathlib.Path(f.name)

    try:
        # Save session
        save_session(session, temp_path)

        # Load session
        loaded_session = load_session(temp_path)

        # Verify waveform database is reconnected
        loaded_primary_file = loaded_session.get_primary_file()
        assert loaded_primary_file is not None
        assert loaded_primary_file.waveform_db is not None
        assert loaded_primary_file.waveform_db.file_path == str(vcd_path)

        # Verify signals are preserved
        assert len(loaded_session.root_nodes) == len(session.root_nodes)

        # Wait for any async signal loading to complete
        if loaded_primary_file.waveform_db and hasattr(loaded_primary_file.waveform_db, 'wait_for_signals'):
            # Collect all handles from loaded session
            handles = []
            def collect_handles(nodes):
                for node in nodes:
                    if isinstance(node, SignalNode) and node.handle is not None:
                        handles.append(node.handle)
                    if isinstance(node, GroupNode):
                        collect_handles(node.children)
            collect_handles(loaded_session.root_nodes)

            # Wait for signals to load
            if handles:
                loaded_primary_file.waveform_db.wait_for_signals(handles, timeout=5.0)

    finally:
        # Clean up
        temp_path.unlink(missing_ok=True)


def test_load_session_missing_waveform():
    """Test loading a session when waveform file is missing."""
    original_session = create_test_session()
    # Change the waveform database path to a non-existent file
    if original_session.waveform_files:
        original_session.waveform_files[0].file_path = "/nonexistent/path.vcd"

    # Save to temporary file
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        temp_path = pathlib.Path(f.name)

    try:
        # Save session
        save_session(original_session, temp_path)

        # Load session - should succeed but without waveform_db
        loaded_session = load_session(temp_path)

        # Verify session loads but waveform_files is empty (no files loaded)
        assert len(loaded_session.waveform_files) == 0
        assert loaded_session.get_primary_file() is None
        assert len(loaded_session.root_nodes) == 2

    finally:
        # Clean up
        temp_path.unlink(missing_ok=True)


def test_sampling_signal_persistence():
    """Test that sampling_signal is correctly saved and loaded."""
    # Create session from a test VCD file
    vcd_path = get_test_input_path(TestFiles.APB_SIM_VCD)
    session = create_sample_session(str(vcd_path))

    primary_file = session.get_primary_file()
    if not primary_file or not primary_file.waveform_db:
        raise RuntimeError("Failed to open waveform database")
    db = primary_file.waveform_db

    hierarchy = db.hierarchy
    all_handles = list(db.get_all_handles())
    all_handles.sort()

    # Add two signals
    if len(all_handles) >= 2:
        var1 = db.get_var(all_handles[0])
        var2 = db.get_var(all_handles[1])

        if var1 and var2:
            signal1 = create_signal_node_from_var(var1, hierarchy, all_handles[0], db)
            signal1.instance_id = 100
            signal2 = create_signal_node_from_var(var2, hierarchy, all_handles[1], db)
            signal2.instance_id = 200
            session.root_nodes = [signal1, signal2]
    else:
        pytest.skip("Not enough signals in test file")
    
    # Set sampling signal
    session.sampling_signal = signal2
    
    # Save session
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        temp_path = pathlib.Path(f.name)
    
    try:
        save_session(session, temp_path)
        
        # Load session
        loaded = load_session(temp_path)
        
        # Verify sampling signal is restored
        assert loaded.sampling_signal is not None, "Sampling signal should be restored"
        assert loaded.sampling_signal.instance_id == 200, "Sampling signal ID should match"
        
    finally:
        temp_path.unlink(missing_ok=True)


def test_sampling_signal_in_nested_group():
    """Test sampling_signal persistence when signal is in a nested group."""
    # Create session from a test VCD file
    vcd_path = get_test_input_path(TestFiles.APB_SIM_VCD)
    session = create_sample_session(str(vcd_path))

    primary_file = session.get_primary_file()
    if not primary_file or not primary_file.waveform_db:
        raise RuntimeError("Failed to open waveform database")
    db = primary_file.waveform_db

    hierarchy = db.hierarchy
    all_handles = list(db.get_all_handles())
    all_handles.sort()

    if len(all_handles) >= 1:
        # Create group with a child from real signal
        group = GroupNode(name='GROUP', instance_id=1000)

        var = db.get_var(all_handles[0])
        if var:
            child = create_signal_node_from_var(var, hierarchy, all_handles[0], db)
            child.parent = group
            child.instance_id = 1001
            group.children = [child]
    else:
        pytest.skip("Not enough signals in test file")
    
    session.root_nodes = [group]
    session.sampling_signal = child
    
    # Save and load
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        temp_path = pathlib.Path(f.name)
    
    try:
        save_session(session, temp_path)
        loaded = load_session(temp_path)
        
        # Verify
        assert loaded.sampling_signal is not None
        assert loaded.sampling_signal.instance_id == 1001
        assert loaded.sampling_signal.parent is not None
        assert loaded.sampling_signal.parent.name == 'GROUP'
        
    finally:
        temp_path.unlink(missing_ok=True)


def test_empty_session_persistence():
    """Test saving and loading an empty session."""
    empty_session = WaveformSession()
    
    # Save to temporary file
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        temp_path = pathlib.Path(f.name)
    
    try:
        # Save session
        save_session(empty_session, temp_path)
        
        # Load session
        loaded_session = load_session(temp_path)
        
        # Verify empty session
        assert len(loaded_session.root_nodes) == 0
        assert len(loaded_session.markers) == 0
        assert loaded_session.cursor_time == 0
        
    finally:
        # Clean up
        temp_path.unlink(missing_ok=True)
