# Async Signal Loading API Redesign for Robustness and Ease of Use

## 1. Use Cases and Requirements Analysis

### Core Functionality Requirements

The current async signal loading implementation suffers from several critical issues that need to be addressed:

1. **Race Condition Issues**: If `async_load_signal` completes before `SignalNode` is inserted into tree, the signal will be lost and `SignalNode` will not be updated
2. **Error-Prone Multiple APIs**: Too many overlapping APIs (`get_signal`, `signal_from_handle`, `preload_signals`, `are_signals_cached`) lead to confusion and blocking calls by mistake
3. **Complex State Management**: `Optional[Signal]` in `SignalNodeSignal` requires manual scanning of the tree to update nodes when signals load
4. **No Future-Like Semantics**: No way to check if a signal is being loaded or block until it's available

### Proposed Solution Requirements

**AsyncLoadedSignal Class Design:**
- Acts as a Future-like wrapper around signal loading
- Provides `is_loaded() -> bool` to check loading status
- Provides `get_signal_blocking() -> Signal` for synchronous access when needed
- Eliminates race conditions by maintaining signal state regardless of tree position

**Unified API Requirements:**
- Single entry point: `load_signal(handle: SignalHandle) -> AsyncLoadedSignal`
- Eliminate confusing APIs: Remove `preload_signals`, `get_signal`, `signal_from_handle`
- Prevent blocking calls by making all signal access go through `AsyncLoadedSignal`

**State Management Requirements:**
- WaveformDB maintains list of `AsyncLoadedSignal` objects waiting for loading
- `SignalLoaded` events update `AsyncLoadedSignal` objects and remove completed ones
- `SignalNodeSignal.signal` field becomes `AsyncLoadedSignal` (non-optional)
- Canvas notifications preserved for re-rendering on async events

### Backward Compatibility Requirements

- All existing signal access patterns must continue to work
- Tests should not require significant changes
- UI behavior should remain the same from user perspective
- Signal rendering should show loading state when signal not yet available

## 2. Codebase Research

### Current Signal Loading Architecture

**Key Files and Patterns:**

**`wavescout/data_model.py:135`**:
```python
class SignalNodeSignal(SignalNode):
    signal: Optional["Signal"] = field(default=None, repr=False, compare=False)
```
This Optional pattern is the root cause of race conditions and complexity.

**`wavescout/waveform_db.py:231-276`**: Current signal loading methods
- `get_signal(handle: SignalHandle) -> Optional[pyrox.Signal]` - Synchronous blocking access
- `signal_from_handle(handle: SignalHandle) -> Optional[pyrox.Signal]` - Alias for get_signal
- `preload_signals(handles: List[SignalHandle]) -> None` - Batch preloading
- `are_signals_cached(handles: List[SignalHandle]) -> bool` - Cache checking

**`wavescout/waveform_controller.py:1258-1276`**: Signal update mechanism
```python
def _update_nodes_with_signal(self, handle: SignalHandle, signal: "Signal") -> None:
    """Update all SignalNodeSignal instances with the given handle."""
```
This tree-scanning approach is inefficient and error-prone.

**`wavescout/waveform_db.py:513-545`**: Async loading entry point
```python
def load_signals_async(self, handles: Sequence[SignalHandle]) -> None:
```

**`wavescout/application/events.py:101-117`**: Existing async events
- `SignalLoadingStartedEvent(handles: list[SignalHandle])`
- `SignalLoadedEvent(pairs: list[tuple[SignalHandle, Signal]])`
- `SignalLoadingFailedEvent(handles: list[SignalHandle], error: str)`

### Architecture Patterns

**Event Bus Pattern**: Already established with `EventBus` for async signal notifications
**Controller Pattern**: `WaveformController` coordinates between UI and data model
**Protocol-Based Design**: `WaveformDBProtocol` provides backend abstraction
**Dataclass-Based State**: Strict typing with no `Any` types used throughout

### Current Signal Access Patterns

