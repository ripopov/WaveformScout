"""Signal Analysis Window for computing and displaying signal statistics."""

from __future__ import annotations

from typing import List, Optional, Dict, Any

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox,
    QRadioButton, QComboBox, QLineEdit, QTableWidget,
    QTableWidgetItem, QProgressBar, QPushButton,
    QLabel, QButtonGroup, QMessageBox,
    QAbstractItemView, QWidget
)

from .analysis_engine import (
    compute_signal_statistics,
    generate_sampling_times_period,
    generate_sampling_times_signal,
    SignalStatistics
)
from .data_model import TreeNode, Time
from .waveform_controller import WaveformController


class SignalAnalysisWorker(QThread):
    """Worker thread for performing signal analysis in the background."""
    
    # Signals
    progress_updated = Signal(int)  # Progress percentage
    result_ready = Signal(str, SignalStatistics)  # Signal name and statistics
    analysis_complete = Signal()
    error_occurred = Signal(str)
    
    def __init__(
        self,
        waveform_db: Any,
        signals: List[TreeNode],
        sampling_mode: str,  # "signal" or "period"
        sampling_signal: Optional[TreeNode],
        sampling_period: int,
        start_time: Time,
        end_time: Time
    ):
        super().__init__()
        self.waveform_db = waveform_db
        self.signals = signals
        self.sampling_mode = sampling_mode
        self.sampling_signal = sampling_signal
        self.sampling_period = sampling_period
        self.start_time = start_time
        self.end_time = end_time
        self._cancelled = False
    
    def cancel(self) -> None:
        """Cancel the analysis."""
        self._cancelled = True
    
    def run(self) -> None:
        """Perform the analysis."""
        try:
            # Generate sampling times based on mode
            if self.sampling_mode == "signal" and self.sampling_signal:
                sampling_times = generate_sampling_times_signal(
                    self.waveform_db,
                    self.sampling_signal,  # type: ignore[arg-type]
                    self.start_time,
                    self.end_time
                )
            elif self.sampling_mode == "period":
                sampling_times = generate_sampling_times_period(
                    self.start_time,
                    self.end_time,
                    self.sampling_period
                )
            else:
                self.error_occurred.emit("Invalid sampling configuration")
                return
            
            if not sampling_times:
                self.error_occurred.emit("No sampling points generated")
                return
            
            # Analyze each signal
            total_signals = len(self.signals)
            for i, signal in enumerate(self.signals):
                if self._cancelled:
                    break
                
                # Compute statistics
                stats = compute_signal_statistics(
                    self.waveform_db,
                    signal,  # type: ignore[arg-type]
                    sampling_times,
                    self.start_time,
                    self.end_time
                )
                
                # Emit result
                self.result_ready.emit(signal.name, stats)
                
                # Update progress
                progress = int((i + 1) * 100 / total_signals)
                self.progress_updated.emit(progress)
            
            if not self._cancelled:
                self.analysis_complete.emit()
                
        except Exception as e:
            self.error_occurred.emit(str(e))


