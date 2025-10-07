"""Comprehensive JETS file loading tests per integration plan.

NOTE: Phase 1 implementation provides basic JETS file loading.
Tests marked with @pytest.mark.skip require Phases 2-4:
- Phase 2: Full hierarchy exposure (Scope/Var iteration over JETS records)
- Phase 3: Signal loading and value generation  
- Phase 4: Complete integration with all edge cases

See docs/features/0054_jets_integration_plan.md for full specification.
"""
import pytest
from pathlib import Path
import pyrox
import json


def test_jets_file_loading():
    """Test loading JETS file (Phase 1)."""
    jets_file = Path(__file__).parent.parent / "jets" / "gpu_sim.jets"
    wf = pyrox.Waveform(str(jets_file))

    # Verify waveform was created
    assert wf is not None
    # JETS file loads successfully without error


def test_jets_file_detection():
    """Test that .jets extension is properly detected (Phase 1)."""
    jets_file = Path(__file__).parent.parent / "jets" / "gpu_sim.jets"

    # Should not raise an error
    wf = pyrox.Waveform(str(jets_file))
    assert wf is not None


def test_jets_record_class_exists():
    """Test that Record class is exported (Phase 1)."""
    # Record class should be available
    assert hasattr(pyrox, 'Record')


# =============================================================================
# PHASE 2+ TESTS - Hierarchy exposure implementation
# =============================================================================

def test_jets_hierarchy():
    """Test JETS hierarchy structure (Records as Scopes)."""
    jets_file = Path(__file__).parent.parent / "jets" / "gpu_sim.jets"
    wf = pyrox.Waveform(str(jets_file))
    hier = wf.hierarchy

    assert hier is not None
    assert hier.file_format() == "JETS"

    # Get top-level scopes (should be root records)
    top_scopes = list(hier.top_scopes())
    assert len(top_scopes) > 0

    # First scope should be a record
    first_scope = top_scopes[0]
    assert first_scope.is_record()
    assert first_scope.scope_type() == "record"

    # Get Record object
    record = first_scope.record()
    assert record is not None
    assert record.id == "host_prog"


def test_jets_hierarchy_navigation():
    """Test navigating JETS hierarchy (child scopes)."""
    jets_file = Path(__file__).parent.parent / "jets" / "gpu_sim.jets"
    wf = pyrox.Waveform(str(jets_file))
    hier = wf.hierarchy

    top_scopes = list(hier.top_scopes())
    root_scope = top_scopes[0]

    # Navigate to children
    child_scopes = list(root_scope.scopes(hier))
    assert len(child_scopes) > 0

    first_child = child_scopes[0]
    assert first_child.is_record()

    child_record = first_child.record()
    assert child_record is not None


def test_jets_record_properties():
    """Test Record object properties and methods."""
    jets_file = Path(__file__).parent.parent / "jets" / "gpu_sim.jets"
    wf = pyrox.Waveform(str(jets_file))
    hier = wf.hierarchy

    top_scopes = list(hier.top_scopes())
    record = top_scopes[0].record()

    # Test basic properties
    assert isinstance(record.id, str)
    assert record.parent_id is None
    assert isinstance(record.record_type, str)
    assert isinstance(record.clk, int)
    assert isinstance(record.name, str)

    # Test time conversion
    assert isinstance(record.start_time_us(), int)
    assert record.start_time_us() >= 0


def test_jets_annotations_and_events():
    """Test annotation and event parsing."""
    jets_file = Path(__file__).parent.parent / "jets" / "gpu_sim.jets"
    wf = pyrox.Waveform(str(jets_file))
    hier = wf.hierarchy

    record = find_record_by_id(hier, "gte")
    assert record is not None

    annotations = record.annotations()
    assert len(annotations) >= 3

    annotation_names = [a["name"] for a in annotations]
    assert "GridDimensions" in annotation_names


def test_jets_record_as_var():
    """Test that Records appear as Vars in scopes."""
    jets_file = Path(__file__).parent.parent / "jets" / "gpu_sim.jets"
    wf = pyrox.Waveform(str(jets_file))
    hier = wf.hierarchy

    top_scopes = list(hier.top_scopes())
    first_scope = top_scopes[0]

    vars_list = list(first_scope.vars(hier))
    assert len(vars_list) >= 1

    var = vars_list[0]
    var_type = var.var_type()
    assert "String" in var_type or "string" in var_type.lower()


def test_jets_signal_loading():
    """Test loading Record as Signal."""
    jets_file = Path(__file__).parent.parent / "jets" / "gpu_sim.jets"
    wf = pyrox.Waveform(str(jets_file))
    hier = wf.hierarchy

    top_scopes = list(hier.top_scopes())
    first_scope = top_scopes[0]
    vars_list = list(first_scope.vars(hier))

    assert len(vars_list) >= 1
    var = vars_list[0]

    signal_handle = var.signal_handle()
    signal = wf.get_signal_by_handle(signal_handle)

    changes = list(signal.all_changes())
    assert len(changes) > 0


