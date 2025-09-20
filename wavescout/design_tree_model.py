"""Design Tree Model - Hierarchical view of digital design signals and scopes.

This module provides a Qt model for displaying the hierarchical structure of a digital
design loaded from waveform files (VCD, FST, etc.). It presents the design hierarchy
as a tree where:
- Scopes (modules, interfaces) are shown as expandable folders
- Signals (wires, registers) are shown as leaf nodes with their properties

The model efficiently handles large designs by building the hierarchy once and providing
fast lookups. It integrates with Qt's Model/View framework to display the hierarchy
in a QTreeView widget.

Key components:
- DesignTreeNode: Represents a single node (scope or signal) in the hierarchy
- DesignTreeModel: Qt model that manages the tree structure and provides data to views

The model supports three columns:
1. Name - The signal or scope name
2. Type - Signal type (wire, reg, etc.) or "scope" for modules
3. Bit Range - Signal width notation like [31:0] for buses

Visual representation of the tree structure:

    ┌──────────────────┬──────────┬────────────┐
    │ Name             │ Type     │ Bit Range  │   (Column Headers)
    ├──────────────────┼──────────┼────────────┤
    │ [+] TOP          │ scope    │            │   
    │  ├─ [+] cpu      │ scope    │            │   (Expandable scopes/modules)
    │  │  ├─ clk       │ wire     │            │
    │  │  ├─ reset     │ wire     │            │
    │  │  ├─ addr      │ wire     │ [31:0]     │   (Multi-bit bus)
    │  │  └─ data      │ reg      │ [63:0]     │
    │  └─ [+] memory   │ scope    │            │
    │     ├─ mem_clk   │ wire     │            │   (Single-bit signals)
    │     ├─ wr_en     │ wire     │            │
    │     └─ rd_data   │ wire     │ [31:0]     │
    └──────────────────┴──────────┴────────────┘

Tree Node Structure:
    DesignTreeNode
    ├── name: str          (e.g., "cpu", "clk")
    ├── is_scope: bool     (True for modules, False for signals)
    ├── var_type: str      (e.g., "wire", "reg", "logic")
    ├── bit_range: str     (e.g., "[31:0]", empty for 1-bit)
    ├── parent: Node       (Parent scope, None for root)
    ├── children: [Node]   (Child nodes, empty for signals)
    ├── var_handle: SignalRef    (Database handle for signal lookup)
    │                      (Integer index used by WaveformDB to efficiently
    │                       retrieve signal data - like a primary key)
    └── var: pyrox.Var     (Pyrox variable reference)
                           (The actual Wellen variable object from the
                            hierarchy - contains signal metadata)

 This is typically used in the side panel of a waveform viewer to allow users to
 browse and select signals to add to the waveform display.
"""

from __future__ import annotations
from typing import Optional, List, overload, Dict, Union, TYPE_CHECKING
from PySide6.QtCore import Qt, QAbstractItemModel, QModelIndex, QPersistentModelIndex, QObject
from PySide6.QtGui import QIcon

if TYPE_CHECKING:
    from pyrox import ScopeIter
from .data_model import SignalRef
from .protocols import WaveformDBProtocol
import pyrox
from .icon_cache import get_icon_cache


class DesignTreeNode:
    """Node in the design hierarchy tree."""

    def __init__(self, name: str, is_scope: bool = False, var_type: str = "",
                 bit_range: str = "", parent: Optional['DesignTreeNode'] = None):
        """Initialize a tree node representing either a scope (module) or signal.
        
        Args:
            name: Display name of the node (e.g., "clk", "cpu_core")
            is_scope: True if this is a module/scope, False if it's a signal
            var_type: Signal type like "wire", "reg", "logic" (empty for scopes)
            bit_range: Signal width like "[31:0]" for buses (empty for single bits)
            parent: Parent node in the tree hierarchy
        """
        self.name = name
        self.is_scope = is_scope
        self.var_type = var_type
        self.bit_range = bit_range
        self.parent = parent
        self.children: List['DesignTreeNode'] = []
        self.var_handle: Optional[SignalRef] = None  # Wellen Var handle for database lookups
        self.var: Optional[pyrox.Var] = None  # Pyrox Var object reference
        self.scope: Optional[pyrox.Scope] = None  # Pyrox scope object for scope nodes

    def add_child(self, child: 'DesignTreeNode') -> None:
        """Add a child node to this node and set this node as its parent."""
        child.parent = self
        self.children.append(child)


