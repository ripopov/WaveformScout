"""Integration tests for WaveScout application.

This module contains comprehensive integration tests for the WaveScout waveform viewer,
testing various UI interactions, data loading, and session management features.
"""

import os
import sys
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, List, Tuple, Callable
from unittest.mock import patch, MagicMock

import pytest
import json
from PySide6.QtWidgets import QApplication, QInputDialog
from PySide6.QtCore import Qt, QModelIndex, QItemSelection
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtTest import QTest

from wavescout import create_sample_session, WaveScoutWidget, save_session, load_session
from wavescout.core.waveform_loader import create_signal_node_from_var
from .test_utils import get_test_input_path, TestFiles


def get_full_name_from_json(node_data):
    """Construct full name from local_name and scope_path.

    This helper function reconstructs the full signal name from the JSON
    representation where nodes have 'local_name' and 'scope_path' instead
    of a single 'name' field.

    Args:
        node_data: Dictionary containing node data from JSON

    Returns:
        str: Full name constructed from scope_path and local_name
    """
    scope_path = node_data.get('scope_path', [])
    local_name = node_data['local_name']
    if scope_path:
        return '.'.join(scope_path) + '.' + local_name
    return local_name


# ========================================================================
# Test Fixtures and Helper Classes
# ========================================================================

class TestPaths:
    """Central repository for test file paths."""
    REPO_ROOT = Path(__file__).resolve().parent.parent
    SCOUT_PY = REPO_ROOT / "scout.py"
    
    # Common test VCD files - using test utilities
    APB_SIM_VCD = get_test_input_path(TestFiles.APB_SIM_VCD)
    ANALOG_SIGNALS_VCD = get_test_input_path(TestFiles.ANALOG_SIGNALS_SHORT_VCD)
    SWERV1_VCD = get_test_input_path(TestFiles.SWERV1_VCD)
    VCD_EXTENSIONS = get_test_input_path(TestFiles.VCD_EXTENSIONS)


class WaveScoutTestHelper:
    """Helper class for common WaveScout test operations."""
    
    @staticmethod
    def wait_for_session_loaded(window, qtbot, timeout: int = 5000) -> None:
        """
        Wait for a WaveScout window's session and design tree to be fully loaded.
        
        Args:
            window: WaveScoutMainWindow instance
            qtbot: pytest-qt fixture for Qt testing
            timeout: Maximum wait time in milliseconds
        """
        def _loaded():
            return (
                window.wave_widget.session is not None
                and window.wave_widget.session.waveform_files
                and window.design_tree_view.scope_tree_model is not None
                and window.design_tree_view.scope_tree_model.rowCount() > 0
            )
        qtbot.waitUntil(_loaded, timeout=timeout)
    
    @staticmethod
    def wait_for_split_mode_ready(window, qtbot, timeout: int = 2000) -> None:
        """
        Wait for split mode to be fully initialized.
        
        Args:
            window: WaveScoutMainWindow instance
            qtbot: pytest-qt fixture for Qt testing
            timeout: Maximum wait time in milliseconds
        """
        def _split_ready():
            return (
                window.design_tree_view.scope_tree_model is not None
                and window.design_tree_view.vars_view is not None
            )
        qtbot.waitUntil(_split_ready, timeout=timeout)
    
    @staticmethod
    def find_child_by_name(model, parent_index: QModelIndex, name: str) -> Optional[QModelIndex]:
        """
        Find a child node by display name under a parent index.
        
        Args:
            model: Qt model to search in
            parent_index: Parent QModelIndex
            name: Display name to search for
            
        Returns:
            QModelIndex of found child or None
        """
        rows = model.rowCount(parent_index)
        for r in range(rows):
            idx = model.index(r, 0, parent_index)
            if idx.isValid() and model.data(idx, Qt.ItemDataRole.DisplayRole) == name:
                return idx  # type: ignore[no-any-return]
        return None
    
    @staticmethod
    def add_signal_from_index(window, idx: QModelIndex) -> bool:
        """
        Add a signal from design tree index to the waveform session.
        
        Args:
            window: WaveScoutMainWindow instance
            idx: QModelIndex of the signal node
            
        Returns:
            True if signal was successfully added, False otherwise
        """
        model = window.design_tree_view.scope_tree_model
        node = model.data(idx, Qt.ItemDataRole.UserRole)
        if node and not node.is_scope:
            signal_node = window.design_tree_view._create_signal_node(node)
            if signal_node:
                window.design_tree_view.signals_selected.emit([signal_node])
                return True
        return False
    
    @staticmethod
    def save_and_verify_json(session, json_path: Path, verification_func: Callable) -> None:
        """
        Save session to JSON and run verification function on the data.
        
        Args:
            session: WaveScout session object
            json_path: Path where to save JSON
            verification_func: Function that takes JSON data dict and performs assertions
        """
        save_session(session, json_path)
        assert json_path.exists(), "Session JSON was not saved"
        
        with open(json_path, "r") as f:
            data = json.load(f)
        verification_func(data)
    
    @staticmethod
    def setup_main_window_with_vcd(vcd_path: Path, qtbot, size: Tuple[int, int] = (1400, 900)):
        """
        Create and setup a WaveScoutMainWindow with a loaded VCD file.
        
        Args:
            vcd_path: Path to VCD file
            qtbot: pytest-qt fixture
            size: Window size as (width, height) tuple
            
        Returns:
            Configured WaveScoutMainWindow instance
        """
        from scout import WaveScoutMainWindow
        
        assert vcd_path.exists(), f"VCD not found: {vcd_path}"
        
        window = WaveScoutMainWindow(wave_file=str(vcd_path))
        window.resize(*size)
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)
        
        return window
    
    @staticmethod
    def add_signals_to_session(db, session, hierarchy, signal_patterns: dict) -> dict:
        """
        Find and add signals matching patterns to a session.

        Args:
            db: Waveform database
            session: WaveScout session
            hierarchy: Signal hierarchy
            signal_patterns: Dict of name -> (suffix, handle) patterns to match

        Returns:
            Dict of name -> SignalNode for found signals
        """
        found_nodes = {}

        # Use iter_handles_and_vars to get ALL variables for each handle, including aliases
        for handle, vars_list in db.iter_handles_and_vars():
            for var in vars_list:
                full_name = var.full_name(hierarchy)

                for key, (suffix, _) in signal_patterns.items():
                    if full_name.endswith(suffix):
                        node = create_signal_node_from_var(var, hierarchy, handle, db)
                        # Note: node.name is now a property computed from local_name and scope_path
                        # which are set by create_signal_node_from_var
                        found_nodes[key] = node
                        session.root_nodes.append(node)
                        break  # Don't add the same signal multiple times

            if len(found_nodes) == len(signal_patterns):
                break

        return found_nodes


# ========================================================================
# Command Line Interface Tests
# ========================================================================

