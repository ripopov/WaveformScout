"""Fast Rust-backed Design Tree Model for large hierarchies.

This module provides a high-performance Qt model using the Rust implementation
for efficient handling of designs with millions of variables and scopes.
"""

from __future__ import annotations
from typing import Optional, TYPE_CHECKING, Any, Union, overload

from PySide6.QtCore import Qt, QAbstractItemModel, QModelIndex, QPersistentModelIndex, QObject

if TYPE_CHECKING:
    from pyrox import SignalHandle, Var, Scope
    import pyrox

from .protocols import WaveformDBProtocol
from .icon_cache import get_icon_cache


class DesignTreeNode:
    """Standalone tree node for backward compatibility.

    This class is used by ScopeTreeModel and tests that need to create nodes directly.
    """

    def __init__(self, name: str, is_scope: bool = False, var_type: str = "",
                 bit_range: str = "", parent: Optional['DesignTreeNode'] = None):
        """Initialize a tree node representing either a scope (module) or signal."""
        self.name = name
        self.is_scope = is_scope
        self.var_type = var_type
        self.bit_range = bit_range
        self.parent = parent
        self.children: list['DesignTreeNode'] = []
        self.var_handle: Optional[SignalHandle] = None
        self.var: Optional[Any] = None
        self.scope: Optional[Any] = None

    def add_child(self, child: 'DesignTreeNode') -> None:
        """Add a child node to this node and set this node as its parent."""
        child.parent = self
        self.children.append(child)


class DesignTreeNodeProxy:
    """Lightweight proxy to Rust node for backward compatibility.

    This proxy provides the same interface as the original DesignTreeNode
    but delegates to the Rust implementation for data access.
    """

    def __init__(self, rust_model: Any, node_idx: int):
        """Initialize proxy with reference to Rust model and node index."""
        self._model = rust_model
        self._idx = node_idx

    @property
    def name(self) -> str:
        """Get the node's display name."""
        return self._model.get_display_text(self._idx, 0) or ""

    @property
    def is_scope(self) -> bool:
        """Check if this node represents a scope/module."""
        return bool(self._model.is_scope(self._idx))

    @property
    def var_handle(self) -> Optional[SignalHandle]:
        """Get the signal handle for database lookups."""
        handle = self._model.get_var_handle(self._idx)
        return handle if handle is not None else None

    @property
    def var(self) -> Optional[Var]:
        """Get the pyrox Var object."""
        v = self._model.get_var(self._idx)
        return v if v is not None else None

    @property
    def scope(self) -> Optional[Scope]:
        """Get the pyrox Scope object for scope nodes."""
        s = self._model.get_scope(self._idx)
        return s if s is not None else None

    @property
    def var_type(self) -> str:
        """Get the variable or scope type."""
        return self._model.get_display_text(self._idx, 1) or ""

    @property
    def bit_range(self) -> str:
        """Get the bit range for multi-bit signals."""
        return self._model.get_display_text(self._idx, 2) or ""

    @property
    def parent(self) -> Optional['DesignTreeNodeProxy']:
        """Get the parent node proxy."""
        parent_idx = self._model.parent(self._idx)
        if parent_idx is not None:
            return DesignTreeNodeProxy(self._model, parent_idx)
        return None

    @property
    def children(self) -> list[Any]:
        """Get child nodes (empty list for compatibility)."""
        # Return empty list for now - could be implemented if needed
        return []


