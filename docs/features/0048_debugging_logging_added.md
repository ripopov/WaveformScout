# Async Loading Debugging - Comprehensive Logging Added

## Summary
Added comprehensive logging throughout the async signal loading pipeline to help diagnose the hanging issue that occurs when double-clicking signals.

## Issue Description
The application hangs after double-clicking on a signal variable in the VarsView. This occurs after Phase 2 of async loading was implemented.

## Logging Added

### 1. Variable Selection and Double-Click Flow (design_tree_view.py)
- `[DESIGN_TREE]` prefix for all logs
- Logs when `_on_variables_selected` is called
- Logs when `_emit_signal_nodes_from_variables` is called
- Shows number of variables selected
- Shows number of signal nodes created
- Shows which handles need async loading vs cached
- Logs when async loading is triggered

### 2. Async Event Bridge (waveform_db.py - AsyncEventBridge class)
- `[ASYNC_BRIDGE]` prefix for all logs
- Logs Qt signal emissions with thread information
- `_emit_loading_started`: Shows when loading started event is published
- `_emit_loaded`: Shows when signals loaded event is published
- `_emit_loading_failed`: Shows when loading failed event is published
- Shows if event bus is missing

### 3. WaveformDB Async Handling (waveform_db.py)
- `[WAVEFORM_DB]` prefix for async-related logs
- `_on_async_event`: Shows thread name, event type, and event details
- `load_signals_async`: Shows number of handles requested, filtered, cached, and loading
- Shows when pyrox backend is called for async loading
- Tracks signal caching after load completes

### 4. Signal Cache Access (waveform_db.py - get_signal method)
- `[GET_SIGNAL]` prefix for all logs
- Shows cache hits vs misses
- Shows which thread is accessing the cache
- Logs when signals are loaded from Rust backend
- Logs errors if signal loading fails

### 5. Event Bus (event_bus.py)
- `[EVENT_BUS]` prefix for all logs
- `subscribe`: Shows handler subscription with event type
- `publish`: Shows event publishing with thread info
- Shows number of subscribers for each event
- Logs handler execution and completion
- Logs exceptions from handlers

### 6. Canvas Updates (waveform_canvas.py)
- `[CANVAS]` prefix for canvas logs
- `update()`: Shows when update is called with arguments
- Shows call stack (last 3 frames) to trace update source
- `paintEvent()`: Shows when painting occurs

### 7. Controller Event Handling (waveform_controller.py)
- `[CONTROLLER]` prefix for controller logs
- `set_session`: Shows session setting and event bus hookup
- Shows when event bus is attached to WaveformDB instances
- `_on_signals_loading`: Shows when loading callback is triggered
- `_on_signals_loaded`: Shows when loaded callback is triggered with signal count

### 8. Main Widget Callbacks (wave_scout_widget.py)
- `[WAVE_SCOUT]` prefix for main widget logs
- `_on_controller_signals_loading`: Shows when controller signals loading
- `_on_controller_signals_loaded`: Shows when controller signals loaded
- Shows canvas update triggers

## How to Use the Logging

### To Reproduce the Hanging Issue:
1. Run the application with logging enabled (it's now built-in)
2. Load a waveform file
3. Select a scope in the design tree
4. Double-click on a variable in VarsView
5. Observe where the logging stops - this indicates where the hang occurs

### What to Look For:
1. **Thread Information**: Check if operations are happening on unexpected threads
2. **Event Flow**: Follow the event chain from variable selection to canvas update
3. **Cache Status**: See if signals are being loaded or are already cached
4. **Callback Execution**: Verify callbacks are being triggered properly
5. **Infinite Loops**: Look for repeated log patterns indicating a loop
6. **Missing Events**: Check if expected events are not being published

### Example Log Flow (Expected):
```
[DESIGN_TREE] _on_variables_selected called with 1 variables
[DESIGN_TREE] _emit_signal_nodes_from_variables called
[DESIGN_TREE] Created 1 signal nodes
[DESIGN_TREE] Triggering async load for 1 handles
[WAVEFORM_DB] load_signals_async called with 1 handles
[WAVEFORM_DB] Calling pyrox load_signals_async
[WAVEFORM_DB] _on_async_event called from thread Thread-1
[WAVEFORM_DB] Event type: SignalStartLoad
[ASYNC_BRIDGE] _emit_loading_started on thread MainThread
[EVENT_BUS] Publishing SignalLoadingStartedEvent
[CONTROLLER] _on_signals_loading callback triggered
[WAVE_SCOUT] _on_controller_signals_loading called
[WAVEFORM_DB] _on_async_event called from thread Thread-1
[WAVEFORM_DB] Event type: SignalLoaded
[ASYNC_BRIDGE] _emit_loaded on thread MainThread
[EVENT_BUS] Publishing SignalLoadedEvent
[CONTROLLER] _on_signals_loaded callback triggered
[WAVE_SCOUT] _on_controller_signals_loaded called
[CANVAS] update() called
```

## Next Steps
1. User should reproduce the hanging issue with logging enabled
2. Analyze the log output to identify where the flow stops
3. Common issues to check:
   - Deadlock between threads
   - Infinite loop in event processing
   - Missing callback registration
   - Qt event loop blocking
   - Signal/slot connection issues