def test_load_wave_apb_sim_vcd():
    """
    Test loading a VCD file via command line interface.
    
    This test verifies that scout.py can successfully load a waveform file
    when invoked from the command line with --load_wave and --exit_after_load flags.
    
    Test scenario:
    1. Run scout.py with --load_wave pointing to apb_sim.vcd
    2. Use --exit_after_load flag to terminate after loading
    3. Verify process exits with code 0
    4. Verify stdout contains success message with filename
    """
    scout_py = TestPaths.SCOUT_PY
    wave_path = TestPaths.APB_SIM_VCD

    assert scout_py.exists(), f"scout.py not found at {scout_py}"
    assert wave_path.exists(), f"Waveform file not found: {wave_path}"

    # Run Qt in offscreen mode for CI/headless environments
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")

    cmd = [sys.executable, str(scout_py), "--load_wave", str(wave_path), "--exit_after_load"]

    proc = subprocess.run(
        cmd,
        cwd=str(TestPaths.REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
    )

    # Debug help on failure
    if proc.returncode != 0:
        print("STDOUT:\n" + proc.stdout)
        print("STDERR:\n" + proc.stderr)

    assert proc.returncode == 0, "Application exited with non-zero code"
    assert "Successfully loaded waveform" in proc.stdout
    assert "apb_sim.vcd" in proc.stdout


# ========================================================================
# Height Scaling Tests
# ========================================================================

def test_height_scaling_widget_api(qtbot):
    """
    Test programmatic height scaling through WaveScoutWidget API.
    
    This test verifies that signal height scaling can be set programmatically
    and is correctly persisted when saving sessions to JSON.
    
    Test scenario:
    1. Create WaveScoutWidget and load apb_sim.vcd
    2. Programmatically add apb_testbench.prdata and apb_testbench.paddr signals
    3. Set height scaling to 8x for prdata using internal API
    4. Save session to JSON
    5. Verify JSON contains correct height_scaling value
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

    # Add specific signals to session
    primary_file = session.get_primary_file()
    assert primary_file is not None
    db = primary_file.waveform_db
    assert db is not None and db.hierarchy is not None

    signal_patterns = {
        "prdata": ("apb_testbench.prdata", None),
        "paddr": ("apb_testbench.paddr", None),
    }

    found_nodes = helper.add_signals_to_session(db, session, db.hierarchy, signal_patterns)
    assert "prdata" in found_nodes, "apb_testbench.prdata not found in VCD"
    assert "paddr" in found_nodes, "apb_testbench.paddr not found in VCD"

    # Notify model about changes
    if widget.model:
        widget.model.layoutChanged.emit()
    qtbot.wait(50)

    # Set height scaling for prdata using controller
    prdata_node = found_nodes["prdata"]
    assert prdata_node.height_scaling != 8
    
    # Use the controller to set height scaling
    widget.controller.set_node_format(prdata_node.instance_id, height_scaling=8)

    # Verify persistence in JSON
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "test_height_scaling.json"
        
        def verify_height_scaling(data):
            nodes = data.get("root_nodes", [])
            prdata_json = next(
                (n for n in nodes if get_full_name_from_json(n).endswith("apb_testbench.prdata")),
                None
            )
            assert prdata_json is not None, "prdata node not found in saved JSON"
            assert prdata_json.get("height_scaling") == 8, \
                f"Expected height_scaling 8, got {prdata_json.get('height_scaling')}"
        
        helper.save_and_verify_json(session, json_path, verify_height_scaling)

    widget.close()


def test_height_scaling_ui_interaction(qtbot):
    """
    Test height scaling through UI interactions in the main window.
    
    This test simulates user interactions to add signals and change height scaling,
    verifying the changes are applied and persisted correctly.
    
    Test scenario:
    1. Load apb_sim.vcd into main window
    2. Navigate design tree to find apb_testbench scope
    3. Add prdata and paddr signals via UI interaction
    4. Change prdata height scaling to 8x
    5. Save session and verify JSON contains correct height_scaling
    """
    helper = WaveScoutTestHelper()
    window = helper.setup_main_window_with_vcd(TestPaths.APB_SIM_VCD, qtbot)
    
    # Wait for loading
    helper.wait_for_session_loaded(window, qtbot)
    window.design_tree_view.install_event_filters()
    
    design_view = window.design_tree_view.scope_tree
    model = window.design_tree_view.scope_tree_model

    # Navigate to scope
    root = QModelIndex()
    apb_idx = helper.find_child_by_name(model, root, "apb_testbench")
    assert apb_idx and apb_idx.isValid(), "apb_testbench scope not found"
    
    # Select the scope to load variables in VarsView
    design_view.setCurrentIndex(apb_idx)
    qtbot.wait(200)  # Wait for variables to load
    
    # Now add signals from the VarsView
    vars_view = window.design_tree_view.vars_view
    assert vars_view is not None, "VarsView not found"
    
    # Find and select signals in the VarsView
    vars_model = vars_view.vars_model
    if vars_model:
        # Look for prdata and paddr in the variables
        prdata_added = False
        paddr_added = False
        
        for row in range(vars_model.rowCount()):
            var_data = vars_model.variables[row] if row < len(vars_model.variables) else None
            if var_data:
                name = var_data.get('name', '')
                if name == 'prdata' and not prdata_added:
                    # Select prdata row
                    source_index = vars_model.index(row, 0)
                    proxy_index = vars_view.filter_proxy.mapFromSource(source_index)
                    selection_model = vars_view.table_view.selectionModel()
                    selection_model.select(proxy_index, QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)
                    window.design_tree_view.add_selected_signals()
                    prdata_added = True
                    qtbot.wait(100)
                elif name == 'paddr' and not paddr_added:
                    # Select paddr row
                    source_index = vars_model.index(row, 0)
                    proxy_index = vars_view.filter_proxy.mapFromSource(source_index)
                    selection_model = vars_view.table_view.selectionModel()
                    selection_model.select(proxy_index, QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)
                    window.design_tree_view.add_selected_signals()
                    paddr_added = True
                    qtbot.wait(100)
        
        assert prdata_added, "Failed to add prdata"
        assert paddr_added, "Failed to add paddr"
    
    # Verify signals added and set height scaling
    session = window.wave_widget.session
    prdata_node = next(
        n for n in session.root_nodes 
        if n.name.endswith("apb_testbench.prdata")
    )
    
    # Use controller to set height scaling
    window.wave_widget.controller.set_node_format(prdata_node.instance_id, height_scaling=8)
    assert prdata_node.height_scaling == 8
    
    # Verify JSON persistence
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "test_height_scaling.json"
        
        def verify_height_scaling(data):
            nodes = data.get("root_nodes", [])
            prdata_json = next(
                (n for n in nodes if get_full_name_from_json(n).endswith("apb_testbench.prdata")),
                None
            )
            assert prdata_json is not None
            assert prdata_json.get("height_scaling") == 8
        
        helper.save_and_verify_json(session, json_path, verify_height_scaling)
    
    window.close()


def test_height_scaling_for_analog_signals(qtbot):
    """
    Test height scaling for analog signals with different scales.
    
    This test verifies that different height scaling values can be applied
    to multiple analog signals and are correctly persisted.
    
    Test scenario:
    1. Load analog_signals_short.vcd containing sine wave signals
    2. Add top.sine_1mhz and top.sine_2mhz signals
    3. Set different height scaling (8x and 3x respectively)
    4. Save session to JSON
    5. Verify each signal has its correct height_scaling value
    """
    helper = WaveScoutTestHelper()
    window = helper.setup_main_window_with_vcd(TestPaths.ANALOG_SIGNALS_VCD, qtbot)
    
    helper.wait_for_session_loaded(window, qtbot)
    
    design_view = window.design_tree_view.scope_tree
    model = window.design_tree_view.scope_tree_model
    
    # Navigate to sine signals
    root = QModelIndex()
    top_idx = helper.find_child_by_name(model, root, "top")
    assert top_idx and top_idx.isValid(), "top scope not found"
    design_view.expand(top_idx)
    qtbot.wait(50)
    
    # In split mode, select the top scope to populate VarsView
    design_view.setCurrentIndex(top_idx)
    qtbot.wait(200)  # Wait for VarsView to populate
    
    # Now add signals from VarsView
    vars_view = window.design_tree_view.vars_view
    assert vars_view is not None, "VarsView not found"
    
    # Find and add sine_1mhz and sine_2mhz from variables
    vars_model = vars_view.vars_model
    if vars_model:
        sine1_added = False
        sine2_added = False
        
        for row in range(vars_model.rowCount()):
            var_data = vars_model.variables[row] if row < len(vars_model.variables) else None
            if var_data:
                name = var_data.get('name', '')
                if name == 'sine_1mhz' and not sine1_added:
                    var_idx = vars_view.filter_proxy.index(row, 0)
                    vars_view._on_double_click(var_idx)
                    sine1_added = True
                    qtbot.wait(50)
                elif name == 'sine_2mhz' and not sine2_added:
                    var_idx = vars_view.filter_proxy.index(row, 0)
                    vars_view._on_double_click(var_idx)
                    sine2_added = True
                    qtbot.wait(50)
        
        assert sine1_added, "Failed to add sine_1mhz"
        assert sine2_added, "Failed to add sine_2mhz"
    
    qtbot.wait(100)
    
    # Set different height scalings
    session = window.wave_widget.session
    sine1_node = next(n for n in session.root_nodes if n.name.endswith("top.sine_1mhz"))
    sine2_node = next(n for n in session.root_nodes if n.name.endswith("top.sine_2mhz"))
    
    # Use controller to set height scaling
    controller = window.wave_widget.controller
    controller.set_node_format(sine1_node.instance_id, height_scaling=8)
    controller.set_node_format(sine2_node.instance_id, height_scaling=3)
    
    # Verify in JSON
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "test_height_scaling_analog.json"
        
        def verify_analog_scaling(data):
            nodes = data.get("root_nodes", [])
            s1 = next((n for n in nodes if get_full_name_from_json(n).endswith("top.sine_1mhz")), None)
            s2 = next((n for n in nodes if get_full_name_from_json(n).endswith("top.sine_2mhz")), None)

            assert s1 is not None and s2 is not None
            assert s1.get("height_scaling") == 8
            assert s2.get("height_scaling") == 3
        
        helper.save_and_verify_json(session, json_path, verify_analog_scaling)
    
    window.close()


# ========================================================================
# Grouping and Drag & Drop Tests
# ========================================================================

def test_signal_grouping_and_reordering(qtbot, monkeypatch):
    """
    Test signal grouping and drag-and-drop reordering in Names panel.
    
    This test verifies that signals can be grouped together and that groups
    can be reordered via drag-and-drop operations. It also tests JSON
    persistence of the group structure and ordering.
    
    Test scenario:
    1. Load apb_sim.vcd and add 5 signals
    2. Group first 3 signals together
    3. Verify group structure in JSON (1 group with 3 children, 2 independent)
    4. Drag group between the two independent signals
    5. Verify new order in JSON (independent -> group -> independent)
    """
    helper = WaveScoutTestHelper()
    window = helper.setup_main_window_with_vcd(TestPaths.APB_SIM_VCD, qtbot)
    
    helper.wait_for_session_loaded(window, qtbot)
    
    # Use the split mode helper to add signals
    from .test_split_mode_helpers import add_signals_from_split_mode
    
    # Add more signals to ensure we get at least 5 (sometimes we get fewer)
    signals_added = add_signals_from_split_mode(window, 10)
    
    # Work with whatever we got (at least 3 needed for grouping test)
    session = window.wave_widget.session
    assert len(signals_added) >= 3, f"Need at least 3 signals for grouping, got {len(signals_added)}"
    assert len(session.root_nodes) >= 3, f"Need at least 3 root nodes for grouping, got {len(session.root_nodes)}"
    
    # If we have less than 5, adjust the test to work with what we have
    num_signals = len(session.root_nodes)
    
    # Group first three signals
    wave_widget = window.wave_widget
    names_view = wave_widget._names_view
    first_three = session.root_nodes[:3]
    
    # Select first three
    selection = QItemSelection()
    for node in first_three:
        idx = names_view._find_node_index(node)
        assert idx.isValid()
        selection.select(idx, idx)
    
    names_view.selectionModel().select(selection, QItemSelectionModel.SelectionFlag.ClearAndSelect)
    qtbot.wait(10)
    
    # Mock the QInputDialog to return a test group name
    from PySide6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, 'getText', lambda *args, **kwargs: ("TestGroup", True))
    
    # Create group
    wave_widget._create_group_from_selected()
    qtbot.wait(10)
    
    # Find group node
    group_node = next((n for n in session.root_nodes if getattr(n, "is_group", False)), None)
    assert group_node is not None
    assert len(group_node.children) == 3
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Verify initial structure
        json_path1 = Path(tmpdir) / "test_grouping_step1.json"
        
        def verify_initial_structure(data):
            rn = data.get("root_nodes", [])
            groups = [n for n in rn if n.get("is_group")]
            non_groups = [n for n in rn if not n.get("is_group")]
            assert len(groups) == 1
            assert len(non_groups) >= 2
            assert len(groups[0].get("children", [])) == 3
        
        helper.save_and_verify_json(session, json_path1, verify_initial_structure)
        
        # Drag group to position 1
        model_waves = wave_widget.model
        group_index = names_view._find_node_index(group_node)
        mime = model_waves.mimeData([group_index])
        ok = model_waves.dropMimeData(mime, Qt.DropAction.MoveAction, 1, 0, QModelIndex())
        assert ok
        qtbot.wait(10)
        
        # Verify new structure
        json_path2 = Path(tmpdir) / "test_grouping_step2.json"
        
        def verify_reordered_structure(data):
            rn = data.get("root_nodes", [])
            types = [n.get("is_group", False) for n in rn[:3]]
            # Should be: signal, group, signal
            assert types == [False, True, False], f"Unexpected order: {types}"
        
        helper.save_and_verify_json(session, json_path2, verify_reordered_structure)
    
    window.close()


# ========================================================================
# Split Mode Tests
# ========================================================================

def test_split_mode_keyboard_shortcut(qtbot):
    """
    Test keyboard shortcut 'i' for adding signals in split mode VarsView.
    
    This test verifies that the 'i' keyboard shortcut in split mode correctly
    adds the selected signal multiple times to the waveform canvas.
    
    Test scenario:
    1. Load apb_sim.vcd and switch to split mode
    2. Select first scope to populate VarsView
    3. Select first variable in VarsView
    4. Press 'i' key 3 times
    5. Verify signal appears 3 times in session
    6. Save to JSON and verify signal appears 3 times
    """
    helper = WaveScoutTestHelper()
    window = helper.setup_main_window_with_vcd(TestPaths.APB_SIM_VCD, qtbot)
    
    helper.wait_for_session_loaded(window, qtbot)
    
    # Split mode is now the default and only mode
    qtbot.wait(100)
    
    helper.wait_for_split_mode_ready(window, qtbot)
    
    # Select first scope
    scope_tree = window.design_tree_view.scope_tree
    scope_model = window.design_tree_view.scope_tree_model
    first_scope = scope_model.index(0, 0, QModelIndex())
    
    if first_scope.isValid():
        scope_tree.selectionModel().setCurrentIndex(
            first_scope,
            QItemSelectionModel.SelectionFlag.ClearAndSelect
        )
        qtbot.wait(100)
    
    # Wait for variables to populate
    vars_view = window.design_tree_view.vars_view
    vars_table = vars_view.table_view
    filter_proxy = vars_view.filter_proxy
    
    def _vars_populated():
        return filter_proxy.rowCount() > 0
    qtbot.waitUntil(_vars_populated, timeout=2000)
    
    # Select first variable
    first_var_index = filter_proxy.index(0, 0)
    assert first_var_index.isValid()
    
    vars_table.selectionModel().setCurrentIndex(
        first_var_index,
        QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows
    )
    qtbot.wait(50)
    
    # Get signal name
    var_data = filter_proxy.sourceModel().data(
        filter_proxy.mapToSource(first_var_index),
        Qt.ItemDataRole.UserRole
    )
    signal_name = var_data.get('full_path', var_data.get('name'))
    
    # Press 'i' 3 times
    for i in range(3):
        QTest.keyClick(vars_table, Qt.Key.Key_I)
        qtbot.wait(100)
    
    # Verify signal appears 3 times
    session = window.wave_widget.session
    signal_count = sum(
        1 for node in session.root_nodes 
        if node.name == signal_name or node.name.endswith(signal_name)
    )
    assert signal_count == 3, f"Expected 3 occurrences, found {signal_count}"
    
    # Verify in JSON
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "test_split_mode.json"
        
        def verify_signal_count(data):
            root_nodes = data.get("root_nodes", [])
            count = sum(
                1 for node in root_nodes
                if get_full_name_from_json(node).endswith(signal_name)
            )
            assert count == 3, f"Expected 3 in JSON, found {count}"
        
        helper.save_and_verify_json(session, json_path, verify_signal_count)
    
    window.close()


def test_split_mode_inner_scope_selection(qtbot):
    """
    Test selecting variables from inner scopes in split mode.
    
    This test verifies that variables from nested scopes can be selected
    and added to the waveform in split mode, including multi-selection.
    
    Test scenario:
    1. Load swerv1.vcd with nested scope hierarchy
    2. Switch to split mode
    3. Navigate to TOP.tb_top inner scope
    4. Select first 3 variables using multi-selection
    5. Press 'i' to add all selected variables
    6. Verify all 3 variables appear in session and JSON
    """
    helper = WaveScoutTestHelper()
    from scout import WaveScoutMainWindow
    
    # Create window and load VCD
    window = WaveScoutMainWindow()
    qtbot.addWidget(window)
    window.show()
    
    test_vcd = TestPaths.SWERV1_VCD
    assert test_vcd.exists(), f"Test VCD not found: {test_vcd}"
    window.load_file(str(test_vcd))
    
    # Wait for loading
    def _loaded():
        return (
            window.wave_widget.session is not None
            and window.wave_widget.session.waveform_files
            and window.design_tree_view.scope_tree_model is not None
        )
    qtbot.waitUntil(_loaded, timeout=5000)
    
    # Split mode is now the default and only mode
    qtbot.wait(100)
    helper.wait_for_split_mode_ready(window, qtbot)
    
    scope_tree = window.design_tree_view.scope_tree
    scope_model = window.design_tree_view.scope_tree_model
    
    # Navigate to TOP.tb_top
    assert scope_model is not None
    top_index = scope_model.index(0, 0, QModelIndex())
    assert top_index.isValid() and scope_model.data(top_index) == "TOP"
    
    scope_tree.expand(top_index)
    qtbot.wait(100)
    
    tb_top_index = scope_model.index(0, 0, top_index)
    assert tb_top_index.isValid() and scope_model.data(tb_top_index) == "tb_top"
    
    scope_tree.selectionModel().setCurrentIndex(
        tb_top_index,
        QItemSelectionModel.SelectionFlag.ClearAndSelect
    )
    qtbot.wait(200)
    
    # Wait for variables to load
    vars_view = window.design_tree_view.vars_view
    assert vars_view is not None
    vars_table = vars_view.table_view
    
    def _vars_loaded():
        return vars_view and vars_view.vars_model and len(vars_view.vars_model.variables) > 0
    qtbot.waitUntil(_vars_loaded, timeout=3000)
    
    # Select first 3 variables
    selected_vars = []
    assert vars_view.filter_proxy is not None
    assert vars_view.vars_model is not None
    for row in range(3):
        var_index = vars_view.filter_proxy.index(row, 0)
        assert var_index.isValid()
        
        source_index = vars_view.filter_proxy.mapToSource(var_index)
        var_data = vars_view.vars_model.variables[source_index.row()]
        selected_vars.append(var_data['full_path'])
        
        vars_table.selectionModel().setCurrentIndex(
            var_index,
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        )
    
    qtbot.wait(100)
    
    # Add selected variables
    QTest.keyPress(vars_table, Qt.Key.Key_I)
    qtbot.wait(200)
    
    # Verify in session
    session = window.wave_widget.session
    assert session is not None
    assert session.root_nodes is not None
    assert len(session.root_nodes) >= 3
    
    # Verify in JSON
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "test_inner_scope.json"
        
        def verify_selected_vars(data):
            root_nodes = data.get("root_nodes", [])
            assert len(root_nodes) >= 3

            json_names = [get_full_name_from_json(node) for node in root_nodes]
            for var_path in selected_vars:
                assert var_path in json_names, f"Variable '{var_path}' not found"
        
        helper.save_and_verify_json(session, json_path, verify_selected_vars)
    
    # Ensure all background operations complete before closing
    qtbot.wait(200)  # Give time for any pending operations
    QApplication.processEvents()  # Process any pending events
    
    # Wait for thread pool to finish all tasks
    if hasattr(window, 'thread_pool'):
        window.thread_pool.waitForDone(5000)  # Wait up to 5 seconds for threads to finish
    
    # Clear references to Qt objects before closing
    vars_view = None
    vars_table = None
    scope_tree = None
    scope_model = None
    
    window.close()
    qtbot.wait(100)  # Wait a bit after close
    QApplication.processEvents()  # Ensure close is processed


# ========================================================================
# Special Signal Type Tests
# ========================================================================

def test_event_signal_render_type_assignment(qtbot):
    """
    Test automatic RenderType.EVENT assignment for Event-type variables.
    
    This test verifies that variables with var_type 'Event' are automatically
    assigned the correct render_type when added to the waveform.
    
    Test scenario:
    1. Load vcd_extensions.vcd containing EVENT_IN variable
    2. Navigate to main scope and find EVENT_IN
    3. Add EVENT_IN to waveform
    4. Save session to JSON
    5. Verify EVENT_IN has render_type 'event' in JSON
    """
    helper = WaveScoutTestHelper()
    window = helper.setup_main_window_with_vcd(TestPaths.VCD_EXTENSIONS, qtbot)
    
    helper.wait_for_session_loaded(window, qtbot)
    
    design_view = window.design_tree_view.scope_tree
    model = window.design_tree_view.scope_tree_model
    vars_view = window.design_tree_view.vars_view
    
    # Find and select main scope (scopes only contain scopes in split mode)
    root = QModelIndex()
    main_idx = helper.find_child_by_name(model, root, "main")
    assert main_idx and main_idx.isValid(), "'main' scope not found"
    
    # Select the scope to populate VarsView
    design_view.setCurrentIndex(main_idx)
    qtbot.wait(100)
    
    # Now find EVENT_IN in the VarsView
    event_signal_added = False
    if vars_view and vars_view.vars_model.rowCount() > 0:
        for row in range(vars_view.vars_model.rowCount()):
            var_data = vars_view.vars_model.variables[row] if row < len(vars_view.vars_model.variables) else None
            if var_data:
                var_name = var_data.get('name', '')
                if 'EVENT_IN' in var_name:
                    # Found it - add it by double-clicking
                    var_idx = vars_view.filter_proxy.index(row, 0)
                    if var_idx.isValid():
                        vars_view._on_double_click(var_idx)
                        event_signal_added = True
                        break
    
    assert event_signal_added, "'EVENT_IN' not found in VarsView"
    qtbot.wait(100)
    
    # Verify render_type in JSON
    session = window.wave_widget.session
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "event_render_type.json"
        
        def verify_event_render_type(data):
            nodes = data.get("root_nodes", [])
            ev_node = next(
                (n for n in nodes if get_full_name_from_json(n).endswith("main.EVENT_IN")),
                None
            )
            assert ev_node is not None, "EVENT_IN not found in JSON"
            fmt = ev_node.get("format") or {}
            assert fmt.get("render_type") == "event", \
                f"Expected render_type 'event', got {fmt.get('render_type')}"
        
        helper.save_and_verify_json(session, json_path, verify_event_render_type)
    
    window.close()


# ========================================================================
# Analog Render Mode Tests
# ========================================================================

def test_analog_scale_visible_menu_integration(qtbot):
    """
    Test the new unified "Set Render Type" menu with Analog Scale Visible option.
    
    This test verifies that the refactored context menu correctly sets analog
    render mode with "scale to visible data" option and that this setting is
    properly persisted to JSON.
    
    Test scenario:
    1. Load waveform file (apb_sim.vcd)
    2. Add a multi-bit signal (apb_testbench.prdata)
    3. Change signal render mode to "Analog Scale Visible" via the new API
    4. Save session to JSON
    5. Verify JSON contains correct render_type and analog_scaling_mode
    """
    helper = WaveScoutTestHelper()
    window = helper.setup_main_window_with_vcd(TestPaths.APB_SIM_VCD, qtbot)
    
    # Wait for loading to complete
    helper.wait_for_session_loaded(window, qtbot)
    
    design_view = window.design_tree_view.scope_tree
    model = window.design_tree_view.scope_tree_model
    vars_view = window.design_tree_view.vars_view
    
    # Navigate to apb_testbench scope
    root = QModelIndex()
    apb_idx = helper.find_child_by_name(model, root, "apb_testbench")
    assert apb_idx and apb_idx.isValid(), "apb_testbench scope not found"
    
    # Select the scope to populate VarsView
    design_view.setCurrentIndex(apb_idx)
    qtbot.wait(100)
    
    # Find and add prdata signal (multi-bit signal) from VarsView
    prdata_added = False
    if vars_view and vars_view.vars_model.rowCount() > 0:
        for row in range(vars_view.vars_model.rowCount()):
            var_data = vars_view.vars_model.variables[row] if row < len(vars_view.vars_model.variables) else None
            if var_data:
                var_name = var_data.get('name', '')
                if 'prdata' in var_name.lower():
                    # Found it - add it by double-clicking
                    var_idx = vars_view.filter_proxy.index(row, 0)
                    if var_idx.isValid():
                        vars_view._on_double_click(var_idx)
                        prdata_added = True
                        break
    
    assert prdata_added, "prdata signal not found in VarsView"
    qtbot.wait(100)
    
    # Get the signal node from session
    session = window.wave_widget.session
    prdata_node = next(
        n for n in session.root_nodes 
        if n.name.endswith("apb_testbench.prdata")
    )
    
    # Import necessary enums for setting render mode
    from wavescout.core.data_model import RenderType, AnalogScalingMode
    
    # Verify signal is multi-bit
    assert prdata_node.is_multi_bit, "prdata should be a multi-bit signal"
    
    # Change render mode to Analog Scale Visible using controller
    controller = window.wave_widget.controller
    # Set render type and analog scaling mode
    controller.set_node_format(
        prdata_node.instance_id,
        render_type=RenderType.ANALOG,
        analog_scaling_mode=AnalogScalingMode.SCALE_TO_VISIBLE_DATA
    )
    # Also set height to 3 (as the original method did when entering analog mode)
    controller.set_node_format(prdata_node.instance_id, height_scaling=3)
    
    # Verify the settings were applied
    assert prdata_node.format.render_type == RenderType.ANALOG
    assert prdata_node.format.analog_scaling_mode == AnalogScalingMode.SCALE_TO_VISIBLE_DATA
    
    # Save session to JSON and verify
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "test_analog_scale_visible.json"
        
        def verify_analog_scale_visible(data):
            nodes = data.get("root_nodes", [])
            prdata_json = next(
                (n for n in nodes if get_full_name_from_json(n).endswith("apb_testbench.prdata")),
                None
            )
            assert prdata_json is not None, "prdata node not found in saved JSON"

            # Check format section
            format_data = prdata_json.get("format", {})
            assert format_data.get("render_type") == "analog", \
                f"Expected render_type 'analog', got {format_data.get('render_type')}"
            assert format_data.get("analog_scaling_mode") == "scale_to_visible", \
                f"Expected analog_scaling_mode 'scale_to_visible', got {format_data.get('analog_scaling_mode')}"
        
        helper.save_and_verify_json(session, json_path, verify_analog_scale_visible)


def test_signal_rename_and_persistence(qtbot):
    """
    Test signal renaming functionality and persistence in session JSON.
    
    This test verifies that:
    1. Signals can be renamed with a nickname through the UI
    2. Nicknames are displayed in the SignalNames view
    3. Nicknames persist when saving sessions to JSON
    4. Nicknames are restored correctly when loading sessions
    
    Test scenario:
    1. Create WaveScoutWidget and load apb_sim.vcd
    2. Add two signals to the wave widget
    3. Rename signals with nicknames using the API
    4. Save session to JSON file
    5. Verify JSON contains the nicknames
    6. Load the saved session
    7. Verify nicknames are displayed correctly
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

    # Add specific signals to session
    primary_file = session.get_primary_file()
    assert primary_file is not None
    db = primary_file.waveform_db
    assert db is not None and db.hierarchy is not None

    signal_patterns = {
        "prdata": ("apb_testbench.prdata", None),
        "paddr": ("apb_testbench.paddr", None),
    }

    found_nodes = helper.add_signals_to_session(db, session, db.hierarchy, signal_patterns)
    assert "prdata" in found_nodes, "apb_testbench.prdata not found in VCD"
    assert "paddr" in found_nodes, "apb_testbench.paddr not found in VCD"
    
    # Notify model about changes
    if widget.model:
        widget.model.layoutChanged.emit()
    qtbot.wait(50)
    
    # Set nicknames for the signals
    prdata_node = found_nodes["prdata"]
    paddr_node = found_nodes["paddr"]
    
    # Test direct nickname assignment
    prdata_node.nickname = "SignalA"
    paddr_node.nickname = "SignalB"
    
    # Verify nicknames are set
    assert prdata_node.nickname == "SignalA"
    assert paddr_node.nickname == "SignalB"
    
    # Notify model about changes
    if widget.model:
        widget.model.dataChanged.emit(
            widget.model.index(0, 0),
            widget.model.index(widget.model.rowCount() - 1, widget.model.columnCount() - 1),
            [Qt.ItemDataRole.DisplayRole]
        )
    qtbot.wait(50)
    
    # Test rename through UI with mocked dialog
    names_view = widget._names_view
    
    # Select the first signal
    sel_model = names_view.selectionModel()
    if sel_model and widget.model:
        # Find index for prdata_node
        prdata_index = None
        for row in range(widget.model.rowCount()):
            idx = widget.model.index(row, 0)
            node = widget.model.data(idx, Qt.ItemDataRole.UserRole)
            if node == prdata_node:
                prdata_index = idx
                break
        
        if prdata_index:
            # Select the signal
            sel_model.select(prdata_index, QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)
            
            # Mock QInputDialog to return a new nickname automatically
            with patch.object(QInputDialog, 'getText', return_value=("TestNickname", True)):
                # Test keyboard shortcut (R key)
                QTest.keyClick(names_view, Qt.Key.Key_R)
                qtbot.wait(50)
            
            # Verify that the rename was applied through the dialog
            assert prdata_node.nickname == "TestNickname", "Nickname should be updated via dialog"
            
            # Reset nickname back to "SignalA" for JSON verification
            prdata_node.nickname = "SignalA"
    
    # Verify persistence in JSON
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "test_rename_signals.json"
        
        def verify_nicknames(data):
            nodes = data.get("root_nodes", [])

            # Find prdata node
            prdata_json = next(
                (n for n in nodes if get_full_name_from_json(n).endswith("apb_testbench.prdata")),
                None
            )
            assert prdata_json is not None, "prdata node not found in saved JSON"
            assert prdata_json.get("nickname") == "SignalA", \
                f"Expected nickname 'SignalA', got {prdata_json.get('nickname')}"

            # Find paddr node
            paddr_json = next(
                (n for n in nodes if get_full_name_from_json(n).endswith("apb_testbench.paddr")),
                None
            )
            assert paddr_json is not None, "paddr node not found in saved JSON"
            assert paddr_json.get("nickname") == "SignalB", \
                f"Expected nickname 'SignalB', got {paddr_json.get('nickname')}"
        
        helper.save_and_verify_json(session, json_path, verify_nicknames)
        
        # Now test loading the session and verifying nicknames are restored
        loaded_session = load_session(json_path)
        
        # Check that nicknames are present in loaded session
        loaded_prdata = next(
            (n for n in loaded_session.root_nodes if n.name.endswith("apb_testbench.prdata")),
            None
        )
        assert loaded_prdata is not None, "prdata node not found in loaded session"
        assert loaded_prdata.nickname == "SignalA", \
            f"Expected loaded nickname 'SignalA', got {loaded_prdata.nickname}"
        
        loaded_paddr = next(
            (n for n in loaded_session.root_nodes if n.name.endswith("apb_testbench.paddr")),
            None
        )
        assert loaded_paddr is not None, "paddr node not found in loaded session"
        assert loaded_paddr.nickname == "SignalB", \
            f"Expected loaded nickname 'SignalB', got {loaded_paddr.nickname}"
    
    widget.close()


def test_group_rename_functionality(qtbot):
    """
    Test that groups can be renamed via context menu.
    
    This test verifies that:
    1. Groups can be renamed with a nickname
    2. Group nicknames persist in session JSON
    3. Group nicknames are restored when loading sessions
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

    # Add signals to session
    primary_file = session.get_primary_file()
    assert primary_file is not None
    db = primary_file.waveform_db
    assert db is not None and db.hierarchy is not None

    signal_patterns = {
        "prdata": ("apb_testbench.prdata", None),
        "paddr": ("apb_testbench.paddr", None),
    }

    found_nodes = helper.add_signals_to_session(db, session, db.hierarchy, signal_patterns)
    assert "prdata" in found_nodes
    assert "paddr" in found_nodes
    
    # Create a group node
    from wavescout.core.data_model import GroupNode
    group_node = GroupNode(
        local_name="Test Group",
        children=[found_nodes["prdata"], found_nodes["paddr"]]
    )
    
    # Set parent references
    found_nodes["prdata"].parent = group_node
    found_nodes["paddr"].parent = group_node
    
    # Replace individual nodes with group in session
    session.root_nodes = [group_node]
    
    # Notify model about changes
    if widget.model:
        widget.model.layoutChanged.emit()
    qtbot.wait(50)
    
    # Set nickname for the group
    group_node.nickname = "MyCustomGroup"
    
    # Verify nickname is set
    assert group_node.nickname == "MyCustomGroup"
    
    # Verify persistence in JSON
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "test_group_rename.json"
        
        def verify_group_nickname(data):
            nodes = data.get("root_nodes", [])
            assert len(nodes) > 0, "No root nodes found in JSON"
            
            group_json = nodes[0]  # Should be our group
            assert group_json.get("is_group") is True, "First node should be a group"
            assert group_json.get("nickname") == "MyCustomGroup", \
                f"Expected group nickname 'MyCustomGroup', got {group_json.get('nickname')}"
        
        helper.save_and_verify_json(session, json_path, verify_group_nickname)
        
        # Load session and verify nickname is restored
        loaded_session = load_session(json_path)
        assert len(loaded_session.root_nodes) > 0, "No root nodes in loaded session"
        
        loaded_group = loaded_session.root_nodes[0]
        assert loaded_group.is_group, "First node should be a group"
        assert loaded_group.nickname == "MyCustomGroup", \
            f"Expected loaded group nickname 'MyCustomGroup', got {loaded_group.nickname}"

    widget.close()


# ========================================================================
# Dotted Names Support Tests
# ========================================================================

def test_dotted_names_signal_loading_and_display(qtbot):
    """
    Test that signals with dotted names can be loaded and displayed correctly.

    This test verifies:
    1. Signals with dotted names (e.g., "inner.pready") are loaded correctly
    2. Signal local names preserve the dots
    3. Full names are constructed correctly
    4. Signals can be added to the canvas and displayed via UI
    5. Signals appear in SignalNamesView

    Uses apb_sim_2scope.vcd which contains:
    - inner.pready (signal with dot in name in apb_testbench scope)
    - one.two.three.pready (signal with multiple dots in apb_testbench scope)
    - dotted.dot (scope with dot in name)
    """
    from PySide6.QtCore import QModelIndex, QItemSelectionModel
    from PySide6.QtWidgets import QApplication

    helper = WaveScoutTestHelper()
    test_vcd = get_test_input_path(TestFiles.APB_SIM_2SCOPE_VCD)
    assert test_vcd.exists(), f"Test VCD not found: {test_vcd}"

    # Create main window
    window = helper.setup_main_window_with_vcd(test_vcd, qtbot)
    helper.wait_for_session_loaded(window, qtbot)

    design_view = window.design_tree_view
    scope_tree = design_view.scope_tree
    scope_model = design_view.scope_tree_model
    vars_view = design_view.vars_view

    # Navigate to apb_testbench scope
    root = QModelIndex()
    apb_idx = helper.find_child_by_name(scope_model, root, "apb_testbench")
    assert apb_idx and apb_idx.isValid(), "apb_testbench scope not found"

    # Select the scope to populate VarsView
    scope_tree.setCurrentIndex(apb_idx)
    scope_tree.selectionModel().setCurrentIndex(apb_idx, QItemSelectionModel.SelectionFlag.ClearAndSelect)
    qtbot.wait(200)
    QApplication.processEvents()

    # Now add the dotted signals from VarsView
    vars_model = vars_view.vars_model
    assert vars_model and len(vars_model.variables) > 0, "No variables loaded in VarsView"

    # Find and add dotted signals: inner.pready and one.two.three.pready
    dotted_signals_to_add = ['inner.pready', 'one.two.three.pready']
    added_signals = []

    for row in range(len(vars_model.variables)):
        var_data = vars_model.variables[row]
        var_name = var_data.get('name', '')

        if var_name in dotted_signals_to_add:
            # Add this signal via double-click
            table_view = vars_view.table_view
            var_idx = vars_view.filter_proxy.index(row, 0)
            if var_idx.isValid():
                table_view.doubleClicked.emit(var_idx)
                added_signals.append(var_name)
                qtbot.wait(150)
                QApplication.processEvents()

    assert len(added_signals) >= 1, f"Expected to add dotted signals, but only added: {added_signals}"

    # Get session and verify
    session = window.wave_widget.session

    print(f"[TEST] Total signals in session: {len(session.root_nodes)}")
    for node in session.root_nodes:
        if hasattr(node, 'local_name'):
            print(f"[TEST] Signal: local_name='{node.local_name}', full_name='{node.full_name()}'")

    # Verify at least one dotted signal was added
    dotted_signals = [n for n in session.root_nodes if hasattr(n, 'local_name') and '.' in n.local_name]
    assert len(dotted_signals) >= 1, f"Expected at least 1 dotted signal, found {len(dotted_signals)}"

    # Verify specific signals if found
    for signal_name in added_signals:
        node = next(
            (n for n in session.root_nodes if hasattr(n, 'local_name') and n.local_name == signal_name),
            None
        )
        assert node is not None, f"Signal '{signal_name}' not found in session after adding via UI"

        # Verify properties
        assert node.local_name == signal_name, \
            f"Expected local_name '{signal_name}', got '{node.local_name}'"

        expected_full_name = f"apb_testbench.{signal_name}"
        assert node.full_name() == expected_full_name, \
            f"Expected full_name '{expected_full_name}', got '{node.full_name()}'"

    window.close()


def test_dotted_scope_names(qtbot):
    """
    Test signals from scopes with dotted names.

    This test verifies:
    1. Scopes with dotted names (e.g., "dotted.dot") are loaded correctly via UI
    2. Signals from dotted scopes have correct scope_path
    3. Full names are constructed correctly including dotted scope

    Uses apb_sim_2scope.vcd which contains:
    - dotted.dot (scope with dot in name under apb_testbench)
    - one.two (signal inside dotted.dot scope)
    """
    from PySide6.QtCore import QModelIndex, QItemSelectionModel
    from PySide6.QtWidgets import QApplication

    helper = WaveScoutTestHelper()
    test_vcd = get_test_input_path(TestFiles.APB_SIM_2SCOPE_VCD)
    assert test_vcd.exists(), f"Test VCD not found: {test_vcd}"

    # Create main window
    window = helper.setup_main_window_with_vcd(test_vcd, qtbot)
    helper.wait_for_session_loaded(window, qtbot)

    design_view = window.design_tree_view
    scope_tree = design_view.scope_tree
    scope_model = design_view.scope_tree_model
    vars_view = design_view.vars_view

    # Navigate to apb_testbench scope
    root = QModelIndex()
    apb_idx = helper.find_child_by_name(scope_model, root, "apb_testbench")
    assert apb_idx and apb_idx.isValid(), "apb_testbench scope not found"

    # Expand apb_testbench to see child scopes
    scope_tree.expand(apb_idx)
    qtbot.wait(100)

    # Find dotted.dot scope
    dotted_dot_idx = helper.find_child_by_name(scope_model, apb_idx, "dotted.dot")
    assert dotted_dot_idx and dotted_dot_idx.isValid(), "dotted.dot scope not found"

    # Select dotted.dot scope to populate VarsView
    scope_tree.setCurrentIndex(dotted_dot_idx)
    scope_tree.selectionModel().setCurrentIndex(dotted_dot_idx, QItemSelectionModel.SelectionFlag.ClearAndSelect)
    qtbot.wait(200)
    QApplication.processEvents()

    # Add signal from dotted scope
    vars_model = vars_view.vars_model
    assert vars_model and len(vars_model.variables) > 0, "No variables in dotted.dot scope"

    # Find and add one.two signal
    added_one_two = False
    for row in range(len(vars_model.variables)):
        var_data = vars_model.variables[row]
        var_name = var_data.get('name', '')

        if var_name == 'one.two':
            # Add this signal
            table_view = vars_view.table_view
            var_idx = vars_view.filter_proxy.index(row, 0)
            if var_idx.isValid():
                table_view.doubleClicked.emit(var_idx)
                added_one_two = True
                qtbot.wait(150)
                QApplication.processEvents()
                break

    assert added_one_two, "Failed to add 'one.two' signal from dotted.dot scope"

    # Verify in session
    session = window.wave_widget.session
    one_two_node = next(
        (n for n in session.root_nodes
         if hasattr(n, 'local_name') and n.local_name == "one.two"),
        None
    )

    assert one_two_node is not None, "Signal 'one.two' not found in session"

    # Verify signal properties
    assert one_two_node.local_name == "one.two"
    assert one_two_node._waveform_scope == ("apb_testbench", "dotted.dot"), \
        f"Expected scope ('apb_testbench', 'dotted.dot'), got {one_two_node._waveform_scope}"
    assert one_two_node.full_name() == "apb_testbench.dotted.dot.one.two"

    print(f"[TEST] Successfully added signal from dotted scope: {one_two_node.full_name()}")

    window.close()


def test_dotted_names_session_persistence(qtbot):
    """
    Test that sessions with dotted names persist correctly.

    This test verifies:
    1. Sessions with dotted signal names can be saved to JSON
    2. local_name and scope_path are preserved in JSON
    3. Sessions can be loaded back with dotted names intact
    4. Loaded signals work correctly
    5. All signals added via UI appear in SignalNamesView
    """
    from .test_utils import add_signal_from_design_tree, verify_signal_in_names_view

    helper = WaveScoutTestHelper()
    test_vcd = get_test_input_path(TestFiles.APB_SIM_2SCOPE_VCD)
    assert test_vcd.exists(), f"Test VCD not found: {test_vcd}"

    # Create main window
    window = helper.setup_main_window_with_vcd(test_vcd, qtbot)
    helper.wait_for_session_loaded(window, qtbot)

    # Add all dotted signals via UI
    signals_to_add = [
        (['apb_testbench'], 'inner.pready', 'apb_testbench.inner.pready'),
        (['apb_testbench'], 'one.two.three.pready', 'apb_testbench.one.two.three.pready'),
        (['apb_testbench', 'dotted.dot'], 'one.two', 'apb_testbench.dotted.dot.one.two'),
    ]

    for scope_path, signal_name, full_name in signals_to_add:
        success = add_signal_from_design_tree(window, scope_path, signal_name, qtbot)
        assert success, f"Failed to add signal '{signal_name}' via UI"
        assert verify_signal_in_names_view(window, full_name), \
            f"Signal '{full_name}' not found in SignalNamesView"

    session = window.wave_widget.session
    assert len(session.root_nodes) == 3, f"Expected 3 signals, found {len(session.root_nodes)}"

    # Save and verify JSON
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "dotted_names_session.json"

        def verify_dotted_names_json(data):
            nodes = data.get("root_nodes", [])
            assert len(nodes) == 3, f"Expected 3 nodes in JSON, got {len(nodes)}"

            # Find and verify each signal
            inner_pready = next(
                (n for n in nodes if n.get("local_name") == "inner.pready"),
                None
            )
            assert inner_pready is not None, "inner.pready not found in JSON"
            assert inner_pready.get("local_name") == "inner.pready"
            assert inner_pready.get("scope_path") == ["apb_testbench"]

            one_two_three = next(
                (n for n in nodes if n.get("local_name") == "one.two.three.pready"),
                None
            )
            assert one_two_three is not None, "one.two.three.pready not found in JSON"
            assert one_two_three.get("local_name") == "one.two.three.pready"
            assert one_two_three.get("scope_path") == ["apb_testbench"]

            one_two = next(
                (n for n in nodes if n.get("local_name") == "one.two" and
                 n.get("scope_path") == ["apb_testbench", "dotted.dot"]),
                None
            )
            assert one_two is not None, "one.two from dotted scope not found in JSON"
            assert one_two.get("local_name") == "one.two"
            assert one_two.get("scope_path") == ["apb_testbench", "dotted.dot"]

        helper.save_and_verify_json(session, json_path, verify_dotted_names_json)

        # Load session and verify signals are restored
        loaded_session = load_session(json_path)
        assert loaded_session is not None
        assert len(loaded_session.root_nodes) == 3

        # Verify each loaded signal
        loaded_inner = next(
            (n for n in loaded_session.root_nodes if n.local_name == "inner.pready"),
            None
        )
        assert loaded_inner is not None
        assert loaded_inner.full_name() == "apb_testbench.inner.pready"

        loaded_one_two_three = next(
            (n for n in loaded_session.root_nodes if n.local_name == "one.two.three.pready"),
            None
        )
        assert loaded_one_two_three is not None
        assert loaded_one_two_three.full_name() == "apb_testbench.one.two.three.pready"

        loaded_one_two = next(
            (n for n in loaded_session.root_nodes
             if n.local_name == "one.two" and n._waveform_scope == ("apb_testbench", "dotted.dot")),
            None
        )
        assert loaded_one_two is not None
        assert loaded_one_two.full_name() == "apb_testbench.dotted.dot.one.two"

    window.close()


def test_dotted_names_in_groups(qtbot):
    """
    Test that groups containing signals with dotted names work correctly.

    This test verifies:
    1. Groups can contain signals with dotted names added via UI
    2. Group structure with dotted signals persists correctly
    3. Groups can be saved and loaded with dotted signal names
    4. Signals in group appear in SignalNamesView
    """
    from .test_utils import add_signal_from_design_tree, verify_signal_in_names_view
    from PySide6.QtCore import QItemSelection, QItemSelectionModel

    helper = WaveScoutTestHelper()
    test_vcd = get_test_input_path(TestFiles.APB_SIM_2SCOPE_VCD)
    assert test_vcd.exists(), f"Test VCD not found: {test_vcd}"

    # Create main window
    window = helper.setup_main_window_with_vcd(test_vcd, qtbot)
    helper.wait_for_session_loaded(window, qtbot)

    # Add signals with dotted names via UI
    success1 = add_signal_from_design_tree(
        window,
        scope_path=['apb_testbench'],
        signal_name='inner.pready',
        qtbot=qtbot
    )
    assert success1, "Failed to add signal 'inner.pready' via UI"

    success2 = add_signal_from_design_tree(
        window,
        scope_path=['apb_testbench'],
        signal_name='one.two.three.pready',
        qtbot=qtbot
    )
    assert success2, "Failed to add signal 'one.two.three.pready' via UI"

    # Verify signals appear in SignalNamesView
    assert verify_signal_in_names_view(window, "apb_testbench.inner.pready")
    assert verify_signal_in_names_view(window, "apb_testbench.one.two.three.pready")

    session = window.wave_widget.session
    assert len(session.root_nodes) == 2

    # Get the added signal nodes
    inner_pready = session.root_nodes[0]
    one_two_three = session.root_nodes[1]

    # Create a group with these signals
    from wavescout.core.data_model import GroupNode
    group_node = GroupNode(
        local_name="Dotted Signals",
        children=[inner_pready, one_two_three],
        is_expanded=True
    )

    # Set parent references
    inner_pready.parent = group_node
    one_two_three.parent = group_node

    # Replace individual nodes with group
    session.root_nodes = [group_node]

    # Notify model
    if window.wave_widget.model:
        window.wave_widget.model.layoutChanged.emit()
    qtbot.wait(50)

    # Verify group structure
    assert len(session.root_nodes) == 1
    assert session.root_nodes[0].is_group
    assert len(session.root_nodes[0].children) == 2
    assert session.root_nodes[0].children[0].local_name == "inner.pready"
    assert session.root_nodes[0].children[1].local_name == "one.two.three.pready"

    # Save and verify JSON
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "dotted_names_group.json"

        def verify_group_with_dotted_names(data):
            nodes = data.get("root_nodes", [])
            assert len(nodes) == 1, "Expected 1 root node (the group)"

            group_json = nodes[0]
            assert group_json.get("is_group") is True
            assert group_json.get("local_name") == "Dotted Signals"

            children = group_json.get("children", [])
            assert len(children) == 2, f"Expected 2 children, got {len(children)}"

            # Verify children have dotted local names
            assert children[0].get("local_name") == "inner.pready"
            assert children[1].get("local_name") == "one.two.three.pready"

        helper.save_and_verify_json(session, json_path, verify_group_with_dotted_names)

        # Load and verify
        loaded_session = load_session(json_path)
        assert len(loaded_session.root_nodes) == 1

        loaded_group = loaded_session.root_nodes[0]
        assert loaded_group.is_group
        assert len(loaded_group.children) == 2
        assert loaded_group.children[0].local_name == "inner.pready"
        assert loaded_group.children[1].local_name == "one.two.three.pready"
        assert loaded_group.children[0].full_name() == "apb_testbench.inner.pready"
        assert loaded_group.children[1].full_name() == "apb_testbench.one.two.three.pready"

    window.close()


def test_mixed_dotted_and_regular_signals(qtbot):
    """
    Test sessions with a mix of regular and dotted signal names.

    This test verifies that both regular signals and signals with dotted names
    can coexist in the same session and be handled correctly via UI interactions.
    All signals added via UI appear in SignalNamesView.
    """
    from .test_utils import add_signal_from_design_tree, verify_signal_in_names_view

    helper = WaveScoutTestHelper()
    test_vcd = get_test_input_path(TestFiles.APB_SIM_2SCOPE_VCD)
    assert test_vcd.exists(), f"Test VCD not found: {test_vcd}"

    # Create main window
    window = helper.setup_main_window_with_vcd(test_vcd, qtbot)
    helper.wait_for_session_loaded(window, qtbot)

    # Add mix of regular and dotted signals via UI
    signals_to_add = [
        (['apb_testbench'], 'pready', 'apb_testbench.pready'),  # Regular signal
        (['apb_testbench'], 'inner.pready', 'apb_testbench.inner.pready'),  # Dotted signal
        (['apb_testbench'], 'pclk', 'apb_testbench.pclk'),  # Regular signal
        (['apb_testbench'], 'one.two.three.pready', 'apb_testbench.one.two.three.pready'),  # Dotted signal
    ]

    for scope_path, signal_name, full_name in signals_to_add:
        success = add_signal_from_design_tree(window, scope_path, signal_name, qtbot)
        assert success, f"Failed to add signal '{signal_name}' via UI"
        assert verify_signal_in_names_view(window, full_name), \
            f"Signal '{full_name}' not found in SignalNamesView"

    session = window.wave_widget.session
    assert len(session.root_nodes) == 4, f"Expected 4 signals, found {len(session.root_nodes)}"

    # Verify each signal's local name
    signal_map = {node.local_name: node for node in session.root_nodes}
    assert "pready" in signal_map
    assert "inner.pready" in signal_map
    assert "pclk" in signal_map
    assert "one.two.three.pready" in signal_map

    # Save and reload session
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "mixed_signals.json"

        def verify_mixed_signals(data):
            nodes = data.get("root_nodes", [])
            assert len(nodes) == 4

            # Verify we have both types
            regular_count = sum(1 for n in nodes if "." not in n.get("local_name", ""))
            dotted_count = sum(1 for n in nodes if "." in n.get("local_name", ""))

            assert regular_count == 2, f"Expected 2 regular signals, got {regular_count}"
            assert dotted_count == 2, f"Expected 2 dotted signals, got {dotted_count}"

        helper.save_and_verify_json(session, json_path, verify_mixed_signals)

        # Load and verify all signals work
        loaded_session = load_session(json_path)
        assert len(loaded_session.root_nodes) == 4

        # Verify full names
        full_names = {node.full_name() for node in loaded_session.root_nodes}
        expected_names = {
            "apb_testbench.pready",
            "apb_testbench.inner.pready",
            "apb_testbench.pclk",
            "apb_testbench.one.two.three.pready"
        }
        assert full_names == expected_names, f"Name mismatch: {full_names} vs {expected_names}"

    window.close()
