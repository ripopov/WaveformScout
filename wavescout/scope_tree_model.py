"""
Scope-only tree model for split mode in DesignTreeView.

This model filters out variables and shows only scopes (modules) in the hierarchy.
"""

from __future__ import annotations
from typing import Optional, Union, overload, List, Dict, TYPE_CHECKING
from PySide6.QtCore import QAbstractItemModel, QModelIndex, QPersistentModelIndex, Qt, Signal, QObject
from PySide6.QtGui import QIcon

if TYPE_CHECKING:
    from pyrox import ScopeIter
import pyrox
from .protocols import WaveformDBProtocol
from .vars_view import VariableData
from .design_tree_model import DesignTreeNode
from .icon_cache import get_icon_cache


class ScopeTreeModel(QAbstractItemModel):
    """Tree model that shows only scopes (modules), filtering out variables."""
    
    # Signal emitted when scope selection changes
    scope_selected = Signal(str)  # Emits the full path of the selected scope
    
    def __init__(self, waveform_db: Optional[WaveformDBProtocol] = None, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.waveform_db = waveform_db
        self.root_node: Optional[DesignTreeNode] = None
        self._icon_cache = get_icon_cache()
        
        if waveform_db:
            self.load_hierarchy(waveform_db)
    
    
    def load_hierarchy(self, waveform_db: WaveformDBProtocol) -> None:
        """Load the hierarchy from waveform database, filtering to show only scopes."""
        self.beginResetModel()
        self.waveform_db = waveform_db
        self.root_node = None
        
        if waveform_db and waveform_db.hierarchy:
            self._build_scope_hierarchy()
        
        self.endResetModel()
    
    def _build_scope_hierarchy(self) -> None:
        """Build the scope-only tree from the waveform database hierarchy."""
        if not self.waveform_db or not self.waveform_db.hierarchy:
            return
        
        hierarchy = self.waveform_db.hierarchy
        
        # Create root node
        self.root_node = DesignTreeNode("TOP", is_scope=True)
        
        # Build hierarchy from top scopes
        self._build_scope_recursive(hierarchy.top_scopes(), self.root_node, hierarchy)
    
    def _build_scope_recursive(self, scopes: ScopeIter, parent_node: DesignTreeNode, hierarchy: pyrox.Hierarchy) -> None:
        """Recursively build scope nodes."""
        for scope in scopes:
            # Create node for this scope
            scope_node = DesignTreeNode(
                name=scope.name(hierarchy),
                is_scope=True,
                parent=parent_node
            )
            scope_node.scope = scope  # Store the scope reference for icon selection
            
            # Add to parent
            if parent_node:
                parent_node.add_child(scope_node)
            
            # Recursively process child scopes
            child_scopes = scope.scopes(hierarchy)
            if child_scopes:
                self._build_scope_recursive(child_scopes, scope_node, hierarchy)
    
    def _create_parent_nodes(self, path_parts: List[str], scope_map: Dict[str, DesignTreeNode]) -> Optional[DesignTreeNode]:
        """Create parent nodes for a given path."""
        current_parent = self.root_node
        current_path = "TOP"
        
        for part in path_parts:
            if current_path == "TOP":
                current_path = part
            else:
                current_path = f"{current_path}.{part}"
            
            if current_path not in scope_map:
                node = DesignTreeNode(
                    name=part,
                    is_scope=True,
                    parent=current_parent
                )
                if current_parent:
                    current_parent.add_child(node)
                scope_map[current_path] = node
                current_parent = node
            else:
                current_parent = scope_map[current_path]
        
        return current_parent
    
    def get_variables_for_scope(self, scope_node: DesignTreeNode) -> List[VariableData]:
        """Get all variables for a given scope node."""
        if not self.waveform_db or not self.waveform_db.hierarchy:
            return []
        
        hierarchy = self.waveform_db.hierarchy
        
        # Build the scope path from the node
        path_parts = []
        current: Optional[DesignTreeNode] = scope_node
        while current and current != self.root_node:
            path_parts.append(current.name)
            current = current.parent
        path_parts.reverse()
        
        # Find the scope by traversing the hierarchy
        scope = self._find_scope_by_path(path_parts, hierarchy)
        if not scope:
            return []
        
        # Get variables in this scope
        variables: List[VariableData] = []
        for var in scope.vars(hierarchy):
            var_data: VariableData = {
                'name': var.name(hierarchy),
                'full_path': var.full_name(hierarchy),
                'var_type': var.var_type(),
                'bit_range': self._format_bit_range(var),
                'var': var
            }
            variables.append(var_data)
        
        return variables
    
    def _find_scope_by_path(self, path_parts: List[str], hierarchy: pyrox.Hierarchy) -> Optional[pyrox.Scope]:
        """Find a scope by its path parts."""
        if not path_parts:
            return None
        
        # Start with top scopes
        current_scopes = hierarchy.top_scopes()
        current_scope = None
        
        for part in path_parts:
            found = False
            for scope in current_scopes:
                if scope.name(hierarchy) == part:
                    current_scope = scope
                    found = True
                    # Get child scopes for next iteration
                    current_scopes = scope.scopes(hierarchy)
                    break
            
            if not found:
                return None
        
        return current_scope
    
    def _format_bit_range(self, var: pyrox.Var) -> str:
        """Format the bit range for display."""
        # Try to get bitwidth using the same method as DesignTreeModel
        try:
            bitwidth = var.bitwidth()
            if bitwidth and bitwidth > 1:
                return f"[{bitwidth - 1}:0]"
        except:
            pass
        
        # Fallback to index if available
        idx = var.index()
        if idx:
            if idx.msb() != idx.lsb():
                return f"[{idx.msb()}:{idx.lsb()}]"
            else:
                return f"[{idx.msb()}]"
        
        return ""
    
    # QAbstractItemModel interface methods
    
    def index(self, row: int, column: int, parent: Union[QModelIndex, QPersistentModelIndex] = QModelIndex()) -> QModelIndex:
        """Create an index for the item at (row, column) with the given parent."""
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        
        if not parent.isValid():
            parent_node = self.root_node
        else:
            parent_node = parent.internalPointer()
        
        if parent_node and row < len(parent_node.children):
            child_node = parent_node.children[row]
            return self.createIndex(row, column, child_node)
        
        return QModelIndex()
    
    @overload
    def parent(self) -> QObject: ...
    
    @overload
    def parent(self, index: Union[QModelIndex, QPersistentModelIndex]) -> QModelIndex: ...
    
    def parent(self, index: Optional[Union[QModelIndex, QPersistentModelIndex]] = None) -> Union[QModelIndex, QObject]:
        """Get the parent index of the given index or parent object."""
        if index is None:
            # Return parent QObject
            return super().parent()
        if not index.isValid():
            return QModelIndex()
        
        node = index.internalPointer()
        parent_node = node.parent
        
        if parent_node == self.root_node or parent_node is None:
            return QModelIndex()
        
        # Find the row of the parent
        if parent_node.parent:
            row = parent_node.parent.children.index(parent_node)
        else:
            row = 0
        
        return self.createIndex(row, 0, parent_node)
    
    def rowCount(self, parent: Union[QModelIndex, QPersistentModelIndex] = QModelIndex()) -> int:
        """Get the number of rows (children) for the given parent."""
        if parent.column() > 0:
            return 0
        
        if not parent.isValid():
            parent_node = self.root_node
        else:
            parent_node = parent.internalPointer()
        
        if parent_node:
            return len(parent_node.children)
        return 0
    
    def hasChildren(self, parent: Union[QModelIndex, QPersistentModelIndex] = QModelIndex()) -> bool:
        """Check if the parent has children."""
        if not parent.isValid():
            # Root always has children if we have a hierarchy
            return self.root_node is not None and len(self.root_node.children) > 0
        
        node = parent.internalPointer()
        if node:
            # Scope nodes can have children
            return len(node.children) > 0
        return False
    
    def columnCount(self, parent: Union[QModelIndex, QPersistentModelIndex] = QModelIndex()) -> int:
        """Get the number of columns."""
        return 1  # Only show scope name
    
    def data(self, index: Union[QModelIndex, QPersistentModelIndex], role: int = Qt.ItemDataRole.DisplayRole) -> object | None:
        """Get data for the given index and role."""
        if not index.isValid():
            return None
        
        node = index.internalPointer()
        if not isinstance(node, DesignTreeNode):
            return None
        
        if role == Qt.ItemDataRole.DisplayRole:
            return node.name
        elif role == Qt.ItemDataRole.DecorationRole and index.column() == 0:
            # Get scope type from the node's scope object
            scope_type = "unknown"
            if node.scope:
                try:
                    scope_type = node.scope.scope_type()
                except:
                    pass
            return self._icon_cache.get_scope_icon(scope_type)
        elif role == Qt.ItemDataRole.ToolTipRole:
            # Build full path for tooltip
            path_parts = []
            current: Optional[DesignTreeNode] = node
            while current and current != self.root_node:
                path_parts.append(current.name)
                current = current.parent
            path_parts.reverse()
            return '.'.join(path_parts) if path_parts else "TOP"
        
        return None
    
    def headerData(self, section: int, orientation: Qt.Orientation, 
                   role: int = Qt.ItemDataRole.DisplayRole) -> str | None:
        """Get header data."""
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return "Scope"
        return None
    
    def flags(self, index: Union[QModelIndex, QPersistentModelIndex]) -> Qt.ItemFlag:
        """Get item flags."""
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable