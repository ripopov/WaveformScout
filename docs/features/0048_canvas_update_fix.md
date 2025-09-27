# Async Signal Loading Canvas Update Fix

## Problem
When signals are loaded asynchronously (not cached), the canvas shows "Loading..." forever even though the signal data is eventually loaded. The signal gets loaded in the background, but the canvas is never notified to repaint.

## Root Cause
The WaveformController properly updates SignalNodeSignal.signal field when async loading completes via `_update_nodes_with_signal()`, but the WaveScoutWidget wasn't listening for the controller's `signals_loaded` callback to trigger a canvas update.

## Solution
Added callback handlers in `wave_scout_widget.py`:

```python
# Register callbacks during initialization
self.controller.on("signals_loaded", self._on_controller_signals_loaded)
self.controller.on("signals_loading", self._on_controller_signals_loading)

# Handler implementations
def _on_controller_signals_loaded(self) -> None:
    """Handle signals loaded event from controller."""
    if self._canvas:
        # Force canvas to repaint now that signals are loaded
        self._canvas.update()

    # Also trigger model update to refresh the values column
    if self.model:
        row_count = self.model.rowCount()
        if row_count > 0:
            self.model.dataChanged.emit(
                self.model.index(0, 0),
                self.model.index(row_count - 1, self.model.columnCount() - 1)
            )

def _on_controller_signals_loading(self) -> None:
    """Handle signals loading event from controller."""
    if self._canvas:
        self._canvas.update()  # Show "Loading..." placeholders
```

## Event Flow
1. User double-clicks uncached signal in design tree
2. SignalNodeSignal created with `signal=None`
3. Controller triggers `load_signals_async()`
4. Canvas shows "Loading..." (checked via `node.signal is None`)
5. Pyrox loads signal in background thread
6. Async callback publishes `SignalLoadedEvent` via event bus
7. Controller receives event and calls `_update_nodes_with_signal()`
8. Controller emits `"signals_loaded"` callback
9. WaveScoutWidget's `_on_controller_signals_loaded()` triggers canvas update
10. Canvas repaints, now showing the actual signal

## Testing Notes
- Signals that are already cached load synchronously and display immediately
- The canvas's tooltip code may trigger synchronous loading when hovering
- To test async loading, ensure signals are not in cache before double-clicking

## Files Changed
- `wavescout/wave_scout_widget.py` - Added controller callback handlers

## Impact
- Fixes the "Loading..." forever issue
- Canvas properly updates when async loading completes
- Values column also updates to show signal values
- No performance impact - only triggers update when signals actually load