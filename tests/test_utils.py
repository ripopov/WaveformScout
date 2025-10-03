"""Common test utilities and fixtures for WaveScout tests."""

from pathlib import Path
from typing import Optional


class MockVar:
    """Mock Var object for tests that don't have a real waveform_db."""

    def __init__(self, name: str = "test_signal", bitwidth: int = 1, var_type: str = "Wire"):
        self._name = name
        self._bitwidth = bitwidth
        self._var_type = var_type

    def name(self, hier=None) -> str:
        return self._name

    def full_name(self, hier=None) -> str:
        return self._name

    def bitwidth(self) -> int:
        return self._bitwidth

    def var_type(self) -> str:
        return self._var_type

    def is_1bit(self) -> bool:
        return self._bitwidth == 1

    def signal_handle(self) -> int:
        return -1  # Invalid handle for test purposes


def get_repo_root() -> Path:
    """Get the repository root directory.
    
    Returns the absolute path to the WaveScout repository root.
    """
    # This file is in tests/, so parent is the repo root
    return Path(__file__).parent.parent.resolve()


def get_test_input_path(filename: str) -> Path:
    """Get the absolute path to a test input file.
    
    Args:
        filename: Name of the file in test_inputs directory
        
    Returns:
        Absolute path to the test input file
        
    Raises:
        FileNotFoundError: If the file doesn't exist
    """
    repo_root = get_repo_root()
    file_path = repo_root / "test_inputs" / filename
    
    if not file_path.exists():
        raise FileNotFoundError(f"Test input file not found: {file_path}")
    
    return file_path


def get_test_inputs_dir() -> Path:
    """Get the absolute path to the test_inputs directory.
    
    Returns:
        Absolute path to test_inputs directory
    """
    repo_root = get_repo_root()
    return repo_root / "test_inputs"


# Common test file constants
class TestFiles:
    """Constants for commonly used test files."""
    
    # VCD files
    APB_SIM_VCD = "apb_sim.vcd"
    APB_SIM_2SCOPE_VCD = "apb_sim_2scope.vcd"
    SWERV1_VCD = "swerv1.vcd"
    VCD_EXTENSIONS = "vcd_extensions.vcd"
    PULSE_TEST_VCD = "pulse_test.vcd"
    STAIRCASE_VCD = "staircase.vcd"
    EVENT_TEST_VCD = "event_test.vcd"
    ANALOG_SIGNALS_VCD = "analog_signals.vcd"
    ANALOG_SIGNALS_SHORT_VCD = "analog_signals_short.vcd"
    DESIGN_GPT5_VCD = "design-gpt5.vcd"
    DESIGN_CLAUDE_VCD = "design_claude.vcd"
    BENCHMARK_DESIGN_VCD = "benchmark_design.vcd"
    
    # FST files
    DES_FST = "des.fst"
    VCD_EXTENSIONS_FST = "vcd_extensions.fst"
    ANALOG_SIGNALS_FST = "analog_signals.fst"
    ANALOG_SIGNALS_SHORT_FST = "analog_signals_short.fst"
    BENCHMARK_SIGNALS_FST = "benchmark_signals.fst"
    DESIGN_CLAUDE_FST = "design_claude.fst"
    
    @classmethod
    def get_path(cls, filename: str) -> Path:
        """Get the absolute path for a test file constant.
        
        Args:
            filename: One of the file constants from this class
            
        Returns:
            Absolute path to the test file
        """
        return get_test_input_path(filename)


def ensure_test_file_exists(filename: str) -> Path:
    """Ensure a test file exists and return its absolute path.
    
    Args:
        filename: Name of the test file
        
    Returns:
        Absolute path to the test file
        
    Raises:
        FileNotFoundError: If the file doesn't exist
    """
    path = get_test_input_path(filename)
    if not path.exists():
        available_files = list(get_test_inputs_dir().glob("*"))
        available_names = [f.name for f in available_files if f.is_file()]
        raise FileNotFoundError(
            f"Test file '{filename}' not found in test_inputs/.\n"
            f"Available files: {', '.join(sorted(available_names))}"
        )
    return path


def get_small_test_file() -> Path:
    """Get a small test file suitable for quick tests.
    
    Returns:
        Path to apb_sim.vcd which is a small file (4.5KB)
    """
    return get_test_input_path(TestFiles.APB_SIM_VCD)


def get_medium_test_file() -> Path:
    """Get a medium-sized test file for more comprehensive tests.
    
    Returns:
        Path to swerv1.vcd which is a medium file (14MB)
    """
    return get_test_input_path(TestFiles.SWERV1_VCD)