class DesignTreeModel(QAbstractItemModel):
    """Qt model that provides a tree view of the design hierarchy from a waveform database.
    
    This model implements QAbstractItemModel to work with Qt's Model/View framework,
    allowing the design hierarchy to be displayed in a QTreeView. It handles:
    - Loading hierarchy from waveform databases
    - Providing data for display (names, types, bit ranges)
    - Managing parent-child relationships for tree expansion
    - Creating icons for visual distinction between scopes and signals
    """

    def __init__(self, waveform_db: Optional[WaveformDBProtocol] = None, parent: Optional[QObject] = None) -> None:
        """Initialize the model with an optional waveform database.
        
        Args:
            waveform_db: Waveform database object containing the design hierarchy
            parent: Parent QObject (usually None)
        """
        super().__init__(parent)
        self.root_node = DesignTreeNode("Root", is_scope=True)
        self.waveform_db = waveform_db
        self._icon_cache = get_icon_cache()

        if waveform_db:
            self.load_hierarchy(waveform_db)


    def load_hierarchy(self, waveform_db: WaveformDBProtocol) -> None:
        """Load and build the complete design hierarchy from a waveform database.
        
        This clears any existing hierarchy and rebuilds it from the provided database.
        The operation is wrapped in begin/endResetModel to notify views of the change.
        
        Args:
            waveform_db: Waveform database object containing the design hierarchy
        """
        self.beginResetModel()  # Notify views that model is being rebuilt
        self.root_node = DesignTreeNode("Root", is_scope=True)
        self.waveform_db = waveform_db

        if waveform_db:
            # Build hierarchy from waveform database
            self._build_hierarchy()

        self.endResetModel()  # Notify views that model rebuild is complete

    def _build_hierarchy(self) -> None:
        """Build the internal tree structure from the waveform database hierarchy.
        
        This method:
        1. Creates a reverse mapping from variables to handles for O(1) lookups
        2. Recursively builds the tree starting from top-level scopes
        3. Populates each node with relevant signal information
        
        The reverse mapping optimization is crucial for large designs where linear
        searches would be too slow.
        """
        if not self.waveform_db or not self.waveform_db.hierarchy:
            return

        hierarchy = self.waveform_db.hierarchy

        # OPTIMIZATION: Build a reverse mapping from variables to handles once
        # This allows O(1) handle lookups instead of O(n) searches
        self._var_to_handle: Optional[Dict[int, SignalRef]] = {}
        for handle, vars_list in self.waveform_db.iter_handles_and_vars():
            # Map each variable in the list to the same handle
            for var in vars_list:
                self._var_to_handle[id(var)] = handle

        # Build hierarchy from scopes
        self._build_scope_recursive(hierarchy.top_scopes(), self.root_node, hierarchy)

        # Clean up the temporary mapping
        self._var_to_handle = None

    def _build_scope_recursive(self, scopes: ScopeIter, parent_node: DesignTreeNode, hierarchy: pyrox.Hierarchy) -> None:
        """Recursively build the tree structure for scopes and their contents.
        
        This method traverses the design hierarchy depth-first, creating nodes for:
        - Each scope (module/interface) as a folder node
        - Each signal within the scope as a leaf node
        - Recursively processing child scopes
        
        Args:
            scopes: List of scope objects from the waveform database
            parent_node: Parent tree node to attach children to
            hierarchy: Hierarchy object for name/type lookups
        """
        for scope in scopes:
            # Create scope node
            scope_name = scope.name(hierarchy)
            scope_node = DesignTreeNode(scope_name, is_scope=True)
            scope_node.scope = scope  # Store the scope reference for icon selection
            parent_node.add_child(scope_node)

            # Add variables in this scope
            for i, var in enumerate(scope.vars(hierarchy)):
                var_name = var.name(hierarchy).split('.')[-1]  # Just the signal name
                var_type = str(var.var_type())

                # Format bit range based on bitwidth
                bit_range = ""
                try:
                    bitwidth = var.bitwidth()
                    if bitwidth is not None and bitwidth > 1:
                        # Multi-bit signal - show as [MSB:0]
                        bit_range = f"[{bitwidth - 1}:0]"
                    elif bitwidth == 1:
                        # Single bit - could show as [0] or leave empty
                        pass  # Leave empty for single bits
                except:
                    # If bitwidth() fails, leave empty
                    pass

                # Create variable node
                var_node = DesignTreeNode(var_name, is_scope=False,
                                          var_type=var_type, bit_range=bit_range)

                # Store the variable reference for later use
                var_node.var = var

                # OPTIMIZATION: Use the pre-built mapping to find handle in O(1)
                if self._var_to_handle:
                    var_node.var_handle = self._var_to_handle.get(id(var))

                scope_node.add_child(var_node)

            # Recursively add child scopes
            child_scopes = scope.scopes(hierarchy)
            if child_scopes:
                self._build_scope_recursive(child_scopes, scope_node, hierarchy)

    # QAbstractItemModel interface methods
    def index(self, row: int, column: int, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> QModelIndex:
        """Create a QModelIndex for the item at (row, column) under the given parent.
        
        This is a required method for QAbstractItemModel. It's used by views to
        navigate the tree structure.
        
        Args:
            row: Row number of the child item (0-based)
            column: Column number (0=Name, 1=Type, 2=Bit Range)
            parent: Parent item's index (invalid index means root level)
            
        Returns:
            QModelIndex for the specified item, or invalid index if not found
        """
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        parent_node = parent.internalPointer() if parent.isValid() else self.root_node

        if parent_node is None:
            return QModelIndex()
            
        if row < len(parent_node.children):
            return self.createIndex(row, column, parent_node.children[row])

        return QModelIndex()

    @overload
    def parent(self) -> QObject: ...
    
    @overload
    def parent(self, index: QModelIndex | QPersistentModelIndex) -> QModelIndex: ...
    
    def parent(self, index: QModelIndex | QPersistentModelIndex | None = None) -> QModelIndex | QObject:
        """Get the parent index of the given item.
        
        This is a required method for QAbstractItemModel. It allows views to
        navigate up the tree hierarchy.
        
        Args:
            index: Child item's index
            
        Returns:
            QModelIndex of the parent item, or invalid index if item is at root level
        """
        # Handle overloaded parent() method
        if index is None:
            return super().parent()
            
        if not index.isValid():
            return QModelIndex()

        node = index.internalPointer()
        parent_node = node.parent

        if parent_node == self.root_node or parent_node is None:
            return QModelIndex()

        # Find row of parent
        grandparent = parent_node.parent
        if grandparent:
            row = grandparent.children.index(parent_node)
            return self.createIndex(row, 0, parent_node)

        return QModelIndex()

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        """Get the number of child rows under the given parent.
        
        This is a required method for QAbstractItemModel. It tells views how many
        children an item has, used for tree expansion.
        
        Args:
            parent: Parent item's index (invalid index means root level)
            
        Returns:
            Number of child items (0 for leaf nodes like signals)
        """
        if parent.column() > 0:
            return 0

        parent_node = parent.internalPointer() if parent.isValid() else self.root_node
        if parent_node is None:
            return 0
        return len(parent_node.children)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        """Get the number of columns in the model.
        
        This is a required method for QAbstractItemModel. The model has 3 columns:
        - Column 0: Signal/scope name
        - Column 1: Type (wire, reg, logic, or "scope")
        - Column 2: Bit range notation like [31:0]
        
        Args:
            parent: Parent index (unused - all items have same column count)
            
        Returns:
            Always returns 3
        """
        return 3  # Name, Type, Bit Range

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Optional[Union[str, QIcon, DesignTreeNode]]:
        """Get data for display or other roles for the given item.
        
        This is a required method for QAbstractItemModel. It provides all the data
        that views need to display items, including text, icons, and custom data.
        
        Args:
            index: Item's index specifying row and column
            role: Qt role indicating what type of data is requested:
                  - Qt.DisplayRole: Text to display
                  - Qt.DecorationRole: Icon for the item
                  - Qt.UserRole: The raw DesignTreeNode object
                  
        Returns:
            Requested data, or None if not available
        """
        if not index.isValid():
            return None

        node = index.internalPointer()
        if not isinstance(node, DesignTreeNode):
            return None
        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return node.name
            elif column == 1:
                return node.var_type if not node.is_scope else "scope"
            elif column == 2:
                return node.bit_range

        elif role == Qt.ItemDataRole.DecorationRole and column == 0:
            if node.is_scope:
                # Get scope type from the node's scope object
                scope_type = "unknown"
                if node.scope:
                    try:
                        scope_type = node.scope.scope_type()
                    except:
                        pass
                return self._icon_cache.get_scope_icon(scope_type)
            else:
                return self._icon_cache.get_signal_icon()

        elif role == Qt.ItemDataRole.UserRole:
            return node

        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Optional[str]:
        """Get header labels for the tree view columns.
        
        This is a required method for QAbstractItemModel. It provides the text
        shown in column headers.
        
        Args:
            section: Column number (0-2)
            orientation: Qt.Horizontal for column headers, Qt.Vertical for row headers
            role: Qt role (only Qt.DisplayRole is handled)
            
        Returns:
            Column header text, or None for unsupported requests
        """
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            headers = ["Name", "Type", "Bit Range"]
            if 0 <= section < len(headers):
                return headers[section]
        return None

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        """Get item flags that control how the user can interact with the item.
        
        This is a required method for QAbstractItemModel. All items in this model
        are enabled and selectable, but not editable.
        
        Args:
            index: Item's index
            
        Returns:
            Qt.ItemFlags indicating the item is enabled and selectable
        """
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags

        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
