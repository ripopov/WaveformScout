#!/usr/bin/env python3
"""Test copy functionality in Signal Analysis results table."""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtWidgets import QApplication, QTableWidgetSelectionRange, QTableWidgetItem
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest

from scout import WaveScoutMainWindow
from wavescout.data_model import SignalNode, SignalNodeSignal, DisplayFormat
from wavescout.signal_analysis_window import SignalAnalysisWindow
from test_utils import get_test_input_path, TestFiles, MockVar


def test_copy_results():
    """Test copying results from the analysis table."""
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    
    print("\n=== Testing Copy Functionality in Results Table ===")
    
    # Create main window and load waveform
    window = WaveScoutMainWindow(wave_file=str(get_test_input_path(TestFiles.APB_SIM_VCD)))
    
    def run_test():
        if not window.wave_widget.session:
            print("ERROR: No session loaded")
            app.quit()
            return
        
        controller = window.wave_widget.controller
        session = controller.session
        
        # Add some test signals
        test_signals = []
        if session.waveform_db:
            # Get first 3 signal handles using the new API
            handles = session.waveform_db.get_all_handles()[:3]
            for handle in handles:
                var = session.waveform_db.var_from_handle(handle)
                if var:
                    # Use the proper load_signal method to create AsyncLoadedSignal
                    async_signal = session.waveform_db.load_signal(handle)

                    # Wait for signal to load with timeout
                    import time
                    start_time = time.time()
                    timeout = 5.0
                    while not async_signal.is_loaded() and (time.time() - start_time) < timeout:
                        QApplication.processEvents()
                        time.sleep(0.01)

                    # Ensure signal is loaded
                    if not async_signal.is_loaded():
                        print(f"WARNING: Signal {handle} did not load in time")

                    signal = SignalNodeSignal(
                        name=var.full_name(session.waveform_db.hierarchy),
                        var=var,  # Add the required var field
                        handle=handle,
                        signal=async_signal,
                        format=DisplayFormat()
                    )
                    test_signals.append(signal)
                    session.root_nodes.append(signal)
        
        # Create analysis window
        analysis_window = SignalAnalysisWindow(
            controller=controller,
            selected_signals=test_signals,
            parent=window
        )
        
        # Manually populate some test results
        print("\nPopulating test results...")
        for i, signal in enumerate(test_signals):
            analysis_window._results_table.setItem(i, 1, QTableWidgetItem(f"{i+1}.111"))  # Min
            analysis_window._results_table.setItem(i, 2, QTableWidgetItem(f"{i+1}.999"))  # Max
            analysis_window._results_table.setItem(i, 3, QTableWidgetItem(f"{i+1}00.5"))  # Sum
            analysis_window._results_table.setItem(i, 4, QTableWidgetItem(f"{i+1}.555"))  # Average
        
        # Test 1: Select all with Ctrl+A and copy with Ctrl+C
        print("\nTest 1: Select all and copy")
        analysis_window._results_table.selectAll()
        
        # Simulate Ctrl+C
        key_event = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_C,
            Qt.KeyboardModifier.ControlModifier
        )
        analysis_window.eventFilter(analysis_window._results_table, key_event)
        
        # Check clipboard
        clipboard = QApplication.clipboard()
        clipboard_text = clipboard.text()
        
        print("Clipboard contents:")
        print(clipboard_text)
        
        # Verify content
        lines = clipboard_text.split('\n')
        assert len(lines) >= 4, f"Expected at least 4 lines (header + 3 data rows), got {len(lines)}"
        
        # Check header
        assert "Signal Name" in lines[0] and "Minimum" in lines[0], "Header not found in clipboard"
        print("✓ Header row copied correctly")
        
        # Check data rows
        for i in range(1, min(4, len(lines))):
            assert "\t" in lines[i], f"Line {i} should be tab-separated"
        print("✓ Data rows are tab-separated")
        
        # Test 2: Select specific range
        print("\nTest 2: Select specific range (row 1-2, columns 1-3)")
        analysis_window._results_table.clearSelection()
        
        # Create a selection range
        selection_range = QTableWidgetSelectionRange(0, 1, 1, 3)  # Rows 0-1, Columns 1-3
        analysis_window._results_table.setRangeSelected(selection_range, True)
        
        # Copy again
        analysis_window._copy_table_selection()
        
        clipboard_text = clipboard.text()
        print("Clipboard contents (partial selection):")
        print(clipboard_text)
        
        lines = clipboard_text.split('\n')
        assert len(lines) == 2, f"Expected 2 lines for 2 rows, got {len(lines)}"
        
        # Check that we have 3 columns per row
        for line in lines:
            parts = line.split('\t')
            assert len(parts) == 3, f"Expected 3 columns, got {len(parts)}"
        print("✓ Partial selection copied correctly")
        
        print("\n✓✓✓ Copy functionality test passed! ✓✓✓")
        
        analysis_window.close()
        app.quit()
    
    # Run test after window loads
    QTimer.singleShot(1000, run_test)
    app.exec()


if __name__ == "__main__":
    test_copy_results()
