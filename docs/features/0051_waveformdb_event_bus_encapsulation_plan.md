# Feature Plan: WaveformDB Event Bus Encapsulation

## 1. Use Cases and Requirements Analysis

### Core Problem
WaveformController currently violates encapsulation by directly accessing and manipulating private attributes of WaveformDB (`_event_bus`, `_event_bridge`, `_loading_handles`) at two locations:
- `wavescout/core/waveform_controller.py:121-148` in `set_session()`
- `wavescout/core/waveform_controller.py:185-188` in `open_waveform_file()`

This creates tight coupling, makes testing difficult, and exposes implementation details that should be private to WaveformDB.

### Requirements

1. **Encapsulation**: WaveformDB should own and manage its event bus, event bridge, and async loading infrastructure without external classes reaching into its private attributes
2. **Initialization**: WaveformDB should provide a clean public API for attaching an event bus, either through constructor injection or a dedicated method
3. **Retry Logic**: The async retry logic for signals that started loading before the event bus was attached should live inside WaveformDB, close to `_on_async_event()` where it belongs
4. **Backwards Compatibility**: Existing functionality must be preserved - sessions loaded in background threads must still get their event bus properly connected
5. **Testability**: The refactored design should make it easier to unit test both WaveformDB and WaveformController in isolation

### Success Criteria
- WaveformController never accesses `_event_bus`, `_event_bridge`, or `_loading_handles` attributes of WaveformDB
- WaveformDB provides a public `attach_event_bus()` method or accepts event_bus in constructor
- Async loading retry logic moves from WaveformController to WaveformDB
- All existing tests pass without modification
- No behavioral changes from user perspective

## 2. Codebase Research

### Current Architecture

#### WaveformDB (`wavescout/core/waveform_db.py`)
- **Lines 217-230**: Constructor accepts optional `event_bus` parameter and creates `AsyncEventBridge` if provided
- **Lines 224-226**: Private attributes: `_event_bus`, `_event_bridge`, `_pending_signals`, `_loading_handles`
- **Lines 504-570**: `_on_async_event()` callback handles async loading events from pyrox backend
- **Lines 571-603**: `load_signals_async()` triggers async signal loading
- **Lines 651-659**: `load_signal()` returns `AsyncLoadedSignal` wrapper

Current initialization pattern:
```python
def __init__(self, event_bus: Optional[EventBus] = None) -> None:
    self._event_bus = event_bus
    self._event_bridge: Optional[AsyncEventBridge] = None
    if self._event_bus:
        self._event_bridge = AsyncEventBridge(self._event_bus)
```

#### WaveformController (`wavescout/core/waveform_controller.py`)

**Problem Location 1: Lines 120-148 in `set_session()`**
```python
from wavescout.core.waveform_db import WaveformDB, AsyncEventBridge
if isinstance(primary_file.waveform_db, WaveformDB):
    waveform_db = primary_file.waveform_db
    # Direct access to private attributes
    if hasattr(waveform_db, '_event_bus') and waveform_db._event_bus is None:
        waveform_db._event_bus = self.event_bus
        waveform_db._event_bridge = AsyncEventBridge(self.event_bus)
        # Re-register async callback
        if waveform_db.waveform:
            waveform_db.waveform.set_async_callback(waveform_db._on_async_event)
        # Retry logic for signals that were loading before event bus attached
        if hasattr(waveform_db, '_loading_handles') and waveform_db._loading_handles:
            handles_to_reload = list(waveform_db._loading_handles)
            if handles_to_reload:
                waveform_db._loading_handles.clear()
                waveform_db.load_signals_async(handles_to_reload)
```

**Problem Location 2: Lines 185-188 in `open_waveform_file()`**
```python
waveform_db = WaveformDB()
waveform_db._event_bus = self.event_bus
from wavescout.core.waveform_db import AsyncEventBridge
waveform_db._event_bridge = AsyncEventBridge(self.event_bus)
waveform_db.open(file_path)
```

#### AsyncEventBridge (`wavescout/core/waveform_db.py:181-212`)
- Qt-based bridge for thread-safe event emission
- Converts async callbacks from worker threads into Qt signals
- Emits `SignalLoadingStartedEvent`, `SignalLoadedEvent`, `SignalLoadingFailedEvent`

### Key Observations

1. **Two Initialization Patterns**: WaveformDB is created in two ways:
   - In `open_waveform_file()`: Created fresh, event bus attached before `open()`
   - In `set_session()`: Already exists (from session loading), event bus attached after the fact

2. **Late Binding Problem**: Sessions loaded in background threads create WaveformDB instances without event bus. The controller must "fix up" these instances later.

3. **Retry Logic**: When event bus is attached late, some signals may already be in `_loading_handles` but their async callbacks were never registered. The controller detects this and retries.

4. **Callback Registration**: `waveform.set_async_callback()` is called in `WaveformDB.open()` (line 266), but only works if `_event_bus` is set.

## 3. Implementation Planning

### Design Decision: Hybrid Approach

Given the two initialization patterns, we'll provide both constructor injection AND a late-binding method:

1. **Constructor parameter** (already exists): For fresh WaveformDB instances in `open_waveform_file()`
2. **`attach_event_bus()` method** (new): For late binding in `set_session()`

### Data Model Changes

**File**: `wavescout/core/waveform_db.py`

No dataclass changes needed - this is purely an encapsulation refactor.

### File-by-File Implementation Plan

