"""
Test for multi-file waveform signal addition bug.

This test reproduces the issue where signals from the second waveform file
cannot be added to the canvas after signals from the first file are already added.
"""

import pytest
from pathlib import Path
from PySide6.QtCore import QModelIndex

from .test_utils import get_test_input_path, TestFiles
from .test_scout_integration import WaveScoutTestHelper


def test_add_signals_from_second_file_after_first(qtbot):
    """
    Test that signals from a second waveform can be added after signals from the first.

    This test reproduces a bug where:
    1. Load apb_sim.vcd
    2. Add a signal from apb_sim.vcd (e.g., pclk)
    3. Load swerv1.vcd
    4. Try to add a signal from swerv1.vcd (e.g., core_clk)
    5. Bug: The signal from swerv1.vcd is NOT added

    Test scenario:
    1. Load apb_sim.vcd
    2. Navigate to apb_testbench.dut scope
    3. Double click on pclk in VarsView to add it
    4. Verify pclk appears in signal list
    5. Load swerv1.vcd (via controller.open_waveform_file)
    6. Navigate to TOP scope in design tree
    7. Double click on core_clk in VarsView
    8. Verify core_clk appears in signal list (expected to FAIL currently)
    """
    from scout import WaveScoutMainWindow

    helper = WaveScoutTestHelper()

    # Get test file paths
    apb_sim_vcd = get_test_input_path(TestFiles.APB_SIM_VCD)
    swerv1_vcd = get_test_input_path(TestFiles.SWERV1_VCD)

    assert apb_sim_vcd.exists(), f"APB sim VCD not found: {apb_sim_vcd}"
    assert swerv1_vcd.exists(), f"Swerv1 VCD not found: {swerv1_vcd}"

    # Create window with first file
    window = helper.setup_main_window_with_vcd(apb_sim_vcd, qtbot, size=(1400, 900))
    helper.wait_for_session_loaded(window, qtbot)
    window.design_tree_view.install_event_filters()

    # Step 1: Add signal from first file (apb_sim.vcd)
    print("\n=== Step 1: Adding signal from first file (apb_sim.vcd) ===")

    design_view = window.design_tree_view.scope_tree
    model = window.design_tree_view.scope_tree_model

    # Navigate to apb_testbench scope
    root = QModelIndex()
    apb_idx = helper.find_child_by_name(model, root, "apb_testbench")
    assert apb_idx and apb_idx.isValid(), "apb_testbench scope not found"

    # Expand and select the scope
    design_view.expand(apb_idx)
    qtbot.wait(100)

    # Find dut subscope
    dut_idx = helper.find_child_by_name(model, apb_idx, "dut")
    assert dut_idx and dut_idx.isValid(), "apb_testbench.dut scope not found"

    # Select dut scope to populate VarsView
    design_view.setCurrentIndex(dut_idx)
    qtbot.wait(200)

    # Find pclk in VarsView and add it
    vars_view = window.design_tree_view.vars_view
    assert vars_view is not None, "VarsView not found"

    pclk_added = False
    vars_model = vars_view.vars_model
    if vars_model and vars_model.rowCount() > 0:
        for row in range(vars_model.rowCount()):
            var_data = vars_model.variables[row] if row < len(vars_model.variables) else None
            if var_data and var_data.get('name') == 'pclk':
                # Double click to add
                var_idx = vars_view.filter_proxy.index(row, 0)
                vars_view._on_double_click(var_idx)
                pclk_added = True
                qtbot.wait(100)
                break

    assert pclk_added, "Failed to add pclk from apb_sim.vcd"

    # Verify pclk is in session
    session = window.wave_widget.session
    assert session is not None
    pclk_nodes = [n for n in session.root_nodes if 'pclk' in n.name.lower()]
    assert len(pclk_nodes) > 0, "pclk was not added to session"
    print(f"✓ pclk added successfully: {pclk_nodes[0].name}")

    # Verify pclk is visible in SignalNamesView
    signal_names_view = window.wave_widget._names_view
    assert signal_names_view is not None
    pclk_visible = False
    for i in range(window.wave_widget.model.rowCount()):
        idx = window.wave_widget.model.index(i, 0)
        node = window.wave_widget.model.data(idx, 0x0100)  # Qt.ItemDataRole.UserRole
        if node and 'pclk' in node.name.lower():
            pclk_visible = True
            break
    assert pclk_visible, "pclk not visible in SignalNamesView"
    print(f"✓ pclk visible in SignalNamesView")

    # Step 2: Load second file (swerv1.vcd)
    print("\n=== Step 2: Loading second file (swerv1.vcd) ===")

    controller = window.wave_widget.controller
    success = controller.open_waveform_file(str(swerv1_vcd))
    assert success, "Failed to load second waveform file"
    qtbot.wait(500)  # Give time for model to update

    # Verify session now has 2 files
    assert len(session.waveform_files) == 2, f"Expected 2 files in session, got {len(session.waveform_files)}"
    print(f"✓ Session now has {len(session.waveform_files)} files")

    # Step 3: Add signal from second file (swerv1.vcd)
    print("\n=== Step 3: Adding signal from second file (swerv1.vcd) ===")

    # The tree should now show both files at the root level
    model = window.design_tree_view.scope_tree_model

    # In multi-file mode, we should have file nodes at root
    from wavescout.multi_file_scope_tree_model import MultiFileScopeTreeModel, FileNode
    assert isinstance(model, MultiFileScopeTreeModel), "Should be using MultiFileScopeTreeModel"

    # Find swerv1.vcd file node (should be second child at root)
    root = QModelIndex()
    swerv1_file_idx = None
    for row in range(model.rowCount(root)):
        idx = model.index(row, 0, root)
        if idx.isValid():
            node = idx.internalPointer()
            if isinstance(node, FileNode) and 'swerv1' in node.file_name:
                swerv1_file_idx = idx
                print(f"Found swerv1.vcd file node at row {row}: {node.file_name}")
                break

    assert swerv1_file_idx is not None, "swerv1.vcd file node not found in tree"

    # Expand swerv1 file node
    design_view.expand(swerv1_file_idx)
    qtbot.wait(100)

    # Find TOP scope under swerv1
    top_idx = helper.find_child_by_name(model, swerv1_file_idx, "TOP")
    assert top_idx and top_idx.isValid(), "TOP scope not found under swerv1.vcd"
    print(f"Found TOP scope under swerv1.vcd")

    # Select TOP scope to populate VarsView
    design_view.setCurrentIndex(top_idx)
    qtbot.wait(300)  # Give more time for variables to load

    # Verify VarsView has variables from TOP scope
    vars_model = vars_view.vars_model
    assert vars_model.rowCount() > 0, f"VarsView is empty after selecting TOP scope (expected variables)"
    print(f"VarsView has {vars_model.rowCount()} variables")

    # Find core_clk in VarsView
    core_clk_found = False
    core_clk_row = -1
    for row in range(vars_model.rowCount()):
        var_data = vars_model.variables[row] if row < len(vars_model.variables) else None
        if var_data:
            var_name = var_data.get('name', '')
            if var_name == 'core_clk':
                core_clk_found = True
                core_clk_row = row
                print(f"Found core_clk at row {row}, full_path: {var_data.get('full_path')}")
                break

    assert core_clk_found, "core_clk variable not found in VarsView"

    # Double click on core_clk to add it
    print(f"Double-clicking core_clk at row {core_clk_row}")
    var_idx = vars_view.filter_proxy.index(core_clk_row, 0)
    vars_view._on_double_click(var_idx)
    qtbot.wait(200)

    # Step 4: Verify core_clk was added to session
    print("\n=== Step 4: Verifying core_clk was added ===")

    # Check if core_clk is in session root_nodes
    core_clk_nodes = [n for n in session.root_nodes if 'core_clk' in n.name]

    # Print all signal names for debugging
    print(f"All signals in session ({len(session.root_nodes)}):")
    for i, node in enumerate(session.root_nodes):
        print(f"  {i}: {node.name} (file_id={node.file_id})")

    # This is the assertion that should fail due to the bug
    assert len(core_clk_nodes) > 0, "BUG REPRODUCED: core_clk was NOT added to session from second file!"

    print(f"✓ core_clk added successfully: {core_clk_nodes[0].name}")
    print(f"  file_id: {core_clk_nodes[0].file_id}")

    # Verify core_clk has the correct file_id (should be 1 for second file)
    assert core_clk_nodes[0].file_id == 1, f"core_clk has wrong file_id: {core_clk_nodes[0].file_id}, expected 1"

    # Verify core_clk is visible in SignalNamesView
    core_clk_visible = False
    for i in range(window.wave_widget.model.rowCount()):
        idx = window.wave_widget.model.index(i, 0)
        node = window.wave_widget.model.data(idx, 0x0100)  # Qt.ItemDataRole.UserRole
        if node and 'core_clk' in node.name:
            core_clk_visible = True
            break

    assert core_clk_visible, "core_clk not visible in SignalNamesView"
    print(f"✓ core_clk visible in SignalNamesView")

    print("\n=== Test PASSED: Bug is NOT present (or has been fixed) ===")

    window.close()


