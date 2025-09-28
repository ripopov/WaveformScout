"""Dialog for navigating to specific time or clock cycle in waveform."""

from typing import Optional

from PySide6.QtCore import Qt, QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator, QKeyEvent, QShowEvent
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QMessageBox, QWidget,
    QFormLayout
)

from wavescout.data_model import Time
from wavescout.waveform_controller import WaveformController


class NavigateTimeDialog(QDialog):
    """Dialog for navigating to a specific time or clock cycle."""
    
    def __init__(self, controller: WaveformController, parent: Optional[QWidget] = None) -> None:
        """Initialize the navigate time dialog.
        
        Args:
            controller: The waveform controller for navigation
            parent: Parent widget
        """
        super().__init__(parent)
        self.controller = controller
        self.clock_info = controller.get_clock_info()
        
        self.timestamp_input: QLineEdit
        self.clock_input: Optional[QLineEdit] = None
        
        self._setup_ui()
        
    def _setup_ui(self) -> None:
        """Set up the dialog UI based on clock signal state."""
        self.setWindowTitle("Navigate to Time/Clock")
        self.setModal(True)
        self.setMinimumWidth(300)
        
        layout = QVBoxLayout(self)
        
        # Create form layout for input fields
        form_layout = QFormLayout()
        
        # Timestamp field (always present)
        self.timestamp_input = QLineEdit()
        self.timestamp_input.setPlaceholderText("Enter timestamp")
        # Accept non-negative integers only
        # Only accept digits (no negative sign, no letters)
        timestamp_validator = QRegularExpressionValidator(QRegularExpression(r"^\d*$"))
        self.timestamp_input.setValidator(timestamp_validator)
        form_layout.addRow("Timestamp:", self.timestamp_input)
        
        # Clock field (only if clock signal is set)
        if self.clock_info is not None:
            self.clock_input = QLineEdit()
            self.clock_input.setPlaceholderText("Enter clock cycle")
            # Accept non-negative integers only (use same regex validator)
            clock_validator = QRegularExpressionValidator(QRegularExpression(r"^\d*$"))
            self.clock_input.setValidator(clock_validator)
            form_layout.addRow("Clock:", self.clock_input)
            
        layout.addLayout(form_layout)
        
        # Button layout
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        # Cancel button
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)
        
        # Ok button
        ok_button = QPushButton("Ok")
        ok_button.clicked.connect(self._validate_and_navigate)
        ok_button.setDefault(True)
        button_layout.addWidget(ok_button)
        
        layout.addLayout(button_layout)
        
        # Connect Enter key to Ok action
        self.timestamp_input.returnPressed.connect(self._validate_and_navigate)
        if self.clock_input:
            self.clock_input.returnPressed.connect(self._validate_and_navigate)
            
    def _validate_and_navigate(self) -> None:
        """Validate input and perform navigation."""
        # Check if clock input has value (priority over timestamp)
        if self.clock_input and self.clock_input.text().strip():
            try:
                cycle = int(self.clock_input.text().strip())
                if cycle < 0:
                    QMessageBox.warning(
                        self, 
                        "Invalid Input", 
                        "Clock cycle must be a non-negative integer."
                    )
                    return
                    
                # Navigate to clock cycle
                self.controller.navigate_to_clock_cycle(cycle)
                self.accept()
                return
            except ValueError:
                QMessageBox.warning(
                    self, 
                    "Invalid Input", 
                    "Clock cycle must be a valid integer."
                )
                return
                
        # Check timestamp input
        if self.timestamp_input.text().strip():
            try:
                time = self._format_time_input(self.timestamp_input.text().strip())
                if time < 0:
                    QMessageBox.warning(
                        self, 
                        "Invalid Input", 
                        "Timestamp must be non-negative."
                    )
                    return
                    
                # Navigate to timestamp
                self.controller.navigate_to_time(time)
                self.accept()
                return
            except ValueError:
                QMessageBox.warning(
                    self, 
                    "Invalid Input", 
                    "Timestamp must be a valid integer."
                )
                return
                
        # No input provided - just close dialog
        self.reject()
        
    def _format_time_input(self, text: str) -> Time:
        """Parse various time formats.
        
        Args:
            text: Input text to parse
            
        Returns:
            Time value in simulation units
            
        Raises:
            ValueError: If input cannot be parsed
        """
        # For now, just parse as integer
        # Future enhancement: support unit suffixes like "100ns", "1us", etc.
        return int(text)
        
    def showEvent(self, event: QShowEvent) -> None:
        """Handle show event to set proper focus.
        
        Args:
            event: The show event
        """
        super().showEvent(event)
        # Set focus after dialog is shown
        if self.clock_input is not None:
            # Default focus on clock field when available
            self.clock_input.setFocus()
        else:
            # Focus on timestamp field when no clock
            self.timestamp_input.setFocus()
    
    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle key press events.
        
        Args:
            event: The key press event
        """
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)