#### File: `wavescout/core/waveform_db.py`

**Changes Required**:

1. **New public method `attach_event_bus()`** (add after `__init__`):
   - Accept `event_bus: EventBus` parameter
   - Create and assign `_event_bridge = AsyncEventBridge(event_bus)`
   - Store `_event_bus = event_bus`
   - If `self.waveform` exists, call `self.waveform.set_async_callback(self._on_async_event)`
   - **Retry logic**: If `self._loading_handles` is non-empty:
     - Capture handles: `handles_to_retry = list(self._loading_handles)`
     - Clear the set: `self._loading_handles.clear()`
     - Re-trigger loading: `self.load_signals_async(handles_to_retry)`
   - Return `None`

2. **Guard in `open()` method** (line 265-266):
   - Change from unconditional callback registration to conditional:
   ```python
   # Only register callback if event bus is attached
   if self._event_bus and self.waveform:
       self.waveform.set_async_callback(self._on_async_event)
   ```

**Integration Points**:
- Called by `WaveformController.set_session()` for late binding
- Constructor parameter path remains unchanged for `open_waveform_file()`

#### File: `wavescout/core/waveform_controller.py`

**Changes Required**:

1. **Simplify `set_session()` method** (lines 120-150):
   - Remove `hasattr()` checks and direct attribute access
   - Replace entire block with:
   ```python
   from wavescout.core.waveform_db import WaveformDB
   if isinstance(primary_file.waveform_db, WaveformDB):
       waveform_db = primary_file.waveform_db
       waveform_db.attach_event_bus(self.event_bus)
   ```
   - Remove import of `AsyncEventBridge` (no longer needed)

2. **Simplify `open_waveform_file()` method** (lines 185-188):
   - Create WaveformDB with event_bus in constructor:
   ```python
   waveform_db = WaveformDB(event_bus=self.event_bus)
   waveform_db.open(file_path)
   ```
   - Remove manual `_event_bus` and `_event_bridge` assignment
   - Remove import of `AsyncEventBridge` (no longer needed)

**Integration Points**:
- Calls `WaveformDB.attach_event_bus()` in session loading path
- Uses constructor parameter in file opening path

### Algorithm: `WaveformDB.attach_event_bus()`

```
PROCEDURE attach_event_bus(event_bus):
    1. Store event_bus reference:
       self._event_bus = event_bus

    2. Create Qt signal bridge for thread safety:
       self._event_bridge = AsyncEventBridge(event_bus)

    3. Register async callback if waveform already loaded:
       IF self.waveform is not None THEN
           self.waveform.set_async_callback(self._on_async_event)
       END IF

    4. Retry any signals that were loading before event bus attached:
       IF self._loading_handles is not empty THEN
           handles_to_retry = list(self._loading_handles)
           self._loading_handles.clear()
           self.load_signals_async(handles_to_retry)
       END IF
END PROCEDURE
```

### Logic Flow Comparison

#### Before (Current)
```
WaveformController.set_session():
  1. Check isinstance(waveform_db, WaveformDB)
  2. Check hasattr(_event_bus) and _event_bus is None
  3. Directly assign _event_bus = self.event_bus
  4. Directly create _event_bridge = AsyncEventBridge(...)
  5. Directly call waveform.set_async_callback(...)
  6. Check hasattr(_loading_handles)
  7. Copy, clear, and retry loading handles

WaveformController.open_waveform_file():
  1. Create WaveformDB()
  2. Directly assign _event_bus = self.event_bus
  3. Directly assign _event_bridge = AsyncEventBridge(...)
  4. Call waveform_db.open(file_path)
```

#### After (Refactored)
```
WaveformController.set_session():
  1. Check isinstance(waveform_db, WaveformDB)
  2. Call waveform_db.attach_event_bus(self.event_bus)

WaveformController.open_waveform_file():
  1. Create WaveformDB(event_bus=self.event_bus)
  2. Call waveform_db.open(file_path)

WaveformDB.attach_event_bus():
  1. Store event_bus
  2. Create event_bridge
  3. Register callback if waveform exists
  4. Retry loading handles if needed
```

### Benefits of Refactoring

1. **Encapsulation**: Private attributes stay private
2. **Single Responsibility**: WaveformDB owns all async loading logic
3. **Testability**: Can mock/verify `attach_event_bus()` calls
4. **Clarity**: Intent is explicit - "attach event bus" vs. "poke internal state"
5. **Maintainability**: Retry logic lives next to `_on_async_event()` where it belongs
6. **Type Safety**: No more `hasattr()` checks - proper method calls with type hints

### Testing Strategy

**Existing Tests**: Should pass without modification since behavior is unchanged

**New Unit Tests** (optional but recommended):
1. Test `WaveformDB.attach_event_bus()` with no waveform loaded
2. Test `WaveformDB.attach_event_bus()` with waveform loaded (verifies callback registration)
3. Test `WaveformDB.attach_event_bus()` with pending loading handles (verifies retry)
4. Verify WaveformController no longer accesses private attributes (static analysis or grep test)

### Migration Notes

**Breaking Changes**: None - this is purely internal refactoring

**Deprecation**: No public APIs are deprecated

**Documentation Updates**: Add docstring to `attach_event_bus()` method explaining:
- When to use (late binding for sessions loaded without event bus)
- What it does (sets up event bridge, registers callback, retries pending loads)
- Thread safety guarantees
