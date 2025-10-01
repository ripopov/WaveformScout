"""Test that canvas properly updates row heights when height_scaling changes."""

import pytest
from pathlib import Path
from PySide6.QtCore import QModelIndex
from wavescout.wave_scout_widget import WaveScoutWidget
from wavescout.data_model import RenderType, AnalogScalingMode
from tests.test_scout_integration import WaveScoutTestHelper, TestPaths, create_sample_session


def test_canvas_updates_on_height_change(qtbot):
    """
    Test that the waveform canvas updates its row heights when height_scaling changes.
    
    This test verifies that the canvas properly responds to height changes by:
    1. Checking initial row heights in canvas
    2. Changing height_scaling via controller
    3. Verifying canvas row heights are updated
    
    Test scenario:
    1. Load apb_sim.vcd with multiple signals
    2. Check initial canvas row heights
    3. Change one signal to height_scaling=3
    4. Verify canvas._row_heights is updated
    5. Switch to analog mode (which sets height=3)
    6. Verify canvas updates again
    """
    helper = WaveScoutTestHelper()
    vcd_path = TestPaths.APB_SIM_VCD
    assert vcd_path.exists(), f"VCD not found: {vcd_path}"
    
    # Create session and widget
    session = create_sample_session(str(vcd_path))
    widget = WaveScoutWidget()
    widget.resize(1200, 800)
    widget.setSession(session)
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    
    # Add multiple signals
    primary_file = session.get_primary_file()
    assert primary_file is not None
    db = primary_file.waveform_db
    assert db is not None and db.hierarchy is not None
    
    signal_patterns = {
        "prdata": ("apb_testbench.prdata", None),
        "paddr": ("apb_testbench.paddr", None),
        "pwrite": ("apb_testbench.pwrite", None),
    }
    
    found_nodes = helper.add_signals_to_session(db, session, db.hierarchy, signal_patterns)
    assert len(found_nodes) == 3, "Should have added 3 signals"
    
    # Notify model about changes
    if widget.model:
        widget.model.layoutChanged.emit()
    qtbot.wait(50)
    
    # Get canvas and check initial state
    canvas = widget._canvas
    assert canvas is not None
    
    # Force canvas to update its internal state
    canvas.update()
    qtbot.wait(50)
    
    # Check initial row heights (all should be default)
    assert hasattr(canvas, '_layout'), "Canvas should have _layout"
    base_height = canvas._row_height

    # All rows should start at base height
    for row in canvas._layout.rows:
        assert row.height_px == base_height, f"Row should have base height"
    
    # Get the first signal node
    prdata_node = found_nodes["prdata"]
    
    # Change height_scaling directly via controller
    widget.controller.set_node_format(prdata_node.instance_id, height_scaling=4)
    qtbot.wait(100)  # Give time for events to propagate
    
    # Check canvas row heights updated
    canvas.update()
    qtbot.wait(50)

    # The first row should now have scaled height
    assert len(canvas._layout.rows) > 0, "Should have at least one row"
    assert canvas._layout.rows[0].height_px == base_height * 4, f"Row 0 should be scaled 4x, got {canvas._layout.rows[0].height_px}"
    
    # Now test analog mode auto-height
    paddr_node = found_nodes["paddr"]
    
    # Switch to analog (should auto-set height to 3)
    names_view = widget._names_view
    names_view._set_render_type_with_scaling(
        paddr_node,
        RenderType.ANALOG,
        AnalogScalingMode.SCALE_TO_ALL_DATA
    )
    qtbot.wait(100)
    
    # Force canvas update
    canvas.update()
    qtbot.wait(50)
    
    # Check paddr row is now scaled
    assert len(canvas._layout.rows) > 1, "Should have at least two rows"
    assert canvas._layout.rows[1].height_px == base_height * 3, f"Row 1 should be scaled 3x for analog"
    
    # Verify the node itself has the right values
    assert paddr_node.format.render_type == RenderType.ANALOG
    assert paddr_node.height_scaling == 3
    
    widget.close()


def test_multiple_height_changes_update_canvas(qtbot):
    """
    Test that multiple rapid height changes all properly update the canvas.
    
    This tests that the layoutChanged signal is properly emitted for each
    height change and the canvas stays in sync.
    """
    helper = WaveScoutTestHelper()
    vcd_path = TestPaths.APB_SIM_VCD
    
    session = create_sample_session(str(vcd_path))
    widget = WaveScoutWidget()
    widget.setSession(session)
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    
    # Add a signal
    primary_file = session.get_primary_file()
    assert primary_file is not None
    db = primary_file.waveform_db
    signal_patterns = {"prdata": ("apb_testbench.prdata", None)}
    found_nodes = helper.add_signals_to_session(db, session, db.hierarchy, signal_patterns)
    
    if widget.model:
        widget.model.layoutChanged.emit()
    qtbot.wait(50)
    
    prdata_node = found_nodes["prdata"]
    canvas = widget._canvas
    base_height = canvas._row_height
    
    # Test multiple height changes
    heights_to_test = [1, 2, 4, 8, 3, 1]
    
    for height in heights_to_test:
        widget.controller.set_node_format(prdata_node.instance_id, height_scaling=height)
        qtbot.wait(50)
        canvas.update()
        qtbot.wait(50)
        
        # Verify canvas updated
        assert len(canvas._layout.rows) > 0, "Should have at least one row"
        expected = base_height * height
        actual = canvas._layout.rows[0].height_px
        assert actual == expected, f"Height {height}: expected {expected}, got {actual}"
    
    widget.close()