def test_jets_signal_values_and_timestamps():
    """Test Record signal values and timestamp conversion."""
    jets_file = Path(__file__).parent.parent / "jets" / "gpu_sim.jets"
    wf = pyrox.Waveform(str(jets_file))
    hier = wf.hierarchy

    record = find_record_by_id(hier, "inst_warp_tb_000_1_0x0000")
    if record is None:
        pytest.skip("Test record not found")

    events = record.events()
    assert len(events) > 0

    scope = find_scope_by_record_id(hier, "inst_warp_tb_000_1_0x0000")
    assert scope is not None

    vars_list = list(scope.vars(hier))
    if len(vars_list) == 0:
        pytest.skip("No vars found")

    signal_handle = vars_list[0].signal_handle()
    signal = wf.get_signal_by_handle(signal_handle)

    changes = list(signal.all_changes())
    assert len(changes) > 0

    first_time, first_value = changes[0]
    value_obj = json.loads(first_value)
    assert "id" in value_obj or "name" in value_obj


def test_jets_signal_json_structure():
    """Test that signal values are valid JSON with expected fields."""
    jets_file = Path(__file__).parent.parent / "jets" / "gpu_sim.jets"
    wf = pyrox.Waveform(str(jets_file))
    hier = wf.hierarchy

    top_scopes = list(hier.top_scopes())
    first_scope = top_scopes[0]
    vars_list = list(first_scope.vars(hier))

    if len(vars_list) == 0:
        pytest.skip("No vars available")

    signal_handle = vars_list[0].signal_handle()
    signal = wf.get_signal_by_handle(signal_handle)

    changes = list(signal.all_changes())
    if len(changes) == 0:
        pytest.skip("No signal changes")

    _, first_value = changes[0]
    value_obj = json.loads(first_value)

    assert isinstance(value_obj, dict)
    assert len(value_obj) > 0


def test_jets_time_conversion():
    """Test clock cycle to microsecond conversion."""
    jets_file = Path(__file__).parent.parent / "jets" / "gpu_sim.jets"
    wf = pyrox.Waveform(str(jets_file))
    hier = wf.hierarchy

    record = find_record_by_id(hier, "host_prog")
    assert record is not None

    start_time = record.start_time_us()
    assert start_time >= 0
    assert start_time < 10


def test_jets_multiple_records():
    """Test that multiple records are loaded correctly."""
    jets_file = Path(__file__).parent.parent / "jets" / "gpu_sim.jets"
    wf = pyrox.Waveform(str(jets_file))
    hier = wf.hierarchy

    all_scopes = collect_all_scopes(hier)
    assert len(all_scopes) > 5

    for scope in all_scopes:
        assert scope.is_record()
        assert scope.scope_type() == "record"


def test_jets_event_timestamps():
    """Test that events have correct timestamps."""
    jets_file = Path(__file__).parent.parent / "jets" / "gpu_sim.jets"
    wf = pyrox.Waveform(str(jets_file))
    hier = wf.hierarchy

    record = find_record_by_id(hier, "inst_warp_tb_000_1_0x0000")
    if record is None:
        pytest.skip("Test record not found")

    events = record.events()
    if len(events) == 0:
        pytest.skip("No events")

    for event in events:
        assert "clk" in event
        assert isinstance(event["clk"], int)
        assert event["clk"] > 0


# Helper functions (used by skipped tests)

def find_record_by_id(hier: pyrox.Hierarchy, record_id: str):
    """Helper to find record by ID in hierarchy."""
    def search_scope(scope):
        if scope.is_record():
            record = scope.record()
            if record and record.id == record_id:
                return record

        for child_scope in scope.scopes(hier):
            result = search_scope(child_scope)
            if result:
                return result
        return None

    for top_scope in hier.top_scopes():
        result = search_scope(top_scope)
        if result:
            return result
    return None


def find_scope_by_record_id(hier: pyrox.Hierarchy, record_id: str):
    """Helper to find Scope wrapper for a Record by ID."""
    def search_scope(scope):
        if scope.is_record():
            record = scope.record()
            if record and record.id == record_id:
                return scope

        for child_scope in scope.scopes(hier):
            result = search_scope(child_scope)
            if result:
                return result
        return None

    for top_scope in hier.top_scopes():
        result = search_scope(top_scope)
        if result:
            return result
    return None


def collect_all_scopes(hier: pyrox.Hierarchy) -> list:
    """Collect all scopes recursively."""
    all_scopes = []

    def collect(scope):
        all_scopes.append(scope)
        for child in scope.scopes(hier):
            collect(child)

    for top_scope in hier.top_scopes():
        collect(top_scope)

    return all_scopes