class SignalAnalysisWindow(QDialog):
    """Modal dialog for signal analysis configuration and results."""
    
    def __init__(
        self,
        controller: WaveformController,
        selected_signals: List[TreeNode],
        parent: Optional[Any] = None
    ):
        super().__init__(parent)
        self._controller = controller
        self._selected_signals = selected_signals
        self._worker: Optional[SignalAnalysisWorker] = None
        self._results: Dict[str, SignalStatistics] = {}
        
        self._setup_ui()
        self._populate_signals()
        self._update_interval_options()
        self._on_interval_changed()  # Initialize marker info display
        self._populate_results_table()
    
    def _setup_ui(self) -> None:
        """Setup the user interface."""
        self.setWindowTitle("Signal Analysis")
        self.setModal(False)
        self.resize(800, 600)
        
        layout = QVBoxLayout(self)
        
        # Sampling configuration group
        sampling_group = QGroupBox("Sampling Configuration")
        sampling_layout = QVBoxLayout(sampling_group)
        
        # Radio buttons for sampling mode
        self._button_group = QButtonGroup(self)
        
        # Sampling signal option
        signal_layout = QHBoxLayout()
        self._signal_radio = QRadioButton("Sampling Signal:")
        self._button_group.addButton(self._signal_radio)
        signal_layout.addWidget(self._signal_radio)
        
        self._signal_combo = QComboBox()
        self._signal_combo.setEnabled(False)
        signal_layout.addWidget(self._signal_combo)
        signal_layout.addStretch()
        sampling_layout.addLayout(signal_layout)
        
        # Sampling period option
        period_layout = QHBoxLayout()
        self._period_radio = QRadioButton("Sampling Period:")
        self._button_group.addButton(self._period_radio)
        period_layout.addWidget(self._period_radio)
        
        self._period_input = QLineEdit()
        self._period_input.setValidator(QIntValidator(1, 2147483647))
        self._period_input.setPlaceholderText("Enter period in time units")
        self._period_input.setEnabled(False)
        self._period_input.setMaximumWidth(200)
        period_layout.addWidget(self._period_input)
        period_layout.addStretch()
        sampling_layout.addLayout(period_layout)
        
        layout.addWidget(sampling_group)
        
        # Interval selection group
        interval_group = QGroupBox("Analysis Interval")
        interval_layout = QVBoxLayout(interval_group)
        
        # Combo box row
        combo_layout = QHBoxLayout()
        combo_layout.addWidget(QLabel("Analyze:"))
        self._interval_combo = QComboBox()
        self._interval_combo.setMinimumWidth(200)
        self._interval_combo.currentIndexChanged.connect(self._on_interval_changed)
        combo_layout.addWidget(self._interval_combo)
        combo_layout.addStretch()
        interval_layout.addLayout(combo_layout)
        
        # Marker info labels (initially hidden)
        self._marker_info_widget = QWidget()
        marker_info_layout = QVBoxLayout(self._marker_info_widget)
        marker_info_layout.setContentsMargins(0, 0, 0, 0)
        
        # Marker A timestamp
        self._marker_a_label = QLabel()
        self._marker_a_label.setStyleSheet("color: #888;")
        marker_info_layout.addWidget(self._marker_a_label)
        
        # Marker B timestamp
        self._marker_b_label = QLabel()
        self._marker_b_label.setStyleSheet("color: #888;")
        marker_info_layout.addWidget(self._marker_b_label)
        
        # Time period
        self._period_label = QLabel()
        self._period_label.setStyleSheet("font-weight: bold;")
        marker_info_layout.addWidget(self._period_label)
        
        interval_layout.addWidget(self._marker_info_widget)
        self._marker_info_widget.setVisible(False)
        
        layout.addWidget(interval_group)
        
        # Results table
        results_group = QGroupBox("Results")
        results_layout = QVBoxLayout(results_group)
        
        self._results_table = QTableWidget()
        self._results_table.setColumnCount(5)
        self._results_table.setHorizontalHeaderLabels([
            "Signal Name", "Minimum", "Maximum", "Sum", "Average"
        ])
        self._results_table.horizontalHeader().setStretchLastSection(True)
        self._results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        results_layout.addWidget(self._results_table)
        
        layout.addWidget(results_group)
        
        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self._start_button = QPushButton("Start Analysis")
        self._start_button.clicked.connect(self._start_analysis)
        button_layout.addWidget(self._start_button)
        
        self._close_button = QPushButton("Close")
        self._close_button.clicked.connect(self.accept)
        button_layout.addWidget(self._close_button)
        
        layout.addLayout(button_layout)
        
        # Connect radio button changes
        self._signal_radio.toggled.connect(self._on_mode_changed)
        self._period_radio.toggled.connect(self._on_mode_changed)
        
        # Setup keyboard shortcuts
        self._setup_keyboard_shortcuts()
        
        # Set default mode
        if self._controller.get_sampling_signal():
            self._signal_radio.setChecked(True)
        else:
            self._period_radio.setChecked(True)
            self._period_input.setText("1000")  # Default period
    
    def _populate_signals(self) -> None:
        """Populate the signal combo box with all available signals."""
        if not self._controller.session:
            return
        
        # Clear combo box
        self._signal_combo.clear()
        
        # Add all signals from the session
        def add_signals(nodes: List[TreeNode], prefix: str = "") -> None:
            for node in nodes:
                if node.is_group:
                    # Recursively add signals from groups
                    group_prefix = f"{prefix}{node.name}/" if prefix else f"{node.name}/"
                    add_signals(node.children, group_prefix)  # type: ignore[attr-defined]
                else:
                    # Add signal to combo box
                    display_name = f"{prefix}{node.name}"
                    self._signal_combo.addItem(display_name, node)
        
        add_signals(self._controller.session.root_nodes)
        
        # Select the current sampling signal if set
        current_sampling = self._controller.get_sampling_signal()
        if current_sampling:
            for i in range(self._signal_combo.count()):
                item = self._signal_combo.itemData(i)
                # Compare by instance_id to handle cases where objects are different but represent same signal
                if item and item.instance_id == current_sampling.instance_id:
                    self._signal_combo.setCurrentIndex(i)
                    break
    
    def _update_interval_options(self) -> None:
        """Update the interval combo box based on available markers."""
        self._interval_combo.clear()
        
        if not self._controller.session:
            self._interval_combo.addItem("Global", "global")
            return
        
        # Check if we have at least 2 markers
        markers = self._controller.session.markers
        valid_markers = [m for m in markers if m and m.time >= 0]
        
        if len(valid_markers) >= 2:
            # Sort markers by time
            valid_markers.sort(key=lambda m: m.time)
            # Add marker interval option FIRST (so it becomes the default)
            label = f"{valid_markers[0].label} - {valid_markers[1].label}"
            self._interval_combo.addItem(label, "markers")
            # Then add global option
            self._interval_combo.addItem("Global", "global")
        else:
            # Only global option available
            self._interval_combo.addItem("Global", "global")
    
    def _on_interval_changed(self) -> None:
        """Handle interval selection change."""
        interval_type = self._interval_combo.currentData()
        
        if interval_type == "markers" and self._controller.session:
            # Show marker info
            markers = self._controller.session.markers
            valid_markers = sorted([m for m in markers if m and m.time >= 0], key=lambda m: m.time)
            
            if len(valid_markers) >= 2:
                marker_a = valid_markers[0]
                marker_b = valid_markers[1]
                
                # Format timestamps
                self._marker_a_label.setText(f"Marker A ({marker_a.label}): {marker_a.time:,}")
                self._marker_b_label.setText(f"Marker B ({marker_b.label}): {marker_b.time:,}")
                
                # Calculate and format period
                period = marker_b.time - marker_a.time
                self._period_label.setText(f"Period: {period:,} time units")
                
                self._marker_info_widget.setVisible(True)
            else:
                self._marker_info_widget.setVisible(False)
        else:
            # Hide marker info for global interval
            self._marker_info_widget.setVisible(False)
    
    def _populate_results_table(self) -> None:
        """Populate the results table with signal names (values empty initially)."""
        # Set row count based on selected signals
        self._results_table.setRowCount(len(self._selected_signals))
        
        # Add signal names to the first column
        for i, signal in enumerate(self._selected_signals):
            # Signal name column
            name_item = QTableWidgetItem(signal.name)
            self._results_table.setItem(i, 0, name_item)
            
            # Initialize other columns as empty
            for j in range(1, 5):  # Columns 1-4 (Min, Max, Sum, Average)
                self._results_table.setItem(i, j, QTableWidgetItem(""))
    
    def _on_mode_changed(self) -> None:
        """Handle sampling mode radio button changes."""
        if self._signal_radio.isChecked():
            self._signal_combo.setEnabled(True)
            self._period_input.setEnabled(False)
        else:
            self._signal_combo.setEnabled(False)
            self._period_input.setEnabled(True)
    
    def _setup_keyboard_shortcuts(self) -> None:
        """Setup keyboard shortcuts for the dialog."""
        # Install event filter to handle Ctrl+C on the table
        self._results_table.installEventFilter(self)
    
    def eventFilter(self, obj: Any, event: Any) -> bool:
        """Event filter to handle keyboard shortcuts on the results table."""
        if obj == self._results_table and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_C and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                self._copy_table_selection()
                return True
        return super().eventFilter(obj, event)
    
    def _copy_table_selection(self) -> None:
        """Copy selected table cells to clipboard in tab-separated format."""
        selection = self._results_table.selectedRanges()
        if not selection:
            return
        
        # Build text from selected cells
        copied_text: List[str] = []
        
        for range_item in selection:
            # Get the range boundaries
            top_row = range_item.topRow()
            bottom_row = range_item.bottomRow()
            left_col = range_item.leftColumn()
            right_col = range_item.rightColumn()
            
            # If full rows are selected, include headers
            if left_col == 0 and right_col == self._results_table.columnCount() - 1:
                # Add header row if we're starting from the top
                if top_row == 0 or not copied_text:
                    headers = []
                    for col in range(left_col, right_col + 1):
                        header_item = self._results_table.horizontalHeaderItem(col)
                        headers.append(header_item.text() if header_item else "")
                    copied_text.append("\t".join(headers))
            
            # Add data rows
            for row in range(top_row, bottom_row + 1):
                row_data = []
                for col in range(left_col, right_col + 1):
                    item = self._results_table.item(row, col)
                    row_data.append(item.text() if item else "")
                copied_text.append("\t".join(row_data))
        
        # Copy to clipboard
        if copied_text:
            clipboard = QApplication.clipboard()
            clipboard.setText("\n".join(copied_text))
    
    def _start_analysis(self) -> None:
        """Start the signal analysis."""
        if not self._controller.session or not self._controller.session.waveform_db:
            QMessageBox.warning(self, "Error", "No waveform loaded")
            return
        
        # Get sampling configuration
        if self._signal_radio.isChecked():
            sampling_mode = "signal"
            index = self._signal_combo.currentIndex()
            if index < 0:
                QMessageBox.warning(self, "Error", "Please select a sampling signal")
                return
            sampling_signal = self._signal_combo.itemData(index)
            sampling_period = 0
        else:
            sampling_mode = "period"
            sampling_signal = None
            try:
                sampling_period = int(self._period_input.text())
                if sampling_period <= 0:
                    raise ValueError()
            except (ValueError, AttributeError):
                QMessageBox.warning(self, "Error", "Please enter a valid positive period")
                return
        
        # Get analysis interval
        interval_type = self._interval_combo.currentData()
        if interval_type == "markers":
            # Use marker interval
            markers = self._controller.session.markers
            valid_markers = sorted([m for m in markers if m and m.time >= 0], key=lambda m: m.time)
            if len(valid_markers) >= 2:
                start_time = valid_markers[0].time
                end_time = valid_markers[1].time
            else:
                # Fallback to global
                start_time = 0
                time_table = self._controller.session.waveform_db.get_time_table()
                end_time = time_table[-1] if time_table else 100000000
        else:
            # Use global interval
            start_time = 0
            time_table = self._controller.session.waveform_db.get_time_table()
            end_time = time_table[-1] if time_table else 100000000
        
        # Clear previous results but keep signal names
        self._results.clear()
        # Clear only the value columns (1-4), keep signal names (column 0)
        for i in range(len(self._selected_signals)):
            for j in range(1, 5):  # Only columns 1-4 (Min, Max, Sum, Average)
                self._results_table.setItem(i, j, QTableWidgetItem(""))
        
        # Setup progress bar
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)
        self._start_button.setEnabled(False)
        
        # Create and start worker thread
        self._worker = SignalAnalysisWorker(
            self._controller.session.waveform_db,
            self._selected_signals,
            sampling_mode,
            sampling_signal,
            sampling_period,
            start_time,
            end_time
        )
        
        # Connect signals
        self._worker.progress_updated.connect(self._on_progress_updated)
        self._worker.result_ready.connect(self._on_result_ready)
        self._worker.analysis_complete.connect(self._on_analysis_complete)
        self._worker.error_occurred.connect(self._on_error)
        
        # Start analysis
        self._worker.start()
    
    def _on_progress_updated(self, progress: int) -> None:
        """Handle progress updates from worker."""
        self._progress_bar.setValue(progress)
    
    def _on_result_ready(self, signal_name: str, stats: SignalStatistics) -> None:
        """Handle result from worker."""
        self._results[signal_name] = stats
        
        # Find the row for this signal
        for i, signal in enumerate(self._selected_signals):
            if signal.name == signal_name:
                # Update table (signal name already there, just update values)
                self._results_table.setItem(i, 1, QTableWidgetItem(f"{stats.min_value:.6g}"))
                self._results_table.setItem(i, 2, QTableWidgetItem(f"{stats.max_value:.6g}"))
                self._results_table.setItem(i, 3, QTableWidgetItem(f"{stats.sum_value:.6g}"))
                self._results_table.setItem(i, 4, QTableWidgetItem(f"{stats.average_value:.6g}"))
                break
    
    def _on_analysis_complete(self) -> None:
        """Handle analysis completion."""
        self._progress_bar.setVisible(False)
        self._start_button.setEnabled(True)
        self._worker = None
    
    def _on_error(self, error_msg: str) -> None:
        """Handle error from worker."""
        self._progress_bar.setVisible(False)
        self._start_button.setEnabled(True)
        self._worker = None
        QMessageBox.critical(self, "Analysis Error", f"Error during analysis: {error_msg}")
    
    def closeEvent(self, event: Any) -> None:
        """Handle window close event."""
        # Cancel any running analysis
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait()
        event.accept()