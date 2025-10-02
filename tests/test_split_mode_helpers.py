"""Helper functions for working with split mode in tests."""

from typing import List, Optional
from PySide6.QtCore import QModelIndex, Qt, QItemSelectionModel
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from scout import WaveScoutMainWindow
from wavescout.core.data_model import TreeNode, SignalNode
from wavescout.core.waveform_db import AsyncLoadedSignal


def add_signals_from_split_mode(window: WaveScoutMainWindow, count: int = 5) -> List[TreeNode]:
    """
    Helper to add signals from the design tree in split mode.

    In split mode:
    - The scope tree only contains scopes (no signals)
    - When a scope is selected, its variables appear in the VarsView
    - Variables are added by double-clicking in the VarsView

    Args:
        window: WaveScoutMainWindow instance
        count: Number of signals to add

    Returns:
        List of SignalNode objects that were actually added to the session
    """
    design_view = window.design_tree_view
    scope_model = design_view.scope_tree_model

    if not scope_model or not window.wave_widget.session:
        return []

    # Track initial count of signals in session
    initial_count = len(window.wave_widget.session.root_nodes)
    signals_added = []

    # Find scopes and add their variables
    def add_from_scope(scope_idx: QModelIndex, remaining: int) -> int:
        """Add variables from a scope, return number still needed."""
        if remaining <= 0:
            return 0

        # Select the scope using the selection model
        selection_model = design_view.scope_tree.selectionModel()
        selection_model.setCurrentIndex(
            scope_idx,
            QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows
        )
        QTest.qWait(150)  # Let the selection propagate and load variables
        QApplication.processEvents()

        # Check if VarsView has variables
        vars_model = design_view.vars_view.vars_model
        if vars_model and hasattr(vars_model, 'variables') and len(vars_model.variables) > 0:
            # Add variables from this scope
            vars_view = design_view.vars_view
            table = vars_view.table_view if hasattr(vars_view, 'table_view') else vars_view.table

            for row in range(min(remaining, len(vars_model.variables))):
                # Get the proxy index for this row
                var_idx = vars_view.filter_proxy.index(row, 0)
                if var_idx.isValid():
                    # Emit double-click signal to add the variable
                    table.doubleClicked.emit(var_idx)
                    QTest.qWait(50)  # Small delay between additions
                    QApplication.processEvents()

                    # Check if signal was added
                    current_count = len(window.wave_widget.session.root_nodes)
                    if current_count > len(signals_added) + initial_count:
                        # A new signal was added
                        new_signal = window.wave_widget.session.root_nodes[-1]
                        signals_added.append(new_signal)
                        remaining -= 1

                    if remaining <= 0:
                        break

        # If we still need more, try child scopes
        if remaining > 0:
            for child_row in range(scope_model.rowCount(scope_idx)):
                child_idx = scope_model.index(child_row, 0, scope_idx)
                if child_idx.isValid():
                    # Expand the child scope
                    design_view.scope_tree.expand(child_idx)
                    QTest.qWait(30)
                    remaining = add_from_scope(child_idx, remaining)
                    if remaining <= 0:
                        break

        return remaining

    # Start from root scopes
    remaining = count
    for row in range(scope_model.rowCount(QModelIndex())):
        root_idx = scope_model.index(row, 0, QModelIndex())
        if root_idx.isValid():
            # Expand root scope
            design_view.scope_tree.expand(root_idx)
            QTest.qWait(50)
            remaining = add_from_scope(root_idx, remaining)
            if remaining <= 0:
                break

    # Wait for all signals to be processed
    QTest.qWait(200)
    QApplication.processEvents()

    return signals_added


def add_signals_by_double_click_vars(window: WaveScoutMainWindow, count: int = 3) -> List[TreeNode]:
    """
    Alternative helper that adds signals directly if the UI method fails.
    This is a fallback for when the split view isn't working as expected.

    Args:
        window: WaveScoutMainWindow instance
        count: Number of signals to add

    Returns:
        List of SignalNode objects that were added
    """
    session = window.wave_widget.session
    if not session or not session.waveform_db:
        return []

    signals_added = []
    waveform_db = session.waveform_db

    if waveform_db.hierarchy:
        # Find variables in the hierarchy
        signal_count = 0
        for scope in waveform_db.hierarchy.top_scopes():
            if signal_count >= count:
                break

            # Check child scopes too
            def add_from_scope_recursive(current_scope, max_count):
                nonlocal signal_count
                if signal_count >= max_count:
                    return

                # Add variables from this scope
                for var in current_scope.vars(waveform_db.hierarchy):
                    if signal_count >= max_count:
                        break

                    handle = var.signal_handle()
                    if handle is not None:
                        # Create signal node
                        signal_node = SignalNode(
                            name=var.name(waveform_db.hierarchy),
                            handle=handle,
                            var=var,
                            signal=AsyncLoadedSignal.placeholder(handle)
                        )

                        # Check if already added
                        already_exists = any(
                            node.handle == handle
                            for node in session.root_nodes
                            if not node.is_group
                        )

                        if not already_exists:
                            session.root_nodes.append(signal_node)
                            signals_added.append(signal_node)
                            signal_count += 1

                # Recurse into child scopes
                for child_scope in current_scope.scopes(waveform_db.hierarchy):
                    if signal_count >= max_count:
                        break
                    add_from_scope_recursive(child_scope, max_count)

            add_from_scope_recursive(scope, count)

    # Notify model of changes
    if signals_added and window.wave_widget.model:
        window.wave_widget.model.layoutChanged.emit()

    return signals_added
