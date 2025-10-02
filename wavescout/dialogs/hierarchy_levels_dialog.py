"""
Dialog for configuring hierarchical name display levels.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, 
    QLabel, QLineEdit, QPushButton, QWidget
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator, QKeyEvent

from wavescout.utils.settings_manager import SettingsManager


class HierarchyLevelsDialog(QDialog):
    """
    Dialog for configuring the number of hierarchical name levels to display.
    """
    
    def __init__(self, parent: QWidget | None = None) -> None:
        """
        Initialize the hierarchy levels configuration dialog.
        
        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self.settings_manager = SettingsManager()
        self._setup_ui()
        self._load_current_value()
        
    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        self.setWindowTitle("Set Hierarchical Name Levels")
        self.setModal(True)
        self.setFixedSize(300, 150)
        
        # Main layout
        layout = QVBoxLayout()
        
        # Input section
        input_layout = QHBoxLayout()
        label = QLabel("Number of levels to display:")
        self.level_input = QLineEdit()
        
        # Set up validator for numeric input only (0-999)
        validator = QIntValidator(0, 999)
        self.level_input.setValidator(validator)
        
        # Connect to text changed to clear invalid input
        self.level_input.textChanged.connect(self._validate_input)
        
        input_layout.addWidget(label)
        input_layout.addWidget(self.level_input)
        layout.addLayout(input_layout)
        
        # Help text
        help_label = QLabel("0 = Show full hierarchy")
        help_label.setStyleSheet("color: gray; font-size: 10pt;")
        layout.addWidget(help_label)
        
        # Add some spacing
        layout.addStretch()
        
        # Button section
        button_layout = QHBoxLayout()
        
        self.max_button = QPushButton("Max")
        self.max_button.setToolTip("Set to 0 (show full hierarchy)")
        self.max_button.clicked.connect(self._on_max_clicked)
        
        self.ok_button = QPushButton("Ok")
        self.ok_button.setDefault(True)
        self.ok_button.clicked.connect(self._on_ok_clicked)
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        
        button_layout.addWidget(self.max_button)
        button_layout.addStretch()
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
        
        # Focus on input field
        self.level_input.setFocus()
        self.level_input.selectAll()
        
    def _load_current_value(self) -> None:
        """Load the current hierarchy level setting."""
        current_value = self.settings_manager.get_hierarchy_levels()
        self.level_input.setText(str(current_value))
    
    def _validate_input(self, text: str) -> None:
        """Validate and clean input text."""
        # Remove any non-digit characters
        cleaned = ''.join(c for c in text if c.isdigit())
        if cleaned != text:
            self.level_input.setText(cleaned)
        
    def _on_max_clicked(self) -> None:
        """Handle Max button click - set to 0 and apply."""
        self.level_input.setText("0")
        self._on_ok_clicked()
        
    def _on_ok_clicked(self) -> None:
        """Handle Ok button click - validate and apply the setting."""
        text = self.level_input.text()
        
        # Validate input
        if not text:
            # Default to 0 if empty
            value = 0
        else:
            try:
                value = int(text)
                # Clamp to valid range
                value = max(0, min(999, value))
            except ValueError:
                # Should not happen with validator, but be safe
                value = 0
                
        # Apply the setting
        self.settings_manager.set_hierarchy_levels(value)
        
        # Close dialog
        self.accept()
        
    def keyPressEvent(self, event: QKeyEvent) -> None:
        """
        Handle key press events.
        
        Args:
            event: The key event
        """
        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            self._on_ok_clicked()
        elif event.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)