def test_jets_wavescout_main_window_integration(qtbot):
    """Test loading JETS file into WaveScoutMainWindow and verifying record tree display.

    This integration test verifies that:
    1. JETS files can be loaded into the main WaveScout window
    2. The record tree model is populated in DesignTreeView
    3. The tree is expandable and navigable
    4. Records are properly displayed with their hierarchy
    5. No changes to WaveScout code are needed - Pyrox handles JETS like waveforms
    """
    from scout import WaveScoutMainWindow
    from PySide6.QtCore import Qt, QModelIndex

    jets_file = Path(__file__).parent.parent / "jets" / "gpu_sim.jets"
    assert jets_file.exists(), f"JETS test file not found: {jets_file}"

    # Create main window with JETS file
    window = WaveScoutMainWindow(wave_file=str(jets_file))
    window.resize(1400, 900)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    # Wait for session and design tree to load
    def session_loaded():
        return (
            window.wave_widget.session is not None
            and window.wave_widget.session.waveform_files
            and window.design_tree_view.scope_tree_model is not None
            and window.design_tree_view.scope_tree_model.rowCount() > 0
        )

    qtbot.waitUntil(session_loaded, timeout=10000)

    # Verify design tree model is populated
    # Note: DesignTreeView visibility may vary depending on UI layout/docking state
    # The important part is that the model exists and is populated
    model = window.design_tree_view.scope_tree_model
    assert model is not None, "ScopeTreeModel should be initialized"
    assert window.design_tree_view is not None, "DesignTreeView should exist"

    # Verify there are root nodes in the tree
    root_count = model.rowCount(QModelIndex())
    assert root_count > 0, "DesignTreeView should have at least one root node"

    # Get first root node
    first_root_idx = model.index(0, 0, QModelIndex())
    assert first_root_idx.isValid(), "First root index should be valid"

    # Verify the root node has displayable data
    root_display_name = model.data(first_root_idx, Qt.ItemDataRole.DisplayRole)
    assert root_display_name is not None, "Root node should have a display name"
    assert isinstance(root_display_name, str), "Display name should be a string"
    assert len(root_display_name) > 0, "Display name should not be empty"

    # Verify the tree is expandable - check if root has children
    child_count = model.rowCount(first_root_idx)

    # The gpu_sim.jets file should have a hierarchical structure with children
    # If the model implementation is complete, we should see child nodes
    has_children = child_count > 0

    if has_children:
        # Tree has children, verify we can access them
        first_child_idx = model.index(0, 0, first_root_idx)
        assert first_child_idx.isValid(), "First child index should be valid"

        child_display_name = model.data(first_child_idx, Qt.ItemDataRole.DisplayRole)
        assert child_display_name is not None, "Child node should have a display name"
        assert isinstance(child_display_name, str), "Child display name should be a string"
        assert len(child_display_name) > 0, "Child display name should not be empty"

    # Count total number of nodes in the tree (all levels)
    def count_all_nodes(parent_idx=QModelIndex()):
        """Recursively count all nodes in tree."""
        count = 0
        rows = model.rowCount(parent_idx)
        for r in range(rows):
            idx = model.index(r, 0, parent_idx)
            if idx.isValid():
                count += 1
                count += count_all_nodes(idx)
        return count

    total_nodes = count_all_nodes()
    assert total_nodes > 0, "Tree should contain at least one node"
    # The gpu_sim.jets file should have many nodes (1000+)
    assert total_nodes > 100, f"Expected large tree, got only {total_nodes} nodes"

    # Verify hierarchy - the gpu_sim.jets file should have a specific structure
    # Root should be "host_prog" based on the JETS file content
    hier = window.wave_widget.session.get_primary_file().waveform_db.hierarchy
    assert hier.file_format() == "JETS", "File format should be JETS"

    # Verify we can access records through the hierarchy
    top_scopes = list(hier.top_scopes())
    assert len(top_scopes) > 0, "Hierarchy should have top-level scopes"

    first_scope = top_scopes[0]
    assert first_scope.is_record(), "First scope should be a record"
    assert first_scope.scope_type() == "record", "Scope type should be 'record'"

    # Get the record and verify its properties
    record = first_scope.record()
    assert record is not None, "Should be able to retrieve Record object"
    assert record.id == "host_prog", "First record ID should be 'host_prog' per gpu_sim.jets"
    assert record.name == "flash_attention_fwd", "Record name should be 'flash_attention_fwd' per gpu_sim.jets"
    assert record.record_type == "HostProgram", "Record type should be 'HostProgram'"

    # Verify child records are accessible
    child_scopes = list(first_scope.scopes(hier))
    assert len(child_scopes) > 0, "Root record should have child records"

    # Verify first child is also a record
    first_child_scope = child_scopes[0]
    assert first_child_scope.is_record(), "Child scope should be a record"

    child_record = first_child_scope.record()
    assert child_record is not None, "Should be able to retrieve child Record object"
    assert child_record.parent_id == "host_prog", "Child's parent_id should reference root"

    # Test expandability in the UI - verify the model supports children
    if has_children:
        assert model.hasChildren(first_root_idx), "Root node should report having children"

    # Verify that accessing vars in a record scope works
    vars_in_scope = list(first_scope.vars(hier))
    assert len(vars_in_scope) >= 1, "Record scope should expose at least one var (the record itself)"

    # Verify the var represents the record as a signal
    record_var = vars_in_scope[0]
    var_type = record_var.var_type()
    assert "String" in var_type or "string" in var_type.lower(), \
        f"Record var should be String type, got {var_type}"

    window.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