1. **Direct Signal Access**: `node.signal` access in rendering and UI code
2. **Cache Checking**: `waveform_db.are_signals_cached()` before loading
3. **Batch Loading**: `waveform_db.preload_signals()` for multiple signals
4. **Controller Updates**: Tree scanning in `_update_nodes_with_signal()`

## 3. Implementation Planning

### File-by-File Changes

#### `wavescout/waveform_db.py`

**New AsyncLoadedSignal Class:**
- Add `AsyncLoadedSignal` class with `is_loaded()` and `get_signal_blocking()` methods
- Maintain internal signal state and loading status
- Thread-safe implementation for async updates

**WaveformDB Changes:**
- Add `_pending_signals: List[AsyncLoadedSignal]` to track loading signals
- Add `load_signal(handle: SignalHandle) -> AsyncLoadedSignal` method
- Remove deprecated methods: `preload_signals`, `get_signal`, `signal_from_handle`
- Update `_on_async_event` to update `AsyncLoadedSignal` objects instead of tree scanning

**Integration Points:**
- AsyncLoadedSignal objects receive updates from SignalLoadedEvent
- Completed AsyncLoadedSignal objects removed from pending list
- Event bus notifications preserved for UI updates

#### `wavescout/data_model.py`

**SignalNodeSignal Changes:**
- Change `signal: Optional["Signal"]` to `signal: AsyncLoadedSignal`
- Update `_comparison_state()` and `deep_copy()` methods
- Remove signal field from comparison (since AsyncLoadedSignal handles state)

**Compatibility Layer:**
- Ensure serialization/deserialization continues to work
- Update any direct signal field access patterns

#### `wavescout/waveform_controller.py`

**Controller Method Updates:**
- Remove `_update_nodes_with_signal()` method (no longer needed)
- Update async event handlers to work with new AsyncLoadedSignal system
- Preserve notification callbacks for canvas updates

**Signal Loading Coordination:**
- Update `load_signals_async()` to use new `load_signal()` API
- Ensure proper event propagation for UI updates

#### Files Using Signal Access

**All signal access points need updates:**
- `wavescout/signal_renderer.py` - Rendering logic
- `wavescout/waveform_canvas.py` - Canvas painting
- `wavescout/signal_sampling.py` - Signal processing
- `wavescout/persistence.py` - Session serialization
- `wavescout/snippet_*` files - Snippet handling
- `tests/` - Test files accessing signals

**Pattern Changes:**
- Replace `if node.signal:` with `if node.signal.is_loaded():`
- Replace `node.signal.some_method()` with `node.signal.get_signal_blocking().some_method()`
- For rendering: Check `is_loaded()` first, show loading indicator if false

### Algorithm Descriptions

**AsyncLoadedSignal Loading Algorithm:**
```
1. AsyncLoadedSignal created with handle and loading state = False
2. Added to WaveformDB._pending_signals list
3. Async loading request sent to backend
4. When SignalLoadedEvent received:
   a. Find matching AsyncLoadedSignal in pending list
   b. Update internal signal reference
   c. Set loading state = True
   d. Remove from pending list
5. UI can check is_loaded() or call get_signal_blocking()
```

**WaveformDB.load_signal() Algorithm:**
```
1. Check if signal already cached
2. If cached: Create AsyncLoadedSignal with signal pre-loaded
3. If not cached: Create AsyncLoadedSignal in loading state
4. Add to pending list (if not cached)
5. Trigger async loading (if not cached)
6. Return AsyncLoadedSignal immediately
```

### AsyncLoadedSignal Implementation Details

**Hybrid Approach with Fast Path (Most Efficient):**

The AsyncLoadedSignal class uses a hybrid approach that optimizes for the common case (cached signals) while providing efficient blocking for async loads:

