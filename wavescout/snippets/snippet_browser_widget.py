"""
Widget for browsing and managing signal snippets in the right sidebar.
"""

from typing import Optional, Any, Union

from PySide6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, Signal, QPoint, QPersistentModelIndex
)
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableView, QLabel,
    QPushButton, QMenu, QMessageBox, QHeaderView, QInputDialog
)

from wavescout.snippets.snippet_manager import Snippet, SnippetManager


class SnippetTableModel(QAbstractTableModel):
    """Table model for displaying snippets."""
    
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.snippet_manager = SnippetManager()
        self.snippets: list[Snippet] = []
        self._refresh_snippets()
        
        # Connect to manager signals
        self.snippet_manager.snippets_changed.connect(self._refresh_snippets)
    
    def _refresh_snippets(self) -> None:
        """Refresh snippet list from manager."""
        self.beginResetModel()
        # Force reload from disk to ensure we have the latest snippets
        # This is important after a new snippet is saved
        self.snippet_manager.load_snippets()
        self.snippets = self.snippet_manager.get_all_snippets()
        # Sort by creation date (newest first)
        self.snippets.sort(key=lambda s: s.created_at, reverse=True)
        self.endResetModel()
    
    def rowCount(self, parent: Union[QModelIndex, QPersistentModelIndex] = QModelIndex()) -> int:
        """Return number of snippets."""
        return len(self.snippets) if not parent.isValid() else 0
    
    def columnCount(self, parent: Union[QModelIndex, QPersistentModelIndex] = QModelIndex()) -> int:
        """Return number of columns."""
        return 4 if not parent.isValid() else 0
    
    def data(self, index: Union[QModelIndex, QPersistentModelIndex], role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Return data for given index and role."""
        if not index.isValid() or index.row() >= len(self.snippets):
            return None
        
        snippet = self.snippets[index.row()]
        column = index.column()
        
        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return snippet.name
            elif column == 1:
                # Shorten parent name if too long
                parent = snippet.parent_name
                if len(parent) > 30:
                    parts = parent.split('.')
                    if len(parts) > 2:
                        return f"{parts[0]}...{parts[-1]}"
                return parent
            elif column == 2:
                return str(snippet.num_nodes)
            elif column == 3:
                return snippet.created_at.strftime("%Y-%m-%d")
        
        elif role == Qt.ItemDataRole.ToolTipRole:
            if column == 0:
                if snippet.description:
                    return f"{snippet.name}\n\n{snippet.description}"
                return snippet.name
            elif column == 1:
                return snippet.parent_name  # Full parent name in tooltip
            elif column == 3:
                return snippet.created_at.strftime("%Y-%m-%d %H:%M:%S")
        
        elif role == Qt.ItemDataRole.UserRole:
            return snippet
        
        return None
    
    def headerData(self, section: int, orientation: Qt.Orientation, 
                   role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Return header data."""
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            headers = ["Name", "Parent Scope", "Signals", "Created"]
            if 0 <= section < len(headers):
                return headers[section]
        return None
    
    def flags(self, index: Union[QModelIndex, QPersistentModelIndex]) -> Qt.ItemFlag:
        """Return item flags."""
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        
        # Only enabled and selectable by default (not editable)
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        
        return flags
    
    def setData(self, index: Union[QModelIndex, QPersistentModelIndex], value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        """Handle data changes - currently not used as renaming is done via dialog."""
        # This method is required by QAbstractTableModel but we don't use inline editing
        return False


class SnippetBrowserWidget(QWidget):
    """Widget for browsing and managing snippets."""
    
    # Signals
    snippet_instantiate = Signal(Snippet)
    
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.snippet_manager = SnippetManager()
        self._setup_ui()
        self._setup_connections()
    
    def _setup_ui(self) -> None:
        """Setup the widget UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Header
        header_layout = QHBoxLayout()
        header_label = QLabel("Signal Snippets")
        header_label.setStyleSheet("QLabel { font-weight: bold; }")
        header_layout.addWidget(header_label)
        header_layout.addStretch()
        
        # Refresh button
        self.refresh_button = QPushButton("↻")
        self.refresh_button.setMaximumWidth(30)
        self.refresh_button.setToolTip("Refresh snippets")
        header_layout.addWidget(self.refresh_button)
        
        layout.addLayout(header_layout)
        
        # Table view
        self.table_view = QTableView()
        self.model = SnippetTableModel(self)
        self.table_view.setModel(self.model)
        
        # Configure table
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table_view.setSortingEnabled(True)
        self.table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        
        # Adjust column widths - all columns resizable
        header = self.table_view.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)  # Name
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)  # Parent Scope
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)  # Signals
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)  # Created
        header.setStretchLastSection(True)  # Last column fills remaining space
        
        layout.addWidget(self.table_view)
        
        # Info label for empty state
        self.empty_label = QLabel("No snippets saved.\n\nRight-click on a signal group\nand select 'Save as Snippet'\nto create your first snippet.")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("QLabel { color: gray; }")
        self.empty_label.setVisible(len(self.model.snippets) == 0)
        layout.addWidget(self.empty_label)
    
    def _setup_connections(self) -> None:
        """Setup signal connections."""
        self.table_view.doubleClicked.connect(self._on_double_click)
        self.table_view.customContextMenuRequested.connect(self._show_context_menu)
        self.refresh_button.clicked.connect(self._refresh_snippets)
        self.model.modelReset.connect(self._on_model_reset)
    
    def _on_model_reset(self) -> None:
        """Handle model reset to update empty state."""
        has_snippets = self.model.rowCount() > 0
        self.table_view.setVisible(has_snippets)
        self.empty_label.setVisible(not has_snippets)
    
    def _refresh_snippets(self) -> None:
        """Refresh snippet list from disk."""
        # Force reload from disk to ensure we have latest snippets
        self.snippet_manager.load_snippets()
        # Now refresh the model
        self.model._refresh_snippets()
    
    def _on_double_click(self, index: QModelIndex) -> None:
        """Handle double-click to instantiate snippet."""
        if not index.isValid():
            return
        
        snippet = self.model.data(index, Qt.ItemDataRole.UserRole)
        if snippet:
            self.snippet_instantiate.emit(snippet)
    
    def _show_context_menu(self, position: QPoint) -> None:
        """Show context menu for snippet operations."""
        index = self.table_view.indexAt(position)
        if not index.isValid():
            return
        
        snippet = self.model.data(index, Qt.ItemDataRole.UserRole)
        if not snippet:
            return
        
        menu = QMenu(self)
        
        # Instantiate action
        instantiate_action = QAction("Instantiate", self)
        instantiate_action.triggered.connect(lambda: self.snippet_instantiate.emit(snippet))
        menu.addAction(instantiate_action)
        
        menu.addSeparator()
        
        # Rename action
        rename_action = QAction("Rename", self)
        rename_action.triggered.connect(lambda: self._rename_snippet(index))
        menu.addAction(rename_action)
        
        # Delete action
        delete_action = QAction("Delete", self)
        delete_action.triggered.connect(lambda: self._delete_snippet(snippet))
        menu.addAction(delete_action)
        
        # Show menu
        menu.exec(self.table_view.mapToGlobal(position))
    
    def _rename_snippet(self, index: QModelIndex) -> None:
        """Rename snippet using a dialog."""
        if not index.isValid():
            return
        
        snippet = self.model.data(index, Qt.ItemDataRole.UserRole)
        if not snippet:
            return
        
        # Show rename dialog
        new_name, ok = QInputDialog.getText(
            self,
            "Rename Snippet",
            f"Enter new name for '{snippet.name}':",
            text=snippet.name
        )
        
        if ok and new_name:
            new_name = new_name.strip()
            
            # Validate new name
            if not new_name:
                QMessageBox.warning(
                    self, "Invalid Name",
                    "Snippet name cannot be empty."
                )
                return
            
            if new_name == snippet.name:
                return  # No change
            
            if self.snippet_manager.snippet_exists(new_name):
                QMessageBox.warning(
                    self, "Name Already Exists",
                    f"A snippet named '{new_name}' already exists."
                )
                return
            
            # Perform rename
            if self.snippet_manager.rename_snippet(snippet.name, new_name):
                self.model._refresh_snippets()
            else:
                QMessageBox.critical(
                    self, "Rename Failed",
                    f"Failed to rename snippet '{snippet.name}'."
                )
    
    def _delete_snippet(self, snippet: Snippet) -> None:
        """Delete a snippet after confirmation."""
        reply = QMessageBox.question(
            self, "Delete Snippet",
            f"Are you sure you want to delete the snippet '{snippet.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            if self.snippet_manager.delete_snippet(snippet.name):
                self.model._refresh_snippets()
            else:
                QMessageBox.critical(
                    self, "Delete Failed",
                    f"Failed to delete snippet '{snippet.name}'."
                )