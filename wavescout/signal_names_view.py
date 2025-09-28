"""Signal names tree view for the WaveScout widget."""

from PySide6.QtWidgets import QTreeView, QAbstractItemView, QMenu, QStyledItemDelegate, QWidget, QStyleOptionViewItem, QInputDialog, QColorDialog, QApplication, QMessageBox
from PySide6.QtCore import Qt, Signal, QModelIndex, QAbstractItemModel, QPoint, QSize, QMimeData
from PySide6.QtGui import QAction, QActionGroup, QKeyEvent, QColor, QKeySequence, QClipboard
from typing import List, Optional, Callable, Union, TYPE_CHECKING, Dict, Any
from PySide6.QtCore import QPersistentModelIndex
import json
from pyrox import SignalHandle
from .data_model import TreeNode, SignalNode, GroupNode, RenderType, AnalogScalingMode, DataFormat, GroupRenderMode
from .config import RENDERING, UI
from .clock_utils import is_valid_clock_signal
from .persistence import _serialize_node, _deserialize_node
from .snippet_manager import SnippetManager
from .snippet_dialogs import SaveSnippetDialog

if TYPE_CHECKING:
    from .waveform_controller import WaveformController


class ScaledHeightDelegate(QStyledItemDelegate):
    """Custom delegate that scales row height based on SignalNode.height_scaling."""
    
    def __init__(self, base_height: int = RENDERING.DEFAULT_ROW_HEIGHT, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._base_height = base_height
        
    def sizeHint(self, option: QStyleOptionViewItem, index: Union[QModelIndex, QPersistentModelIndex]) -> QSize:
        """Return size hint with scaled height based on node's height_scaling."""
        # Get the default size hint
        size = super().sizeHint(option, index)
        
        # Get the signal node from the model
        node = index.data(Qt.ItemDataRole.UserRole)
        if isinstance(node, TreeNode):
            # Scale the height based on height_scaling
            scaled_height = self._base_height * node.height_scaling
            size.setHeight(scaled_height)
        else:
            size.setHeight(self._base_height)
            
        return size


class BaseColumnView(QTreeView):
    """Base class for column-specific tree views."""
    
    def __init__(self, visible_column: int, allow_expansion: bool = True, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._visible_column = visible_column
        self._show_multiple_columns = False  # Can be overridden by subclasses
        self.setRootIsDecorated(True)
        self.setAlternatingRowColors(UI.TREE_ALTERNATING_ROWS)
        self.setUniformRowHeights(UI.TREE_UNIFORM_ROW_HEIGHTS)  # Changed to False to allow variable row heights
        self.setHeaderHidden(False)
        self.setItemsExpandable(allow_expansion)
        # Enable multi-selection
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        
        # Set custom delegate for height scaling
        self._delegate = ScaledHeightDelegate(base_height=RENDERING.DEFAULT_ROW_HEIGHT, parent=self)
        self.setItemDelegate(self._delegate)
        
    def setModel(self, model: Optional[QAbstractItemModel]) -> None:
        super().setModel(model)
        # Hide columns based on configuration
        if model:
            for col in range(model.columnCount()):
                if hasattr(self, '_show_multiple_columns') and self._show_multiple_columns:
                    # For SignalValuesView, show columns 1 and 2
                    should_hide = col not in [1, 2]
                else:
                    # For other views, show only the specified column
                    should_hide = col != self._visible_column
                self.setColumnHidden(col, should_hide)
                    
    def expandAll(self) -> None:
        # Override in subclasses that don't allow expansion
        if not self.itemsExpandable():
            pass
        else:
            super().expandAll()


class SignalNamesView(BaseColumnView):
    """Tree view for signal names (column 0)."""
    
    # Constants
    SIGNAL_NODE_MIME_TYPE = "application/x-wavescout-signalnodes"
    
    # Signals
    navigate_to_scope_requested = Signal(str, str)  # Emits (scope_path, signal_name)
    
    def __init__(self, controller: 'WaveformController', parent: Optional[QWidget] = None) -> None:
        super().__init__(visible_column=0, allow_expansion=True, parent=parent)
        self._controller = controller
        
        # Enable context menu
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        
        # Enable drag and drop
        if UI.DRAG_DROP_ENABLED:
            self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            self.setDefaultDropAction(Qt.DropAction.MoveAction)
            self.setDragDropOverwriteMode(False)
            self.setDropIndicatorShown(True)
            self.setDragEnabled(True)

    def _get_selected_signal_nodes(self) -> List[SignalNode]:
        """Return a list of selected SignalNode items (excluding groups)."""
        nodes: List[SignalNode] = []
        sel_model = self.selectionModel()
        if not sel_model:
            return nodes
        for idx in sel_model.selectedRows(0):
            n = self.model().data(idx, Qt.ItemDataRole.UserRole)
            if isinstance(n, SignalNode):
                nodes.append(n)
        return nodes

    def _get_all_selected_nodes(self) -> List[TreeNode]:
        """Return a list of all selected SignalNode items (including groups)."""
        nodes: List[TreeNode] = []
        sel_model = self.selectionModel()
        if not sel_model:
            return nodes
        for idx in sel_model.selectedRows(0):
            n = self.model().data(idx, Qt.ItemDataRole.UserRole)
            if isinstance(n, TreeNode):
                nodes.append(n)
        return nodes

    def _apply_to_selected_signals(self, apply_fn: Callable[[TreeNode], None], predicate: Optional[Callable[[TreeNode], bool]] = None) -> None:
        """Apply a function to all selected signal nodes.
        - apply_fn: callable taking a SignalNode
        - predicate: optional callable taking a SignalNode and returning bool
        """
        for n in self._get_selected_signal_nodes():
            if predicate is None or predicate(n):
                apply_fn(n)

    def _show_context_menu(self, position: QPoint) -> None:
        """Show context menu at the given position."""
        # Get the index at the position
        index = self.indexAt(position)
        if not index.isValid():
            return
            
        # Get the signal node
        node = self.model().data(index, Qt.ItemDataRole.UserRole)
        if not isinstance(node, TreeNode):
            return
            
        # Create context menu
        menu = QMenu(self)
        
        # Add "Create Group" action for both groups and signals
        # This allows users to create nested groups
        if self._get_all_selected_nodes():  # If any nodes are selected
            create_group_action = QAction("Create Group", self)
            create_group_action.triggered.connect(self._create_group_from_selected)
            menu.addAction(create_group_action)
            menu.addSeparator()
        
        # For groups, show rename and save as snippet actions
        if isinstance(node, GroupNode):
            # Render Mode submenu for groups
            render_mode_menu = menu.addMenu("Render Mode")

            # Determine if group contains subgroups (disable overlapped for nested groups)
            has_subgroups = any(isinstance(child, GroupNode) for child in node.children)

            # Action group for exclusivity
            render_mode_group = QActionGroup(self)
            render_mode_group.setExclusive(True)

            # Separate Rows (default)
            separate_action = QAction("Separate Rows", self)
            separate_action.setCheckable(True)
            separate_action.setChecked(node.group_render_mode in (None, GroupRenderMode.SEPARATE_ROWS))
            separate_action.triggered.connect(lambda: self._controller.set_group_render_mode(node.instance_id, GroupRenderMode.SEPARATE_ROWS))
            render_mode_group.addAction(separate_action)
            render_mode_menu.addAction(separate_action)

            # Overlapped
            overlapped_action = QAction("Overlapped", self)
            overlapped_action.setCheckable(True)
            overlapped_action.setChecked(node.group_render_mode == GroupRenderMode.OVERLAPPED)
            overlapped_action.setEnabled(not has_subgroups)
            overlapped_action.triggered.connect(lambda: self._controller.set_group_render_mode(node.instance_id, GroupRenderMode.OVERLAPPED))
            render_mode_group.addAction(overlapped_action)
            render_mode_menu.addAction(overlapped_action)

            # Separator after render mode
            menu.addSeparator()

            # Rename action
            rename_action = QAction("Rename", self)
            rename_action.triggered.connect(self._rename_selected_signal)
            menu.addAction(rename_action)
            
            menu.addSeparator()
            
            # Add "Save as Snippet" action
            save_snippet_action = QAction("Save as Snippet", self)
            save_snippet_action.triggered.connect(lambda: self._save_as_snippet(node))
            menu.addAction(save_snippet_action)
            
            # Show the menu at the cursor position
            menu.exec(self.viewport().mapToGlobal(position))
            return

        # For signals, show all options
        # At this point we know node is a signal (groups returned above)
        assert isinstance(node, SignalNode)
        # Add data format submenu
        format_menu = menu.addMenu("Data Format")
        
        # Create action group for data format options (only one can be selected)
        format_group = QActionGroup(self)
        format_group.setExclusive(True)
        
        # Define data format options
        format_options = [
            ("Unsigned", DataFormat.UNSIGNED),
            ("Signed", DataFormat.SIGNED),
            ("Hex", DataFormat.HEX),
            ("Binary", DataFormat.BIN),
            ("Float32", DataFormat.FLOAT)
        ]
        
        # Create actions for each data format option
        for display_name, format_value in format_options:
            action = QAction(display_name, self)
            action.setCheckable(True)
            action.setChecked(node.format.data_format == format_value)
            action.setData(format_value)
            action.triggered.connect(lambda checked, f=format_value: self._apply_to_selected_signals(lambda n: self._set_data_format(n, f)))
            format_group.addAction(action)
            format_menu.addAction(action)
        
        # Add color selection action
        color_action = QAction("Set Color...", self)
        color_action.triggered.connect(self._set_signal_color)
        menu.addAction(color_action)
        menu.addSeparator()
        
        # Add render type submenu for multi-bit signals
        if node.is_multi_bit:
            render_menu = menu.addMenu("Set Render Type")
            
            # Create action group for render type options
            render_group = QActionGroup(self)
            render_group.setExclusive(True)
            
            # Bus option
            bus_action = QAction("Bus", self)
            bus_action.setCheckable(True)
            bus_action.setChecked(node.format.render_type == RenderType.BUS)
            bus_action.triggered.connect(lambda: self._apply_to_selected_signals(
                lambda n: self._set_render_type(n, RenderType.BUS), 
                predicate=lambda n: getattr(n, 'is_multi_bit', False)
            ))
            render_group.addAction(bus_action)
            render_menu.addAction(bus_action)
            
            # Analog Scale All option
            analog_all_action = QAction("Analog Scale All", self)
            analog_all_action.setCheckable(True)
            analog_all_action.setChecked(
                node.format.render_type == RenderType.ANALOG and 
                node.format.analog_scaling_mode == AnalogScalingMode.SCALE_TO_ALL_DATA
            )
            analog_all_action.triggered.connect(lambda: self._apply_to_selected_signals(
                lambda n: self._set_render_type_with_scaling(n, RenderType.ANALOG, AnalogScalingMode.SCALE_TO_ALL_DATA),
                predicate=lambda n: getattr(n, 'is_multi_bit', False)
            ))
            render_group.addAction(analog_all_action)
            render_menu.addAction(analog_all_action)
            
            # Analog Scale Visible option
            analog_visible_action = QAction("Analog Scale Visible", self)
            analog_visible_action.setCheckable(True)
            analog_visible_action.setChecked(
                node.format.render_type == RenderType.ANALOG and 
                node.format.analog_scaling_mode == AnalogScalingMode.SCALE_TO_VISIBLE_DATA
            )
            analog_visible_action.triggered.connect(lambda: self._apply_to_selected_signals(
                lambda n: self._set_render_type_with_scaling(n, RenderType.ANALOG, AnalogScalingMode.SCALE_TO_VISIBLE_DATA),
                predicate=lambda n: getattr(n, 'is_multi_bit', False)
            ))
            render_group.addAction(analog_visible_action)
            render_menu.addAction(analog_visible_action)
        
        # Add separator before rename action
        menu.addSeparator()
        
        # Add rename action
        rename_action = QAction("Rename", self)
        rename_action.triggered.connect(self._rename_selected_signal)
        menu.addAction(rename_action)
        
        # Add separator before navigation action
        menu.addSeparator()
        
        # Add navigate to scope action (only for signals, not groups)
        if isinstance(node, SignalNode):
            navigate_action = QAction("Navigate to scope", self)
            navigate_action.triggered.connect(self._navigate_to_scope)
            menu.addAction(navigate_action)

            # Add clock signal options if this is a valid clock signal
            if self._controller.session and self._controller.session.waveform_db:
                db = self._controller.session.waveform_db
                if node.handle is not None:
                    if is_valid_clock_signal(node.var):
                        menu.addSeparator()
                        
                        # Check if this signal is already the clock
                        if self._controller.is_clock_signal(node):
                            clear_clock_action = QAction("Clear Clock", self)
                            clear_clock_action.triggered.connect(self._controller.clear_clock_signal)
                            menu.addAction(clear_clock_action)
                        else:
                            set_clock_action = QAction("Set as Clock", self)
                            set_clock_action.triggered.connect(lambda: self._controller.set_clock_signal(node))
                            menu.addAction(set_clock_action)
                    
                    # Add sampling signal options
                    menu.addSeparator()
                    # Get the WVar for this node to check if it's a valid signal
                    if is_valid_clock_signal(node.var):
                        if self._controller.is_sampling_signal(node):
                            clear_sampling_action = QAction("Clear Sampling Signal", self)
                            clear_sampling_action.triggered.connect(self._controller.clear_sampling_signal)
                            menu.addAction(clear_sampling_action)
                        else:
                            set_sampling_action = QAction("Set as Sampling Signal", self)
                            set_sampling_action.triggered.connect(lambda: self._controller.set_sampling_signal(node))
                            menu.addAction(set_sampling_action)
        
        # Add analysis option
        menu.addSeparator()
        analyze_action = QAction("Analyze...", self)
        analyze_action.triggered.connect(self._trigger_analysis)
        analyze_action.setShortcut(QKeySequence("A"))
        menu.addAction(analyze_action)
        
        # Add height scaling submenu
        height_menu = menu.addMenu("Set Height Scaling")
        
        # Create action group for height options (only one can be selected)
        height_group = QActionGroup(self)
        height_group.setExclusive(True)
        
        # Define height scaling options
        height_options = [1, 2, 3, 4, 8]
        
        # Create actions for each height option
        for height_value in height_options:
            action = QAction(f"{height_value}x", self)
            action.setCheckable(True)
            action.setChecked(node.height_scaling == height_value)
            action.setData(height_value)
            action.triggered.connect(lambda checked, h=height_value: self._apply_to_selected_signals(lambda n: self._set_height_scaling(n, h)))
            height_group.addAction(action)
            height_menu.addAction(action)
        
        # Show the menu at the cursor position
        menu.exec(self.viewport().mapToGlobal(position))
        
    def _set_data_format(self, node: TreeNode, data_format: DataFormat) -> None:
        """Set the data format for the given signal node."""
        self._controller.set_node_format(node.instance_id, data_format=data_format)
    
    def _set_signal_color(self) -> None:
        """Open color dialog and apply selected color to all selected signals."""
        # Get first selected signal's current color
        selected = self._get_selected_signal_nodes()
        if not selected:
            return
        
        current_color = QColor(selected[0].format.color)
        
        # Open color dialog
        new_color = QColorDialog.getColor(
            current_color, 
            self, 
            "Select Signal Color"
        )
        
        if new_color.isValid():
            # Apply to all selected signals
            color_str = new_color.name()  # Returns hex format "#RRGGBB"
            for node in selected:
                self._controller.set_node_format(
                    node.instance_id,
                    color=color_str
                )
                    
    def _set_height_scaling(self, node: TreeNode, height_scaling: int) -> None:
        """Set the height scaling for the given signal node."""
        self._controller.set_node_format(node.instance_id, height_scaling=height_scaling)
                    
    def _set_render_type(self, node: TreeNode, render_type: RenderType) -> None:
        """Set the render type for the given signal node."""
        self._controller.set_node_format(node.instance_id, render_type=render_type)
                    
    def _set_render_type_with_scaling(self, node: TreeNode, render_type: RenderType, scaling_mode: AnalogScalingMode) -> None:
        """Set both render type and analog scaling mode for the given signal node.
        Additionally, when switching into Analog mode via this context action,
        set the row height scaling to 3 by default for better analog visibility.
        This auto-adjustment happens only when transitioning from a non-Analog
        render type to Analog; users can still change height scaling later.
        """
        # Check if we're transitioning into Analog from a different mode
        # We must check BEFORE calling set_node_format since it updates the node
        old_render_type = node.format.render_type  # type: ignore[attr-defined]
        entering_analog = (render_type == RenderType.ANALOG and old_render_type != RenderType.ANALOG)
        
        # Use controller to set render type and analog scaling mode
        self._controller.set_node_format(
            node.instance_id, 
            render_type=render_type,
            analog_scaling_mode=scaling_mode
        )
        
        # If entering analog mode and height is still 1, set it to 3
        if entering_analog and node.height_scaling == 1:
            self._controller.set_node_format(node.instance_id, height_scaling=3)
                    
    def _find_node_index(self, target_node: TreeNode, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        """Find the model index for the given node."""
        model = self.model()
        if not model:
            return QModelIndex()
            
        for row in range(model.rowCount(parent)):
            index = model.index(row, 0, parent)
            node = model.data(index, Qt.ItemDataRole.UserRole)
            
            if node == target_node:
                return index
                
            # Recursively search children
            if model.hasChildren(index):
                child_index = self._find_node_index(target_node, index)
                if child_index.isValid():
                    return child_index
                    
        return QModelIndex()
    
    def _navigate_to_scope(self) -> None:
        """Navigate to the parent scope of the selected signal."""
        # Get all selected nodes
        nodes = self._get_all_selected_nodes()
        if not nodes:
            return
        
        # Take the first selected node (skip groups)
        node = None
        for n in nodes:
            if not n.is_group:
                node = n
                break
        
        if not node:
            return
        
        # Extract scope path from signal path
        scope_path = self._extract_scope_path(node.name)
        if scope_path:
            # Emit signal to request navigation with both scope and full signal name
            self.navigate_to_scope_requested.emit(scope_path, node.name)
    
    def _extract_scope_path(self, signal_path: str) -> str:
        """Extract parent scope from signal path.
        
        Examples:
            'top.cpu.alu.result' -> 'top.cpu.alu'
            'signal' -> '' (no scope)
        """
        parts = signal_path.split('.')
        if len(parts) <= 1:
            return ''  # Top-level signal has no parent scope
        return '.'.join(parts[:-1])
    
    def _trigger_analysis(self) -> None:
        """Open the signal analysis window for selected signals."""
        # Get selected non-group signals
        selected_signals = self._get_selected_signal_nodes()
        if not selected_signals:
            return
        
        # Import here to avoid circular dependencies
        from .signal_analysis_window import SignalAnalysisWindow
        
        # Create and show the analysis window
        window = SignalAnalysisWindow(
            controller=self._controller,
            selected_signals=selected_signals,  # type: ignore[arg-type]
            parent=self
        )
        window.exec()
    
    def _rename_selected_signal(self) -> None:
        """Rename the first selected signal or group with a user-defined nickname."""
        # Get all selected nodes (including groups)
        nodes = self._get_all_selected_nodes()
        if not nodes:
            return
        
        # Take the first selected node
        node = nodes[0]
        
        # Prepare dialog
        current_nickname = node.nickname if node.nickname else ""
        signal_name = node.name
        
        # Show input dialog
        new_nickname, ok = QInputDialog.getText(
            self,
            "Rename Signal",
            f"Enter nickname for '{signal_name}':",
            text=current_nickname
        )
        
        if ok:
            self._controller.rename_node(node.instance_id, new_nickname if new_nickname else "")
    
    def _create_group_from_selected(self) -> None:
        """Create a new group containing the selected nodes."""
        selected_nodes = self._get_all_selected_nodes()
        if not selected_nodes:
            return
        
        # Get group name from user
        group_name, ok = QInputDialog.getText(
            self,
            "Create Group",
            "Enter name for the new group:",
            text=""
        )
        
        # If user cancelled, don't create the group
        if not ok:
            return
        
        # Create the group using controller's high-level method
        # Pass None for empty string to trigger default naming
        self._controller.create_group_from_nodes(
            selected_nodes,
            group_name if group_name else None,
            GroupRenderMode.SEPARATE_ROWS
        )
    
    def _save_as_snippet(self, group_node: TreeNode) -> None:
        """Save a group as a reusable snippet."""
        if not isinstance(group_node, GroupNode):
            QMessageBox.warning(self, "Invalid Selection", "Only groups can be saved as snippets.")
            return

        # Find common parent scope
        snippet_manager = SnippetManager()
        parent_scope = snippet_manager.find_common_parent(group_node)

        # Show save dialog
        dialog = SaveSnippetDialog(group_node, parent_scope, self)
        if dialog.exec() == SaveSnippetDialog.DialogCode.Accepted:
            QMessageBox.information(self, "Snippet Saved", f"Snippet saved successfully.")
    
    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle key press events."""
        # Check for Ctrl+C (Copy)
        if event.key() == Qt.Key.Key_C and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self._copy_selected_nodes()
            event.accept()
        # Check for Ctrl+V (Paste)
        elif event.key() == Qt.Key.Key_V and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self._paste_nodes()
            event.accept()
        # Check for 'R' or 'r' key
        elif event.key() == Qt.Key.Key_R and not event.modifiers():
            # Trigger rename for selected signal
            self._rename_selected_signal()
            event.accept()
        # Check for 'A' or 'a' key
        elif event.key() == Qt.Key.Key_A and not event.modifiers():
            # Trigger analysis for selected signals
            self._trigger_analysis()
            event.accept()
        else:
            # Pass to parent for default handling
            super().keyPressEvent(event)
    
    def _copy_selected_nodes(self) -> None:
        """Copy selected nodes to clipboard in both internal and plain text formats."""
        from wavescout.timing_utils import tprint
        nodes = self._get_all_selected_nodes()
        if not nodes:
            tprint("[COPY] No nodes selected")
            return

        tprint(f"[COPY] Copying {len(nodes)} nodes")

        # Serialize nodes for internal format
        json_str = self._serialize_nodes(nodes)
        tprint(f"[COPY] Serialized to {len(json_str)} bytes")

        # Create plain text format
        plain_text = self._nodes_to_plain_text(nodes)

        # Set both formats on clipboard
        mime_data = QMimeData()
        mime_data.setData(self.SIGNAL_NODE_MIME_TYPE, json_str.encode('utf-8'))
        mime_data.setText(plain_text)

        clipboard = QApplication.clipboard()
        clipboard.setMimeData(mime_data)
        tprint("[COPY] Data set on clipboard")

        # Show status message
        count = len(nodes)
        self._controller.event_bus.publish(
            type('StatusMessage', (), {'message': f"Copied {count} signal{'s' if count != 1 else ''}"})()
        )
    
    def _paste_nodes(self) -> None:
        """Paste nodes from clipboard at the insertion point."""
        from wavescout.timing_utils import tprint
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()

        # Check if clipboard has any data
        if not mime_data:
            tprint("[PASTE] No clipboard data")
            return

        # Check for internal format first
        if mime_data.hasFormat(self.SIGNAL_NODE_MIME_TYPE):
            data = mime_data.data(self.SIGNAL_NODE_MIME_TYPE).data()
            try:
                # Ensure we have bytes for decoding
                if isinstance(data, bytes):
                    json_str = data.decode('utf-8')
                else:
                    json_str = bytes(data).decode('utf-8')

                tprint(f"[PASTE] Deserializing {len(json_str)} bytes")
                nodes = self._deserialize_nodes(json_str)
                tprint(f"[PASTE] Deserialized {len(nodes)} nodes")

                if nodes:
                    # Validate nodes against current WaveformDB
                    validated_nodes = self._validate_nodes(nodes)
                    tprint(f"[PASTE] Validated {len(validated_nodes)} nodes")

                    if validated_nodes:
                        # Get insertion point from current selection
                        selected = self._get_all_selected_nodes()
                        after_id = selected[0].instance_id if selected else None
                        tprint(f"[PASTE] Inserting after node ID: {after_id}")

                        # Insert nodes using controller
                        self._controller.insert_nodes(validated_nodes, after_id)

                        # Show status message
                        count = len(validated_nodes)
                        self._controller.event_bus.publish(
                            type('StatusMessage', (), {'message': f"Pasted {count} signal{'s' if count != 1 else ''}"})()
                        )

                        # Scroll to first pasted node if possible
                        if validated_nodes and self.model():
                            first_node = validated_nodes[0]
                            index = self._find_node_index(first_node)
                            if index.isValid():
                                self.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
                    else:
                        tprint("[PASTE] No nodes passed validation")
                else:
                    tprint("[PASTE] No nodes deserialized")
            except Exception as e:
                tprint(f"[PASTE] Error: {e}")
                import traceback
                traceback.print_exc()
        else:
            tprint("[PASTE] No internal format in clipboard")
    
    def _serialize_nodes(self, nodes: List[TreeNode]) -> str:
        """Serialize a list of SignalNode objects to JSON string."""
        data = {
            'version': 1,
            'nodes': [_serialize_node(node) for node in nodes]
        }
        return json.dumps(data)
    
    def _deserialize_nodes(self, json_str: str) -> List[TreeNode]:
        """Deserialize JSON string to a list of SignalNode objects with new instance IDs."""
        try:
            data = json.loads(json_str)
            if not isinstance(data, dict) or 'nodes' not in data:
                return []

            # Get waveform_db if available for proper deserialization
            waveform_db = None
            if self._controller.session and self._controller.session.waveform_db:
                waveform_db = self._controller.session.waveform_db

            nodes = []
            for node_data in data.get('nodes', []):
                # Deserialize the node with waveform_db for proper var population
                node = _deserialize_node(node_data, waveform_db=waveform_db, parent=None)
                # Create a deep copy to ensure new instance IDs
                node_copy = node.deep_copy()
                nodes.append(node_copy)

            return nodes
        except Exception:
            return []
    
    def _nodes_to_plain_text(self, nodes: List[TreeNode]) -> str:
        """Convert nodes to plain text format for external paste."""
        lines = []
        
        def add_node(node: TreeNode, indent: int = 0) -> None:
            # Use nickname if available, otherwise name
            name = node.nickname if node.nickname else node.name
            lines.append('  ' * indent + name)
            
            # Add children for groups
            if isinstance(node, GroupNode) and node.children:
                for child in node.children:
                    add_node(child, indent + 1)
        
        for node in nodes:
            add_node(node)
        
        return '\n'.join(lines)
    
    def _validate_nodes(self, nodes: List[TreeNode]) -> List[TreeNode]:
        """Validate nodes against current WaveformDB, filtering out invalid handles."""
        if not self._controller.session or not self._controller.session.waveform_db:
            # If no waveform loaded, keep groups but remove signals
            validated: List[TreeNode] = []
            for node in nodes:
                if isinstance(node, GroupNode):
                    # Keep group but validate its children
                    node.children = self._validate_nodes(node.children)
                    validated.append(node)
            return validated

        db = self._controller.session.waveform_db
        validated2: List[TreeNode] = []

        for node in nodes:
            if isinstance(node, GroupNode):
                # Always keep groups, but validate their children
                node.children = self._validate_nodes(node.children)
                validated2.append(node)
            elif isinstance(node, SignalNode) and node.handle is not None:
                # Check if handle exists in current DB and populate var
                try:
                    var = db.get_var(node.handle)
                    if var:
                        # Populate the var field which may be None after deserialization
                        node.var = var
                        # Create or update AsyncLoadedSignal for the handle
                        node.signal = db.load_signal(node.handle)
                        validated2.append(node)
                except Exception:
                    # Skip nodes with invalid handles
                    pass

        return validated2