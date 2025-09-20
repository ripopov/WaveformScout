"""
Design Tree View Widget

A widget that shows the design hierarchy with scopes in the top panel 
and filtered variables in the bottom panel.
"""

from __future__ import annotations
from typing import Optional, List, cast, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from pyrox import Var
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeView, QPushButton,
    QLabel, QSplitter, QLineEdit, QTableView,
    QHeaderView, QProgressDialog, QApplication, QAbstractItemView
)
from PySide6.QtCore import Qt, Signal, QModelIndex, QSortFilterProxyModel, QEvent, QObject
from PySide6.QtGui import QKeyEvent
import pyrox

from .design_tree_model import DesignTreeModel, DesignTreeNode
from pyrox import SignalHandle

from .data_model import SignalNode, RenderType, DisplayFormat
from .settings_manager import SettingsManager
from .scope_tree_model import ScopeTreeModel
from .vars_view import VarsView

from .protocols import WaveformDBProtocol
from .vars_view import VariableData


class DesignTreeView(QWidget):
    """
    Design tree widget with split view showing scopes and variables
    """
    
    # Signals
    signals_selected = Signal(list)  # List of SignalNode objects
    status_message = Signal(str)
    
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        
        self.waveform_db: Optional['WaveformDBProtocol'] = None
        self.design_tree_model: Optional[DesignTreeModel] = None  # Keep for compatibility
        self.scope_tree_model: Optional[ScopeTreeModel] = None
        self.vars_view: Optional[VarsView] = None
        
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
    
    def set_waveform_db(self, waveform_db: Optional['WaveformDBProtocol']) -> None:
        """Set the waveform database and initialize models"""
        self.waveform_db = waveform_db
        
        if waveform_db is None:
            self.design_tree_model = None
            self.scope_tree_model = None
            self.scope_tree.setModel(None)
            if self.vars_view:
                self.vars_view.set_variables([])
            return
        
        # Create and set the models
        self.design_tree_model = DesignTreeModel(waveform_db)  # Keep for compatibility
        
        # Create scope tree model
        self.scope_tree_model = ScopeTreeModel(waveform_db)
        self.scope_tree.setModel(self.scope_tree_model)
        self.scope_tree.selectionModel().currentChanged.connect(self._on_scope_selection_changed)
        
        # Clear variables view
        if self.vars_view:
            self.vars_view.set_variables([])
    
    def _create_signal_node(self, node: DesignTreeNode) -> Optional[SignalNode]:
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
                handle = self.waveform_db.get_handle_for_var(var)
        
        # If not, try to find signal handle by path
        if handle is None:
            handle = self._find_signal_handle(full_path)
            
        if handle is None:
            return None
        
        # Determine render type using helper and var_type if available
        var_obj = getattr(node, 'var', None)
        is_single_bit = self._is_single_bit(var_obj, handle)
        var_type_str = None
        if var_obj is None and self.waveform_db and handle is not None:
            try:
                var_obj = self.waveform_db.get_var(handle)
            except Exception:
                var_obj = None
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
        
        return SignalNode(
            name=full_path,
            handle=handle,
            format=format,
            is_multi_bit=not is_single_bit
        )
    
    def _find_signal_handle(self, full_path: str) -> Optional[SignalHandle]:
        """Find signal handle in waveform database"""
        if not self.waveform_db:
            return None
        
        # Use the public find_handle_by_path method
        handle = self.waveform_db.find_handle_by_path(full_path)
        return handle
    
    def add_selected_signals(self) -> None:
        """Add currently selected signals to waveform (called by 'I' shortcut)"""
        signal_nodes: List[SignalNode] = []
        
        # Get selected variables from VarsView
        if self.vars_view:
            selected_vars = self.vars_view.get_selected_variables()
            for var_data in selected_vars:
                signal_node = self._create_signal_node_from_var(var_data)
                if signal_node:
                    signal_nodes.append(signal_node)
        
        if signal_nodes:
            # Show progress dialog for batch operations
            if len(signal_nodes) > 10:
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
            
            self.signals_selected.emit(signal_nodes)
            self.status_message.emit(f"Added {len(signal_nodes)} signal(s)")
    
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
    
    def _find_scope_by_path(self, path_parts: List[str], model: Union[DesignTreeModel, ScopeTreeModel], parent: QModelIndex) -> QModelIndex:
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
        variables = self.scope_tree_model.get_variables_for_scope(scope_node)
        
        # Update vars view
        if self.vars_view:
            self.vars_view.set_variables(variables)
    
    def _on_variables_selected(self, var_data_list: List[VariableData]) -> None:
        """Handle variables selected from VarsView."""
        signal_nodes = []
        for var_data in var_data_list:
            signal_node = self._create_signal_node_from_var(var_data)
            if signal_node:
                signal_nodes.append(signal_node)
        
        if signal_nodes:
            self.signals_selected.emit(signal_nodes)
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
    
    def _create_signal_node_from_var(self, var_data: 'VariableData') -> Optional[SignalNode]:
        """Create a SignalNode from variable data."""
        if not var_data or not self.waveform_db:
            return None
        
        full_path = var_data.get('full_path', var_data.get('name'))
        if not full_path:
            return None
        
        # Check if we have a var object directly in the data
        var = var_data.get('var')
        handle = None
        
        if var and self.waveform_db:
            # Try to get handle from var object (method is required by protocol)
            handle = self.waveform_db.get_handle_for_var(var)
        
        if handle is None:
            # Fallback to path-based lookup
            handle = self._find_signal_handle(full_path)
        
        if handle is None:
            return None
        
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
        
        return SignalNode(
            name=full_path,
            handle=handle,
            format=format,
            is_multi_bit=not is_single_bit
        )
