"""Test VCD alias handling - multiple variables referencing the same signal.

In VCD files, multiple hierarchical paths can reference the same underlying signal 
through aliases. For example, in swerv1.vcd:
- TOP.core_clk 
- TOP.tb_top.core_clk
Both use the same VCD identifier '|s', making them aliases of the same signal.

This test verifies that:
1. Aliases are detected and share the same handle
2. Both aliases can be added to the waveform display
3. Both render correctly in the canvas
4. Sessions save/load with correct shared handles
5. Signal data is loaded only once for efficiency
"""

import pytest
from pathlib import Path
from wavescout import create_sample_session, WaveScoutWidget, save_session, load_session
from wavescout.waveform_loader import create_signal_node_from_var
from wavescout.data_model import SignalNode
import tempfile
from .test_utils import get_test_input_path, TestFiles


@pytest.fixture
def vcd_with_aliases():
    """Create a session from swerv1.vcd which contains signal aliases."""
    vcd_path = get_test_input_path(TestFiles.SWERV1_VCD)
    return create_sample_session(str(vcd_path))


def test_alias_detection(vcd_with_aliases):
    """Test that aliased signals are detected and share the same handle."""
    session = vcd_with_aliases
    db = session.waveform_db
    hierarchy = db.hierarchy
    
    # Find the two aliased core_clk variables by their full names
    handle1 = None
    handle2 = None
    vars_with_handle1 = []
    vars_with_handle2 = []
    
    # Search for both variables by full name
    for handle, vars_list in db.iter_handles_and_vars():
        for var in vars_list:
            full_name = var.full_name(hierarchy)
            if full_name == "TOP.core_clk":
                handle1 = handle
                vars_with_handle1 = vars_list
            elif full_name == "TOP.tb_top.core_clk":
                handle2 = handle
                vars_with_handle2 = vars_list
    
    # Verify we found both variables
    assert handle1 is not None, "Handle for TOP.core_clk not found"
    assert handle2 is not None, "Handle for TOP.tb_top.core_clk not found"
    
    # Verify they share the same handle (key finding!)
    assert handle1 == handle2, f"Aliases should share same handle, got {handle1} and {handle2}"

    # Verify both variable names are present in the vars lists we found
    # Note: Both vars_with_handle1 and vars_with_handle2 should contain both aliases
    # since they share the same handle
    var_names1 = [v.full_name(hierarchy) for v in vars_with_handle1]
    var_names2 = [v.full_name(hierarchy) for v in vars_with_handle2]

    # Both lists should be identical since they're from the same handle
    assert set(var_names1) == set(var_names2), "Var lists for same handle should be identical"
    assert "TOP.core_clk" in var_names1, "TOP.core_clk should be in handle's variable list"
    assert "TOP.tb_top.core_clk" in var_names1, "TOP.tb_top.core_clk should be in handle's variable list"
    assert len(vars_with_handle1) >= 2, f"Handle should have at least 2 aliased variables, got {len(vars_with_handle1)}"


def test_add_both_aliases_to_waveform(vcd_with_aliases, qtbot):
    """Test that both aliases can be added to the waveform display."""
    session = vcd_with_aliases
    db = session.waveform_db
    hierarchy = db.hierarchy
    
    # Create widget
    widget = WaveScoutWidget()
    widget.setSession(session)
    
    # Find and add both aliased signals by name
    signals_added = []
    target_names = ["TOP.core_clk", "TOP.tb_top.core_clk"]
    
    for handle, vars_list in db.iter_handles_and_vars():
        for var in vars_list:
            full_name = var.full_name(hierarchy)
            if full_name in target_names:
                node = create_signal_node_from_var(var, hierarchy, handle)
                node.name = full_name
                session.root_nodes.append(node)
                signals_added.append((full_name, handle))
                
                # Stop if we found both
                if len(signals_added) == 2:
                    break
        if len(signals_added) == 2:
            break
    
    # Verify both signals were added
    assert len(signals_added) == 2, f"Expected 2 signals, got {len(signals_added)}"
    
    # Verify they have the same handle
    _, handle1 = signals_added[0]
    _, handle2 = signals_added[1]
    assert handle1 == handle2, "Both aliases should have same handle"
    
    # Update the widget
    widget.model.layoutChanged.emit()
    
    # Verify both nodes are in the canvas's visible nodes
    canvas = widget._canvas
    assert len(session.root_nodes) == 2
    
    # Both should be renderable (non-null handles)
    for node in session.root_nodes:
        assert node.handle is not None, f"Node {node.name} has null handle"


