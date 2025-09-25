# Async Signal Loading Implementation Plan

## 1. Use Cases and Requirements Analysis

### Core Functionality
Refactor Scout to use the async signal loading API (`load_signals_async`) instead of synchronous loading to prevent UI blocking during signal data retrieval.

### Specific Requirements from User Prompt
1. **Signal Loading Entry Points** (must all be converted to async):
   - VarsView double-click on a signal
   - VarsView multi-select + i/I shortcut
   - Session restoration from JSON file (persistence)
   - Copy-paste operations from SignalNames panel
   - Snippet instantiation

2. **SignalNodeSignal Creation Algorithm**:
   - Check if signal is already cached in `waveform_db`
   - If cached: create SignalNodeSignal using cached signal
   - If not cached: create SignalNodeSignal with `None`/empty `Optional[Signal]` and start background loading

3. **Event Management**:
   - WaveformSession manages `SignalLoaded` events from pyrox
   - Update signals in design tree when loaded
   - Display `SignalStartLoad`/`SignalLoaded` events in status bar

4. **Loading State Tracking**:
   - Maintain list of signals not yet loaded
   - Prevent duplicate `load_signals_async` requests (e.g., double-clicking twice)

5. **UI Behavior**:
   - Display SignalNodes instantly in SignalNamesView
   - Show "Loading..." in WaveformCanvas rows for nodes with empty signal Optional
   - Cannot render waveform values until signals are loaded

6. **Canvas Re-rendering**:
   - `SignalLoaded` event triggers re-rendering via WaveformController

7. **Legacy Test Support**:
   - Provide synchronous wait mechanism for tests that rely on signals being loaded

## 2. Codebase Research

### Async Loading API (pyrox.pyi)
- **Events**: `SignalStartLoadEvent`, `SignalLoadedEvent` with handles and signal objects
- **Callback**: `AsyncCallback = Callable[[AsyncEvent], None]`
- **Methods**: `set_async_callback()`, `load_signals_async(handles: List[SignalHandle])`
- **Event Data**: `SignalLoadedEvent` contains `List[Tuple[SignalHandle, Signal]]`

### Current Signal Loading Implementation
1. **scout.py:1226-1424**: Main signal loading logic
   - `_on_signals_selected()`: Entry point from design tree
   - `_load_signals_async()`: Existing async loader with QProgressDialog
   - `_add_node_to_session()`: Adds nodes after loading

2. **waveform_db.py:196-249**:
   - `get_signal()`: Synchronous signal retrieval with Python-side cache
   - `are_signals_cached()`: Checks if signals are in cache
   - `preload_signals()`: Batch signal loading (synchronous)

3. **data_model.py:129-149**:
   - `SignalNodeSignal`: Currently has `signal: Optional[Signal]` field
   - `var: Var` field is non-optional (recently added)

4. **waveform_loader.py:11-58**:
   - `create_signal_node_from_var()`: Creates SignalNodeSignal instances
   - Currently doesn't populate the signal field

5. **design_tree_view.py:200-209**:
   - Creates SignalNodeSignal and immediately loads signal synchronously

### Event System (application/)
- **EventBus**: Publish-subscribe pattern for application events
- **Event base class**: All events inherit from `Event` with timestamp
- No existing signal loading events defined

### Current Async Pattern (scout.py)
- Uses `QThreadPool` with `LoaderRunnable` for background loading
- Shows `QProgressDialog` during loading
- Stores pending nodes in `_loading_state`

## 3. Implementation Planning

### New Event Classes

**File**: `wavescout/application/events.py`
- Add `SignalLoadingStartedEvent`: Contains list of handles being loaded
- Add `SignalLoadedEvent`: Contains list of (handle, Signal) tuples
- Add `SignalLoadingFailedEvent`: Contains handles that failed and error message

### WaveformDB Changes

**File**: `wavescout/waveform_db.py`

**New Fields**:
- `_loading_handles: Set[SignalHandle]` - Track handles currently being loaded
- `_async_callback_set: bool` - Track if callback is registered

**Modified Methods**:
- `open()`: Register async callback with pyrox.Waveform
- `get_signal()`: Return None if signal is being loaded (check `_loading_handles`)
- `close()`: Clear loading state and unregister callback

**New Methods**:
- `_on_async_event(event)`: Handle pyrox async events, publish to EventBus
- `load_signals_async(handles)`: Filter out cached/loading signals, call pyrox API
- `is_signal_loading(handle)`: Check if handle is in `_loading_handles`
- `wait_for_all_signals(timeout)`: Synchronous wait for tests

