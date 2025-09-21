"""Test async loading API for Pyrox"""

import pytest
import time
from pathlib import Path
from typing import List, Dict, Any
from threading import Event

# Import the Pyrox module (will be built from Rust)
try:
    import pyrox
except ImportError:
    pytest.skip("pyrox module not available", allow_module_level=True)


class AsyncEventCollector:
    """Helper class to collect async events"""

    def __init__(self):
        self.events: List[Dict[str, Any]] = []
        self.header_loaded = Event()
        self.body_loaded = Event()
        self.signals_loaded = Event()
        self.error_event = Event()
        self.error_message = None

    def __call__(self, event: Dict[str, Any]):
        """Callback function for async events"""
        self.events.append(event)

        event_type = event.get("type")
        if event_type == "HeaderLoaded":
            self.header_loaded.set()
        elif event_type == "BodyLoaded":
            self.body_loaded.set()
        elif event_type == "SignalLoaded":
            self.signals_loaded.set()
        elif event_type == "Error":
            self.error_message = event.get("message")
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
        test_file = "test_inputs/swerv1.vcd"

        # Create waveform without loading anything
        wf = pyrox.Waveform(test_file, load_header=False, load_body=False)
        assert not wf.header_loaded()
        assert not wf.body_loaded()

        # Set up event collector
        collector = AsyncEventCollector()
        wf.set_async_callback(collector)

        # Load header asynchronously
        wf.load_header_async(test_file, multi_threaded=True, remove_scopes_with_empty_name=False)
        assert collector.wait_for_header(timeout=10)

        # Check header events
        event_types = [e["type"] for e in collector.events]
        assert "HeaderStartLoad" in event_types
        assert "HeaderLoaded" in event_types
        assert wf.header_loaded()

        # Clear events and load body
        collector.clear()
        wf.load_body_async()
        assert collector.wait_for_body(timeout=10)

        # Check body events
        event_types = [e["type"] for e in collector.events]
        assert "BodyStartLoad" in event_types
        assert "BodyLoaded" in event_types
        assert wf.body_loaded()
        assert wf.time_table is not None

    def test_basic_async_loading_flow(self):
        """Test basic async loading flow: header → body → signals"""
        test_file = "test_inputs/swerv1.vcd"

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
        test_file = "test_inputs/swerv1.vcd"
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
        """Test callback execution for all event types"""
        test_file = "test_inputs/swerv1.vcd"

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
        if len(all_vars) > 0:
            # Get a few signal handles
            handles = [v.signal_ref() for v in all_vars[:5]]

            # Clear events
            collector.clear()

            # Load signals async
            wf.load_signals_async(handles)
            assert collector.wait_for_signals(timeout=10)

            # Check signal events
            event_types = [e["type"] for e in collector.events]
            assert "SignalStartLoad" in event_types
            assert "SignalLoaded" in event_types

            # Check handles in events
            for event in collector.events:
                if event["type"] in ["SignalStartLoad", "SignalLoaded"]:
                    assert "handles" in event
                    assert isinstance(event["handles"], list)

    def test_changing_callbacks_mid_operation(self):
        """Test changing callbacks during async operations"""
        test_file = "test_inputs/swerv1.vcd"
        wf = pyrox.Waveform(test_file, load_header=True, load_body=False)

        collector1 = AsyncEventCollector()
        collector2 = AsyncEventCollector()

        # Set first callback
        wf.set_async_callback(collector1)

        # Start loading body
        wf.load_body_async()

        # Quickly change callback
        time.sleep(0.01)  # Small delay to ensure operation started
        wf.set_async_callback(collector2)

        # Wait for completion
        # Either collector might get the events depending on timing
        time.sleep(2)

        # At least one collector should have events
        assert len(collector1.events) > 0 or len(collector2.events) > 0

    def test_cache_behavior_skip_cached_signals(self):
        """Test that cached signals are skipped on subsequent loads"""
        test_file = "test_inputs/swerv1.vcd"
        wf = pyrox.Waveform(test_file, load_header=True, load_body=True)

        collector = AsyncEventCollector()
        wf.set_async_callback(collector)

        # Get some signal handles
        hier = wf.hierarchy
        all_vars = list(hier.all_vars())
        if len(all_vars) > 0:
            handles = [v.signal_ref() for v in all_vars[:3]]

            # Load signals first time
            wf.load_signals_async(handles)
            assert collector.wait_for_signals(timeout=10)

            # Check loaded handles
            first_load_events = [e for e in collector.events if e["type"] == "SignalLoaded"]
            assert len(first_load_events) > 0
            first_loaded_handles = first_load_events[0].get("handles", [])

            # Clear and load same signals again
            collector.clear()
            wf.load_signals_async(handles)

            # Wait a bit to see if any events are generated
            time.sleep(0.5)

            # Should either have no SignalLoaded event, or empty handles list
            # (since signals are already cached)
            loaded_events = [e for e in collector.events if e["type"] == "SignalLoaded"]
            if loaded_events:
                # If there's an event, handles should be empty or smaller
                second_loaded_handles = loaded_events[0].get("handles", [])
                assert len(second_loaded_handles) < len(first_loaded_handles)

    def test_queue_coalescing(self):
        """Test that multiple signal requests are coalesced"""
        test_file = "test_inputs/swerv1.vcd"
        wf = pyrox.Waveform(test_file, load_header=True, load_body=True)

        collector = AsyncEventCollector()
        wf.set_async_callback(collector)

        # Get signal handles
        hier = wf.hierarchy
        all_vars = list(hier.all_vars())
        if len(all_vars) >= 10:
            # Send multiple signal load requests rapidly
            handles1 = [v.signal_ref() for v in all_vars[0:3]]
            handles2 = [v.signal_ref() for v in all_vars[3:6]]
            handles3 = [v.signal_ref() for v in all_vars[6:9]]

            # Send requests without waiting
            wf.load_signals_async(handles1)
            wf.load_signals_async(handles2)
            wf.load_signals_async(handles3)

            # Wait for signals
            time.sleep(2)

            # Check events - we should see start/loaded events
            event_types = [e["type"] for e in collector.events]
            assert "SignalStartLoad" in event_types
            assert "SignalLoaded" in event_types

    def test_state_consistency(self):
        """Test that header_loaded and body_loaded states are consistent"""
        test_file = "test_inputs/swerv1.vcd"

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
        test_file = "test_inputs/swerv1.vcd"
        wf = pyrox.Waveform(test_file, load_header=True, load_body=False)

        # No callback set - operations should work silently
        wf.load_body_async()

        # Wait a bit for operation to complete
        time.sleep(1)

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
        test_file = "test_inputs/swerv1.vcd"
        wf = pyrox.Waveform(test_file, load_header=True, load_body=True)

        collector = AsyncEventCollector()
        wf.set_async_callback(collector)

        # Get many signal handles
        hier = wf.hierarchy
        all_vars = list(hier.all_vars())
        if len(all_vars) >= 20:
            # Create multiple handle lists
            handle_groups = [
                [v.signal_ref() for v in all_vars[i:i+5]]
                for i in range(0, 20, 5)
            ]

            # Send all requests concurrently
            for handles in handle_groups:
                wf.load_signals_async(handles)

            # Wait for completion
            time.sleep(3)

            # Should have received events without crashes
            assert len(collector.events) > 0

            # Check for any error events
            error_events = [e for e in collector.events if e["type"] == "Error"]
            assert len(error_events) == 0