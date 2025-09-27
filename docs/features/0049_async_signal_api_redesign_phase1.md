# Async Signal Loading API Redesign - Phase 1: AsyncLoadedSignal Implementation

## Phase 1 Overview

Phase 1 focuses on implementing the core `AsyncLoadedSignal` class and new WaveformDB APIs while maintaining backward compatibility with existing code. No GUI components or existing APIs will be modified in this phase.

## 1. Core Implementation Goals

### AsyncLoadedSignal Class
- Implement a Future-like wrapper for asynchronously loaded signals
- Provide thread-safe signal state management
- Support both cached (fast path) and async loading scenarios
- Zero overhead for cached signals

### WaveformDB Integration
- Add new `load_signal()` API alongside existing methods
- Maintain list of pending AsyncLoadedSignal objects
- Update async event handlers to populate AsyncLoadedSignal instances
- Keep all existing APIs functional for backward compatibility

## 2. Implementation Details

### AsyncLoadedSignal Class Implementation

Location: `wavescout/waveform_db.py` (add to existing file)

```python
import threading
from typing import Optional
from dataclasses import dataclass

class AsyncLoadedSignal:
    """Future-like wrapper for asynchronously loaded signals with efficient blocking."""

    def __init__(self, handle: SignalHandle, waveform_db: 'WaveformDB'):
        self._handle = handle
        self._signal: Optional[Signal] = None
        self._loaded = threading.Event()
        self._loading = False
        self._error: Optional[str] = None

        # Fast path: Check if already cached
        if waveform_db.is_signal_cached(handle):
            self._signal = waveform_db._signal_cache[handle]
            self._loaded.set()
        else:
            # Trigger async loading if not already in progress
            if not waveform_db.is_signal_loading(handle):
                waveform_db.load_signals_async([handle])
            self._loading = True

    def is_loaded(self) -> bool:
        """Check if signal is loaded without blocking."""
        return self._loaded.is_set()

    def get_signal_blocking(self, timeout: Optional[float] = None) -> Signal:
        """Get signal, blocking until loaded or timeout occurs."""
        # Fast path - already loaded
        if self._loaded.is_set():
            if self._error:
                raise RuntimeError(f"Signal {self._handle} loading failed: {self._error}")
            return self._signal

        # Slow path - wait for loading
        timeout = timeout or 30.0

        if self._loaded.wait(timeout):
            if self._error:
                raise RuntimeError(f"Signal {self._handle} loading failed: {self._error}")
            return self._signal

        raise TimeoutError(f"Signal {self._handle} loading timed out after {timeout}s")

    def _update_signal(self, signal: Signal) -> None:
        """Called by WaveformDB when signal loads successfully."""
        self._signal = signal
        self._loading = False
        self._loaded.set()

    def _update_error(self, error: str) -> None:
        """Called by WaveformDB when signal loading fails."""
        self._error = error
        self._loading = False
        self._loaded.set()

    @property
    def handle(self) -> SignalHandle:
        """Get the signal handle."""
        return self._handle
```

### WaveformDB Modifications

Location: `wavescout/waveform_db.py` (modify existing class)

**New attributes to add:**
```python
class WaveformDB:
    def __init__(self):
        # ... existing init code ...
        self._pending_signals: List[AsyncLoadedSignal] = []
        self._loading_handles: Set[SignalHandle] = set()
```

**New methods to add:**
```python
def load_signal(self, handle: SignalHandle) -> AsyncLoadedSignal:
    """Load a signal asynchronously, returning an AsyncLoadedSignal wrapper.

    This is the new unified API for signal loading that eliminates race conditions
    and provides future-like semantics.
    """
    async_signal = AsyncLoadedSignal(handle, self)

    # Track pending signals only if not already cached
    if not async_signal.is_loaded():
        self._pending_signals.append(async_signal)
        self._loading_handles.add(handle)

    return async_signal

def is_signal_cached(self, handle: SignalHandle) -> bool:
    """Check if a signal is already in the cache."""
    return handle in self._signal_cache

def is_signal_loading(self, handle: SignalHandle) -> bool:
    """Check if a signal is currently being loaded."""
    return handle in self._loading_handles
```