class DesignTreeModel(QAbstractItemModel):
    """Fast Qt model wrapper around Rust DesignTreeModel.

    This provides a thin Python wrapper around the high-performance Rust
    implementation while maintaining full compatibility with Qt's model/view
    framework and the existing WaveformScout codebase.
    """

    def __init__(self, waveform_db: Optional[WaveformDBProtocol] = None,
                 parent: Optional[QObject] = None):
        """Initialize the model with optional waveform database.

        Args:
            waveform_db: The waveform database to load hierarchy from
            parent: Optional Qt parent object
        """
        super().__init__(parent)
        self.waveform_db = waveform_db
        self._rust_model: Optional[Any] = None
        self._icon_cache = get_icon_cache()

        if waveform_db:
            self.load_hierarchy(waveform_db)

    def load_hierarchy(self, waveform_db: WaveformDBProtocol) -> None:
        """Load hierarchy from waveform database into the model.

        This creates a new Rust model from the hierarchy, which builds
        the tree structure efficiently in Rust.

        Args:
            waveform_db: The waveform database containing the hierarchy
        """
        self.beginResetModel()
        self.waveform_db = waveform_db

        if waveform_db and waveform_db.hierarchy:
            # Create Rust model which builds the tree efficiently
            import pyrox
            self._rust_model = pyrox.PyDesignTreeModel(waveform_db.hierarchy)  # type: ignore[attr-defined]
        else:
            self._rust_model = None

        self.endResetModel()

    def index(self, row: int, column: int,
              parent: Union[QModelIndex, QPersistentModelIndex] = QModelIndex()) -> QModelIndex:
        """Create a QModelIndex for the item at (row, column) under parent.

        Args:
            row: Row number of the child
            column: Column number (0=Name, 1=Type, 2=Bit Range)
            parent: Parent index or invalid index for root

        Returns:
            QModelIndex for the specified item or invalid index
        """
        if not self._rust_model:
            return QModelIndex()

        parent_idx = parent.internalId() if parent.isValid() else None
        node_idx = self._rust_model.index(row, column, parent_idx)

        if node_idx is not None:
            return self.createIndex(row, column, node_idx)
        return QModelIndex()

    @overload
    def parent(self) -> QObject: ...

    @overload
    def parent(self, index: Union[QModelIndex, QPersistentModelIndex], /) -> QModelIndex: ...

    def parent(self, index: Optional[Union[QModelIndex, QPersistentModelIndex]] = None) -> Union[QObject, QModelIndex]:
        """Get the parent index of the given index.

        Args:
            index: Child index to get parent for

        Returns:
            Parent QModelIndex or invalid index for root items
        """
        if index is None:
            return super().parent()

        if not index.isValid() or not self._rust_model:
            return QModelIndex()

        node_idx = index.internalId()
        parent_idx = self._rust_model.parent(node_idx)

        if parent_idx is not None:
            # Get parent's row in its parent
            grandparent_idx = self._rust_model.parent(parent_idx)
            row = self._rust_model.get_row_of_child(grandparent_idx, parent_idx)
            if row is not None:
                return self.createIndex(row, 0, parent_idx)

        return QModelIndex()

    def rowCount(self, parent: Union[QModelIndex, QPersistentModelIndex] = QModelIndex()) -> int:
        """Get number of child rows under the given parent.

        Args:
            parent: Parent index or invalid index for root

        Returns:
            Number of child rows
        """
        if not self._rust_model:
            return 0

        parent_idx = parent.internalId() if parent.isValid() else None
        return int(self._rust_model.row_count(parent_idx))

    def columnCount(self, parent: Union[QModelIndex, QPersistentModelIndex] = QModelIndex()) -> int:
        """Get number of columns (always 3: Name, Type, Bit Range).

        Args:
            parent: Parent index (unused, columns are consistent)

        Returns:
            Always returns 3
        """
        return 3  # Always 3 columns regardless of whether model is loaded

    def data(self, index: Union[QModelIndex, QPersistentModelIndex], role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Get data for the given index and role.

        Args:
            index: Model index to get data for
            role: Qt role (DisplayRole, DecorationRole, UserRole, etc.)

        Returns:
            Data for the role or None
        """
        if not index.isValid() or not self._rust_model:
            return None

        node_idx = index.internalId()
        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return self._rust_model.get_display_text(node_idx, column)

        elif role == Qt.ItemDataRole.DecorationRole and column == 0:
            # Provide icons for first column
            if self._rust_model.is_scope(node_idx):
                scope_type = self._rust_model.get_scope_type(node_idx) or "unknown"
                return self._icon_cache.get_scope_icon(scope_type)
            else:
                return self._icon_cache.get_signal_icon()

        elif role == Qt.ItemDataRole.UserRole:
            # Return a lightweight node proxy for compatibility
            return DesignTreeNodeProxy(self._rust_model, node_idx)

        return None

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Get header data for the given section.

        Args:
            section: Column number
            orientation: Header orientation (horizontal/vertical)
            role: Qt role

        Returns:
            Header text or None
        """
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            headers = ["Name", "Type", "Bit Range"]
            if 0 <= section < len(headers):
                return headers[section]
        return None

    def flags(self, index: Union[QModelIndex, QPersistentModelIndex]) -> Qt.ItemFlag:
        """Get item flags for the given index.

        Args:
            index: Model index

        Returns:
            Qt item flags
        """
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags

        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def find_node_by_path(self, path: str) -> Optional[QModelIndex]:
        """Find a node by its hierarchical path.

        Args:
            path: Dot-separated hierarchical path (e.g., "TOP.cpu.clk")

        Returns:
            QModelIndex for the node or None if not found
        """
        if not self._rust_model:
            return None

        node_idx = self._rust_model.find_by_path(path)
        if node_idx is not None:
            # Need to determine row to create proper index
            parent_idx = self._rust_model.parent(node_idx)
            row = self._rust_model.get_row_of_child(parent_idx, node_idx)
            if row is not None:
                return self.createIndex(row, 0, node_idx)

        return None

    def get_node(self, index: QModelIndex) -> Optional[DesignTreeNodeProxy]:
        """Get the node proxy for the given index.

        Args:
            index: Model index

        Returns:
            Node proxy or None
        """
        if not index.isValid() or not self._rust_model:
            return None

        return DesignTreeNodeProxy(self._rust_model, index.internalId())

    @property
    def has_hierarchy(self) -> bool:
        """Check if the model has a loaded hierarchy."""
        return self._rust_model is not None

    @property
    def root_node(self) -> DesignTreeNode:
        """Get the root node for backward compatibility with tests."""
        # Create a dummy root node for tests
        if not hasattr(self, '_root_node'):
            self._root_node = DesignTreeNode("Root", is_scope=True)
        return self._root_node