### WaveformSession Changes

**File**: `wavescout/data_model.py`

**New Fields**:
- `loading_signals: Set[SignalHandle]` - Track loading state at session level

**New Methods**:
- `update_signal_for_handle(handle, signal)`: Update all nodes with this handle
- `get_loading_count()`: Return number of signals currently loading

### WaveformController Changes

**File**: `wavescout/waveform_controller.py`

**New Methods**:
- `_on_signal_loaded(event)`: Handle SignalLoadedEvent
  - Update session nodes
  - Trigger canvas redraw via callbacks
- `_on_signal_loading_started(event)`: Update loading state
- Subscribe to events in `__init__`

### Signal Loading Entry Points

**File**: `scout.py`

**Modified Methods**:
- `_on_signals_selected()`:
  - Create nodes with `signal=None` for uncached signals
  - Add nodes immediately to session
  - Trigger async loading for uncached handles
  - Remove progress dialog logic

- `_add_node_to_session()`:
  - Accept nodes with `signal=None`
  - No longer wait for signals to be loaded

**File**: `wavescout/design_tree_view.py`

**Modified Methods**:
- `_create_signal_node()`:
  - Don't call `get_signal()` synchronously
  - Check if cached, set signal field accordingly
  - Return node with or without signal

**File**: `wavescout/persistence.py`

**Modified Methods**:
- Session loading:
  - Create nodes without signals first
  - Collect all handles needing loading
  - Trigger single async load for all handles
  - Don't block on signal loading

### UI Updates

**File**: `wavescout/waveform_canvas.py`

**Modified Methods**:
- `paintEvent()` or signal rendering:
  - Check if `node.signal is None`
  - Display "Loading..." text for loading signals
  - Skip waveform rendering for loading signals

**File**: `wavescout/signal_names_view.py`
- No changes needed - names display immediately

**File**: `scout.py`

**Status Bar Updates**:
- Subscribe to `SignalLoadingStartedEvent` and `SignalLoadedEvent`
- Update status bar with loading progress

### Copy-Paste Support

**File**: `wavescout/signal_names_view.py`

**Modified Methods**:
- `_paste_signals()`:
  - Create nodes without waiting for signals
  - Trigger async loading for uncached signals

### Snippet Support

**File**: `wavescout/snippet_window.py` (if exists)
- Apply same pattern: create nodes first, load async

### Test Support

**File**: `wavescout/waveform_db.py`

**New Method**:
```python
def wait_for_all_signals(self, timeout: float = 5.0) -> bool:
    """Wait for all pending signals to load. For testing only."""
    start = time.time()
    while self._loading_handles:
        if time.time() - start > timeout:
            return False
        time.sleep(0.01)
        QApplication.processEvents()
    return True
```

**File**: `tests/conftest.py` or test files
- Add fixture or helper that calls `wait_for_all_signals()` after operations

### Algorithm: Async Signal Loading Flow

1. **User triggers signal addition** (double-click, paste, etc.)
2. **Create SignalNodeSignal**:
   ```
   handle = var.signal_handle()
   if waveform_db.are_signals_cached([handle]):
       signal = waveform_db.get_signal(handle)
   else:
       signal = None
       handles_to_load.append(handle)
   node = SignalNodeSignal(..., signal=signal)
   ```
3. **Add node to session immediately**
4. **Trigger async loading if needed**:
   ```
   if handles_to_load:
       waveform_db.load_signals_async(handles_to_load)
   ```
5. **WaveformDB processes async events**:
   - Receives `SignalLoadedEvent` from pyrox
   - Updates cache
   - Publishes application event via EventBus
6. **WaveformController handles event**:
   - Updates session nodes with loaded signals
   - Triggers canvas redraw
7. **Canvas repaints**:
   - Nodes with signals render normally
   - Nodes without signals show "Loading..."

### Performance Considerations

1. **Batch Loading**: Collect multiple signal requests and load in batches
2. **Duplicate Prevention**: Track loading handles to prevent duplicate requests
3. **Cache Management**: Existing Python-side cache remains for fast access
4. **Event Throttling**: Consider throttling canvas redraws during bulk loading

### Migration Strategy

1. **Phase 1**: Implement infrastructure (events, async callback)
2. **Phase 2**: Convert one entry point (e.g., design tree double-click)
3. **Phase 3**: Convert remaining entry points
4. **Phase 4**: Add test support and update tests
5. **Phase 5**: Remove old synchronous loading code