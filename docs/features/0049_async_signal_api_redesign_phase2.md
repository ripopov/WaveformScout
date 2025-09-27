# Async Signal Loading API Redesign - Phase 2: GUI Migration and Legacy API Removal

## Phase 2 Overview

Phase 2 migrates all GUI components to use the AsyncLoadedSignal API implemented in Phase 1 and removes deprecated signal loading methods. This phase requires careful coordination to ensure all signal access points are updated.

## 1. Migration Goals

### API Cleanup
- Remove deprecated methods: `get_signal()`, `signal_from_handle()`, `preload_signals()`, `are_signals_cached()`
- Eliminate `Optional[Signal]` pattern from `SignalNodeSignal`
- Remove tree-scanning signal update logic from `WaveformController`

### GUI Component Migration
- Update all signal access patterns to use AsyncLoadedSignal
- Implement loading state indicators in rendering
- Preserve async update notifications for canvas refresh

## 2. File-by-File Migration Plan

### `wavescout/data_model.py`

**SignalNodeSignal Changes:**
```python
@dataclass
class SignalNodeSignal(SignalNode):
    """Modified to use AsyncLoadedSignal instead of Optional[Signal]"""

    # OLD: signal: Optional["Signal"] = field(default=None, repr=False, compare=False)
    # NEW:
    signal: "AsyncLoadedSignal" = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        """Initialize with AsyncLoadedSignal if not provided."""
        if not hasattr(self, 'signal') or self.signal is None:
            # Create placeholder AsyncLoadedSignal
            from wavescout.waveform_db import AsyncLoadedSignal
            self.signal = AsyncLoadedSignal.placeholder(self.handle)

    def _comparison_state(self) -> tuple[Any, ...]:
        """Update comparison to exclude AsyncLoadedSignal."""
        return (
            self.handle,
            self.name,
            self.parent_index,
            self.row,
            # signal excluded from comparison
        )

    def deep_copy(self) -> "SignalNodeSignal":
        """Deep copy maintaining AsyncLoadedSignal reference."""
        return SignalNodeSignal(
            handle=self.handle,
            name=self.name,
            signal=self.signal,  # Share AsyncLoadedSignal reference
            parent_index=self.parent_index,
            row=self.row,
        )
```

### `wavescout/waveform_controller.py`

**Remove deprecated methods:**
```python
# DELETE THIS METHOD ENTIRELY:
def _update_nodes_with_signal(self, handle: SignalHandle, signal: "Signal") -> None:
    """No longer needed - AsyncLoadedSignal handles updates directly."""
    pass  # DELETE

# UPDATE async event handler:
def on_async_event(self, event: ApplicationEvent) -> None:
    """Simplified event handler without tree scanning."""
    if isinstance(event, SignalLoadedEvent):
        # Only handle UI notifications, no tree updates needed
        if self._signal_loaded_callback:
            self._signal_loaded_callback(event.pairs)

        # Trigger canvas refresh
        self.canvas_update_needed.emit()

    elif isinstance(event, SignalLoadingFailedEvent):
        # Handle loading failures
        if self._signal_error_callback:
            self._signal_error_callback(event.handles, event.error)
```

**Update signal loading coordination:**
```python
def add_signal_nodes(self, handles: List[SignalHandle]) -> None:
    """Add signal nodes with AsyncLoadedSignal wrappers."""
    for handle in handles:
        # Get AsyncLoadedSignal from WaveformDB
        async_signal = self.waveform_db.load_signal(handle)

        # Create node with AsyncLoadedSignal
        node = SignalNodeSignal(
            handle=handle,
            name=self._get_signal_name(handle),
            signal=async_signal
        )

        # Add to tree
        self._add_node_to_tree(node)
```

### `wavescout/waveform_db.py`

