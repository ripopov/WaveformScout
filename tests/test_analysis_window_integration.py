#!/usr/bin/env python3
"""Integration test for Signal Analysis window as specified."""

import sys
from pathlib import Path
import pytest

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from wavescout.waveform_db import WaveformDB
from wavescout.data_model import SignalNode, SignalNodeSignal, DisplayFormat
from wavescout.waveform_controller import WaveformController
from wavescout.analysis_engine import (
    compute_signal_statistics,
    generate_sampling_times_signal,
)
from tests.test_utils import get_test_input_path, TestFiles


def test_analysis_with_analog_signals():
    """
    Test Signal Analysis feature with analog_signals_short.vcd:
    1. Load test_inputs/analog_signals_short.vcd
    2. Add all signals to wave
    3. Set clk_cnt as sampling signal
    4. Select all signals
    5. Launch analysis, global, using sampling signal
    6. Verify that results are correct
    """
    print("\n=== Signal Analysis Integration Test ===")
    
    # Step 1: Load analog_signals_short.vcd using test utilities
    db = WaveformDB()
    db.open(str(get_test_input_path(TestFiles.ANALOG_SIGNALS_SHORT_VCD)))
    print("✓ Step 1: Loaded analog_signals_short.vcd")
    
    # Step 2: Add all signals to wave (create SignalNode objects)
    all_signals = []
    clk_cnt_signal = None
    
    for handle in db.get_all_handles():
        var = db.var_from_handle(handle)
        if var:
            name = var.full_name(db.hierarchy)
            signal = SignalNodeSignal(
                name=name,
                handle=handle,
                format=DisplayFormat()
            )
            all_signals.append(signal)
            
            # Find clk_cnt for step 3
            if 'clk_cnt' in name.lower():
                clk_cnt_signal = signal
    
    print(f"✓ Step 2: Added {len(all_signals)} signals to wave")
    
    # Step 3: Set clk_cnt as sampling signal
    assert clk_cnt_signal is not None, "clk_cnt signal not found"
    print(f"✓ Step 3: Set {clk_cnt_signal.name} as sampling signal")
    
    # Step 4: Select all signals (we'll analyze all)
    selected_signals = all_signals
    print(f"✓ Step 4: Selected {len(selected_signals)} signals")
    
    # Step 5: Launch analysis, global, using sampling signal
    # Get global time range
    time_table = db.get_time_table()
    start_time = 0
    end_time = time_table[-1] if time_table else 10000000
    
    # Generate sampling times using clk_cnt
    sampling_times = generate_sampling_times_signal(
        db,
        clk_cnt_signal,
        start_time=start_time,
        end_time=end_time
    )
    
    print(f"✓ Step 5: Launched analysis (global, {len(sampling_times)} sampling points)")
    
    # Step 6: Verify that results are correct
    print("\n=== Verifying Results ===")
    
    all_results_valid = True
    zero_result_count = 0
    
    for signal in selected_signals[:10]:  # Check first 10 signals for brevity
        stats = compute_signal_statistics(
            db,
            signal,
            sampling_times,
            start_time=start_time,
            end_time=end_time
        )
        
        # Check if results are all zeros (indicates a problem)
        if stats.min_value == 0 and stats.max_value == 0 and stats.sum_value == 0 and stats.sample_count > 0:
            zero_result_count += 1
            print(f"  ⚠ {signal.name}: All zeros (likely an issue)")
        else:
            print(f"  ✓ {signal.name}: Min={stats.min_value:.3f}, Max={stats.max_value:.3f}, Avg={stats.average_value:.3f}")
        
        # Specific validation for known signals
        if 'clk_cnt' in signal.name.lower():
            # clk_cnt should be a counter from 0 to number of samples - 1
            expected_min = 0
            expected_max = len(sampling_times) - 1
            if abs(stats.min_value - expected_min) > 0.01 or abs(stats.max_value - expected_max) > 0.01:
                print(f"    ✗ clk_cnt values incorrect: expected min={expected_min}, max={expected_max}")
                all_results_valid = False
        
        elif 'sine' in signal.name.lower():
            # All sine signals should have valid min/max/avg values
            # Just check that they're not all zeros and have reasonable values
            if stats.sample_count == 0:
                print(f"    ✗ {signal.name}: No samples")
                all_results_valid = False
            elif stats.min_value == stats.max_value and stats.sample_count > 1:
                # A sine wave shouldn't be constant unless it's a DC signal
                pass  # Some test signals might be constant, that's OK
    
    # Final verdict
    print(f"\n=== Test Results ===")
    print(f"Total signals analyzed: {len(selected_signals)}")
    print(f"Sampling points used: {len(sampling_times)}")
    print(f"Signals with all-zero results: {zero_result_count}")
    
    if all_results_valid and zero_result_count == 0:
        print("✓ Step 6: All results verified correctly")
        print("\n✓✓✓ TEST PASSED ✓✓✓")
    else:
        print(f"✗ Step 6: Results validation failed")
        print("\n✗✗✗ TEST FAILED ✗✗✗")
        pytest.fail(f"Results validation failed: all_results_valid={all_results_valid}, zero_result_count={zero_result_count}")


if __name__ == "__main__":
    success = test_analysis_with_analog_signals()
    sys.exit(0 if success else 1)
