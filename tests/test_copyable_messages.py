"""Test that message boxes have copyable text."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox
from wavescout.utils.message_box_utils import show_critical, show_warning, show_information, show_question


def test_message_box_text_is_selectable(qtbot):
    """Test that message box text has correct interaction flags for copying."""
    from unittest.mock import patch, MagicMock
    
    # Mock QMessageBox to capture the instance
    captured_msg_box = None
    original_exec = QMessageBox.exec
    
    def mock_exec(self):
        nonlocal captured_msg_box
        captured_msg_box = self
        return QMessageBox.Ok
    
    with patch.object(QMessageBox, 'exec', mock_exec):
        # Test critical message
        show_critical(None, "Test", "Test message")
        assert captured_msg_box is not None
        flags = captured_msg_box.textInteractionFlags()
        assert flags & Qt.TextSelectableByMouse
        assert flags & Qt.TextSelectableByKeyboard
        
        # Reset for next test
        captured_msg_box = None
        
        # Test warning message
        show_warning(None, "Test", "Test message")
        assert captured_msg_box is not None
        flags = captured_msg_box.textInteractionFlags()
        assert flags & Qt.TextSelectableByMouse
        assert flags & Qt.TextSelectableByKeyboard
        
        # Reset for next test
        captured_msg_box = None
        
        # Test information message
        show_information(None, "Test", "Test message")
        assert captured_msg_box is not None
        flags = captured_msg_box.textInteractionFlags()
        assert flags & Qt.TextSelectableByMouse
        assert flags & Qt.TextSelectableByKeyboard
        
        # Reset for next test
        captured_msg_box = None
        
        # Test question dialog
        show_question(None, "Test", "Test question")
        assert captured_msg_box is not None
        flags = captured_msg_box.textInteractionFlags()
        assert flags & Qt.TextSelectableByMouse
        assert flags & Qt.TextSelectableByKeyboard


def test_message_box_with_detailed_text(qtbot):
    """Test that message boxes with detailed text work correctly."""
    from unittest.mock import patch, MagicMock
    
    captured_msg_box = None
    
    def mock_exec(self):
        nonlocal captured_msg_box
        captured_msg_box = self
        return QMessageBox.Ok
    
    with patch.object(QMessageBox, 'exec', mock_exec):
        # Test with detailed text
        show_critical(None, "Error", "Main error", detailed_text="Detailed error info")
        
        assert captured_msg_box is not None
        assert captured_msg_box.text() == "Main error"
        assert captured_msg_box.detailedText() == "Detailed error info"
        
        # Check that text is selectable
        flags = captured_msg_box.textInteractionFlags()
        assert flags & Qt.TextSelectableByMouse
        assert flags & Qt.TextSelectableByKeyboard