```python
import threading
import time
from typing import Optional
from PySide6.QtWidgets import QApplication

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
        """Get signal, blocking until loaded or timeout occurs.

        Args:
            timeout: Maximum time to wait in seconds (default: 30.0)

        Returns:
            The loaded Signal object

        Raises:
            RuntimeError: If signal loading failed
            TimeoutError: If timeout occurred before loading completed
        """
        # Fast path - already loaded
        if self._loaded.is_set():
            if self._error:
                raise RuntimeError(f"Signal {self._handle} loading failed: {self._error}")
            return self._signal

        # Slow path - wait for loading
        timeout = timeout or 30.0

        # Use threading.Event for efficient waiting without CPU spinning
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

    def __repr__(self) -> str:
        status = "loaded" if self._loaded.is_set() else "loading" if self._loading else "pending"
        return f"AsyncLoadedSignal(handle={self._handle}, status={status})"
```

**Implementation Rationale:**

1. **Fast Path Optimization**: Cached signals return immediately without any synchronization overhead
2. **Efficient Blocking**: Uses `threading.Event.wait()` which blocks at the OS level without CPU spinning
3. **Thread Safety**: `threading.Event` provides atomic operations for loading state
4. **Error Handling**: Proper error propagation with timeout support
6. **Zero Overhead**: Minimal memory footprint and computation cost

**Key Performance Benefits:**

- **Cached signals**: Instant return with zero synchronization overhead
- **Loading signals**: Efficient OS-level blocking without busy waiting
- **Thread safety**: Built-in atomic operations via threading primitives
- **Timeout support**: Prevents indefinite blocking with configurable timeouts
- **Memory efficient**: Lightweight wrapper with minimal state

### UI Integration

**Canvas Rendering Updates:**
- Check `node.signal.is_loaded()` before rendering signal data
- Show "Loading..." placeholder when `is_loaded()` returns False
- Preserve existing async update notifications

**No New UI Components Required:**
- Existing loading indicators can be reused
- Status bar notifications continue to work
- Canvas updates triggered by existing event system

### Performance Considerations

**Memory Usage:**
- AsyncLoadedSignal objects are lightweight wrappers (~80 bytes per instance)
- Zero additional memory overhead for cached signals (fast path)
- Pending signals list size bounded by active loading requests
- `threading.Event` uses minimal OS resources

**Threading Performance:**
- **Cached signals**: Zero synchronization overhead (immediate return)
- **Loading signals**: Efficient OS-level blocking using `threading.Event.wait()`
- **No CPU spinning**: Event-based waiting eliminates busy loops
- **Thread safety**: Built-in atomic operations via threading primitives
- Existing event bus threading model preserved

**Cache Efficiency:**
- Fast path optimization: `O(1)` access for cached signals
- Eliminate redundant cache checking APIs
- Single point of truth for signal loading state
- Reduced complexity in signal access patterns

**Blocking Performance:**
- `threading.Event.wait()` uses efficient OS primitives (futex on Linux, WaitForSingleObject on Windows)
- Configurable timeouts prevent indefinite blocking
- Minimal context switching overhead

### Error Handling

**Loading Failures:**
- AsyncLoadedSignal can represent failed loading state
- get_signal_blocking() can raise appropriate exceptions
- UI can check for loading failure and show error state

**Thread Safety:**
- AsyncLoadedSignal updates must be atomic
- Proper synchronization for pending signals list
- Event handler thread safety preserved

**Backward Compatibility:**
- Migration path for existing signal access code
- Gradual rollout possible with compatibility shims
- Comprehensive test coverage for regression prevention

### Testing Strategy

**Unit Tests:**
- AsyncLoadedSignal behavior testing
- WaveformDB integration testing
- Event handling verification

**Integration Tests:**
- Full async loading workflow
- UI update verification
- Performance regression testing

**Migration Testing:**
- All existing tests must pass with minimal changes
- Signal rendering accuracy verification
- Session save/load functionality testing

### Success Criteria

1. **Elimination of Race Conditions**: AsyncLoadedSignal objects always receive updates regardless of tree position
2. **API Simplification**: Single `load_signal()` entry point replaces multiple confusing APIs
3. **Blocking Call Prevention**: All signal access goes through AsyncLoadedSignal interface
4. **Preserved Functionality**: Existing UI behavior and performance maintained
5. **Test Compatibility**: Minimal test changes required for migration
6. **Type Safety**: Maintain strict typing with no `Any` types introduced