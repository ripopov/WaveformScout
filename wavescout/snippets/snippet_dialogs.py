"""
Dialogs for snippet save and instantiation operations.
"""

from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout,
    QLineEdit, QTextEdit, QLabel, QDialogButtonBox, QMessageBox, QWidget
)

from wavescout.core.data_model import TreeNode, GroupNode, SignalNode
from wavescout.snippets.snippet_manager import Snippet, SnippetManager
from wavescout.core.waveform_db import WaveformDB


class SaveSnippetDialog(QDialog):
    """Dialog for saving a signal group as a snippet."""
    
    def __init__(self, group_node: GroupNode, parent_scope: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.group_node = group_node
        self.parent_scope = parent_scope
        self.snippet_manager = SnippetManager()
        
        self.setWindowTitle("Save as Snippet")
        self.setModal(True)
        self.setMinimumWidth(400)
        
        self._setup_ui()
        self._setup_connections()
    
    def _setup_ui(self) -> None:
        """Setup the dialog UI."""
        layout = QVBoxLayout(self)
        
        # Form layout for fields
        form_layout = QFormLayout()
        
        # Name field
        self.name_edit = QLineEdit(self.group_node.name)
        self.name_edit.selectAll()
        form_layout.addRow("Snippet Name:", self.name_edit)
        
        # Parent scope (read-only)
        self.parent_label = QLabel(self.parent_scope)
        form_layout.addRow("Parent Scope:", self.parent_label)
        
        # Node count (read-only)
        node_count = self._count_nodes(self.group_node)
        self.count_label = QLabel(str(node_count))
        form_layout.addRow("Signal Count:", self.count_label)
        
        # Description field
        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText("Optional description...")
        self.description_edit.setMaximumHeight(80)
        form_layout.addRow("Description:", self.description_edit)
        
        layout.addLayout(form_layout)
        
        # Buttons
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | 
            QDialogButtonBox.StandardButton.Cancel
        )
        layout.addWidget(self.button_box)
    
    def _setup_connections(self) -> None:
        """Setup signal connections."""
        self.button_box.accepted.connect(self._on_save)
        self.button_box.rejected.connect(self.reject)
        self.name_edit.textChanged.connect(self._validate_name)
    
    def _count_nodes(self, node: TreeNode) -> int:
        """Count total nodes in tree."""
        if isinstance(node, GroupNode):
            count = 0  # Groups don't count
            for child in node.children:
                count += self._count_nodes(child)
            return count
        else:
            return 1  # Signals count
    
    def _validate_name(self, text: str) -> None:
        """Validate snippet name."""
        save_button = self.button_box.button(QDialogButtonBox.StandardButton.Save)
        
        if not text:
            save_button.setEnabled(False)
            return
        
        # Check for invalid characters
        invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
        if any(char in text for char in invalid_chars):
            save_button.setEnabled(False)
            self.name_edit.setStyleSheet("QLineEdit { color: red; }")
            return
        
        # Check if name already exists
        if self.snippet_manager.snippet_exists(text):
            save_button.setEnabled(False)
            self.name_edit.setStyleSheet("QLineEdit { color: orange; }")
            self.name_edit.setToolTip("A snippet with this name already exists")
        else:
            save_button.setEnabled(True)
            self.name_edit.setStyleSheet("")
            self.name_edit.setToolTip("")
    
    def _on_save(self) -> None:
        """Handle save button click."""
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Invalid Name", "Please enter a snippet name.")
            return
        
        # Create snippet
        snippet = Snippet(
            name=name,
            parent_name=self.parent_scope,
            num_nodes=self._count_nodes(self.group_node),
            nodes=self.group_node.children,  # Save children, not the group itself
            description=self.description_edit.toPlainText()
        )
        
        # Save snippet
        if self.snippet_manager.save_snippet(snippet):
            self.accept()
        else:
            QMessageBox.critical(self, "Save Failed", "Failed to save snippet.")


