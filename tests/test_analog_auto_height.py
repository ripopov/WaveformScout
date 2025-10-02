"""Test that switching to Analog render mode automatically sets row height."""

import pytest
from pathlib import Path
from PySide6.QtCore import QModelIndex
from wavescout.widgets.wave_scout_widget import WaveScoutWidget
from wavescout.core.data_model import RenderType, AnalogScalingMode
from tests.test_scout_integration import WaveScoutTestHelper, TestPaths, create_sample_session


def test_analog_scale_all_auto_height(qtbot):
    """
    Test that switching to "Analog Scale All" automatically sets row height to 3.
    
    This is a regression test to ensure that when a signal is switched to
    analog rendering mode, the row height is automatically increased to 3
    for better visibility.
    
    Test scenario:
    1. Load apb_sim.vcd containing multi-bit signals
    2. Add prdata signal (multi-bit)
    3. Verify initial height_scaling is 1
    4. Switch to "Analog Scale All" via SignalNamesView method
    5. Verify height_scaling is automatically set to 3
    6. Switch back to Bus mode
    7. Verify height remains at 3 (not reset)
    8. Switch to Analog again
    9. Verify height stays at 3 (no double setting)
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
    
    # Add prdata signal to session
    primary_file = session.get_primary_file()
    assert primary_file is not None
    db = primary_file.waveform_db
    assert db is not None and db.hierarchy is not None
    
    signal_patterns = {
        "prdata": ("apb_testbench.prdata", None),
    }
    
    found_nodes = helper.add_signals_to_session(db, session, db.hierarchy, signal_patterns)
    assert "prdata" in found_nodes, "apb_testbench.prdata not found in VCD"
    
    # Notify model about changes
    if widget.model:
        widget.model.layoutChanged.emit()
    qtbot.wait(50)
    
    # Get the signal node
    prdata_node = found_nodes["prdata"]
    
    # Verify initial state
    assert prdata_node.format.render_type == RenderType.BUS, "Should start in BUS mode"
    assert prdata_node.height_scaling == 1, "Should start with height_scaling = 1"
    
    # Get the SignalNamesView to test the method directly
    names_view = widget._names_view
    
    # Switch to Analog Scale All
    names_view._set_render_type_with_scaling(
        prdata_node,
        RenderType.ANALOG,
        AnalogScalingMode.SCALE_TO_ALL_DATA
    )
    
    # Verify render type and height were both updated
    assert prdata_node.format.render_type == RenderType.ANALOG, "Should be in ANALOG mode"
    assert prdata_node.format.analog_scaling_mode == AnalogScalingMode.SCALE_TO_ALL_DATA
    assert prdata_node.height_scaling == 3, "Height should be automatically set to 3"
    
    # Switch back to Bus mode
    names_view._set_render_type(prdata_node, RenderType.BUS)
    
    # Verify height remains at 3 (not reset)
    assert prdata_node.format.render_type == RenderType.BUS, "Should be back in BUS mode"
    assert prdata_node.height_scaling == 3, "Height should remain at 3"
    
    # Switch to Analog Scale Visible
    names_view._set_render_type_with_scaling(
        prdata_node,
        RenderType.ANALOG,
        AnalogScalingMode.SCALE_TO_VISIBLE_DATA
    )
    
    # Verify height stays at 3 (not set again since it's already > 1)
    assert prdata_node.format.render_type == RenderType.ANALOG
    assert prdata_node.format.analog_scaling_mode == AnalogScalingMode.SCALE_TO_VISIBLE_DATA
    assert prdata_node.height_scaling == 3, "Height should stay at 3"
    
    widget.close()


def test_analog_scale_visible_auto_height(qtbot):
    """
    Test that switching to "Analog Scale Visible" also sets row height to 3.
    
    Test scenario:
    1. Load apb_sim.vcd 
    2. Add paddr signal (multi-bit)
    3. Verify initial height_scaling is 1
    4. Switch to "Analog Scale Visible" 
    5. Verify height_scaling is automatically set to 3
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
    
    # Add paddr signal to session
    primary_file = session.get_primary_file()
    assert primary_file is not None
    db = primary_file.waveform_db
    assert db is not None and db.hierarchy is not None
    
    signal_patterns = {
        "paddr": ("apb_testbench.paddr", None),
    }
    
    found_nodes = helper.add_signals_to_session(db, session, db.hierarchy, signal_patterns)
    assert "paddr" in found_nodes, "apb_testbench.paddr not found in VCD"
    
    # Notify model about changes
    if widget.model:
        widget.model.layoutChanged.emit()
    qtbot.wait(50)
    
    # Get the signal node
    paddr_node = found_nodes["paddr"]
    
    # Verify initial state
    assert paddr_node.format.render_type == RenderType.BUS
    assert paddr_node.height_scaling == 1
    
    # Get the SignalNamesView
    names_view = widget._names_view
    
    # Switch directly to Analog Scale Visible
    names_view._set_render_type_with_scaling(
        paddr_node,
        RenderType.ANALOG,
        AnalogScalingMode.SCALE_TO_VISIBLE_DATA
    )
    
    # Verify both render type and height were updated
    assert paddr_node.format.render_type == RenderType.ANALOG
    assert paddr_node.format.analog_scaling_mode == AnalogScalingMode.SCALE_TO_VISIBLE_DATA
    assert paddr_node.height_scaling == 3, "Height should be automatically set to 3"
    
    widget.close()


def test_analog_height_not_changed_if_already_scaled(qtbot):
    """
    Test that if a signal already has height_scaling > 1, switching to analog
    doesn't override the user's custom height setting.
    
    Test scenario:
    1. Load apb_sim.vcd
    2. Add prdata signal
    3. Set custom height_scaling to 8
    4. Switch to Analog mode
    5. Verify height_scaling remains at 8 (not changed to 3)
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
    
    # Add prdata signal
    primary_file = session.get_primary_file()
    assert primary_file is not None
    db = primary_file.waveform_db
    assert db is not None and db.hierarchy is not None
    
    signal_patterns = {
        "prdata": ("apb_testbench.prdata", None),
    }
    
    found_nodes = helper.add_signals_to_session(db, session, db.hierarchy, signal_patterns)
    assert "prdata" in found_nodes
    
    if widget.model:
        widget.model.layoutChanged.emit()
    qtbot.wait(50)
    
    prdata_node = found_nodes["prdata"]
    
    # Set custom height first
    widget.controller.set_node_format(prdata_node.instance_id, height_scaling=8)
    assert prdata_node.height_scaling == 8
    
    # Now switch to Analog
    names_view = widget._names_view
    names_view._set_render_type_with_scaling(
        prdata_node,
        RenderType.ANALOG,
        AnalogScalingMode.SCALE_TO_ALL_DATA
    )
    
    # Verify height remains at user's custom value
    assert prdata_node.format.render_type == RenderType.ANALOG
    assert prdata_node.height_scaling == 8, "Height should remain at user's custom value"
    
    widget.close()