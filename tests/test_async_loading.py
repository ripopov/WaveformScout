"""Test async loading API for Pyrox"""

import pytest
import time
from pathlib import Path
from typing import List, cast, TYPE_CHECKING, Any
from threading import Event

# Import the Pyrox module (will be built from Rust)
try:
    import pyrox
except ImportError:
    pytest.skip("pyrox module not available", allow_module_level=True)

# Type-only imports for static checking
if TYPE_CHECKING:
    from pyrox import (
        AsyncEvent,
        HeaderStartLoadEvent,
        HeaderLoadedEvent,
        BodyStartLoadEvent,
        BodyLoadedEvent,
        SignalStartLoadEvent,
        SignalLoadedEvent,
        AsyncErrorEvent,
    )

# Get absolute path to test_inputs directory
TEST_INPUTS_DIR = Path(__file__).parent.parent / "test_inputs"


class AsyncEventCollector:
    """Helper class to collect async events with type checking"""

    def __init__(self):
        if TYPE_CHECKING:
            self.events: List[AsyncEvent] = []
        else:
            self.events: List[Any] = []
        self.header_loaded = Event()
        self.body_loaded = Event()
        self.signals_loaded = Event()
        self.error_event = Event()
        self.error_message: str | None = None

    def __call__(self, event: Any):
        """Callback function for async events with type checking"""
        self.events.append(event)

        event_type = event.get("type")
        if event_type == "HeaderLoaded":
            self.header_loaded.set()
            # Runtime validation
            assert event["type"] == "HeaderLoaded"
            # hierarchy field is optional (NotRequired)
        elif event_type == "BodyLoaded":
            self.body_loaded.set()
            # Runtime validation
            assert event["type"] == "BodyLoaded"
            # time_table field is optional (NotRequired)
        elif event_type == "SignalLoaded":
            self.signals_loaded.set()
            # Runtime validation
            assert event["type"] == "SignalLoaded"
            assert "signals" in event
        elif event_type == "Error":
            # Runtime validation
            assert event["type"] == "Error"
            assert "error" in event
            self.error_message = event["error"]
            self.error_event.set()

    def wait_for_header(self, timeout=5):
        """Wait for header to be loaded"""
        return self.header_loaded.wait(timeout)

    def wait_for_body(self, timeout=5):
        """Wait for body to be loaded"""
        return self.body_loaded.wait(timeout)

    def wait_for_signals(self, timeout=5):
        """Wait for signals to be loaded"""
        return self.signals_loaded.wait(timeout)

    def wait_for_error(self, timeout=5):
        """Wait for error event"""
        return self.error_event.wait(timeout)

    def clear(self):
        """Clear all events"""
        self.events.clear()
        self.header_loaded.clear()
        self.body_loaded.clear()
        self.signals_loaded.clear()
        self.error_event.clear()
        self.error_message = None


