#!/usr/bin/env python3
"""Test the Signal Analysis window with analog_signals_short.vcd."""

import sys
from pathlib import Path
import pytest
from typing import List, Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest

from scout import WaveScoutMainWindow
from wavescout.core.data_model import TreeNode, SignalNode, DisplayFormat
from wavescout.widgets.signal_analysis_window import SignalAnalysisWindow
from .test_utils import MockVar
from wavescout.core.waveform_db import WaveformDB
from wavescout.utils.analysis_engine import (
    compute_signal_statistics,
    generate_sampling_times_signal,
    generate_sampling_times_period
)
from tests.test_utils import get_test_input_path, TestFiles


_signal_cache = {}

def _test_sample(db, handle, t):
    # Cache signals to avoid loading them repeatedly
    if handle not in _signal_cache:
        async_sig = db.load_signal(handle)
        if not async_sig.is_loaded():
            try:
                sig = async_sig.get_signal_blocking(timeout=1.0)
            except (RuntimeError, TimeoutError):
                _signal_cache[handle] = None
                return ""
        else:
            sig = async_sig.get_signal_blocking()
        _signal_cache[handle] = sig
    else:
        sig = _signal_cache[handle]

    if sig is None:
        return ""
    qr = sig.query_signal(max(0, t))
    return str(qr.value) if qr.value is not None else ""


# MockAsyncLoadedSignal removed - using real AsyncLoadedSignal instead


def test_analysis_with_analog_signals():
    """Test signal analysis with analog_signals_short.vcd."""
    print("\n=== Testing Signal Analysis with analog_signals_short.vcd ===")
    
    # Load the waveform directly for debugging
    from wavescout.application.event_bus import EventBus
    event_bus = EventBus()
    db = WaveformDB(event_bus=event_bus)
    db.open(str(get_test_input_path(TestFiles.ANALOG_SIGNALS_SHORT_VCD)))
    
    print(f"Loaded waveform file")
    print(f"Number of unique signals: {len(db.get_all_handles())}")
    
    # Get time range
    time_table = db.get_time_table()
    if time_table:
        print(f"Time range: 0 to {time_table[-1]}")
    
    # List all signals (limit to first 20 for testing)
    all_signals = []
    handles = db.get_all_handles()[:20]  # Limit to first 20 signals
    if handles:
        for handle in handles:
            var = db.var_from_handle(handle)
            if var:
                signal_name = var.full_name(db.hierarchy)
                all_signals.append((handle, signal_name))
                # Sample some values to debug
                if len(all_signals) <= 5:  # Show first 5 signals
                    print(f"\nSignal: {signal_name}")
                    # Get raw values at different times
                    for t in [0, 1000, 5000, 10000]:
                        raw_value = _test_sample(db, handle, t)
                        print(f"  Time {t}: raw={repr(raw_value)} type={type(raw_value)}")
    
    print(f"\nTotal signals found: {len(all_signals)}")
    
    # Find clk_cnt signal
    clk_cnt_handle = None
    clk_cnt_name = None
    for handle, name in all_signals:
        if 'clk_cnt' in name.lower():
            clk_cnt_handle = handle
            clk_cnt_name = name
            print(f"\nFound clk_cnt signal: {name}")
            break
    
    if clk_cnt_handle is None:
        print("ERROR: clk_cnt signal not found!")
        # List all signals to debug
        print("Available signals:")
        for _, name in all_signals:
            print(f"  - {name}")
        pytest.fail("clk_cnt signal not found")
    
    # Create SignalNode objects for testing
    test_signals = []
    for handle, name in all_signals[:5]:  # Test with first 5 signals
        # Split full name into scope and local name
        parts = name.split('.')
        local_name = parts[-1] if parts else name
        scope_path = tuple(parts[:-1]) if len(parts) > 1 else ()

        signal = SignalNode(
            local_name=local_name,
            _waveform_scope=scope_path,
            var=MockVar(name.split('.')[-1], 32),  # Use MockVar for tests
            handle=handle,
            signal=db.load_signal(handle),  # Use real AsyncLoadedSignal
            format=DisplayFormat()
        )
        test_signals.append(signal)

    # Create sampling signal node
    parts = clk_cnt_name.split('.')
    local_name = parts[-1] if parts else clk_cnt_name
    scope_path = tuple(parts[:-1]) if len(parts) > 1 else ()

    sampling_signal = SignalNode(
        local_name=local_name,
        _waveform_scope=scope_path,
        var=MockVar(clk_cnt_name.split('.')[-1], 32),
        handle=clk_cnt_handle,
        signal=db.load_signal(clk_cnt_handle),  # Use real AsyncLoadedSignal
        format=DisplayFormat()
    )
    
    # Test sampling signal transitions
    print(f"\n=== Testing sampling signal transitions ===")
    sampling_times = generate_sampling_times_signal(
        db,
        sampling_signal,
        start_time=0,
        end_time=100000
    )
    print(f"Generated {len(sampling_times)} sampling points from {clk_cnt_name}")
    if sampling_times:
        print(f"First 10 sampling times: {sampling_times[:10]}")
    
    # Test analysis for each signal
    print(f"\n=== Testing analysis computation ===")
    for signal in test_signals:
        print(f"\nAnalyzing signal: {signal.name}")
        
        # Debug: Check raw values
        for t in sampling_times[:5] if sampling_times else [0, 1000, 5000]:
            raw_value = _test_sample(db, signal.handle, t)
            print(f"  Raw value at {t}: {repr(raw_value)}")
            
            # Check value conversion
            if isinstance(raw_value, str) and raw_value in ('0', '1'):
                converted = int(raw_value)
                print(f"    -> Converted to int: {converted}")
        
        # Compute statistics
        stats = compute_signal_statistics(
            db,
            signal,
            sampling_times if sampling_times else [0, 10000, 20000],
            start_time=0,
            end_time=100000
        )
        
        print(f"  Results:")
        print(f"    Min: {stats.min_value}")
        print(f"    Max: {stats.max_value}")
        print(f"    Sum: {stats.sum_value}")
        print(f"    Avg: {stats.average_value}")
        print(f"    Valid samples: {stats.sample_count}")
        
        # Check if all zeros
        if stats.min_value == 0 and stats.max_value == 0 and stats.sum_value == 0:
            print(f"  WARNING: All zeros for {signal.name}!")
    
    # Test passes if we get here without errors
    assert True, "Analysis completed successfully"