**Remove deprecated APIs:**
```python
# DELETE these methods entirely:
def get_signal(self, handle: SignalHandle) -> Optional[pyrox.Signal]:
    """DEPRECATED - Use load_signal() instead."""
    raise DeprecationWarning("Use load_signal() instead of get_signal()")

def signal_from_handle(self, handle: SignalHandle) -> Optional[pyrox.Signal]:
    """DEPRECATED - Use load_signal() instead."""
    raise DeprecationWarning("Use load_signal() instead of signal_from_handle()")

def preload_signals(self, handles: List[SignalHandle]) -> None:
    """DEPRECATED - Use load_signal() for each handle."""
    raise DeprecationWarning("Use load_signal() instead of preload_signals()")

def are_signals_cached(self, handles: List[SignalHandle]) -> bool:
    """DEPRECATED - Check AsyncLoadedSignal.is_loaded() instead."""
    raise DeprecationWarning("Check AsyncLoadedSignal.is_loaded() instead")
```

**Add placeholder support to AsyncLoadedSignal:**
```python
class AsyncLoadedSignal:
    # ... existing implementation ...

    @classmethod
    def placeholder(cls, handle: SignalHandle) -> "AsyncLoadedSignal":
        """Create a placeholder AsyncLoadedSignal for uninitialized nodes."""
        instance = cls.__new__(cls)
        instance._handle = handle
        instance._signal = None
        instance._loaded = threading.Event()
        instance._loading = False
        instance._error = None
        return instance
```

### `wavescout/signal_renderer.py`

**Update rendering to check loading state:**
```python
def render_signal(
    self,
    painter: QPainter,
    node: SignalNodeSignal,
    rect: QRect,
    time_range: TimeRange,
) -> None:
    """Render signal with loading state handling."""

    # Check if signal is loaded
    if not node.signal.is_loaded():
        # Render loading indicator
        self._render_loading_state(painter, rect, node.name)
        return

    try:
        # Get the actual signal (blocking should be instant for loaded signals)
        signal = node.signal.get_signal_blocking(timeout=0.001)

        # Existing rendering logic
        self._render_signal_data(painter, signal, rect, time_range)

    except (RuntimeError, TimeoutError):
        # Render error state
        self._render_error_state(painter, rect, node.name)

def _render_loading_state(self, painter: QPainter, rect: QRect, name: str) -> None:
    """Render loading indicator for signals being loaded."""
    painter.setPen(self.theme.loading_color)
    painter.drawText(rect, Qt.AlignCenter, f"Loading {name}...")

def _render_error_state(self, painter: QPainter, rect: QRect, name: str) -> None:
    """Render error state for failed signal loading."""
    painter.setPen(self.theme.error_color)
    painter.drawText(rect, Qt.AlignCenter, f"Error loading {name}")
```

### `wavescout/waveform_canvas.py`

**Update canvas painting:**
```python
def paintEvent(self, event: QPaintEvent) -> None:
    """Paint waveforms with async loading support."""
    painter = QPainter(self)

    for node in self.visible_nodes:
        if isinstance(node, SignalNodeSignal):
            # Renderer handles loading state internally
            self.signal_renderer.render_signal(
                painter, node, node.rect, self.time_range
            )

    # Schedule repaint if any signals are still loading
    if self._has_loading_signals():
        QTimer.singleShot(100, self.update)  # Check again in 100ms

def _has_loading_signals(self) -> bool:
    """Check if any visible signals are still loading."""
    for node in self.visible_nodes:
        if isinstance(node, SignalNodeSignal):
            if not node.signal.is_loaded():
                return True
    return False
```

### `wavescout/signal_sampling.py`

**Update sampling to handle async signals:**
```python
def sample_signal(
    node: SignalNodeSignal,
    time_range: TimeRange,
    num_samples: int
) -> Optional[np.ndarray]:
    """Sample signal data for rendering."""

    # Quick check without blocking
    if not node.signal.is_loaded():
        return None

    try:
        # Get signal with minimal timeout
        signal = node.signal.get_signal_blocking(timeout=0.001)

        # Existing sampling logic
        return _perform_sampling(signal, time_range, num_samples)

    except (RuntimeError, TimeoutError):
        return None
```

### `wavescout/persistence.py`