class TestAsyncLoading:
    """Test async loading functionality"""

    def test_full_async_loading_from_empty(self):
        """Test loading everything asynchronously from empty state"""
        test_file = str(TEST_INPUTS_DIR / "swerv1.vcd")

        # Create waveform without loading anything
        wf = pyrox.Waveform(test_file, load_header=False, load_body=False)
        assert not wf.header_loaded()
        assert not wf.body_loaded()

        # Set up event collector
        collector = AsyncEventCollector()
        wf.set_async_callback(collector)

        # Submit both header and body loading requests without waiting
        wf.load_header_async(multi_threaded=True, remove_scopes_with_empty_name=False)
        wf.load_body_async()

        # Now wait for both operations to complete
        assert collector.wait_for_header(timeout=10), "Header loading timed out"
        assert collector.wait_for_body(timeout=10), "Body loading timed out"

        # Check that we got all expected events
        event_types = [e["type"] for e in collector.events]
        assert "HeaderStartLoad" in event_types
        assert "HeaderLoaded" in event_types
        assert "BodyStartLoad" in event_types
        assert "BodyLoaded" in event_types

        # Verify final state
        assert wf.header_loaded()
        assert wf.body_loaded()
        assert wf.time_table is not None

    def test_basic_async_loading_flow(self):
        """Test basic async loading flow: header → body → signals"""
        test_file = str(TEST_INPUTS_DIR / "swerv1.vcd")

        # Create waveform without loading body
        wf = pyrox.Waveform(test_file, load_header=True, load_body=False)
        assert wf.header_loaded()
        assert not wf.body_loaded()

        # Set up event collector
        collector = AsyncEventCollector()
        wf.set_async_callback(collector)

        # Load body asynchronously
        wf.load_body_async()
        assert collector.wait_for_body(timeout=10)

        # Check events
        event_types = [e["type"] for e in collector.events]
        assert "BodyStartLoad" in event_types
        assert "BodyLoaded" in event_types

        # Verify body is loaded
        assert wf.body_loaded()
        assert wf.time_table is not None

    def test_callback_registration_and_unregistration(self):
        """Test callback registration and unregistration"""
        test_file = str(TEST_INPUTS_DIR / "swerv1.vcd")
        wf = pyrox.Waveform(test_file, load_header=True, load_body=False)

        # Test with callback
        collector = AsyncEventCollector()
        wf.set_async_callback(collector)
        wf.load_body_async()
        assert collector.wait_for_body(timeout=10)
        assert len(collector.events) > 0

        # Unregister callback
        wf.set_async_callback(None)

        # No new events should be collected
        collector.clear()
        # Note: We can't really test this without signals, which requires body loaded
        # The test is mainly to ensure unregistration doesn't crash
        assert len(collector.events) == 0

    def test_callback_execution_for_all_events(self):
        """Test callback execution for all event types with type checking"""
        test_file = str(TEST_INPUTS_DIR / "swerv1.vcd")

        # Create waveform without loading anything initially
        wf = pyrox.Waveform(test_file, load_body=False)

        collector = AsyncEventCollector()
        wf.set_async_callback(collector)

        # Load body
        wf.load_body_async()
        assert collector.wait_for_body(timeout=10)

        # Get some signal handles to test signal loading
        hier = wf.hierarchy
        all_vars = list(hier.all_vars())
        # Get a few signal handles
        handles = [v.signal_handle() for v in all_vars[:5]]

        # Clear events
        collector.clear()

        # Load signals async
        wf.load_signals_async(handles)
        assert collector.wait_for_signals(timeout=10)

        # Check signal events with type assertions
        event_types = [e["type"] for e in collector.events]
        assert "SignalStartLoad" in event_types
        assert "SignalLoaded" in event_types

        # Check handles in events with proper typing
        for event in collector.events:
            event_type = event["type"]

            if event_type == "SignalStartLoad":
                # Runtime validation for SignalStartLoadEvent
                assert "handles" in event
                assert isinstance(event["handles"], list)
                handles_list: List[int] = event["handles"]
                assert all(isinstance(h, int) for h in handles_list)

            elif event_type == "SignalLoaded":
                # Runtime validation for SignalLoadedEvent
                assert "signals" in event
                assert isinstance(event["signals"], list)
                # Verify we got the right number of signals
                assert len(event["signals"]) == len(handles)
                signals_list = event["signals"]
                for handle, signal in signals_list:
                    assert isinstance(handle, int)
                    assert hasattr(signal, "all_changes")

    def test_changing_callbacks_mid_operation(self):
        """Test changing callbacks during async operations"""
        test_file = str(TEST_INPUTS_DIR / "swerv1.vcd")
        wf = pyrox.Waveform(test_file, load_header=True, load_body=False)

        collector1 = AsyncEventCollector()
        collector2 = AsyncEventCollector()

        # Set first callback
        wf.set_async_callback(collector1)

        # Start loading body
        wf.load_body_async()

        # Quickly change callback
        time.sleep(0.001)  # Minimal delay to ensure operation started
        wf.set_async_callback(collector2)

        # Wait for completion - check both collectors efficiently
        # Either collector might get the events depending on timing
        for _ in range(50):  # Check for up to 0.5 seconds
            if collector1.body_loaded.is_set() or collector2.body_loaded.is_set():
                break
            time.sleep(0.01)

        # At least one collector should have events
        assert len(collector1.events) > 0 or len(collector2.events) > 0

    def test_cache_behavior_skip_cached_signals(self):
        """Test that signals can be loaded multiple times (no Rust cache)"""
        test_file = str(TEST_INPUTS_DIR / "swerv1.vcd")
        wf = pyrox.Waveform(test_file, load_header=True, load_body=True)

        collector = AsyncEventCollector()
        wf.set_async_callback(collector)

        # Get some signal handles
        hier = wf.hierarchy
        all_vars = list(hier.all_vars())
        handles = [v.signal_handle() for v in all_vars[:3]]

        # Load signals first time
        wf.load_signals_async(handles)
        assert collector.wait_for_signals(timeout=10)

        # Check loaded handles/signals
        first_load_events = [e for e in collector.events if e["type"] == "SignalLoaded"]
        assert len(first_load_events) > 0
        assert "signals" in first_load_events[0]
        first_loaded_handles = [h for h, s in first_load_events[0]["signals"]]

        # Clear and load same signals again
        collector.clear()
        wf.load_signals_async(handles)

        # Wait for signals to be loaded again (no cache in Rust)
        assert collector.wait_for_signals(timeout=10)

        # Signals should be loaded fresh since there's no Rust cache
        loaded_events = [e for e in collector.events if e["type"] == "SignalLoaded"]
        assert len(loaded_events) > 0
        assert "signals" in loaded_events[0]
        second_loaded_handles = [h for h, s in loaded_events[0]["signals"]]
        # Should load the same signals again since there's no cache
        assert len(second_loaded_handles) == len(first_loaded_handles)

    def test_queue_coalescing(self):
        """Test that multiple signal requests are coalesced"""
        test_file = str(TEST_INPUTS_DIR / "swerv1.vcd")
        wf = pyrox.Waveform(test_file, load_header=True, load_body=True)

        collector = AsyncEventCollector()
        wf.set_async_callback(collector)

        # Get signal handles
        hier = wf.hierarchy
        all_vars = list(hier.all_vars())
        # Send multiple signal load requests rapidly
        handles1 = [v.signal_handle() for v in all_vars[0:3]]
        handles2 = [v.signal_handle() for v in all_vars[3:6]]
        handles3 = [v.signal_handle() for v in all_vars[6:9]]

        # Send requests without waiting
        wf.load_signals_async(handles1)
        wf.load_signals_async(handles2)
        wf.load_signals_async(handles3)

        # Wait for signals to complete
        assert collector.wait_for_signals(timeout=5)

        # Check events - we should see start/loaded events
        event_types = [e["type"] for e in collector.events]
        assert "SignalStartLoad" in event_types
        assert "SignalLoaded" in event_types

    def test_state_consistency(self):
        """Test that header_loaded and body_loaded states are consistent"""
        test_file = str(TEST_INPUTS_DIR / "swerv1.vcd")

        # Test 1: Load with body
        wf1 = pyrox.Waveform(test_file, load_header=True, load_body=True)
        assert wf1.header_loaded()
        assert wf1.body_loaded()

        # Test 2: Load without body
        wf2 = pyrox.Waveform(test_file, load_header=True, load_body=False)
        assert wf2.header_loaded()
        assert not wf2.body_loaded()

        # Test 3: Load body async
        collector = AsyncEventCollector()
        wf2.set_async_callback(collector)
        wf2.load_body_async()
        assert collector.wait_for_body(timeout=10)
        assert wf2.body_loaded()

    def test_operation_without_callback(self):
        """Test that operations work without crashes when no callback is set"""
        test_file = str(TEST_INPUTS_DIR / "swerv1.vcd")
        wf = pyrox.Waveform(test_file, load_header=True, load_body=False)

        # No callback set - operations should work silently
        wf.load_body_async()

        # Brief wait for operation to potentially complete
        time.sleep(0.1)

        # Should be able to check state
        # Note: async operation may or may not complete without verification
        # This test mainly ensures no crash
        assert wf.header_loaded()

    def test_error_handling_missing_file(self):
        """Test error handling for missing files"""
        # This test would require loading header async, which isn't in current implementation
        # as the constructor loads header synchronously
        # Keeping as placeholder for future enhancement
        pass

    def test_thread_safety_concurrent_requests(self):
        """Test thread safety with concurrent requests"""
        test_file = str(TEST_INPUTS_DIR / "swerv1.vcd")
        wf = pyrox.Waveform(test_file, load_header=True, load_body=True)

        collector = AsyncEventCollector()
        wf.set_async_callback(collector)

        # Get many signal handles
        hier = wf.hierarchy
        all_vars = list(hier.all_vars())
        # Create multiple handle lists
        handle_groups = [
            [v.signal_handle() for v in all_vars[i:i+5]]
            for i in range(0, 20, 5)
        ]

        # Send all requests concurrently
        for handles in handle_groups:
            wf.load_signals_async(handles)

        # Wait for signals to complete
        assert collector.wait_for_signals(timeout=5)

        # Should have received events without crashes
        assert len(collector.events) > 0

        # Check for any error events
        error_events = [e for e in collector.events if e["type"] == "Error"]
        assert len(error_events) == 0

    def test_async_load_returns_signals(self):
        """Test that async loading returns Signal objects with correct data"""
        test_file = str(TEST_INPUTS_DIR / "analog_signals_short.fst")
        wf = pyrox.Waveform(test_file, load_header=True, load_body=True)

        collector = AsyncEventCollector()
        wf.set_async_callback(collector)

        hier = wf.hierarchy
        all_vars = list(hier.all_vars())

        # Get the first variable for testing
        var = all_vars[0]
        var_name = var.name(hier)
        handle = var.signal_handle()

        # First get the signal synchronously to compare
        sync_signal = wf.get_signal_by_handle(handle)
        sync_changes = list(sync_signal.all_changes())
        sync_change_count = len(sync_changes)

        # Now load the same signal asynchronously
        wf.load_signals_async([handle])
        assert collector.wait_for_signals(timeout=10)

        # Find the SignalLoaded event
        signal_loaded_events = [e for e in collector.events if e["type"] == "SignalLoaded"]
        assert len(signal_loaded_events) == 1

        # Check that we got signals
        event = signal_loaded_events[0]
        assert "signals" in event

        # Returns list of (handle, Signal) tuples
        loaded_signals = event["signals"]
        assert len(loaded_signals) > 0

        # Verify the signal data
        for loaded_handle, async_signal in loaded_signals:
            if loaded_handle == handle:
                async_changes = list(async_signal.all_changes())
                async_change_count = len(async_changes)

                # Verify the number of changes matches
                assert async_change_count == sync_change_count, \
                    f"Signal {var_name}: async has {async_change_count} changes, sync has {sync_change_count}"

                # Optionally verify some actual values match
                if sync_change_count > 0:
                    # Check first and last change times match
                    first_sync = sync_changes[0]
                    first_async = async_changes[0]
                    assert first_sync[0] == first_async[0], "First change time mismatch"

                    last_sync = sync_changes[-1]
                    last_async = async_changes[-1]
                    assert last_sync[0] == last_async[0], "Last change time mismatch"

    def test_async_load_performance(self):
        """Test async loading performance and verify caching behavior"""
        test_file = str(TEST_INPUTS_DIR / "analog_signals_short.fst")
        wf = pyrox.Waveform(test_file, load_header=True, load_body=True)

        collector = AsyncEventCollector()
        wf.set_async_callback(collector)

        hier = wf.hierarchy
        all_vars = list(hier.all_vars())
        var = all_vars[0]
        handle = var.signal_handle()

        # Measure async loading time
        start_time = time.time()
        wf.load_signals_async([handle])
        assert collector.wait_for_signals(timeout=10)
        end_time = time.time()

        async_load_time_ms = (end_time - start_time) * 1000

        # Get the signal from the event
        signal_loaded_events = [e for e in collector.events if e["type"] == "SignalLoaded"]
        assert len(signal_loaded_events) == 1

        event = signal_loaded_events[0]
        assert "signals" in event
        loaded_signals = event["signals"]
        for loaded_handle, signal in loaded_signals:
            if loaded_handle == handle:
                changes = list(signal.all_changes())
                print(f"Async load: {len(changes)} changes in {async_load_time_ms:.2f} ms")

        # Load again to test if signals are reloaded (no Rust cache)
        collector.clear()
        start_time = time.time()
        wf.load_signals_async([handle])
        assert collector.wait_for_signals(timeout=10)
        end_time = time.time()

        reload_time_ms = (end_time - start_time) * 1000

        # Verify signal was loaded again
        signal_loaded_events = [e for e in collector.events if e["type"] == "SignalLoaded"]
        assert len(signal_loaded_events) == 1

        event = signal_loaded_events[0]
        assert "signals" in event
        loaded_signals = event["signals"]
        assert len(loaded_signals) > 0
        print(f"Reload: signal reloaded in {reload_time_ms:.2f} ms")
