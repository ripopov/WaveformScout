# Async Signal Loading - Phase 1 Implementation

## Overview
Phase 1 focuses on building the core infrastructure and converting the primary UI components (DesignTreeView and SignalNamesView) to demonstrate async signal loading with a proof-of-concept application.

## Phase 1 Steps

### 1. Infrastructure: WaveformDB Async Plumbing

#### 1.1 Event Definitions (`wavescout/application/events.py`)
- Add `SignalLoadingStartedEvent(handles: list[SignalHandle])`
- Add `SignalLoadedEvent(pairs: list[tuple[SignalHandle, Signal]])`
- Add `SignalLoadingFailedEvent(handles: list[SignalHandle], error: str)`

#### 1.2 WaveformDB Updates (`wavescout/waveform_db.py`)
- Add `_loading_handles: set[SignalHandle]` tracking
- Implement `_on_async_event(event: AsyncEvent)` callback
- Register callback in `open()`, clear in `close()`
- Add `load_signals_async(handles: Sequence[SignalHandle])` method
- Add query methods:
  - `is_signal_loading(handle: SignalHandle) -> bool`
  - `pending_signal_count() -> int`
  - `wait_for_signals(handles: Iterable[SignalHandle], timeout: float = 5.0) -> bool`
- Add `load_signals_blocking(handles)` for compatibility

#### 1.3 Session Model (`wavescout/data_model.py`)
- Add `loading_handles: set[SignalHandle]` to `WaveformSession`
- Add `is_loading(handle: SignalHandle) -> bool` helper

#### 1.4 Controller Integration (`wavescout/waveform_controller.py`)
- Subscribe to `SignalLoadingStartedEvent` and `SignalLoadedEvent`
- Update session loading state on events
- Trigger model updates when signals arrive
- Update `SignalNodeSignal` instances with loaded data

### 2. Design Tree & Clipboard Conversion

#### 2.1 DesignTreeView (`wavescout/design_tree_view.py`)
- Modify `_create_signal_node()`:
  - Remove synchronous `waveform_db.get_signal()` call
  - Check cache with `waveform_db.are_signals_cached()`
  - Leave `signal=None` for uncached handles
  - Schedule async load via controller
- Update `_emit_signal_nodes_from_variables()`:
  - Batch all handles needing load
  - Single `load_signals_async()` call at end
- Add loading indicator rendering in delegate

#### 2.2 SignalNamesView (`wavescout/signal_names_view.py`)
- Update `_validate_nodes()`:
  - Remove synchronous signal population
  - Schedule async loads for pasted content
- Modify rendering to show "Loading..." for `signal=None`
- Ensure clipboard operations remain non-blocking

#### 2.3 Canvas Placeholder (`wavescout/waveform_canvas.py`)
- Update paint logic to render "Loading..." text when `node.signal is None`
- Add visual feedback (e.g., grayed out row) for loading signals

### 3. PoC Application

#### 3.1 Minimal Test Application (`poc_async_app.py`)
Create a standalone application that demonstrates:
- Loading a waveform file
- Design tree with async signal loading
- Signal names view with clipboard support
- Visual loading indicators
- Status bar progress updates

#### 3.2 Integration Points
- Wire up event bus between components
- Connect WaveformDB async events to UI updates
- Implement basic status reporting

#### 3.3 Validation Scenarios
- Double-click multiple signals rapidly
- Copy/paste large signal groups
- Load signals from different hierarchy levels
- Verify UI remains responsive during loads

## Success Criteria for Phase 1

1. **Infrastructure Complete**:
   - WaveformDB has async callback registered
   - Events flow through EventBus
   - Session tracks loading state
   - Controller updates nodes on load

2. **UI Components Work**:
   - DesignTreeView shows nodes immediately
   - SignalNamesView handles paste without blocking
   - Canvas displays loading placeholders
   - No UI freezes during signal loading

3. **PoC Demonstrates Value**:
   - Application runs without crashes
   - Loading indicators appear/disappear correctly
   - Multiple simultaneous loads handled
   - Performance improvement visible

## Testing Phase 1

### Unit Tests
- Test WaveformDB async event handling
- Verify loading state tracking
- Test event publication/subscription

### Integration Tests
- Test DesignTreeView with mock async backend
- Test SignalNamesView clipboard with delays
- Verify controller state updates

### Manual Testing
- Load large FST/VCD files
- Rapid signal selection
- Copy/paste stress test
- Verify no regressions in basic functionality

## Phase 1 Deliverables

1. Modified core infrastructure files
2. Updated DesignTreeView and SignalNamesView
3. Working PoC application
4. Test suite additions
5. Documentation of API changes

## Next Steps (Phase 2 Preview)
After Phase 1 validation:
- Extend to persistence/session restore
- Convert snippet system
- Replace progress dialogs
- Complete test migration
- Remove legacy code