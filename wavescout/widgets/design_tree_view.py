"""
Design Tree View Widget

A widget that shows the design hierarchy with scopes in the top panel 
and filtered variables in the bottom panel.
"""

from __future__ import annotations

import time
from typing import Optional, List, cast, TYPE_CHECKING, Union

if TYPE_CHECKING:
    from wavescout.core.waveform_db import Var
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeView,
    QLabel, QSplitter, QProgressDialog, QApplication, QAbstractItemView
)
from PySide6.QtCore import Qt, Signal, QModelIndex, QEvent, QObject
from PySide6.QtGui import QKeyEvent

from pyrox import SignalHandle

from ..core.data_model import TreeNode, SignalNode, RenderType, DisplayFormat, WaveformFileReference
from ..utils.settings_manager import SettingsManager
from ..models.scope_tree_model import ScopeTreeModel, DesignTreeNode
from ..models.multi_file_scope_tree_model import MultiFileScopeTreeModel
from .vars_view import VarsView

from ..core.waveform_db import WaveformDB
from .vars_view import VariableData
from ..utils.timing_utils import tprint


class DesignTreeView(QWidget):
    """
    Design tree widget with split view showing scopes and variables
    """
    
    # Signals
    signals_selected = Signal(list)  # List of SignalNode objects
    status_message = Signal(str)
    
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self.waveform_db: Optional['WaveformDB'] = None
        self.waveform_files: List[WaveformFileReference] = []
        self.scope_tree_model: Optional[Union[ScopeTreeModel, MultiFileScopeTreeModel]] = None
        self.vars_view: Optional[VarsView] = None
        self.current_file_id: int = 0  # Track current file for signal creation

        # Settings manager
        self.settings_manager = SettingsManager()

        # Setup UI
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Create the UI structure"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Header
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(5, 5, 5, 5)
        
        title_label = QLabel("Design Hierarchy")
        title_label.setStyleSheet("font-weight: bold;")
        header_layout.addWidget(title_label)
        
        header_layout.addStretch()
        
        layout.addWidget(header_widget)
        
        # Split widget with scopes and variables
        self.split_widget = QSplitter(Qt.Orientation.Vertical)
        
        # Top panel: Scope tree
        self.scope_tree = QTreeView()
        self.scope_tree.setAlternatingRowColors(True)
        self.scope_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # Let QTreeView handle expansion by default - don't override
        self.scope_tree.setExpandsOnDoubleClick(True)
        self.split_widget.addWidget(self.scope_tree)
        
        # Bottom panel: Variables view
        self.vars_view = VarsView()
        self.vars_view.variables_selected.connect(self._on_variables_selected)
        self.split_widget.addWidget(self.vars_view)
        
        # Set initial splitter sizes (30% top, 70% bottom)
        self.split_widget.setSizes([300, 700])
        
        layout.addWidget(self.split_widget)
        
        # For backwards compatibility, create unified_tree reference
        self.unified_tree = self.scope_tree
    
    def set_waveform_db(self, waveform_db: Optional['WaveformDB']) -> None:
        """Set the waveform database and initialize models"""
        tprint(f"DesignTreeView.set_waveform_db called with waveform_db={waveform_db is not None}")
        start_time = time.time()

        self.waveform_db = waveform_db

        if waveform_db is None:
            self.scope_tree_model = None
            self.scope_tree.setModel(None)
            if self.vars_view:
                self.vars_view.set_variables([])
            tprint(f"  DesignTreeView cleared (took {time.time() - start_time:.3f}s)")
            return

        # Create and set the models
        model_start = time.time()
        tprint(f"  Created ScopeTreeModel (took {time.time() - model_start:.3f}s)")

        # Create scope tree model
        scope_model_start = time.time()
        self.scope_tree_model = ScopeTreeModel(waveform_db)
        tprint(f"  Created ScopeTreeModel (took {time.time() - scope_model_start:.3f}s)")

        # Set the model on the view
        set_model_start = time.time()
        self.scope_tree.setModel(self.scope_tree_model)
        self.scope_tree.selectionModel().currentChanged.connect(self._on_scope_selection_changed)
        tprint(f"  Set model on scope_tree view (took {time.time() - set_model_start:.3f}s)")

        # Clear variables view
        if self.vars_view:
            self.vars_view.set_variables([])

        tprint(f"  DesignTreeView.set_waveform_db completed (total: {time.time() - start_time:.3f}s)")

    def set_waveform_files(self, waveform_files: List[WaveformFileReference]) -> None:
        """Set multiple waveform files and initialize multi-file model."""
        tprint(f"DesignTreeView.set_waveform_files called with {len(waveform_files)} files")
        start_time = time.time()

        # Check if files are already set (avoid redundant rebuilds that clear selection)
        # Compare by content: check if we have the same number of files with same file_ids
        if (self.waveform_files and self.scope_tree_model is not None and
            len(self.waveform_files) == len(waveform_files) and
            all(a.file_id == b.file_id for a, b in zip(self.waveform_files, waveform_files))):
            tprint(f"  Files already set, skipping rebuild")
            return

        self.waveform_files = list(waveform_files)  # Store a copy to avoid reference issues

        if not waveform_files:
            self.scope_tree_model = None
            self.scope_tree.setModel(None)
            if self.vars_view:
                self.vars_view.set_variables([])
            tprint(f"  DesignTreeView cleared (took {time.time() - start_time:.3f}s)")
            return

        # Set waveform_db to first file for backward compatibility
        self.waveform_db = waveform_files[0].waveform_db if waveform_files else None

        if len(waveform_files) == 1:
            # Single file mode - use regular ScopeTreeModel
            self.current_file_id = waveform_files[0].file_id
            self.scope_tree_model = ScopeTreeModel(waveform_files[0].waveform_db)
        else:
            # Multi-file mode - use MultiFileScopeTreeModel
            self.current_file_id = waveform_files[0].file_id  # Default to first file
            self.scope_tree_model = MultiFileScopeTreeModel(waveform_files)

        # Set the model on the view
        self.scope_tree.setModel(self.scope_tree_model)
        self.scope_tree.selectionModel().currentChanged.connect(self._on_scope_selection_changed)

        # Clear variables view
        if self.vars_view:
            self.vars_view.set_variables([])

        tprint(f"  DesignTreeView.set_waveform_files completed (total: {time.time() - start_time:.3f}s)")

    def _get_current_file_id(self) -> int:
        """Get the file_id for the currently selected scope.

        In single-file mode, returns the only file's ID.
        In multi-file mode, determines from the current scope selection.
        """
        if len(self.waveform_files) == 1:
            return self.waveform_files[0].file_id

        # Multi-file mode: get file_id from current scope selection
        if isinstance(self.scope_tree_model, MultiFileScopeTreeModel):
            current_index = self.scope_tree.currentIndex()
            if current_index.isValid():
                return self.scope_tree_model.get_file_id_for_index(current_index)

        # Default to current_file_id
        return self.current_file_id

    def _create_signal_node(self, node: DesignTreeNode) -> Optional[TreeNode]:
        """Create a SignalNode from a tree node"""
        if node.is_scope or not self.waveform_db:
            return None
        
        # Build full path
        path_parts = []
        current = node
        while current and current.parent:
            path_parts.append(current.name)
            current = current.parent
        
        if not path_parts:
            return None
        
        path_parts.reverse()
        full_path = ".".join(path_parts)
        
        # Get handle from node if available
        handle = None
        if getattr(node, 'var_handle', None) is not None:
            handle = node.var_handle
        elif getattr(node, 'var', None) and self.waveform_db:
            # Try to get handle from var object (method is required by protocol)
            var = getattr(node, 'var', None)
            if var is not None:
                handle = var.signal_handle()
        
        # If not, try to find signal handle by path
        if handle is None:
            handle = self._find_signal_handle(full_path)
            
        if handle is None:
            return None
        
        # Get var object if not already available
        var_obj = getattr(node, 'var', None)
        if var_obj is None and self.waveform_db and handle is not None:
            try:
                var_obj = self.waveform_db.get_var(handle)
            except Exception:
                var_obj = None

        # If still no var, we cannot proceed
        if var_obj is None:
            return None

        # Determine render type using helper and var_type if available
        is_single_bit = self._is_single_bit(var_obj, handle)
        var_type_str = None
        if var_obj is not None:
            try:
                var_type_str = str(var_obj.var_type())
            except Exception:
                var_type_str = None
        if var_type_str == "Event":
            render_type = RenderType.EVENT
        else:
            render_type = RenderType.BOOL if is_single_bit else RenderType.BUS
        format = DisplayFormat(render_type=render_type)

        signal = self.waveform_db.load_signal(handle)

        # Split full_path into scope_path and local_name
        # Use var.scope_path if available
        if var_obj and hasattr(var_obj, 'scope_path'):
            hierarchy = self.waveform_db.hierarchy if hasattr(self.waveform_db, 'hierarchy') else None
            if hierarchy:
                local_name = var_obj.name(hierarchy)
                scope_path = tuple(var_obj.scope_path(hierarchy))
            else:
                # Fallback to splitting full_path
                parts = full_path.split('.')
                local_name = parts[-1] if parts else full_path
                scope_path = tuple(parts[:-1]) if len(parts) > 1 else ()
        else:
            # Fallback to splitting full_path
            parts = full_path.split('.')
            local_name = parts[-1] if parts else full_path
            scope_path = tuple(parts[:-1]) if len(parts) > 1 else ()

        signal_node = SignalNode(
            local_name=local_name,
            _waveform_scope=scope_path,
            handle=handle,
            signal=signal,
            var=var_obj,  # Pass the var object
            format=format,
            is_multi_bit=not is_single_bit,
            file_id=self._get_current_file_id()
        )

        return signal_node

    def _find_signal_handle(self, full_path: str) -> Optional[SignalHandle]:
        """Find signal handle in waveform database"""
        if not self.waveform_db:
            return None

        # Convert dotted string to path segments for new API
        path_segments = full_path.split('.')
        handle = self.waveform_db.find_handle_by_path(path_segments)
        return handle
    
    def add_selected_signals(self) -> None:
        """Add currently selected signals to waveform (called by 'I' shortcut)"""
        if self.vars_view:
            selected_vars = self.vars_view.get_selected_variables()
            self._emit_signal_nodes_from_variables(selected_vars, show_progress=True)
    
    def navigate_to_scope(self, scope_path: str, signal_name: str = '') -> bool:
        """Navigate to the specified scope and optionally select a variable.
        
        Args:
            scope_path: Hierarchical path like 'top.cpu.alu'
            signal_name: Optional full signal path to select the variable
            
        Returns:
            True if navigation successful, False otherwise
        """
        if not scope_path:
            return False
            
        path_parts = scope_path.split('.')
        
        # Use the scope tree in split mode
        tree = self.scope_tree
        model = self.scope_tree_model
            
        if not model:
            return False
            
        # Find the scope node
        index = self._find_scope_by_path(path_parts, model, QModelIndex())
        if not index.isValid():
            self.status_message.emit(f"Scope not found: {scope_path}")
            return False
            
        # Expand and select the scope first
        tree.expand(index)
        tree.setCurrentIndex(index)
        
        # If signal_name provided, find and select the specific variable
        if signal_name:
            # Extract the variable name (last component of the signal path)
            var_name = signal_name.split('.')[-1]
            # Remove any array indices for comparison (e.g., "signal[7:0]" -> "signal")
            var_name_base = var_name.split('[')[0] if '[' in var_name else var_name
            
            # Select the variable in the VarsView
            if self.vars_view:
                # The scope selection has already triggered loading variables in VarsView
                # Now we need to select the matching variable in the table
                
                # Give UI time to update after scope selection
                QApplication.processEvents()
                
                # Search through the variables in the table model
                proxy_model = self.vars_view.filter_proxy
                source_model = self.vars_view.vars_model
                
                if source_model and proxy_model:
                    # Search in the source model
                    for row in range(source_model.rowCount()):
                        var_data = source_model.variables[row] if row < len(source_model.variables) else None
                        if var_data:
                            # Get the variable name from the data
                            table_var_name = var_data.get('name', '')
                            # Compare base names (without array indices)
                            table_var_base = table_var_name.split('[')[0] if '[' in table_var_name else table_var_name
                            
                            if table_var_base == var_name_base:
                                # Found the variable, select it in the table
                                # Map source row to proxy row
                                source_index = source_model.index(row, 0)
                                proxy_index = proxy_model.mapFromSource(source_index)
                                
                                if proxy_index.isValid():
                                    # Select the row in the table view
                                    self.vars_view.table_view.setCurrentIndex(proxy_index)
                                    self.vars_view.table_view.scrollTo(proxy_index, QAbstractItemView.ScrollHint.PositionAtCenter)
                                    self.status_message.emit(f"Navigated to: {signal_name}")
                                    return True
                    
                    # Variable not found in VarsView
                    self.status_message.emit(f"Navigated to scope: {scope_path} (variable '{var_name}' not visible)")
                else:
                    tree.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
                    self.status_message.emit(f"Navigated to: {scope_path}")
        else:
            # No specific variable requested, just show the scope
            tree.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
            self.status_message.emit(f"Navigated to: {scope_path}")
        
        return True
    
    def _find_scope_by_path(self, path_parts: List[str], model: Union[ScopeTreeModel, MultiFileScopeTreeModel], parent: QModelIndex) -> QModelIndex:
        """Recursively find a scope node by its path components.
        
        Args:
            path_parts: List of path components to match
            model: The tree model to search
            parent: Parent index to start searching from
            
        Returns:
            QModelIndex of found node or invalid index if not found
        """
        if not path_parts:
            return QModelIndex()
            
        target_name = path_parts[0]
        remaining_parts = path_parts[1:]
        
        # Search children of current parent
        for row in range(model.rowCount(parent)):
            index = model.index(row, 0, parent)
            if not index.isValid():
                continue
                
            # Get node name
            node = index.internalPointer()
            if node and hasattr(node, 'name') and node.name == target_name:
                # If this is the last part, we found it
                if not remaining_parts:
                    return index
                    
                # Otherwise, continue searching deeper if it's a scope
                if hasattr(node, 'is_scope') and node.is_scope:
                    # Ensure the node is expanded in the view
                    # Expand in scope tree
                    self.scope_tree.expand(index)
                    
                    # Recursively search children
                    result = self._find_scope_by_path(remaining_parts, model, index)
                    if result.isValid():
                        return result
        
        return QModelIndex()
    
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Event filter to handle keyboard shortcuts"""
        if event.type() == QEvent.Type.KeyPress:
            key_event = cast(QKeyEvent, event)
            
            # Check if the event is from one of our monitored widgets
            is_from_scope = obj == self.scope_tree
            is_from_vars = self.vars_view and obj == self.vars_view.table_view
            
            # 'i', 'I' or Insert key - add selected signals
            if key_event.key() == Qt.Key.Key_I:
                # Accept both lowercase 'i' (no modifiers) and uppercase 'I' (with Shift)
                if (key_event.modifiers() == Qt.KeyboardModifier.NoModifier or 
                    key_event.modifiers() == Qt.KeyboardModifier.ShiftModifier):
                    # Only process if from the vars view
                    if is_from_vars:
                        self.add_selected_signals()
                        return True
            elif key_event.key() == Qt.Key.Key_Insert:
                if is_from_vars:
                    self.add_selected_signals()
                    return True
            
            # Ctrl+F - focus filter
            elif (key_event.key() == Qt.Key.Key_F and 
                  key_event.modifiers() == Qt.KeyboardModifier.ControlModifier):
                if self.vars_view:
                    self.vars_view.focus_filter()
                    return True
            
            # Escape - clear filter
            elif key_event.key() == Qt.Key.Key_Escape:
                if self.vars_view:
                    self.vars_view.clear_filter()
                    return True
        
        return super().eventFilter(obj, event)
    
    def install_event_filters(self) -> None:
        """Install event filters on tree views"""
        self.scope_tree.installEventFilter(self)
        if self.vars_view:
            self.vars_view.table_view.installEventFilter(self)
    
    def _on_scope_selection_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        """Handle scope selection change in split mode."""
        if not current.isValid() or not self.scope_tree_model:
            return

        # Get the selected scope node
        scope_node = current.internalPointer()
        if not scope_node:
            return

        # Get variables for this scope
        # MultiFileScopeTreeModel takes index, ScopeTreeModel takes node
        from ..models.multi_file_scope_tree_model import MultiFileScopeTreeModel
        if isinstance(self.scope_tree_model, MultiFileScopeTreeModel):
            variables = self.scope_tree_model.get_variables_for_scope(current)
        else:
            variables = self.scope_tree_model.get_variables_for_scope(scope_node)
        
        # Update vars view
        if self.vars_view:
            self.vars_view.set_variables(variables)
    
    def _on_variables_selected(self, var_data_list: List[VariableData]) -> None:
        """Handle variables selected from VarsView."""
        tprint(f"[DESIGN_TREE] _on_variables_selected: {len(var_data_list)} variables")
        for var_data in var_data_list[:3]:  # Show first 3
            if isinstance(var_data, dict):
                tprint(f"[DESIGN_TREE]   Variable: {var_data.get('full_path', var_data.get('name', 'unknown'))}")
        self._emit_signal_nodes_from_variables(var_data_list, show_progress=False)

    def _emit_signal_nodes_from_variables(self, var_data_list: List[VariableData], show_progress: bool = False) -> None:
        """Convert variables to signal nodes and emit them for waveform display.

        Args:
            var_data_list: List of variable data to convert
            show_progress: Whether to show progress dialog for large batches
        """
        tprint(f"[DESIGN_TREE] _emit_signal_nodes_from_variables: {len(var_data_list)} variables")
        signal_nodes = []
        handles_to_load: list[int] = []

        for var_data in var_data_list:
            signal_node = self._create_signal_node_from_var(var_data)
            if signal_node:
                signal_nodes.append(signal_node)
                # Collect uncached handles for async loading
                if isinstance(signal_node, SignalNode) and signal_node.handle is not None:
                    if signal_node.signal is None:  # Not cached
                        handles_to_load.append(signal_node.handle)

        if signal_nodes:
            # Show progress dialog for batch operations when requested
            if show_progress and len(signal_nodes) > 10:
                progress = QProgressDialog(
                    "Adding signals...", "Cancel", 0, len(signal_nodes), self
                )
                progress.setWindowModality(Qt.WindowModality.WindowModal)
                progress.show()

                for i, signal_node in enumerate(signal_nodes):
                    if progress.wasCanceled():
                        break
                    progress.setValue(i)
                    QApplication.processEvents()

                progress.setValue(len(signal_nodes))

            # Emit nodes immediately (with signal=None for uncached)
            tprint(f"[DESIGN_TREE] Emitting {len(signal_nodes)} signal nodes")
            self.signals_selected.emit(signal_nodes)

            # Trigger async loading for uncached handles
            if handles_to_load and self.waveform_db:
                tprint(f"[DESIGN_TREE] Triggering async load for {len(handles_to_load)} handles: {handles_to_load[:5]}...")
                self.waveform_db.load_signals_async(handles_to_load)
                self.status_message.emit(f"Added {len(signal_nodes)} signal(s), loading {len(handles_to_load)} in background")
            else:
                tprint(f"[DESIGN_TREE] All {len(signal_nodes)} signals are cached")
                self.status_message.emit(f"Added {len(signal_nodes)} signal(s)")
    
    def _is_single_bit(self, var_obj: Optional[Var], handle: Optional[SignalHandle]) -> bool:
        """Determine if a variable/signal is single-bit using wellen API.
        
        Tries the provided var object first; if not available, attempts to fetch
        it from the waveform_db using the handle. Falls back to True on errors
        to keep behavior safe by default.
        """
        is_single_bit = True
        # Ensure we have a var object (get_var is required by protocol)
        if var_obj is None and self.waveform_db is not None and handle is not None:
            try:
                var_obj = self.waveform_db.get_var(handle)
            except Exception:
                var_obj = None
        # Use wellen is_1bit if available
        if var_obj is not None:
            try:
                is_single_bit = bool(var_obj.is_1bit())
            except Exception:
                is_single_bit = True
        return is_single_bit
    
    def _create_signal_node_from_var(self, var_data: 'VariableData') -> Optional[TreeNode]:
        """Create a SignalNode from variable data."""
        if not var_data:
            return None

        # Get the current file_id to determine which WaveformDB to use
        file_id = self._get_current_file_id()

        # Get the correct WaveformDB for this file_id
        current_db = None
        if len(self.waveform_files) > 0:
            # Multi-file mode: find the WaveformDB for the current file_id
            for file_ref in self.waveform_files:
                if file_ref.file_id == file_id:
                    current_db = file_ref.waveform_db
                    break
        else:
            # Single-file mode (backward compat): use self.waveform_db
            current_db = self.waveform_db

        if not current_db:
            return None

        full_path = var_data.get('full_path', var_data.get('name'))
        if not full_path:
            return None

        # Check if we have a var object directly in the data
        var = var_data.get('var')

        # Look up handle by path using the correct WaveformDB
        # Convert dotted string to path segments for new API
        path_segments = full_path.split('.')
        handle = current_db.find_handle_by_path(path_segments)

        if handle is None:
            return None

        # Ensure we have a var object
        if var is None and current_db and handle is not None:
            var = current_db.get_var(handle)

        if var is None:
            return None  # Cannot create signal without var

        # Determine render type using the helper and var_type if available
        is_single_bit = self._is_single_bit(var, handle)
        var_type_str = None
        # Try get var_type from var_data first
        vt = var_data.get('var_type')
        if vt is not None:
            var_type_str = str(vt)
        elif var is not None:
            try:
                var_type_str = str(var.var_type())
            except Exception:
                var_type_str = None
        if var_type_str == "Event":
            render_type = RenderType.EVENT
        else:
            render_type = RenderType.BOOL if is_single_bit else RenderType.BUS
        format = DisplayFormat(render_type=render_type)

        signal = current_db.load_signal(handle)

        # Split full_path into scope_path and local_name
        # Use var.scope_path if available, otherwise split full_path
        if var and hasattr(var, 'scope_path'):
            hierarchy = current_db.hierarchy if hasattr(current_db, 'hierarchy') else None
            if hierarchy:
                local_name = var.name(hierarchy)
                scope_path = tuple(var.scope_path(hierarchy))
            else:
                # Fallback to splitting full_path
                parts = full_path.split('.')
                local_name = parts[-1] if parts else full_path
                scope_path = tuple(parts[:-1]) if len(parts) > 1 else ()
        else:
            # Fallback to splitting full_path
            parts = full_path.split('.')
            local_name = parts[-1] if parts else full_path
            scope_path = tuple(parts[:-1]) if len(parts) > 1 else ()

        signal_node = SignalNode(
            local_name=local_name,
            _waveform_scope=scope_path,
            handle=handle,
            signal=signal,
            var=var,  # Pass the var object
            format=format,
            is_multi_bit=not is_single_bit,
            file_id=file_id
        )

        return signal_node