**Modify async event handler:**
```python
def _on_async_event(self, event: ApplicationEvent) -> None:
    """Handle async loading events and update AsyncLoadedSignal objects."""
    if isinstance(event, SignalLoadedEvent):
        for handle, signal in event.pairs:
            # Update cache (existing code)
            self._signal_cache[handle] = signal

            # NEW: Update pending AsyncLoadedSignal objects
            for async_signal in self._pending_signals[:]:
                if async_signal.handle == handle:
                    async_signal._update_signal(signal)
                    self._pending_signals.remove(async_signal)

            # Remove from loading set
            self._loading_handles.discard(handle)

            # Existing tree update code (keep for compatibility)
            if self.controller:
                self.controller._update_nodes_with_signal(handle, signal)

    elif isinstance(event, SignalLoadingFailedEvent):
        for handle in event.handles:
            # NEW: Update pending AsyncLoadedSignal objects with error
            for async_signal in self._pending_signals[:]:
                if async_signal.handle == handle:
                    async_signal._update_error(event.error)
                    self._pending_signals.remove(async_signal)

            # Remove from loading set
            self._loading_handles.discard(handle)
```

## 3. Unit Test Implementation

Location: `tests/test_async_loaded_signal.py` (new file)

### Test Suite Structure

The test suite consists of two main test classes:
1. **TestAsyncLoadedSignal** - Unit tests for the AsyncLoadedSignal class
2. **TestWaveformDBIntegration** - Integration tests for WaveformDB with AsyncLoadedSignal

### TestAsyncLoadedSignal Test Cases

#### Fixtures
- **qt_app**: Ensures a Qt application instance exists for event processing
- **waveform_db**: Creates a WaveformDB instance with test waveform loaded from `test_inputs/analog_signals_short.fst`

#### Test: test_cached_signal_fast_path
**Purpose**: Verify that cached signals return immediately without async loading
**Steps**:
1. Get a valid signal handle from the loaded waveform
2. Pre-cache the signal using `get_signal()`
3. Create an AsyncLoadedSignal instance
4. Verify signal is immediately available (`is_loaded()` returns True)
5. Verify the loaded signal matches the cached signal

#### Test: test_async_loading_real_signal
**Purpose**: Test async loading of a real signal from FST file
**Steps**:
1. Get a valid signal handle (using second signal to avoid cache)
2. Clear the signal cache to force async loading
3. Create AsyncLoadedSignal - should trigger async loading
4. Wait for async loading with Qt event processing (5 second timeout)
5. Verify signal loaded successfully
6. Verify signal has required methods (`get_value_at`, `get_changes`)

#### Test: test_multiple_signals_concurrent_loading
**Purpose**: Test concurrent loading of multiple signals
**Steps**:
1. Get 5 signal handles from the waveform
2. Clear the signal cache
3. Create multiple AsyncLoadedSignal instances
4. Verify all signals are initially in loading state
5. Wait for all signals to load (10 second timeout)
6. Verify all signals loaded successfully

#### Test: test_blocking_with_timeout
**Purpose**: Test blocking call with timeout on non-cached signal
**Steps**:
1. Get a signal handle and clear cache
2. Mock `load_signals_async` to prevent actual loading
3. Create AsyncLoadedSignal instance
4. Call `get_signal_blocking()` with 0.1 second timeout
5. Verify TimeoutError is raised

#### Test: test_signal_value_access
**Purpose**: Test accessing actual signal values through AsyncLoadedSignal
**Steps**:
1. Find an analog signal handle by searching for "analog" in signal names
2. Create AsyncLoadedSignal instance
3. Wait for loading if needed (5 second timeout)
4. Get the loaded signal and verify it has value changes
5. Verify ability to get values at specific times
6. Confirm value retrieval works correctly