def get_fst_test_file() -> Path:
    """Get an FST format test file.

    Returns:
        Path to des.fst
    """
    return get_test_input_path(TestFiles.DES_FST)


def add_signal_from_design_tree(window, scope_path: list, signal_name: str, qtbot) -> bool:
    """Add a signal from design tree by navigating scopes and double-clicking in VarsView.

    This is the UI-driven approach to adding signals, matching how users interact
    with the application through DesignTreeView and VarsView.

    Args:
        window: WaveScoutMainWindow instance
        scope_path: List of scope names to navigate (e.g., ['apb_testbench'])
        signal_name: Name of the signal to add (e.g., 'inner.pready')
        qtbot: pytest-qt fixture

    Returns:
        True if signal was successfully added, False otherwise
    """
    from PySide6.QtCore import QModelIndex, QItemSelectionModel
    from PySide6.QtWidgets import QApplication

    design_view = window.design_tree_view
    scope_tree = design_view.scope_tree
    scope_model = design_view.scope_tree_model
    vars_view = design_view.vars_view

    if not scope_model or not vars_view:
        return False

    # Navigate through scope path
    current_idx = QModelIndex()
    for scope_name in scope_path:
        found = False
        for row in range(scope_model.rowCount(current_idx)):
            idx = scope_model.index(row, 0, current_idx)
            if idx.isValid() and scope_model.data(idx) == scope_name:
                scope_tree.expand(idx)
                current_idx = idx
                found = True
                break

        if not found:
            return False

    # Select the final scope to populate VarsView
    scope_tree.setCurrentIndex(current_idx)
    scope_tree.selectionModel().setCurrentIndex(
        current_idx,
        QItemSelectionModel.SelectionFlag.ClearAndSelect
    )
    qtbot.wait(200)  # Wait for VarsView to populate
    QApplication.processEvents()

    # Find signal in VarsView
    vars_model = vars_view.vars_model
    if not vars_model or not hasattr(vars_model, 'variables'):
        return False

    for row in range(len(vars_model.variables)):
        var_data = vars_model.variables[row]
        if var_data.get('name') == signal_name:
            # Found the signal - emit double-click via table view to trigger the proper event
            table_view = vars_view.table_view
            var_idx = vars_view.filter_proxy.index(row, 0)
            if var_idx.isValid():
                # Track initial count
                initial_count = len(window.wave_widget.session.root_nodes)
                print(f"[TEST_UTILS] Adding signal '{signal_name}', initial count: {initial_count}")

                # Emit the double-click signal properly
                table_view.doubleClicked.emit(var_idx)
                qtbot.wait(100)
                QApplication.processEvents()

                # Wait for signal to be added (with timeout)
                for i in range(20):  # Wait up to 2 seconds
                    current_count = len(window.wave_widget.session.root_nodes)
                    if current_count > initial_count:
                        print(f"[TEST_UTILS] Signal added! New count: {current_count}")
                        qtbot.wait(50)  # Extra wait for stability
                        QApplication.processEvents()
                        return True
                    qtbot.wait(100)
                    QApplication.processEvents()

                # Check one more time and print debug info
                final_count = len(window.wave_widget.session.root_nodes)
                print(f"[TEST_UTILS] Timeout waiting for signal. Final count: {final_count}")
                if window.wave_widget.session.root_nodes:
                    print(f"[TEST_UTILS] Current signals in session:")
                    for node in window.wave_widget.session.root_nodes:
                        if hasattr(node, 'full_name'):
                            print(f"[TEST_UTILS]   - {node.full_name()}")
                return final_count > initial_count

    return False


def verify_signal_in_names_view(window, signal_full_name: str) -> bool:
    """Verify that a signal appears in the SignalNamesView.

    Args:
        window: WaveScoutMainWindow instance
        signal_full_name: Full name of the signal to find (e.g., 'apb_testbench.inner.pready')

    Returns:
        True if signal is found in the names view, False otherwise
    """
    from PySide6.QtCore import Qt

    session = window.wave_widget.session
    if not session:
        return False

    # Search through session root nodes
    for node in session.root_nodes:
        if hasattr(node, 'full_name'):
            if node.full_name() == signal_full_name:
                return True
        # Also check children if it's a group
        if hasattr(node, 'is_group') and node.is_group and hasattr(node, 'children'):
            for child in node.children:
                if hasattr(child, 'full_name') and child.full_name() == signal_full_name:
                    return True

    return False