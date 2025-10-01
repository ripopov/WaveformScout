"""
Multi-file scope tree model that wraps multiple ScopeTreeModel instances.

When multiple waveform files are loaded, this model shows file nodes at the root level,
with each file's hierarchy as children. For single-file mode, it delegates directly to
ScopeTreeModel for backward compatibility.
"""

from __future__ import annotations

from typing import Optional, List, Dict, Union, Any, TYPE_CHECKING, overload
from pathlib import Path

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QPersistentModelIndex, Qt, Signal, QObject

if TYPE_CHECKING:
    from .data_model import WaveformFileReference
    from .scope_tree_model import DesignTreeNode

from .scope_tree_model import ScopeTreeModel, DesignTreeNode
from .icon_cache import get_icon_cache


class FileNode:
    """Represents a file at the root level of the multi-file tree."""

    def __init__(self, file_id: int, file_name: str, model: ScopeTreeModel):
        self.file_id = file_id
        self.file_name = file_name
        self.model = model
        self.is_file_node = True


class MultiFileScopeTreeModel(QAbstractItemModel):
    """Tree model that wraps multiple ScopeTreeModel instances for multi-file support.

    Root level shows file nodes when multiple files are loaded.
    Single file mode delegates directly to ScopeTreeModel for backward compatibility.
    """

    scope_selected = Signal(str)  # Emits the full path of the selected scope

    def __init__(self, waveform_files: List['WaveformFileReference'], parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.waveform_files = waveform_files
        self.file_models: Dict[int, ScopeTreeModel] = {}
        self.file_nodes: List[FileNode] = []
        self._icon_cache = get_icon_cache()
        self._single_file_mode = len(waveform_files) == 1
        # Map from node object id to file_id for quick lookup
        self._node_to_file_id: Dict[int, int] = {}

        # Create a ScopeTreeModel for each file
        for file_ref in waveform_files:
            if file_ref.waveform_db:
                model = ScopeTreeModel(file_ref.waveform_db)
                self.file_models[file_ref.file_id] = model

                # Create file node
                file_name = Path(file_ref.file_path).name
                file_node = FileNode(file_ref.file_id, file_name, model)
                self.file_nodes.append(file_node)

                # Build mapping from all nodes in this model to file_id
                self._map_nodes_to_file_id(model.root_node, file_ref.file_id)

    def is_single_file_mode(self) -> bool:
        """Check if in single-file mode (backward compatibility)."""
        return self._single_file_mode

    def _map_nodes_to_file_id(self, node: Optional['DesignTreeNode'], file_id: int) -> None:
        """Recursively map all nodes in a tree to their file_id."""
        if node is None:
            return
        self._node_to_file_id[id(node)] = file_id
        for child in node.children:
            self._map_nodes_to_file_id(child, file_id)

    def get_file_id_for_index(self, index: QModelIndex) -> int:
        """Get the file_id for a given index.

        In single-file mode, returns the only file's ID.
        In multi-file mode, uses node mapping to find the file node.
        """
        if self._single_file_mode and self.waveform_files:
            return self.waveform_files[0].file_id

        # Check if this is directly a file node
        internal_ptr = index.internalPointer()
        if isinstance(internal_ptr, FileNode):
            return internal_ptr.file_id

        # Look up the node in our mapping
        if isinstance(internal_ptr, DesignTreeNode):
            node_id = id(internal_ptr)
            if node_id in self._node_to_file_id:
                return self._node_to_file_id[node_id]

        # Default to first file if somehow we can't determine
        return self.waveform_files[0].file_id if self.waveform_files else 0

    def rowCount(self, parent: Union[QModelIndex, QPersistentModelIndex] = QModelIndex()) -> int:
        """Return number of rows under the given parent."""
        if self._single_file_mode:
            # Delegate to the single model
            if self.file_models:
                model = list(self.file_models.values())[0]
                return model.rowCount(parent)
            return 0

        # Multi-file mode
        if not parent.isValid():
            # Root level: show file nodes
            return len(self.file_nodes)

        internal_ptr = parent.internalPointer()
        if isinstance(internal_ptr, FileNode):
            # File node: show children of the hidden TOP node (i.e., top-level scopes)
            model = internal_ptr.model
            if model.root_node:
                return len(model.root_node.children)
            return 0
        elif isinstance(internal_ptr, DesignTreeNode):
            # Delegate to the appropriate file model
            if isinstance(parent, QModelIndex):
                file_id = self.get_file_id_for_index(parent)
                maybe_model = self.file_models.get(file_id)
                if maybe_model is not None:
                    # Need to recreate the index within the child model
                    child_index = self._map_to_child_model(parent, maybe_model)
                    return maybe_model.rowCount(child_index)

        return 0

    def columnCount(self, parent: Union[QModelIndex, QPersistentModelIndex] = QModelIndex()) -> int:
        """Return number of columns (always 1 for tree)."""
        return 1

    def data(self, index: Union[QModelIndex, QPersistentModelIndex], role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Return data for the given index and role."""
        if not index.isValid():
            return None

        internal_ptr = index.internalPointer()

        # Handle file nodes
        if isinstance(internal_ptr, FileNode):
            if role == Qt.ItemDataRole.DisplayRole:
                return internal_ptr.file_name
            elif role == Qt.ItemDataRole.DecorationRole:
                # Use a scope icon for file nodes
                return self._icon_cache.get_scope_icon("unknown")
            return None

        # Handle DesignTreeNode - return data directly from the node
        if isinstance(internal_ptr, DesignTreeNode):
            if role == Qt.ItemDataRole.DisplayRole:
                return internal_ptr.name
            elif role == Qt.ItemDataRole.DecorationRole:
                # Get the file model to access icon cache
                if isinstance(index, QModelIndex):
                    file_id = self.get_file_id_for_index(index)
                    maybe_model = self.file_models.get(file_id)
                    if maybe_model is not None:
                        # Use the model's icon cache
                        if internal_ptr.is_scope and hasattr(internal_ptr, 'scope') and internal_ptr.scope:
                            return maybe_model._icon_cache.get_scope_icon(str(internal_ptr.scope.scope_type()))
                        else:
                            return maybe_model._icon_cache.get_scope_icon("module")
            return None

        # Delegate to child model (for backward compatibility in single-file mode)
        if self._single_file_mode:
            if self.file_models:
                model = list(self.file_models.values())[0]
                return model.data(index, role)

        return None

    def index(self, row: int, column: int, parent: Union[QModelIndex, QPersistentModelIndex] = QModelIndex()) -> QModelIndex:
        """Return index for the given row, column, and parent."""
        if row < 0 or column != 0:
            return QModelIndex()

        if self._single_file_mode:
            # Delegate to the single model
            if self.file_models:
                model = list(self.file_models.values())[0]
                return model.index(row, column, parent)
            return QModelIndex()

        # Multi-file mode
        if not parent.isValid():
            # Root level: return file node
            if row < len(self.file_nodes):
                file_node = self.file_nodes[row]
                return self.createIndex(row, column, file_node)
            return QModelIndex()

        internal_ptr = parent.internalPointer()

        if isinstance(internal_ptr, FileNode):
            # File node: return child from its model (top-level scopes)
            # Skip the hidden "TOP" root node and return its children directly
            model = internal_ptr.model
            if model.root_node and row < len(model.root_node.children):
                # Get the nth child of TOP (which are the actual top-level scopes)
                child_node = model.root_node.children[row]
                return self.createIndex(row, column, child_node)
            return QModelIndex()
        elif isinstance(internal_ptr, DesignTreeNode):
            # Scope node: delegate to the appropriate model
            if isinstance(parent, QModelIndex):
                file_id = self.get_file_id_for_index(parent)
                maybe_model = self.file_models.get(file_id)
                if maybe_model is not None:
                    child_index = self._map_to_child_model(parent, maybe_model)
                    result_index = maybe_model.index(row, column, child_index)
                    if result_index.isValid():
                        child_node = result_index.internalPointer()
                        return self.createIndex(row, column, child_node)

        return QModelIndex()

    @overload
    def parent(self) -> QObject: ...

    @overload
    def parent(self, index: Union[QModelIndex, QPersistentModelIndex]) -> QModelIndex: ...

    def parent(self, index: Union[QModelIndex, QPersistentModelIndex, None] = None) -> Union[QModelIndex, QObject]:
        """Return parent index for the given index."""
        # Handle overloaded parent() method
        if index is None:
            return super().parent()

        if not index.isValid():
            return QModelIndex()

        if self._single_file_mode:
            # Delegate to the single model
            if self.file_models:
                model = list(self.file_models.values())[0]
                return model.parent(index)
            return QModelIndex()

        # Multi-file mode
        internal_ptr = index.internalPointer()

        if isinstance(internal_ptr, FileNode):
            # File nodes have no parent (they're at root)
            return QModelIndex()
        elif isinstance(internal_ptr, DesignTreeNode):
            node = internal_ptr
            # Get the file_id to access the correct model
            if isinstance(index, QModelIndex):
                file_id = self.get_file_id_for_index(index)
                maybe_model = self.file_models.get(file_id)
                if maybe_model is None:
                    return QModelIndex()

                # Check if node's parent is the root_node (the hidden "TOP")
                if node.parent is None or (node.parent and id(node.parent) == id(maybe_model.root_node)):
                    # This is a top-level scope in a file, parent is the file node
                    for row, file_node in enumerate(self.file_nodes):
                        if file_node.file_id == file_id:
                            return self.createIndex(row, 0, file_node)
                    return QModelIndex()
                else:
                    # Find row of parent in its parent's children
                    parent_node = node.parent
                    # Check if grandparent is the root_node
                    if parent_node.parent is None or (parent_node.parent and id(parent_node.parent) == id(maybe_model.root_node)):
                        # Parent is a top-level scope, grandparent is file node
                        for row, file_node in enumerate(self.file_nodes):
                            if file_node.file_id == file_id:
                                # Return index for parent node under file node
                                if maybe_model.root_node:
                                    node_id = id(parent_node)
                                    for child_row, child in enumerate(maybe_model.root_node.children):
                                        if id(child) == node_id:
                                            return self.createIndex(child_row, 0, parent_node)
                        return QModelIndex()
                    else:
                        # Parent has a parent, calculate row
                        row = parent_node.parent.children.index(parent_node) if parent_node in parent_node.parent.children else 0
                        return self.createIndex(row, 0, parent_node)

        return QModelIndex()

    def _map_to_child_model(self, index: QModelIndex, model: ScopeTreeModel) -> QModelIndex:
        """Map an index from this model to the corresponding child model index."""
        if not index.isValid():
            return QModelIndex()

        # The internal pointer should already be a DesignTreeNode from the child model
        internal_ptr = index.internalPointer()
        if isinstance(internal_ptr, DesignTreeNode):
            # Need to reconstruct the index in the child model
            # For now, we can use the node directly since it's from the child model
            node = internal_ptr
            # Check if node's parent is the root_node (the hidden "TOP")
            if node.parent is None or (node.parent and id(node.parent) == id(model.root_node)):
                # Top-level node - direct child of root_node
                # Find it by object identity in root_node.children
                if model.root_node:
                    node_id = id(node)
                    for row, child in enumerate(model.root_node.children):
                        if id(child) == node_id:
                            return model.index(row, 0, QModelIndex())
            else:
                # Not a top-level node - find row in parent's children
                row = node.parent.children.index(node) if node in node.parent.children else 0
                parent_index = self._find_parent_index_in_model(node.parent, model)
                return model.index(row, 0, parent_index)

        return QModelIndex()

    def _find_parent_index_in_model(self, node: DesignTreeNode, model: ScopeTreeModel) -> QModelIndex:
        """Find the index of a node in a child model by recursively building the path."""
        # Check if this node's parent is the root_node (the hidden "TOP")
        if node.parent is None or (node.parent and id(node.parent) == id(model.root_node)):
            # This is a top-level node (direct child of root_node)
            # Find its row in root_node.children
            if model.root_node:
                node_id = id(node)
                for row, child in enumerate(model.root_node.children):
                    if id(child) == node_id:
                        # Return the index for this top-level node
                        return model.index(row, 0, QModelIndex())
            # If not found, return invalid index
            return QModelIndex()

        # Not a top-level node - recursively find parent's index, then find this node under it
        parent_index = self._find_parent_index_in_model(node.parent, model)
        if not parent_index.isValid():
            return QModelIndex()

        # Find this node's row in its parent's children
        row = node.parent.children.index(node) if node in node.parent.children else 0
        return model.index(row, 0, parent_index)

    def get_variables_for_scope(self, index: QModelIndex) -> List[Any]:
        """Get variables for the selected scope."""
        if not index.isValid():
            return []

        internal_ptr = index.internalPointer()

        # File nodes don't have variables
        if isinstance(internal_ptr, FileNode):
            return []

        # Delegate to child model
        if self._single_file_mode:
            if self.file_models:
                models_list = list(self.file_models.values())
                if models_list:
                    model = models_list[0]
                    if isinstance(internal_ptr, DesignTreeNode):
                        return model.get_variables_for_scope(internal_ptr)
        else:
            file_id = self.get_file_id_for_index(index)
            maybe_model = self.file_models.get(file_id)
            if maybe_model is not None and isinstance(internal_ptr, DesignTreeNode):
                return maybe_model.get_variables_for_scope(internal_ptr)

        return []