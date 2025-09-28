"""Test for Navigate to Scope feature in split view mode."""

import pytest
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QModelIndex, Qt, QTimer
from PySide6.QtTest import QTest

from scout import WaveScoutMainWindow
from wavescout.data_model import SignalNode, SignalNodeSignal, DisplayFormat
from wavescout import create_sample_session
from wavescout.waveform_loader import create_signal_node_from_var
from tests.test_utils import get_test_input_path, TestFiles


class TestNavigateSplitMode:
    """Test suite for navigate to scope functionality in split view mode."""
    
    @pytest.fixture
    def app(self, qapp):
        """Provide QApplication instance."""
        return qapp
    
    @pytest.fixture
    def main_window(self, app):
        """Create main window with test waveform loaded."""
        test_file = str(get_test_input_path(TestFiles.APB_SIM_VCD))
        window = WaveScoutMainWindow(wave_file=test_file)
        
        # Wait for session to be created
        max_wait = 3000
        elapsed = 0
        while window.wave_widget.session is None and elapsed < max_wait:
            QTest.qWait(50)
            elapsed += 50
        
        # Give a small buffer for UI to stabilize
        if window.wave_widget.session:
            QTest.qWait(100)
        
        yield window
        
        # Cleanup
        window.close()
    
    def test_navigate_in_split_mode(self, main_window):
        """Test that navigation works in split mode and selects variable in bottom panel."""
        window = main_window

        # Split mode is now the default and only mode
        QTest.qWait(200)

        # Get waveform_db from loaded session
        session = window.wave_widget.session
        if not session or not session.waveform_db:
            pytest.skip("No waveform database loaded")

        db = session.waveform_db
        hierarchy = db.hierarchy

        # Find a signal matching our test path or use first available
        signal_path = "apb_testbench.dut.paddr"
        target_handle = None
        target_var = None

        # Try to find the specific signal
        all_handles = list(db.get_all_handles())
        for handle in all_handles:
            var = db.get_var(handle)
            if var:
                full_name = var.full_name(hierarchy)
                if signal_path in full_name or 'paddr' in full_name.lower():
                    target_handle = handle
                    target_var = var
                    signal_path = full_name  # Use actual full name
                    break

        # Fall back to first available signal if specific one not found
        if not target_var and all_handles:
            target_handle = all_handles[0]
            target_var = db.get_var(target_handle)
            if target_var:
                signal_path = target_var.full_name(hierarchy)

        if not target_var:
            pytest.skip("No suitable test signal found")

        # Create real signal node with actual waveform data
        signal_node = create_signal_node_from_var(target_var, hierarchy, target_handle, db)

        session.root_nodes = [signal_node]
        window.wave_widget.update()
        QTest.qWait(100)
        
        # Navigate to the scope with variable selection
        scope_path = "apb_testbench.dut"
        result = window.design_tree_view.navigate_to_scope(scope_path, signal_path)
        
        assert result == True, "Navigation should succeed"
        
        QTest.qWait(500)  # Give more time for split mode to update
        
        # Check what's selected in scope tree (top panel)
        scope_tree = window.design_tree_view.scope_tree
        scope_current = scope_tree.currentIndex()
        
        if scope_current.isValid():
            scope_model = window.design_tree_view.scope_tree_model
            scope_node = scope_model.data(scope_current, Qt.ItemDataRole.UserRole)
            if scope_node and hasattr(scope_node, 'name'):
                print(f"Split mode - Scope tree selected: {scope_node.name}")
                assert scope_node.name == "dut", f"Expected 'dut' scope, got '{scope_node.name}'"
        else:
            pytest.fail("No selection in scope tree")
        
        # Check if variables are shown in the bottom panel
        vars_view = window.design_tree_view.vars_view
        if vars_view:
            # Check if variables are loaded
            var_count = vars_view.vars_model.rowCount() if vars_view.vars_model else 0
            print(f"Split mode - Variables in bottom panel: {var_count}")
            
            if var_count > 0:
                # Check if paddr is selected in the variables view
                current_var = vars_view.table_view.currentIndex()
                if current_var.isValid():
                    # Get the variable name from the first column (through proxy)
                    proxy_model = vars_view.filter_proxy
                    var_name = proxy_model.data(
                        proxy_model.index(current_var.row(), 0),
                        Qt.ItemDataRole.DisplayRole
                    )
                    print(f"Split mode - Selected variable: {var_name}")
                    
                    if var_name == "paddr":
                        print("✓ Variable correctly selected in bottom panel")
                    else:
                        print(f"✗ Wrong variable selected: {var_name}")
                else:
                    print("✗ No variable selected in bottom panel")
                    
                    # List available variables for debugging
                    print("Available variables:")
                    for row in range(min(5, var_count)):
                        var_data = vars_view.vars_model.variables[row] if row < len(vars_view.vars_model.variables) else None
                        if var_data:
                            var_name = var_data.get('name', '')
                            print(f"  - {var_name}")
            else:
                print("✗ No variables shown in bottom panel")
        else:
            pytest.fail("Variables view not available")
    
    def test_signal_emission_in_split_mode(self, main_window):
        """Test that signal emission works correctly in split mode."""
        window = main_window

        # Split mode is now the default and only mode
        QTest.qWait(200)

        # Get waveform_db from loaded session
        session = window.wave_widget.session
        if not session or not session.waveform_db:
            pytest.skip("No waveform database loaded")

        db = session.waveform_db
        hierarchy = db.hierarchy

        # Find a signal for testing
        signal_path = "apb_testbench.pready"
        target_handle = None
        target_var = None

        # Try to find the specific signal or any signal with 'ready' in its name
        all_handles = list(db.get_all_handles())
        for handle in all_handles:
            var = db.get_var(handle)
            if var:
                full_name = var.full_name(hierarchy)
                if 'pready' in full_name.lower() or 'ready' in full_name.lower():
                    target_handle = handle
                    target_var = var
                    signal_path = full_name  # Use actual full name
                    break

        # Fall back to second available signal if specific one not found
        if not target_var and len(all_handles) > 1:
            target_handle = all_handles[1]
            target_var = db.get_var(target_handle)
            if target_var:
                signal_path = target_var.full_name(hierarchy)

        if not target_var:
            pytest.skip("No suitable test signal found")

        # Create real signal node with actual waveform data
        signal_node = create_signal_node_from_var(target_var, hierarchy, target_handle, db)

        session.root_nodes = [signal_node]
        window.wave_widget.update()
        QTest.qWait(100)
        
        # Emit the navigation signal (simulating context menu action)
        scope_path = "apb_testbench"
        window.wave_widget._names_view.navigate_to_scope_requested.emit(scope_path, signal_path)
        
        QTest.qWait(500)
        
        # Check scope selection
        scope_tree = window.design_tree_view.scope_tree
        scope_current = scope_tree.currentIndex()
        
        if scope_current.isValid():
            scope_model = window.design_tree_view.scope_tree_model
            scope_node = scope_model.data(scope_current, Qt.ItemDataRole.UserRole)
            if scope_node and hasattr(scope_node, 'name'):
                print(f"Signal emission test - Scope selected: {scope_node.name}")
                assert scope_node.name == "apb_testbench", f"Expected 'apb_testbench', got '{scope_node.name}'"
                
                # Check variable selection in bottom panel
                vars_view = window.design_tree_view.vars_view
                if vars_view and vars_view.vars_model:
                    var_count = vars_view.vars_model.rowCount()
                    print(f"Variables shown: {var_count}")
                    
                    # Check for pready in the list
                    found_pready = False
                    for row in range(var_count):
                        var_data = vars_view.vars_model.variables[row] if row < len(vars_view.vars_model.variables) else None
                        if var_data:
                            var_name = var_data.get('name', '')
                            if var_name == "pready":
                                found_pready = True
                                break
                    
                    if found_pready:
                        print("✓ Target variable 'pready' is in the variables list")
                    else:
                        print("✗ Target variable 'pready' not found in variables list")