class InstantiateSnippetDialog(QDialog):
    """Dialog for instantiating a snippet with scope remapping."""
    
    @staticmethod
    def validate_and_resolve_nodes(nodes: list[TreeNode],
                                   waveform_db: WaveformDB) -> tuple[list[TreeNode], list[int]]:
        """Validate signal nodes exist and resolve their handles.

        This extracts the validation logic from _remap_and_validate's inner function.
        No remapping - uses exact signal names.

        Returns:
            Tuple of (validated nodes, handles that need async loading)
        """
        def validate_node(node: TreeNode) -> TreeNode:
            new_node = node.deep_copy()

            if isinstance(node, SignalNode):
                assert isinstance(new_node, SignalNode)  # Help type checker
                path_segments = node.path()
                handle = waveform_db.find_handle_by_path(path_segments)
                if handle is None:
                    raise ValueError(f"Signal '{node.full_name()}' not found in waveform")
                new_node.handle = handle

                # Create AsyncLoadedSignal for the handle
                new_node.signal = waveform_db.load_signal(handle)

                return new_node

            if isinstance(node, GroupNode):
                assert isinstance(new_node, GroupNode)  # Help type checker
                validated_children = [validate_node(child) for child in node.children]
                new_node.children = validated_children
                for child in validated_children:
                    child.parent = new_node
                return new_node

            return new_node

        validated_nodes = [validate_node(node) for node in nodes]

        # Collect handles that need async loading
        handles_to_load: list[int] = []

        def collect_handles(node: TreeNode) -> None:
            if isinstance(node, SignalNode) and node.handle is not None and node.handle != -1:
                if not waveform_db.is_signal_cached(node.handle):
                    handles_to_load.append(node.handle)
            elif isinstance(node, GroupNode):
                for child in node.children:
                    collect_handles(child)

        for node in validated_nodes:
            collect_handles(node)

        return validated_nodes, handles_to_load
    
    def __init__(self, snippet: Snippet, waveform_db: Optional[WaveformDB], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.snippet = snippet
        self.waveform_db = waveform_db
        self.remapped_nodes: Optional[list[TreeNode]] = None
        self.handles_to_load: list[int] = []
        self.group_name: str = snippet.name  # Default to snippet name
        
        self.setWindowTitle(f"Instantiate Snippet: {snippet.name}")
        self.setModal(True)
        self.setMinimumWidth(500)
        
        self._setup_ui()
        self._setup_connections()
        self._validate_scope()
    
    def _setup_ui(self) -> None:
        """Setup the dialog UI."""
        layout = QVBoxLayout(self)
        
        # Info section
        info_layout = QFormLayout()
        info_layout.addRow("Snippet:", QLabel(self.snippet.name))
        info_layout.addRow("Original Scope:", QLabel(self.snippet.parent_name))
        info_layout.addRow("Signal Count:", QLabel(str(self.snippet.num_nodes)))
        
        if self.snippet.description:
            desc_label = QLabel(self.snippet.description)
            desc_label.setWordWrap(True)
            info_layout.addRow("Description:", desc_label)
        
        layout.addLayout(info_layout)
        
        # Separator
        layout.addSpacing(10)
        
        # Instantiation options
        form_layout = QFormLayout()
        
        # Group name input (editable)
        self.group_name_edit = QLineEdit(self.snippet.name)
        self.group_name_edit.setToolTip("Name for the group that will contain the instantiated signals")
        form_layout.addRow("Group Name:", self.group_name_edit)
        
        # Target scope input
        self.scope_edit = QLineEdit(self.snippet.parent_name)
        self.scope_edit.selectAll()
        form_layout.addRow("Target Scope:", self.scope_edit)
        
        # Validation feedback
        self.validation_label = QLabel()
        self.validation_label.setWordWrap(True)
        form_layout.addRow("", self.validation_label)
        
        layout.addLayout(form_layout)
        
        # Preview section
        self.preview_label = QLabel("Signals to be created:")
        layout.addWidget(self.preview_label)
        
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMaximumHeight(150)
        layout.addWidget(self.preview_text)
        
        # Buttons
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | 
            QDialogButtonBox.StandardButton.Cancel
        )
        self.ok_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        layout.addWidget(self.button_box)
    
    def _setup_connections(self) -> None:
        """Setup signal connections."""
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)
        self.scope_edit.textChanged.connect(self._on_scope_changed)
        self.group_name_edit.textChanged.connect(self._on_group_name_changed)
    
    def _on_scope_changed(self) -> None:
        """Handle scope text change."""
        self._validate_scope()
    
    def _on_group_name_changed(self, text: str) -> None:
        """Handle group name change."""
        self.group_name = text.strip()
        # Validate that group name is not empty
        if not self.group_name:
            self.ok_button.setEnabled(False)
        else:
            # Re-validate scope to update OK button state
            self._validate_scope()
    
    def _on_accept(self) -> None:
        """Handle accept button - store the group name before accepting."""
        self.group_name = self.group_name_edit.text().strip()
        if not self.group_name:
            QMessageBox.warning(self, "Invalid Group Name", "Please enter a group name.")
            return
        self.accept()
    
    def _validate_scope(self) -> None:
        """Validate the target scope and preview remapped signals."""
        target_scope = self.scope_edit.text().strip()
        group_name = self.group_name_edit.text().strip()
        
        # Check group name first
        if not group_name:
            self.validation_label.setText("❌ Please enter a group name")
            self.validation_label.setStyleSheet("QLabel { color: red; }")
            self.ok_button.setEnabled(False)
            return
        
        if not self.waveform_db:
            self.validation_label.setText("⚠ No waveform loaded")
            self.validation_label.setStyleSheet("QLabel { color: orange; }")
            self.ok_button.setEnabled(False)
            return
        
        if not target_scope:
            self.validation_label.setText("❌ Please enter a target scope")
            self.validation_label.setStyleSheet("QLabel { color: red; }")
            self.ok_button.setEnabled(False)
            return
        
        # Try to remap and validate
        try:
            self.remapped_nodes, self.handles_to_load = self._remap_and_validate(target_scope)

            # Update preview
            preview_lines = []
            for node in self._get_all_signals(self.remapped_nodes):
                preview_lines.append(f"  {node.name}")

            self.preview_text.setPlainText("\n".join(preview_lines[:20]))  # Limit preview
            if len(preview_lines) > 20:
                self.preview_text.append(f"\n  ... and {len(preview_lines) - 20} more")

            self.validation_label.setText("✓ All signals found in target scope")
            self.validation_label.setStyleSheet("QLabel { color: green; }")
            self.ok_button.setEnabled(True)
            
        except Exception as e:
            self.validation_label.setText(f"❌ {str(e)}")
            self.validation_label.setStyleSheet("QLabel { color: red; }")
            self.preview_text.clear()
            self.ok_button.setEnabled(False)
            self.remapped_nodes = None

    @staticmethod
    def build_full_paths(node: TreeNode, parent_scope: str) -> TreeNode:
        """Build full paths by concatenating parent scope with relative names."""
        new_node = node.deep_copy()

        if isinstance(node, SignalNode):
            if parent_scope:
                # Update waveform scope to include parent_scope
                parent_parts = parent_scope.split('.')
                new_scope_path = tuple(parent_parts) + node.scope_path()
                object.__setattr__(new_node, '_waveform_scope', new_scope_path)
            return new_node

        if isinstance(node, GroupNode):
            assert isinstance(new_node, GroupNode)  # Help type checker
            # Note: GroupNode scope_path is computed from parent chain,
            # so we don't need to update it manually - just set children and their parents

            new_children = [InstantiateSnippetDialog.build_full_paths(child, parent_scope) for child in node.children]
            new_node.children = new_children
            for child in new_children:
                child.parent = new_node

        return new_node
    
    def _remap_and_validate(self, new_parent_scope: str) -> tuple[list[TreeNode], list[int]]:
        """Build full paths from relative names and validate they exist.

        Returns:
            Tuple of (validated nodes, handles that need async loading)
        """
        if not self.waveform_db:
            raise ValueError("No waveform database available")

        # Build full paths by concatenating parent scope with relative names
        full_path_nodes = []
        for node in self.snippet.nodes:
            full_path_nodes.append(self.build_full_paths(node, new_parent_scope))

        # Then validate and resolve handles
        validated_nodes, handles_to_load = self.validate_and_resolve_nodes(full_path_nodes, self.waveform_db)

        # NOTE: Don't call load_signals_async here - let the caller handle async loading
        # after the nodes are added to the session tree so they can be found and updated

        return validated_nodes, handles_to_load
    
    def _get_all_signals(self, nodes: list[TreeNode]) -> list[TreeNode]:
        """Get all non-group signals from node list."""
        signals: list[TreeNode] = []
        
        def collect_signals(node: TreeNode) -> None:
            if isinstance(node, SignalNode):
                signals.append(node)
            elif isinstance(node, GroupNode):
                for child in node.children:
                    collect_signals(child)
        
        for node in nodes:
            collect_signals(node)
        
        return signals
    
    def get_remapped_nodes(self) -> Optional[list[TreeNode]]:
        """Get the remapped nodes if validation succeeded."""
        return self.remapped_nodes
    
    def get_group_name(self) -> str:
        """Get the user-specified group name."""
        return self.group_name

    def get_handles_to_load(self) -> list[int]:
        """Return handles that should be loaded asynchronously after instantiation."""
        return self.handles_to_load