#### Test: test_concurrent_thread_access
**Purpose**: Test thread-safe concurrent access to AsyncLoadedSignal
**Steps**:
1. Get a signal handle and clear cache to force async loading
2. Create AsyncLoadedSignal instance
3. Define reader thread function that calls `get_signal_blocking()` and accesses signal changes
4. Start 5 reader threads concurrently
5. Process Qt events to allow async loading (15 second timeout)
6. Wait for all threads to complete
7. Verify all threads succeeded without errors
8. Verify each thread got valid signal data

### TestWaveformDBIntegration Test Cases

#### Fixtures
- **qt_app**: Ensures a Qt application instance exists for event processing
- **waveform_db**: Creates a WaveformDB instance with test waveform loaded

#### Test: test_load_signal_api_with_real_file
**Purpose**: Test the new load_signal() API with real FST file
**Steps**:
1. Get 3 valid handles from the waveform
2. Clear cache to test loading
3. Request signal loading using `load_signal()` API
4. Verify each returned object is an AsyncLoadedSignal instance
5. Verify handles match requested handles
6. Verify signals are tracked in pending list

#### Test: test_pending_signals_cleared_after_loading
**Purpose**: Test that pending signals are cleared after successful loading
**Steps**:
1. Get 3 signal handles and clear cache
2. Create AsyncLoadedSignals using `load_signal()`
3. Verify pending list has entries
4. Wait for loading to complete (10 second timeout)
5. Verify pending list is cleared
6. Verify all signals are loaded

#### Test: test_event_bus_integration
**Purpose**: Test that AsyncLoadedSignal updates via event bus notifications
**Steps**:
1. Setup event bus if not already configured
2. Get a handle and clear cache
3. Subscribe to SignalLoadedEvent on the event bus
4. Create AsyncLoadedSignal using `load_signal()`
5. Wait for loading (10 second timeout)
6. Verify signal loaded and event was fired
7. Verify the loaded signal is valid

#### Test: test_cache_reuse_performance
**Purpose**: Test that cached signals have zero overhead
**Steps**:
1. Get 10 signal handles
2. Pre-load all signals into cache
3. Measure time to create AsyncLoadedSignals for cached signals
4. Verify all signals are immediately loaded
5. Verify elapsed time is less than 10ms total (< 1ms per signal)
6. Verify all signals are immediately accessible with minimal timeout

#### Test: test_mixed_cached_and_async_signals
**Purpose**: Test handling mix of cached and non-cached signals
**Steps**:
1. Get 6 signal handles
2. Pre-cache the first 3 signals
3. Clear the last 3 signals from cache
4. Load all 6 signals using `load_signal()`
5. Verify first 3 (cached) signals are immediately ready
6. Wait for last 3 (async) signals to load (5 second timeout each)
7. Verify all signals loaded successfully

## 4. Phase 1 Deliverables

1. **AsyncLoadedSignal class** in `wavescout/waveform_db.py`
2. **New WaveformDB methods**: `load_signal()`, `is_signal_cached()`, `is_signal_loading()`
3. **Updated async event handler** to populate AsyncLoadedSignal objects
4. **Comprehensive unit tests** in `tests/test_async_loaded_signal.py`

## 5. Validation Criteria

- All existing tests must pass without modification
- New unit tests achieve 100% coverage of AsyncLoadedSignal
- No changes to GUI components or existing APIs
- Cached signals have zero overhead (fast path)
- Thread-safe concurrent access verified
- Memory usage remains constant (no leaks in pending list)

## 6. Migration Path to Phase 2

Phase 1 establishes the foundation without breaking changes:
- AsyncLoadedSignal is available for new code
- Existing APIs continue to work
- Both old and new patterns can coexist
- Phase 2 will migrate GUI components to use AsyncLoadedSignal
- Phase 2 will deprecate and remove old APIs