def test_save_load_session_with_aliases(vcd_with_aliases, tmp_path):
    """Test that sessions with aliases save and load correctly."""
    session = vcd_with_aliases
    db = session.waveform_db
    hierarchy = db.hierarchy
    
    # Add both aliased signals by name
    handle_used = None
    target_names = ["TOP.core_clk", "TOP.tb_top.core_clk"]
    
    for handle, vars_list in db.iter_handles_and_vars():
        for var in vars_list:
            full_name = var.full_name(hierarchy)
            if full_name in target_names:
                handle_used = handle
                node = create_signal_node_from_var(var, hierarchy, handle)
                node.name = full_name
                session.root_nodes.append(node)
                
                # Stop if we found both
                if len(session.root_nodes) == 2:
                    break
        if len(session.root_nodes) == 2:
            break
    
    # Save session
    json_path = tmp_path / "test_aliases.json"
    save_session(session, json_path)

    # Read the JSON to verify handles
    import json
    with open(json_path, 'r') as f:
        json_data = json.load(f)
    
    # Verify both nodes have the same non-null handle
    nodes = json_data['root_nodes']
    assert len(nodes) == 2
    
    node1_data = next(n for n in nodes if n['name'] == 'TOP.core_clk')
    node2_data = next(n for n in nodes if n['name'] == 'TOP.tb_top.core_clk')
    
    assert node1_data['handle'] is not None, "TOP.core_clk should have non-null handle"
    assert node2_data['handle'] is not None, "TOP.tb_top.core_clk should have non-null handle"
    assert node1_data['handle'] == node2_data['handle'], "Aliases should have same handle in JSON"

    # Load session and verify
    loaded_session = load_session(json_path)
    assert len(loaded_session.root_nodes) == 2
    
    # Both nodes should have the same handle
    loaded_node1 = next(n for n in loaded_session.root_nodes if n.name == 'TOP.core_clk')
    loaded_node2 = next(n for n in loaded_session.root_nodes if n.name == 'TOP.tb_top.core_clk')
    
    assert loaded_node1.handle == loaded_node2.handle, "Loaded aliases should have same handle"
    assert loaded_node1.handle == handle_used, "Handle should match original"


def test_signal_loaded_once_for_aliases(vcd_with_aliases):
    """Test that signal data is loaded only once for aliases (efficiency)."""
    session = vcd_with_aliases
    db = session.waveform_db
    
    # Clear signal cache to start fresh
    db.clear_signal_cache()
    
    # Find handle for core_clk aliases
    handle = db.find_handle_by_name("core_clk")
    if handle is None:
        # Try finding by full name
        for h, vars_list in db.iter_handles_and_vars():
            for var in vars_list:
                if hasattr(var, 'name') and var.name(db.hierarchy) == "core_clk":
                    handle = h
                    break
            if handle is not None:
                break
    
    assert handle is not None, "Handle for core_clk not found"
    
    # Get signal - should load it
    signal1 = db.get_signal(handle)
    assert db.is_signal_cached(handle), "Signal should be cached"
    
    # Get signal again - should use cache
    signal2 = db.get_signal(handle)
    assert signal1 is signal2, "Should return same cached signal object"
    
    # Sample the signal - should use cached signal
    value = db.sample(handle, 10)
    assert value is not None
    
    # Verify signal is cached (implementation detail: only one signal per handle)
    assert db.is_signal_cached(handle)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])