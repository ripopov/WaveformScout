"""Test persistence functionality for saving and loading sessions."""

import pytest
import tempfile
import pathlib
from wavescout import save_session, load_session, create_sample_session
from wavescout.data_model import (
    WaveformSession,
    SignalNode,
    SignalNodeGroup,
    SignalNodeSignal,
    DisplayFormat,
    DataFormat,
    Viewport,
    Marker,
    AnalysisMode,
    GroupRenderMode,
)
from .test_utils import get_test_input_path, TestFiles, MockVar


def create_test_session():
    """Create a test session with various signal configurations."""
    session = WaveformSession()
    
    # Add simple signal
    node1 = SignalNodeSignal(
        name="clk",
        var=MockVar("clk"),
        handle=1,
        format=DisplayFormat(
            data_format=DataFormat.BIN,
            color="#33C3F0"
        )
    )
    
    # Add group with children
    group = SignalNodeGroup(
        name="CPU",
        group_render_mode=GroupRenderMode.OVERLAPPED,
        is_expanded=False
    )
    
    child1 = SignalNodeSignal(
        name="pc[31:0]",
        var=MockVar("pc", 32),
        handle=2,
        format=DisplayFormat(
            data_format=DataFormat.HEX,
            color="#FF0000"
        ),
        parent=group,
        nickname="Program Counter"
    )
    
    child2 = SignalNodeSignal(
        name="instruction[31:0]",
        var=MockVar("instruction", 32),
        handle=3,
        format=DisplayFormat(
            data_format=DataFormat.HEX,
            color="#00FF00"
        ),
        parent=group
    )
    
    group.children = [child1, child2]
    
    # Set up session
    session.root_nodes = [node1, group]
    # Create viewport with new normalized coordinate system
    # Total duration is 10000, we want to show from 1000 to 2000 (10% of the waveform)
    session.viewport = Viewport()
    session.viewport.total_duration = 10000  # Total waveform duration
    session.viewport.left = 0.1   # 1000/10000 = 0.1
    session.viewport.right = 0.2  # 2000/10000 = 0.2
    session.markers = [
        Marker(time=1100, label="A", color="#FF0000"),
        Marker(time=1750, label="B", color="#00FF00")
    ]
    session.cursor_time = 1250
    session.analysis_mode = AnalysisMode(
        mode="max",
        range_start=1000,
        range_end=2000
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
        assert loaded_session.viewport.left == 0.1
        assert loaded_session.viewport.right == 0.2
        assert loaded_session.viewport.total_duration == 10000
        # Verify calculated properties
        assert loaded_session.viewport.start_time == 1000
        assert loaded_session.viewport.end_time == 2000
        assert loaded_session.cursor_time == 1250
        
        # Verify markers
        assert len(loaded_session.markers) == 2
        assert loaded_session.markers[0].time == 1100
        assert loaded_session.markers[0].label == "A"
        assert loaded_session.markers[1].time == 1750
        assert loaded_session.markers[1].label == "B"
        
        # Verify analysis mode
        assert loaded_session.analysis_mode.mode == "max"
        assert loaded_session.analysis_mode.range_start == 1000
        assert loaded_session.analysis_mode.range_end == 2000
        
        # Verify first node (simple signal)
        node1 = loaded_session.root_nodes[0]
        assert node1.name == "clk"
        assert node1.handle == 1
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
        assert child1.name == "pc[31:0]"
        assert child1.handle == 2
        assert child1.nickname == "Program Counter"
        assert child1.format.data_format == DataFormat.HEX
        assert child1.format.color == "#FF0000"
        assert child1.parent == group
        
        child2 = group.children[1]
        assert child2.name == "instruction[31:0]"
        assert child2.handle == 3
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
        assert loaded_session.waveform_db is not None
        assert loaded_session.waveform_db.file_path == str(vcd_path)

        # Verify signals are preserved
        assert len(loaded_session.root_nodes) == len(session.root_nodes)

        # Wait for any async signal loading to complete
        if loaded_session.waveform_db and hasattr(loaded_session.waveform_db, 'wait_for_signals'):
            # Collect all handles from loaded session
            handles = []
            def collect_handles(nodes):
                for node in nodes:
                    if isinstance(node, SignalNodeSignal) and node.handle is not None:
                        handles.append(node.handle)
                    if isinstance(node, SignalNodeGroup):
                        collect_handles(node.children)
            collect_handles(loaded_session.root_nodes)

            # Wait for signals to load
            if handles:
                loaded_session.waveform_db.wait_for_signals(handles, timeout=5.0)

    finally:
        # Clean up
        temp_path.unlink(missing_ok=True)


def test_load_session_missing_waveform():
    """Test loading a session when waveform file is missing."""
    original_session = create_test_session()
    # Set a fake waveform database path
    from wavescout.waveform_db import WaveformDB
    fake_db = WaveformDB()
    fake_db.uri = "/nonexistent/path.vcd"
    original_session.waveform_db = fake_db
    
    # Save to temporary file
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        temp_path = pathlib.Path(f.name)
    
    try:
        # Save session
        save_session(original_session, temp_path)
        
        # Load session - should succeed but without waveform_db
        loaded_session = load_session(temp_path)
        
        # Verify session loads but waveform_db is None
        assert loaded_session.waveform_db is None
        assert len(loaded_session.root_nodes) == 2
        
    finally:
        # Clean up
        temp_path.unlink(missing_ok=True)


def test_sampling_signal_persistence():
    """Test that sampling_signal is correctly saved and loaded."""
    # Create session with sampling signal
    session = WaveformSession()
    
    # Add signals
    signal1 = SignalNodeSignal(name='data', var=MockVar('data'), handle=1, instance_id=100)
    signal2 = SignalNodeSignal(name='clock', var=MockVar('clock'), handle=2, instance_id=200)
    session.root_nodes = [signal1, signal2]
    
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
        assert loaded.sampling_signal.name == 'clock', "Sampling signal name should match"
        assert loaded.sampling_signal.instance_id == 200, "Sampling signal ID should match"
        
    finally:
        temp_path.unlink(missing_ok=True)


def test_sampling_signal_in_nested_group():
    """Test sampling_signal persistence when signal is in a nested group."""
    session = WaveformSession()
    
    # Create group with children
    group = SignalNodeGroup(name='GROUP', instance_id=1000)
    child = SignalNodeSignal(name='child_signal', var=MockVar('child_signal'), handle=10, parent=group, instance_id=1001)
    group.children = [child]
    
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
        assert loaded.sampling_signal.name == 'child_signal'
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
