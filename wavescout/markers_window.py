"""Markers management window for WaveScout."""

from typing import Optional

from PySide6.QtCore import Qt, Signal, QModelIndex, QPersistentModelIndex
from PySide6.QtGui import QColor, QKeyEvent, QCloseEvent, QPainter, QBrush
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QColorDialog, QHeaderView, QWidget,
    QStyledItemDelegate, QStyleOptionViewItem
)

from . import config
from .message_box_utils import show_warning
from .waveform_controller import WaveformController

MARKER_LABELS = config.MARKER_LABELS
RENDERING = config.RENDERING


class ColorCellDelegate(QStyledItemDelegate):
    """Custom delegate for color cells that prevents selection highlighting."""
    
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> None:
        """Paint the color cell without selection highlight."""
        # For color column, always paint the color without selection
        if index.column() == 1:  # Color column
            # Try to get color from UserRole first, then from BackgroundRole
            color_value = index.data(Qt.ItemDataRole.UserRole)
            if not color_value:
                # Try to get from background brush
                bg_brush = index.data(Qt.ItemDataRole.BackgroundRole)
                if isinstance(bg_brush, QBrush):
                    color_value = bg_brush.color().name()
            
            # Draw the color cell background, ignoring selection state
            rect = option.rect  # type: ignore[attr-defined]
            if color_value:
                painter.fillRect(rect, QColor(color_value))
            else:
                # Draw default background
                palette = option.palette  # type: ignore[attr-defined]
                painter.fillRect(rect, palette.base())
        else:
            # Use default painting for other columns
            super().paint(painter, option, index)


class MarkersWindow(QDialog):
    """Dialog window for managing waveform markers."""
    
    markers_changed = Signal()
    
    def __init__(self, controller: WaveformController, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Markers")
        self.setModal(False)  # Non-modal so user can interact with main window
        self.resize(400, 300)
        
        # Set up UI
        self._setup_ui()
        
        # Load markers
        self._load_markers()
        
        # Connect to controller events
        self.controller.on("markers_changed", self._on_markers_changed)
        
    def _setup_ui(self) -> None:
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        
        # Create table widget
        self.table = QTableWidget(RENDERING.MAX_MARKERS, 3)  # MAX_MARKERS rows, 3 columns
        self.table.setHorizontalHeaderLabels(["Marker", "Color", "Timestamp"])
        
        # Set custom delegate for color column to prevent selection highlighting
        color_delegate = ColorCellDelegate(self.table)
        self.table.setItemDelegateForColumn(1, color_delegate)
        
        # Configure table
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setDefaultSectionSize(80)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        
        # Make timestamp column editable
        self.table.itemChanged.connect(self._on_item_changed)
        
        # Connect cell click for color selection
        self.table.cellClicked.connect(self._on_cell_clicked)
        
        # Enable mouse tracking for hover effects
        self.table.setMouseTracking(True)
        self.table.cellEntered.connect(self._on_cell_entered)
        
        layout.addWidget(self.table)
        
        # Add buttons
        button_layout = QHBoxLayout()
        
        self.delete_button = QPushButton("Delete Selected")
        self.delete_button.clicked.connect(self._delete_selected)
        button_layout.addWidget(self.delete_button)
        
        button_layout.addStretch()
        
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        button_layout.addWidget(self.close_button)
        
        layout.addLayout(button_layout)
        
    def _load_markers(self) -> None:
        """Load markers from controller into table."""
        self.table.blockSignals(True)  # Prevent triggering itemChanged
        
        for i in range(RENDERING.MAX_MARKERS):
            # Marker name (read-only)
            name_item = QTableWidgetItem(MARKER_LABELS[i])
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, 0, name_item)
            
            # Get marker from controller
            marker = self.controller.get_marker(i)
            
            if marker:
                # Color cell (clickable)
                color_item = QTableWidgetItem()
                color_item.setBackground(QColor(marker.color))
                color_item.setFlags(color_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                color_item.setData(Qt.ItemDataRole.UserRole, marker.color)
                color_item.setToolTip("Click to change color")
                self.table.setItem(i, 1, color_item)
                
                # Timestamp (editable)
                time_item = QTableWidgetItem(str(marker.time))
                self.table.setItem(i, 2, time_item)
            else:
                # Empty color cell
                color_item = QTableWidgetItem()
                color_item.setFlags(color_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(i, 1, color_item)
                
                # Empty timestamp
                time_item = QTableWidgetItem("")
                time_item.setFlags(time_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(i, 2, time_item)
        
        self.table.blockSignals(False)
    
    def _on_markers_changed(self) -> None:
        """Handle markers changed event from controller."""
        self._load_markers()
    
    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        """Handle item changes in the table."""
        if item.column() == 2:  # Timestamp column
            row = item.row()
            text = item.text().strip()
            
            if text:
                try:
                    timestamp = int(text)
                    # Update or create marker
                    existing_marker = self.controller.get_marker(row)
                    if existing_marker:
                        self.controller.update_marker_time(row, timestamp)
                    else:
                        # Create new marker with default color
                        self.controller.add_marker(row, timestamp, config.COLORS.MARKER_DEFAULT_COLOR)
                except ValueError:
                    # Invalid timestamp, restore previous value
                    marker = self.controller.get_marker(row)
                    if marker:
                        item.setText(str(marker.time))
                    else:
                        item.setText("")
                    show_warning(self, "Invalid Value", "Please enter a valid integer timestamp.")
            else:
                # Empty timestamp, remove marker
                self.controller.remove_marker(row)
    
    def _delete_selected(self) -> None:
        """Delete the selected marker."""
        current_row = self.table.currentRow()
        if current_row >= 0:
            self.controller.remove_marker(current_row)
    
    def _on_cell_clicked(self, row: int, column: int) -> None:
        """Handle cell click events."""
        if column == 1:  # Color column
            marker = self.controller.get_marker(row)
            if marker:
                # Open color picker
                current_color = QColor(marker.color)
                new_color = QColorDialog.getColor(current_color, self, "Select Marker Color")
                if new_color.isValid():
                    self.controller.update_marker_color(row, new_color.name())
    
    def _on_cell_entered(self, row: int, column: int) -> None:
        """Handle cell hover events."""
        if column == 1 and self.controller.get_marker(row):  # Color column with marker
            self.table.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.table.setCursor(Qt.CursorShape.ArrowCursor)
    
    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle key press events."""
        if event.key() == Qt.Key.Key_Delete:
            self._delete_selected()
            event.accept()
        else:
            super().keyPressEvent(event)
    
    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle close event."""
        # Unsubscribe from controller events
        self.controller.off("markers_changed", self._on_markers_changed)
        super().closeEvent(event)