def test_time_range_clipping_with_different_duration_waveforms(qtbot):
    """
    Test that time range is correctly updated when loading waveforms with different durations.

    This test reproduces a bug where:
    1. Load apb_sim.vcd (ends at #10350000)
    2. Load periodic_signals.vcd (ends at #5000000000, much larger)
    3. Bug: The displayed time range is clipped to the range of the first waveform
    4. Zoom to fit shows correct timescale, but signals appear clipped

    Expected behavior:
    - After loading the second file, the viewport time range should expand to accommodate
      the larger time range from periodic_signals.vcd
    - Both waveforms should be fully visible without clipping
    """
    from scout import WaveScoutMainWindow

    helper = WaveScoutTestHelper()

    # Get test file paths
    apb_sim_vcd = get_test_input_path(TestFiles.APB_SIM_VCD)
    periodic_vcd = get_test_input_path("periodic_signals.vcd")

    assert apb_sim_vcd.exists(), f"APB sim VCD not found: {apb_sim_vcd}"
    assert periodic_vcd.exists(), f"Periodic signals VCD not found: {periodic_vcd}"

    # Create window with first file
    print("\n=== Step 1: Loading first file (apb_sim.vcd) ===")
    window = helper.setup_main_window_with_vcd(apb_sim_vcd, qtbot, size=(1400, 900))
    helper.wait_for_session_loaded(window, qtbot)

    session = window.wave_widget.session
    controller = window.wave_widget.controller

    # Get the time range after loading first file
    # apb_sim.vcd ends at #10350000
    initial_total_duration = session.viewport.total_duration
    print(f"Initial viewport total_duration after loading apb_sim.vcd: {initial_total_duration}")
    print(f"Initial viewport range: [{session.viewport.start_time}, {session.viewport.end_time}]")

    # Verify the initial total_duration matches apb_sim.vcd
    # The end time should be around 10350000
    assert initial_total_duration > 0, "Initial total_duration should be > 0"
    assert initial_total_duration < 20000000, f"Initial total_duration seems too large: {initial_total_duration}"

    # For apb_sim.vcd, the expected end time is 10350000
    expected_apb_duration = 10350000
    assert abs(initial_total_duration - expected_apb_duration) < 1000000, \
        f"Initial total_duration {initial_total_duration} doesn't match expected {expected_apb_duration}"

    # Load second file with much larger time range
    print("\n=== Step 2: Loading second file (periodic_signals.vcd) ===")
    success = controller.open_waveform_file(str(periodic_vcd))
    assert success, "Failed to load second waveform file"
    qtbot.wait(500)

    # Verify session now has 2 files
    assert len(session.waveform_files) == 2, f"Expected 2 files in session, got {len(session.waveform_files)}"
    print(f"✓ Session now has {len(session.waveform_files)} files")

    # Check the time range after loading second file
    # periodic_signals.vcd ends at #5000000000, which is MUCH larger than apb_sim.vcd
    updated_total_duration = session.viewport.total_duration
    print(f"Viewport total_duration after loading periodic_signals.vcd: {updated_total_duration}")
    print(f"Updated viewport range: [{session.viewport.start_time}, {session.viewport.end_time}]")

    # The bug: total_duration is NOT updated to accommodate the larger waveform
    # Expected: updated_total_duration should be >= 5000000000
    # Bug behavior: updated_total_duration remains ~10350000 (clipped to first file)

    print(f"\n=== Verifying time range was updated ===")
    print(f"  Initial total_duration (apb_sim.vcd):  {initial_total_duration}")
    print(f"  Updated total_duration (after periodic): {updated_total_duration}")
    print(f"  Expected total_duration (periodic_signals.vcd): >= 5000000000")

    # This assertion should FAIL if the bug exists
    assert updated_total_duration >= 5000000000, \
        f"BUG REPRODUCED: Viewport total_duration was NOT updated to accommodate larger waveform! " \
        f"Expected >= 5000000000, got {updated_total_duration}"

    print(f"✓ Viewport total_duration correctly updated to accommodate both waveforms")

    # Verify that zoom to fit works correctly
    print("\n=== Step 3: Testing zoom to fit ===")
    controller.zoom_to_fit()
    qtbot.wait(200)

    viewport_after_zoom = session.viewport
    print(f"Viewport after zoom to fit:")
    print(f"  total_duration: {viewport_after_zoom.total_duration}")
    print(f"  range: [{viewport_after_zoom.start_time}, {viewport_after_zoom.end_time}]")

    # After zoom to fit, viewport should show the full range of the larger waveform
    assert viewport_after_zoom.end_time >= 5000000000, \
        f"Zoom to fit did not expand viewport to full time range! " \
        f"Expected >= 5000000000, got {viewport_after_zoom.end_time}"

    print(f"✓ Zoom to fit correctly shows full time range")

    # Step 4: Add signals from both files and verify they are not clipped
    print("\n=== Step 4: Verifying signals are not clipped ===")

    # Check session waveform bounds (moved from canvas to session in refactoring)
    session = window.wave_widget.controller.session
    print(f"Session waveform_max_time: {session.waveform_max_time}")

    # The session should be aware of the full time range across all files
    # This is where the clipping bug might manifest
    if session.waveform_max_time is not None:
        assert session.waveform_max_time >= 5000000000, \
            f"BUG REPRODUCED: Session waveform_max_time is clipped to first file! " \
            f"Expected >= 5000000000, got {session.waveform_max_time}"
        print(f"✓ Session waveform_max_time correctly set to {session.waveform_max_time}")
    else:
        print("⚠ Session waveform_max_time is None (might not be initialized yet)")

    print("\n=== Test PASSED: Time range bug is NOT present (or has been fixed) ===")

    window.close()