**Update session serialization:**
```python
def save_session(session: Session, path: Path) -> None:
    """Save session with AsyncLoadedSignal handling."""

    # Convert nodes for serialization
    serialized_nodes = []
    for node in session.nodes:
        if isinstance(node, SignalNodeSignal):
            # Save only the handle, not the AsyncLoadedSignal
            node_data = {
                "type": "signal",
                "handle": node.handle,
                "name": node.name,
                "parent_index": node.parent_index,
            }
            serialized_nodes.append(node_data)

    # ... rest of serialization

def load_session(path: Path, waveform_db: WaveformDB) -> Session:
    """Load session and create AsyncLoadedSignal wrappers."""

    # ... deserialize data

    nodes = []
    for node_data in data["nodes"]:
        if node_data["type"] == "signal":
            # Create AsyncLoadedSignal for the handle
            async_signal = waveform_db.load_signal(node_data["handle"])

            node = SignalNodeSignal(
                handle=node_data["handle"],
                name=node_data["name"],
                signal=async_signal,
                parent_index=node_data.get("parent_index"),
            )
            nodes.append(node)

    return Session(nodes=nodes)
```

### Test File Updates

**Update all test files that access signals:**
```python
# Pattern to replace throughout tests:

# OLD:
if node.signal:
    value = node.signal.get_value_at(time)

# NEW:
if node.signal.is_loaded():
    signal = node.signal.get_signal_blocking()
    value = signal.get_value_at(time)

# OR for tests that need immediate access:
signal = node.signal.get_signal_blocking(timeout=5.0)  # Allow loading in tests
value = signal.get_value_at(time)
```

## 3. Migration Strategy

### Step-by-Step Process

1. **Update data model first** - Modify `SignalNodeSignal` to use AsyncLoadedSignal
2. **Update WaveformDB** - Remove deprecated methods (with deprecation warnings initially)
3. **Update controller** - Remove tree-scanning logic
4. **Update renderers** - Add loading state handling
5. **Update auxiliary components** - Persistence, sampling, etc.
6. **Update tests** - Fix all test failures from API changes
7. **Final cleanup** - Remove deprecation warnings, finalize API

### Gradual Rollout Option

```python
# Temporary compatibility shim in SignalNodeSignal
@property
def signal_compat(self) -> Optional[Signal]:
    """Temporary compatibility property."""
    if self.signal.is_loaded():
        try:
            return self.signal.get_signal_blocking(timeout=0.001)
        except:
            return None
    return None
```

## 4. UI/UX Considerations

### Loading States
- Show "Loading..." text for signals being loaded
- Use distinct color (e.g., gray) for loading state
- Consider progress indicator for bulk loading

### Error States
- Show error icon or text when loading fails
- Provide retry option in context menu
- Log errors to status bar

### Performance
- Canvas refresh rate limited to 10 FPS during loading
- Batch UI updates for multiple signals
- Prioritize visible signals for loading

## 5. Testing Requirements

### Unit Tests
- Update all existing unit tests for new API
- Add tests for loading state rendering
- Test error handling in UI components
- Verify backward compatibility during migration

### Integration Tests
- Full signal loading workflow with UI
- Session save/load with AsyncLoadedSignal
- Snippet instantiation with new API
- Marker and analysis window compatibility

### Performance Tests
- Measure UI responsiveness during bulk loading
- Verify no memory leaks in pending signals
- Check thread safety under load

## 6. Rollback Plan

If issues arise during Phase 2:

1. **Revert to Phase 1** - Keep AsyncLoadedSignal but restore old APIs
2. **Add compatibility layer** - Implement adapters between old and new APIs
3. **Gradual migration** - Update components one at a time
4. **Feature flag** - Toggle between old and new implementation

## 7. Success Metrics

- **Zero race conditions** - No signals lost during async loading
- **Simplified API** - Single `load_signal()` entry point
- **Improved UX** - Clear loading and error states
- **Performance maintained** - No regression in rendering speed
- **Test coverage** - All tests passing with new implementation
- **Code reduction** - Remove 200+ lines of redundant code

## 8. Timeline Estimate

- Data model updates: 2 hours
- WaveformDB cleanup: 1 hour
- Controller simplification: 1 hour
- Renderer updates: 3 hours
- Auxiliary component updates: 2 hours
- Test fixes: 3 hours
- Integration testing: 2 hours
- Documentation: 1 hour

**Total: ~15 hours**

## 9. Post-Migration Cleanup

After successful Phase 2 deployment:

1. Remove all deprecated method implementations
2. Delete compatibility shims
3. Update documentation with new API patterns
4. Create migration guide for external plugins
5. Performance profiling and optimization
6. Consider further AsyncLoadedSignal enhancements