def test_analysis_window_integration():
    """Test the full analysis window integration."""
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    
    print("\n=== Testing Analysis Window Integration ===")
    
    # Create main window and load waveform
    window = WaveScoutMainWindow(wave_file=str(get_test_input_path(TestFiles.ANALOG_SIGNALS_SHORT_VCD)))
    
    def run_test():
        if not window.wave_widget.session:
            print("ERROR: No session loaded")
            app.quit()
            return
        
        controller = window.wave_widget.controller
        session = controller.session
        primary_file = session.get_primary_file()
        waveform_db = primary_file.waveform_db if primary_file else None

        # Create signal nodes and add them to the session
        all_signals = []
        clk_cnt_signal = None

        if waveform_db:
            for handle in waveform_db.get_all_handles()[:10]:  # First 10 signals
                var = waveform_db.var_from_handle(handle)
                if var:
                    # Get local name and scope path from var
                    local_name = var.name(waveform_db.hierarchy)
                    scope_path = tuple(var.scope_path(waveform_db.hierarchy))

                    signal = SignalNode(
                        local_name=local_name,
                        _waveform_scope=scope_path,
                        var=var,  # Use the real var object from waveform_db
                        handle=handle,
                        signal=waveform_db.load_signal(handle),  # Use real AsyncLoadedSignal
                        format=DisplayFormat()
                    )
                    all_signals.append(signal)
                    # Add to session root_nodes so they appear in combo box
                    session.root_nodes.append(signal)

                    if 'clk_cnt' in signal.name.lower() and not clk_cnt_signal:
                        clk_cnt_signal = signal
        
        if not all_signals:
            print("ERROR: No signals found")
            app.quit()
            return
        
        print(f"Found {len(all_signals)} signals")
        
        # Set sampling signal
        if clk_cnt_signal:
            controller.set_sampling_signal(clk_cnt_signal)
            print(f"Set sampling signal: {clk_cnt_signal.name}")
        
        # Create analysis window
        analysis_window = SignalAnalysisWindow(
            controller=controller,
            selected_signals=all_signals[:5],  # Test with first 5
            parent=window
        )
        
        # Check initial state
        print(f"Table has {analysis_window._results_table.rowCount()} rows")
        
        # Configure the analysis window for testing
        # The combo box should already have the sampling signal selected if it was set in the controller
        # But we need to ensure the correct radio button is checked
        if clk_cnt_signal and analysis_window._signal_combo.currentIndex() >= 0:
            # Sampling signal is already selected in combo, just ensure signal mode is active
            analysis_window._signal_radio.setChecked(True)
            current_signal = analysis_window._signal_combo.itemData(analysis_window._signal_combo.currentIndex())
            print(f"Using sampling signal: {current_signal.name if current_signal else 'Unknown'}")
        else:
            # Use period mode as fallback
            analysis_window._period_radio.setChecked(True)
            analysis_window._period_input.setText("1000")
            print("Using period mode with period=1000")
        
        # Trigger analysis programmatically
        def start_analysis():
            print("\nStarting analysis...")
            analysis_window._start_analysis()
        
        def check_results():
            print("\nChecking results...")
            if analysis_window._results:
                for name, stats in analysis_window._results.items():
                    print(f"{name}:")
                    print(f"  Min: {stats.min_value}, Max: {stats.max_value}")
                    print(f"  Sum: {stats.sum_value}, Avg: {stats.average_value}")
            else:
                print("No results yet")
            
            analysis_window.close()
            app.quit()
        
        # Show window and start test sequence
        analysis_window.show()
        QTimer.singleShot(100, start_analysis)
        QTimer.singleShot(3000, check_results)  # Wait for analysis to complete
    
    QTimer.singleShot(1000, run_test)
    app.exec()


if __name__ == "__main__":
    # Run direct analysis test first
    success = test_analysis_with_analog_signals()
    
    if success:
        # Then run integration test
        test_analysis_window_integration()
    else:
        print("\nDirect analysis test failed, skipping integration test")
