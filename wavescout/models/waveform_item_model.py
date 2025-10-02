"""Qt Model/View bridge for waveform data."""

from PySide6.QtCore import Qt, QModelIndex, QAbstractItemModel, QPersistentModelIndex, QObject, QMimeData, QByteArray
from typing import overload, List, Optional, Union, Any, Sequence, TYPE_CHECKING
import json
import time
from ..utils.timing_utils import tprint
from ..core.data_model import WaveformSession, TreeNode, GroupNode, SignalNode
from ..rendering.signal_sampling import parse_signal_value
from ..application.events import StructureChangedEvent, FormatChangedEvent
from ..utils.settings_manager import SettingsManager

if TYPE_CHECKING:
    from ..core.waveform_controller import WaveformController


class WaveformItemModel(QAbstractItemModel):
    """Exposes SignalNode tree to Qt views while keeping dataclass purity."""

    def __init__(self, session: WaveformSession, controller: 'WaveformController', parent: Optional[QObject] = None) -> None:
        init_start = time.time()
        super().__init__(parent)
        self._session = session
        self._controller = controller
        self._headers = ["Signal", "Value", "Format", "Color", "Waveform"]
        self._cleanup_done = False

        # Get settings manager instance
        settings_start = time.time()
        self._settings_manager = SettingsManager()

        # Cache hierarchy levels for performance
        self._cached_hierarchy_levels = self._settings_manager.get_hierarchy_levels()

        # Connect to hierarchy levels changed signal
        self._settings_manager.hierarchy_levels_changed.connect(self._on_hierarchy_levels_changed)
        tprint(f"      WaveformItemModel settings: {time.time() - settings_start:.3f}s")

        # Subscribe to controller events
        events_start = time.time()
        self._controller.event_bus.subscribe(StructureChangedEvent, self._on_structure_changed)
        self._controller.event_bus.subscribe(FormatChangedEvent, self._on_format_changed)
        tprint(f"      WaveformItemModel events: {time.time() - events_start:.3f}s")

        # Connect to destroyed signal for cleanup
        self.destroyed.connect(self._cleanup)
        tprint(f"      WaveformItemModel.__init__ total: {time.time() - init_start:.3f}s")
    
    def _cleanup(self) -> None:
        """Clean up event subscriptions before deletion."""
        if not self._cleanup_done:
            self._cleanup_done = True
            try:
                # Disconnect settings manager signal
                self._settings_manager.hierarchy_levels_changed.disconnect(self._on_hierarchy_levels_changed)
                # Unsubscribe from controller events
                self._controller.event_bus.unsubscribe(StructureChangedEvent, self._on_structure_changed)
                self._controller.event_bus.unsubscribe(FormatChangedEvent, self._on_format_changed)
            except Exception:
                pass  # Ignore errors during cleanup

    # -- overriding row/column API --
    def columnCount(self, _parent: Union[QModelIndex, QPersistentModelIndex] = QModelIndex()) -> int:
        return 5  # One column for each panel: Signal, Value, Format, Color, Waveform

    def rowCount(self, parent: Union[QModelIndex, QPersistentModelIndex] = QModelIndex()) -> int:
        # Return number of children for given parent (or root nodes)
        if not parent.isValid():
            return len(self._session.root_nodes)
        
        node = parent.internalPointer()
        if isinstance(node, GroupNode):
            return len(node.children)
        return 0

    def index(self, row: int, col: int, parent: Union[QModelIndex, QPersistentModelIndex] = QModelIndex()) -> QModelIndex:
        # Create QModelIndex for child at (row, col) under parent
        if not self.hasIndex(row, col, parent):
            return QModelIndex()
        
        if not parent.isValid():
            # Top level
            if 0 <= row < len(self._session.root_nodes):
                return self.createIndex(row, col, self._session.root_nodes[row])
        else:
            parent_node = parent.internalPointer()
            if isinstance(parent_node, GroupNode) and 0 <= row < len(parent_node.children):
                return self.createIndex(row, col, parent_node.children[row])
        
        return QModelIndex()

    @overload
    def parent(self) -> QObject: ...
    
    @overload
    def parent(self, child_idx: QModelIndex | QPersistentModelIndex) -> QModelIndex: ...
    
    def parent(self, child_idx: QModelIndex | QPersistentModelIndex | None = None) -> QModelIndex | QObject:
        # Handle overloaded parent() method
        if child_idx is None:
            return super().parent()
        
        # Return parent index of given child, navigating the tree structure
        if not child_idx.isValid():
            return QModelIndex()
        
        node = child_idx.internalPointer()
        if not node or not node.parent:
            return QModelIndex()
        
        parent_node = node.parent
        
        # Find row of parent within its siblings
        if parent_node.parent:
            # Parent has a grandparent
            row = parent_node.parent.children.index(parent_node)
        else:
            # Parent is a root node
            try:
                row = self._session.root_nodes.index(parent_node)
            except ValueError:
                return QModelIndex()
        
        return self.createIndex(row, 0, parent_node)

    def data(self, index: Union[QModelIndex, QPersistentModelIndex], role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        # Return appropriate data based on column and role
        if not index.isValid():
            return None
        
        node = index.internalPointer()
        if not isinstance(node, TreeNode):
            return None

        if role == Qt.ItemDataRole.DisplayRole:
            col = index.column()
            if col == 0:
                return self._format_signal_name(node)
            elif col == 1:
                # Value at cursor position
                return self._value_at_cursor(node)
            elif col == 2:
                # Format column - show data format
                return self._format_at_cursor(node)
            elif col == 3:
                # Color column - return empty string for display (color shown via BackgroundRole)
                return ""
            elif col == 4:
                return ""  # Waveform painted by canvas
        elif role == Qt.ItemDataRole.ForegroundRole:
            if isinstance(node, SignalNode):
                return node.format.color
            return None
        elif role == Qt.ItemDataRole.BackgroundRole:
            # Show color in the Color column (column 3)
            if index.column() == 3 and isinstance(node, SignalNode):
                if node.format.color:
                    from PySide6.QtGui import QColor
                    return QColor(node.format.color)
            return None
        elif role == Qt.ItemDataRole.UserRole:
            return node  # For delegates to access full node data
        
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if 0 <= section < len(self._headers):
                return self._headers[section]
        return None

    def flags(self, index: Union[QModelIndex, QPersistentModelIndex]) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.ItemIsDropEnabled
        
        default_flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        
        # Enable drag for valid items
        node = index.internalPointer()
        if node and isinstance(node, TreeNode):
            return default_flags | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled
        
        return default_flags

    def hasChildren(self, parent: Union[QModelIndex, QPersistentModelIndex] = QModelIndex()) -> bool:
        if not parent.isValid():
            return len(self._session.root_nodes) > 0
        
        node = parent.internalPointer()
        return isinstance(node, GroupNode) and len(node.children) > 0

    def _format_signal_name(self, node: TreeNode) -> str:
        # Nickname takes precedence, else use hierarchical display mode
        if node.nickname:
            return node.nickname

        # Get base name (with file prefix if needed)
        base_name = self._get_display_name(node)

        # Use cached hierarchy levels from settings (0 = show full path)
        if self._cached_hierarchy_levels == 0:
            return base_name
        else:
            # Split hierarchical name and take last N levels
            parts = base_name.split('.')
            n = self._cached_hierarchy_levels
            return '.'.join(parts[-n:]) if len(parts) > n else base_name

    def _get_display_name(self, node: TreeNode) -> str:
        """Format node name with file prefix if needed.

        Returns:
            - Single file: node.name
            - Multiple files, primary file (file_id=0): node.name
            - Multiple files, other files: "{filename}:{node.name}"
        """
        # Groups don't need file prefix
        if not isinstance(node, SignalNode):
            return node.name

        # Single file or no files loaded
        if len(self._session.waveform_files) <= 1:
            return node.name

        # Multi-file mode
        signal_node = node
        file_ref = self._session.get_file_by_id(signal_node.file_id)

        # Primary file (first in list) doesn't need prefix
        if file_ref and file_ref == self._session.waveform_files[0]:
            return node.name

        # Other files need prefix
        if file_ref:
            from pathlib import Path
            filename = Path(file_ref.file_path).name
            return f"{filename}:{node.name}"

        # Fallback if file not found
        return node.name
    
    def _value_at_cursor(self, node: TreeNode) -> str:
        # Query WaveformDB for signal value at cursor time and format it according to node.format.data_format
        if isinstance(node, GroupNode) or not self._session.waveform_files:
            return ""

        # Now we know it's a SignalNodeSignal
        assert isinstance(node, SignalNode)  # Help type checker
        signal_node = node
        if signal_node.handle is None:
            return ""
        try:
            # Use cached Signal object from node
            if not signal_node.signal.is_loaded():
                return ""
            signal_obj = signal_node.signal.get_signal_blocking(timeout=0.001)
            if not signal_obj:
                return ""
            query = signal_obj.query_signal(max(0, self._session.cursor_time))
            raw_value = query.value

            # Determine bit width similar to rendering logic
            bit_width = signal_node.var.bitwidth() or 32
            
            # Use the same parser as waveform_canvas to get formatted string
            value_str, _, _ = parse_signal_value(raw_value, signal_node.format.data_format, bit_width)
            return value_str or ""
        except Exception:
            return ""
    
    def _format_at_cursor(self, node: TreeNode) -> str:
        # Return the data format for the signal
        if isinstance(node, GroupNode):
            return ""

        # Now we know it's a SignalNodeSignal
        assert isinstance(node, SignalNode)  # Help type checker
        signal_node = node
        if signal_node.handle is None:
            return ""

        # Return the format as a string
        return signal_node.format.data_format.value
    
    def _on_structure_changed(self, event: StructureChangedEvent) -> None:
        """Handle structure change events from controller."""
        # Check if model is still valid before processing
        if self._cleanup_done:
            return
        try:
            # For now, do a full reset. Later we can optimize with fine-grained updates
            self.beginResetModel()
            self.endResetModel()
        except RuntimeError:
            # Model already deleted, ignore
            pass
    
    def _on_format_changed(self, event: FormatChangedEvent) -> None:
        """Handle format change events from controller."""
        # Check if model is still valid before processing
        if self._cleanup_done:
            return
        try:
            # Find the node and emit dataChanged for it
            node = self._find_node_by_id(event.node_id)
            if node:
                # Check if height changed - if so, we need layoutChanged to update canvas row heights
                if 'height' in event.changes:
                    # Height changed, need full layout update for canvas to recalculate row positions
                    self.layoutChanged.emit()
                else:
                    # Find the model index for this node
                    index = self._create_index_for_node(node)
                    if index.isValid():
                        # Emit dataChanged for all columns
                        self.dataChanged.emit(index, self.index(index.row(), 3, index.parent()))
        except RuntimeError:
            # Model already deleted, ignore
            pass
    
    def _on_hierarchy_levels_changed(self, levels: int) -> None:
        """Handle hierarchy levels setting change."""
        # Check if model is still valid
        if self._cleanup_done:
            return
        
        # Update cached value
        self._cached_hierarchy_levels = levels
        
        # Emit dataChanged for first column (signal names) of all nodes
        try:
            # Use layoutChanged to force complete refresh of names column
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(self.rowCount() - 1, 0)
            )
            
            # Also update all child nodes recursively
            def emit_for_children(parent_index: QModelIndex) -> None:
                rows = self.rowCount(parent_index)
                if rows > 0:
                    # Emit for this level
                    self.dataChanged.emit(
                        self.index(0, 0, parent_index),
                        self.index(rows - 1, 0, parent_index)
                    )
                    # Recurse for children
                    for row in range(rows):
                        child_index = self.index(row, 0, parent_index)
                        if self.hasChildren(child_index):
                            emit_for_children(child_index)
            
            # Start recursion from root
            for row in range(self.rowCount()):
                root_index = self.index(row, 0)
                if self.hasChildren(root_index):
                    emit_for_children(root_index)
                    
        except RuntimeError:
            # Model already deleted, ignore
            pass
    
    def _find_node_by_id(self, node_id: int) -> Optional[TreeNode]:
        """Find a node by its instance ID."""
        def search(nodes: List[TreeNode]) -> Optional[TreeNode]:
            for node in nodes:
                if node.instance_id == node_id:
                    return node
                if isinstance(node, GroupNode):
                    found = search(node.children)
                    if found:
                        return found
            return None
        return search(self._session.root_nodes)
    
    def _create_index_for_node(self, target_node: TreeNode) -> QModelIndex:
        """Create a QModelIndex for a given node."""
        # Find the path from root to node
        path = []
        current = target_node
        while current.parent:
            path.append(current)
            current = current.parent
        path.append(current)
        path.reverse()
        
        # Build index by traversing path
        index = QModelIndex()
        for i, node in enumerate(path):
            if i == 0:
                # Root level
                try:
                    row = self._session.root_nodes.index(node)
                    index = self.index(row, 0)
                except ValueError:
                    return QModelIndex()
            else:
                # Child level
                parent_node = path[i-1]
                if not isinstance(parent_node, GroupNode):
                    return QModelIndex()
                try:
                    row = parent_node.children.index(node)
                    index = self.index(row, 0, index)
                except ValueError:
                    return QModelIndex()
        
        return index
    
    # -- Drag and Drop Support --
    def supportedDropActions(self) -> Qt.DropAction:
        return Qt.DropAction.MoveAction
    
    def mimeTypes(self) -> List[str]:
        return ["application/x-wavescout-signalnodes"]
    
    def mimeData(self, indexes: Sequence[QModelIndex]) -> QMimeData:
        if not indexes:
            return QMimeData()
        
        # Collect unique nodes (avoid duplicates from multiple columns)
        nodes_data = []
        seen_nodes = []
        
        for index in indexes:
            if index.column() == 0:  # Only process first column
                node = index.internalPointer()
                if node and node not in seen_nodes:
                    seen_nodes.append(node)
                    # Store node path for reconstruction
                    node_path = self._get_node_path(node)
                    nodes_data.append({
                        'path': node_path,
                        'row': index.row(),
                        'is_group': node.is_group
                    })
        
        if not nodes_data:
            return QMimeData()
        
        mime_data = QMimeData()
        data = json.dumps(nodes_data).encode('utf-8')
        mime_data.setData("application/x-wavescout-signalnodes", QByteArray(data))
        return mime_data
    
    def canDropMimeData(self, data: QMimeData, action: Qt.DropAction, row: int, column: int, parent: Union[QModelIndex, QPersistentModelIndex]) -> bool:
        if not data.hasFormat("application/x-wavescout-signalnodes"):
            return False
        
        if action != Qt.DropAction.MoveAction:
            return False
        
        # Always allow drops - we'll handle the logic in dropMimeData
        return True
    
    def dropMimeData(self, data: QMimeData, action: Qt.DropAction, row: int, column: int, parent: Union[QModelIndex, QPersistentModelIndex]) -> bool:
        if not self.canDropMimeData(data, action, row, column, parent):
            return False

        # Parse the drag data
        byte_data = data.data("application/x-wavescout-signalnodes")
        nodes_data = json.loads(bytes(byte_data.data()).decode('utf-8'))
        
        # Determine drop target and insertion position
        if row == -1 and parent.isValid():
            # Dropped directly on an item
            target_node = parent.internalPointer()
            
            if isinstance(target_node, GroupNode):
                # Dropped on a group - insert at the beginning of the group
                parent_node = target_node
                target_list = target_node.children
                insert_row = 0
            else:
                # Dropped on a non-group item - insert after it in the same parent
                parent_node = target_node.parent
                
                if isinstance(parent_node, GroupNode):
                    target_list = parent_node.children
                    # Find the position of the target item and insert after it
                    try:
                        target_index = target_list.index(target_node)
                        insert_row = target_index + 1
                    except ValueError:
                        insert_row = len(target_list)
                else:
                    parent_node = None
                    # Target is a root node
                    target_list = self._session.root_nodes
                    try:
                        target_index = target_list.index(target_node)
                        insert_row = target_index + 1
                    except ValueError:
                        insert_row = len(target_list)
        elif parent.isValid():
            # Dropped between items in a group
            parent_node = parent.internalPointer()
            if isinstance(parent_node, GroupNode):
                target_list = parent_node.children
            else:
                parent_node = None
                target_list = self._session.root_nodes
            insert_row = row if row != -1 else len(target_list)
        else:
            # Dropped at root level
            parent_node = None
            target_list = self._session.root_nodes
            insert_row = row if row != -1 else len(target_list)
        
        # Collect nodes to move
        nodes_to_move = []
        for node_data in nodes_data:
            node = self._find_node_by_path(node_data['path'])
            if node:
                nodes_to_move.append(node)
        
        if not nodes_to_move:
            return False
        
        # Perform the move
        try:
            return self._move_nodes(nodes_to_move, parent_node, insert_row)
        except Exception as e:
            tprint(f"Drop failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _get_node_path(self, node: TreeNode) -> List[str]:
        """Get the path from root to this node."""
        path = []
        current: Optional[TreeNode] = node
        while current:
            path.append(current.name)
            current = current.parent
        return list(reversed(path))
    
    def _find_node_by_path(self, path: List[str]) -> Optional[TreeNode]:
        """Find a node by its path from root."""
        if not path:
            return None
        
        # Start from root nodes
        current_list = self._session.root_nodes
        current_node = None
        
        for name in path:
            found = False
            for node in current_list:
                if node.name == name:
                    current_node = node
                    current_list = node.children if isinstance(node, GroupNode) else []
                    found = True
                    break
            if not found:
                return None
        
        return current_node
    
    def _move_nodes(self, nodes: List[TreeNode], new_parent: Optional[TreeNode], insert_row: int) -> bool:
        """Move nodes to a new parent at the specified position."""
        # Validate the move operation
        if not self._validate_move(nodes, new_parent):
            return False
        
        node_ids = [node.instance_id for node in nodes]
        parent_id = new_parent.instance_id if new_parent else None
        self._controller.move_nodes(node_ids, parent_id, insert_row)
        return True
    
    def _validate_move(self, nodes: List[TreeNode], new_parent: Optional[TreeNode]) -> bool:
        """Validate that the move operation is allowed."""
        # Prevent moving a node into itself or its descendants
        for node in nodes:
            if new_parent:
                ancestor: Optional[TreeNode] = new_parent
                while ancestor:
                    if ancestor == node:
                        return False
                    ancestor = ancestor.parent
        return True
    def _find_index_for_node(self, node: TreeNode) -> QModelIndex:
        """Find the QModelIndex for a given node."""
        if not node.parent:
            # Root node
            try:
                row = self._session.root_nodes.index(node)
                return self.createIndex(row, 0, node)
            except ValueError:
                return QModelIndex()
        else:
            # Non-root node
            try:
                parent = node.parent
                if not isinstance(parent, GroupNode):
                    return QModelIndex()
                row = parent.children.index(node)
                parent_index = self._find_index_for_node(parent)
                return self.index(row, 0, parent_index)
            except ValueError:
                return QModelIndex()
