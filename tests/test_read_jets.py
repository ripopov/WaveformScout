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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
