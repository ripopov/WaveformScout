"""PySide6 GUI for viewing GPU execution traces in JETS format.

This module provides a tree view for hierarchical GPU traces with
a details panel for viewing annotations and events.
"""

from typing import Optional, Dict, Any, List

# Global flag for debug output (set via --debug command line flag)
DEBUG_OUTPUT = False

def debug_print(*args, **kwargs):
    """Print debug output if DEBUG_OUTPUT is enabled."""
    if DEBUG_OUTPUT:
        print(*args, **kwargs)

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QTreeWidget, QTreeWidgetItem, QFileDialog,
    QLabel, QSplitter, QToolBar, QStatusBar, QListWidget, QListWidgetItem
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QBrush
import json

try:
    from .parser import TraceParser
except ImportError:
    from pyjets.parser import TraceParser


class TraceTreeWidget(QTreeWidget):
    """Tree widget for displaying hierarchical trace records."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabels(['ID', 'Name', 'Type', 'Start', 'End', 'Duration'])
        self.setColumnWidth(0, 150)  # ID
        self.setColumnWidth(1, 200)  # Name
        self.setColumnWidth(2, 150)  # Type
        self.setUniformRowHeights(True)  # Performance optimization

        # Mapping from record ID to tree item
        self.record_to_item = {}

    def set_trace_data(self, roots: List[Dict[str, Any]]):
        """Populate tree with trace data.

        Args:
            roots: List of root record nodes from parsed trace
        """
        self.clear()
        self.record_to_item.clear()
        for root in roots:
            self._add_record_item(root, None)

        # Only expand top 2 levels for performance with large traces
        self.expandToDepth(1)

    def _add_record_item(self, record: Dict[str, Any], parent: Optional[QTreeWidgetItem]):
        """Recursively add record and children to tree.

        Args:
            record: Record dictionary
            parent: Parent tree item (None for root)
        """
        item = QTreeWidgetItem()

        # Set text for columns: ID, Name, Type, Start, End, Duration
        item.setText(0, record.get('id', 'N/A'))
        item.setText(1, record.get('name', 'N/A'))
        item.setText(2, record.get('record_type', 'N/A'))
        item.setText(3, str(record.get('clk', 'N/A')))
        item.setText(4, str(record.get('end_clk', 'N/A')))
        item.setText(5, str(record.get('duration', 'N/A')))

        # Store record data in item (use Qt.ItemDataRole.UserRole on column 0 for ID)
        item.setData(0, Qt.ItemDataRole.UserRole, record)

        # Add to mapping
        record_id = record.get('id')
        if record_id:
            self.record_to_item[record_id] = item

        if parent:
            parent.addChild(item)
        else:
            self.addTopLevelItem(item)

        # Add children recursively
        for child in record.get('children', []):
            self._add_record_item(child, item)


class TraceViewerWindow(QMainWindow):
    """Main window for JETS trace viewer application."""

    def __init__(self):
        super().__init__()
        self.trace_data = None
        self.file_path = None

        self.setWindowTitle('JETS Trace Viewer')
        self.setGeometry(100, 100, 1200, 800)

        self._setup_ui()

    def _create_actions(self):
        """Create all actions for menus and toolbar."""
        # Open action
        self.open_action = QAction('📁 Open Trace', self)
        self.open_action.setShortcut('Ctrl+O')
        self.open_action.setStatusTip('Open a JETS trace file')
        self.open_action.triggered.connect(self.open_trace)

    def _create_menus(self):
        """Create menu bar."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu('&File')
        file_menu.addAction(self.open_action)
        file_menu.addSeparator()

        exit_action = QAction('E&xit', self)
        exit_action.setShortcut('Ctrl+Q')
        exit_action.setStatusTip('Exit application')
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

    def _setup_ui(self):
        """Set up the user interface."""
        # Create actions first
        self._create_actions()

        # Create menu bar
        self._create_menus()

        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        layout = QVBoxLayout(central_widget)

        # Toolbar
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)

        # Add actions to toolbar
        toolbar.addAction(self.open_action)

        # Header info label
        self.header_label = QLabel('No trace loaded')
        self.header_label.setStyleSheet('padding: 8px; font-weight: bold;')
        self.header_label.setMaximumHeight(40)
        layout.addWidget(self.header_label, 0)  # 0 = no stretch

        # Main vertical splitter (top: tree, bottom: details)
        main_splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(main_splitter, 1)  # 1 = take all remaining space

        # Tree view (top panel)
        self.tree_widget = TraceTreeWidget()
        main_splitter.addWidget(self.tree_widget)

        # Bottom section: Details list
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        # Label for bottom panel
        self.details_label = QLabel('Annotations & Events (select a record to view)')
        self.details_label.setStyleSheet('padding: 4px; font-weight: bold;')
        bottom_layout.addWidget(self.details_label)

        # List widget for annotations and events
        self.details_list = QListWidget()
        self.details_list.setStyleSheet('font-family: monospace;')
        bottom_layout.addWidget(self.details_list)

        main_splitter.addWidget(bottom_widget)

        # Set main splitter proportions (70% top, 30% bottom)
        main_splitter.setSizes([600, 200])

        # Connect tree selection to details panel
        self.tree_widget.itemSelectionChanged.connect(self._on_tree_selection_changed)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage('Ready')

    def open_trace(self, file_path: Optional[str] = None):
        """Open and display a trace file.

        Args:
            file_path: Path to trace file (if None, shows file dialog)
        """
        # Qt signals sometimes pass False as a parameter, treat it as None
        if file_path is False:
            file_path = None

        if file_path is None:
            import os
            dialog = QFileDialog(self)
            dialog.setWindowTitle('Open JETS Trace')
            dialog.setNameFilter('JETS Traces (*.jets *.jsonl);;All Files (*)')
            dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
            dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
            dialog.setDirectory(os.getcwd())

            if not dialog.exec():
                return

            selected_files = dialog.selectedFiles()
            if not selected_files:
                return
            file_path = selected_files[0]

        if not file_path:
            return

        try:
            self.status_bar.showMessage(f'Loading {file_path}...')

            parser = TraceParser(file_path)
            self.trace_data = parser.parse()
            self.file_path = file_path

            self._update_display()

            self.status_bar.showMessage(f'Loaded {file_path}')

        except Exception as e:
            error_msg = f'Error loading trace: {str(e)}'
            self.status_bar.showMessage(error_msg)
            if DEBUG_OUTPUT:
                import traceback
                traceback.print_exc()

    def _update_display(self):
        """Update tree view with current trace data."""
        if not self.trace_data:
            return

        # Update header label
        header = self.trace_data.get('header', {})
        metadata = header.get('metadata', {})
        gpu_model = metadata.get('gpu_model', 'Unknown')
        clock_freq = metadata.get('clock_frequency_ghz', 'Unknown')
        self.header_label.setText(
            f'GPU: {gpu_model} | Clock: {clock_freq} GHz'
        )

        # Get roots
        roots = self.trace_data.get('roots', [])

        # Update tree view
        self.tree_widget.set_trace_data(roots)

    def _on_tree_selection_changed(self):
        """Update details panel when tree selection changes."""
        self.details_list.clear()

        selected_items = self.tree_widget.selectedItems()
        if not selected_items:
            self.details_label.setText('Annotations & Events (select a record to view)')
            return

        item = selected_items[0]
        record = item.data(0, Qt.ItemDataRole.UserRole)

        if not record or not isinstance(record, dict):
            self.details_label.setText('Annotations & Events (select a record to view)')
            return

        record_id = record.get('id', 'N/A')
        self.details_label.setText(f'Annotations & Events for record: {record_id}')

        # Add record itself as first item (exclude children, annotations, events to avoid duplication)
        # Order fields: clk, type, name, id, then everything else
        record_ordered = {}
        for key in ['clk', 'record_type', 'name', 'id']:
            if key in record:
                record_ordered[key] = record[key]
        for k, v in record.items():
            if k not in ['children', 'annotations', 'events', 'clk', 'record_type', 'name', 'id']:
                record_ordered[k] = v
        record_json = json.dumps(record_ordered, separators=(',', ':'))
        record_item = QListWidgetItem(record_json)
        record_item.setForeground(QBrush(QColor(100, 150, 255)))  # Blue for record
        self.details_list.addItem(record_item)

        annotations = record.get('annotations', [])
        events = record.get('events', [])

        if annotations:
            for annotation in annotations:
                # Order fields: type, name, record_id, then everything else
                ann_ordered = {}
                for key in ['type', 'name', 'record_id']:
                    if key in annotation:
                        ann_ordered[key] = annotation[key]
                for k, v in annotation.items():
                    if k not in ['type', 'name', 'record_id']:
                        ann_ordered[k] = v
                json_str = json.dumps(ann_ordered, separators=(',', ':'))
                annotation_item = QListWidgetItem(json_str)
                annotation_item.setForeground(QBrush(QColor(100, 200, 100)))  # Green for annotations
                self.details_list.addItem(annotation_item)

        if events:
            for event in events:
                # Order fields: clk, type, name, record_id, then everything else
                evt_ordered = {}
                for key in ['clk', 'type', 'name', 'record_id']:
                    if key in event:
                        evt_ordered[key] = event[key]
                for k, v in event.items():
                    if k not in ['clk', 'type', 'name', 'record_id']:
                        evt_ordered[k] = v
                json_str = json.dumps(evt_ordered, separators=(',', ':'))
                event_item = QListWidgetItem(json_str)
                event_item.setForeground(QBrush(QColor(255, 165, 0)))  # Orange for events
                self.details_list.addItem(event_item)

        if not annotations and not events:
            info_item = QListWidgetItem('(no annotations or events for this record)')
            info_item.setForeground(QBrush(QColor(150, 150, 150)))  # Gray for info
            self.details_list.addItem(info_item)


def main():
    """Entry point for standalone viewer application."""
    import sys
    import argparse

    # Parse command line arguments
    parser = argparse.ArgumentParser(description='JETS Trace Viewer')
    parser.add_argument('trace_file', nargs='?', help='Path to JETS trace file to open')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    args = parser.parse_args()

    # Set global debug flag
    global DEBUG_OUTPUT
    DEBUG_OUTPUT = args.debug

    app = QApplication(sys.argv)

    window = TraceViewerWindow()
    window.show()

    if args.trace_file:
        window.open_trace(args.trace_file)

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
