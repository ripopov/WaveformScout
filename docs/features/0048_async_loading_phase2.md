# Async Signal Loading - Phase 2 Implementation

## Overview
Phase 2 builds on the successful Phase 1 implementation to complete the async signal loading migration. Phase 1 established the core infrastructure with thread-safe event handling, and Phase 2 will convert remaining components (persistence, snippets), polish the UI experience, and clean up legacy code.

## Prerequisites (Completed in Phase 1)
✅ Event-driven async infrastructure with `AsyncEventBridge` for thread safety
✅ `WaveformDB` with async callbacks and loading state tracking
✅ `WaveformSession` and `WaveformController` integration
✅ `DesignTreeView` and `SignalNamesView` converted to async
✅ `WaveformCanvas` with loading placeholders
✅ Thread-safe event handling from worker threads to Qt main thread

## Phase 2 Focus Areas

### ✅ Already Working (Phase 1)
- Core async infrastructure
- Design tree double-click signal loading
- Clipboard paste with async loading
- Basic loading placeholders in canvas
- Thread-safe event handling
- Progress tracking in PoC app

### 🔧 Remaining Work (Phase 2)
- Session persistence with async restore
- Snippet system conversion
- Production status bar integration in main app
- Enhanced loading animations
- Legacy code removal
- Full test suite updates

## Key Lessons from Phase 1

### Thread Safety Critical
- **Issue**: Pyrox callbacks execute on worker threads, causing Qt threading violations
- **Solution**: Use `AsyncEventBridge` with Qt signals to safely cross thread boundaries
- **Pattern**: Never update Qt objects directly from async callbacks; always use signal/slot mechanism

### Testing Considerations
- **Issue**: UI components like `VarsView` have nested widgets (e.g., `table_view`)
- **Solution**: Access the actual Qt widgets for testing (e.g., `vars_view.table_view` not `vars_view`)
- **Pattern**: Use `hasattr()` checks and proper widget hierarchy navigation in tests

### Cache-First Approach
- **Always check cache** before scheduling async loads using `are_signals_cached()`
- **Batch operations** to reduce async overhead
- **Leave `signal=None`** for uncached signals to trigger loading placeholders

## Phase 2 Steps

### 4. Persistence & Snippets

#### 4.1 Session Persistence (`wavescout/persistence.py`)
- Update `_deserialize_node()`:
  - Create nodes with `signal=None`
  - Collect handles for batch loading
  - Return handle list alongside nodes
- Modify `_resolve_signal_handles()`:
  - Remove synchronous `get_signal()` calls
  - Schedule async batch load
  - Let controller update nodes when ready
- Update session restoration flow:
  - Load structure first
  - Trigger async signal loads
  - UI updates as signals arrive

#### 4.2 Snippet System (`wavescout/snippet_manager.py`)
- Update `SnippetManager.apply_snippet()`:
  - Create nodes without signals
  - Batch load required handles
  - Apply snippet structure immediately
- Modify snippet dialogs:
  - Show snippet preview without signals
  - Load signals async when applying
  - Update preview as signals arrive

#### 4.3 Waveform Loader (`wavescout/waveform_loader.py`)
- Update `create_signal_node_from_var()`:
  - Default to `signal=None`
  - Let caller handle async loading
- Remove any remaining sync loading calls
- Ensure all helpers support async pattern

### 5. Status & Canvas Polish

#### 5.1 Status Bar Integration (`scout.py`)
- Remove `QProgressDialog` usage
- Add status bar widget for signal loading:
  - "Loading 3 signals..." during load
  - "All signals ready" on completion
  - Progress indicator for large batches
- Subscribe to loading events:
  - Update count on `SignalLoadingStartedEvent`
  - Clear status on `SignalLoadedEvent`
- **Implementation Notes from Phase 1**:
  - Use `QProgressBar` widget in status bar for visual feedback
  - Show/hide with `setVisible()` based on loading state
  - Use `QTimer.singleShot()` to auto-hide after completion (2 seconds)
  - Track `_loading_count` and `_loaded_count` for accurate progress
  - Update progress bar with `setValue()` as signals load

#### 5.2 Canvas Improvements (`wavescout/waveform_canvas.py`)
- Enhance loading placeholder rendering:
  - Subtle animation or pulsing effect
  - Different style for loading vs error
  - Preserve row height for layout stability
- Add loading overlay for batch operations:
  - Semi-transparent overlay during large loads
  - Cancel button for long operations
  - Progress percentage if available
- **Current Phase 1 Implementation**:
  - Basic "Loading..." text shown when `node.signal is None`
  - Gray color (#808080) for loading text
  - Positioned at row center with proper alignment
  - Canvas updates automatically via controller callbacks
  - Room for enhancement with animations in Phase 2

#### 5.3 Legacy Code Removal
- Delete `_load_signals_async()` from `scout.py`
- Remove `QThreadPool` signal loading infrastructure
- Clean up unused imports and helpers
- Mark deprecated methods with warnings

### 6. Tests & Cleanup

#### 6.1 Test Infrastructure
- Add async-aware test fixtures:
  ```python
  @pytest.fixture
  def async_waveform_db():
      # DB with mock async backend
      # Helper to wait for loads
  ```
- Create test utilities:
  - `wait_for_signal_loads()`
  - `assert_eventually_loaded()`
  - Mock async event generators
- **Phase 1 Testing Insights**:
  - Use `QApplication.processEvents()` in wait loops for Qt event handling
  - Mock pyrox objects with `cast(Any, object())` since they can't be instantiated
  - Access nested widgets properly (e.g., `vars_view.table_view.model()`)
  - Use `qtbot.wait()` for timing-dependent operations
  - Always set `QT_QPA_PLATFORM=offscreen` for headless testing

#### 6.2 Test Suite Updates
- **Clipboard tests** (`test_signal_names_view.py`):
  - Add `wait_for_signals()` before assertions
  - Test partial paste (some cached, some loading)
  - Verify clipboard during active loads

- **Persistence tests** (`test_persistence.py`):
  - Test save during signal loading
  - Test restore with async waits
  - Verify session state consistency

- **Integration tests** (`test_async_loading.py`):
  - Test concurrent load batches
  - Test load cancellation
  - Test error handling paths
  - Test cache invalidation

#### 6.3 Backward Compatibility
- Test with backends lacking async support:
  - Verify fallback to sync loading
  - Check warning messages
  - Ensure no functionality loss
- Test mixed sync/async scenarios:
  - Some signals cached, others loading
  - Switching between backends
  - Migration path testing

### 7. Documentation Updates

#### 7.1 API Documentation
- Document new WaveformDB methods
- Update protocol definitions
- Add async event specifications
- Migration guide for extensions

#### 7.2 Developer Guide
- Best practices for async signal handling
- Common patterns and anti-patterns
- Testing async code guidelines
- Performance tuning tips

## Success Criteria for Phase 2

1. **Complete Feature Coverage**:
   - All signal loading paths converted
   - No remaining sync `get_signal()` calls
   - Legacy code removed

2. **Polish & Performance**:
   - Smooth loading animations
   - Clear progress feedback
   - No UI jank or flicker
   - Better than baseline performance

3. **Test Coverage**:
   - All tests updated for async
   - No flaky test failures
   - Coverage maintained or improved
   - CI/CD pipeline green

4. **Production Ready**:
   - No regressions found
   - Memory usage acceptable
   - Error handling robust
   - Documentation complete

## Testing Phase 2

### Regression Testing
- Full test suite pass
- Manual testing checklist
- Performance benchmarks
- Memory profiling

### Edge Cases
- Network/slow filesystem
- Corrupted waveform files
- Backend crashes/timeouts
- Rapid session switching

### User Acceptance
- Beta testing with real workflows
- Feedback incorporation
- Final bug fixes
- Release preparation

## Phase 2 Deliverables

1. Fully converted codebase
2. Complete test coverage
3. Performance metrics
4. Updated documentation
5. Migration guide
6. Release notes

## Critical Implementation Details from Phase 1

### Thread Safety Architecture
The `AsyncEventBridge` pattern is essential for thread safety:
```python
class AsyncEventBridge(QObject):
    loading_started = Signal(list)
    loaded = Signal(list)

    def __init__(self, event_bus):
        # Connect Qt signals to event bus on main thread
        self.loading_started.connect(self._emit_to_event_bus)
```

### Protocol Updates Required
Any new async methods must be added to `WaveformDBProtocol`:
- `are_signals_cached(handles: List[SignalHandle]) -> bool`
- `load_signals_async(handles: Sequence[SignalHandle]) -> None`
- `is_signal_loading(handle: SignalHandle) -> bool`
- `pending_signal_count() -> int`

### Event Flow Pattern
1. UI component checks cache: `if waveform_db.are_signals_cached([handle])`
2. If cached, load synchronously: `node.signal = waveform_db.get_signal(handle)`
3. If not cached, leave empty: `node.signal = None`
4. Trigger async load: `waveform_db.load_signals_async([handle])`
5. Worker thread invokes callback with results
6. `AsyncEventBridge` emits Qt signal to cross thread boundary
7. Main thread publishes event via `EventBus`
8. Controller updates all matching nodes
9. UI repaints automatically

## Post-Phase 2 Considerations

### Future Enhancements
- Predictive signal pre-loading
- Smart caching strategies
- Background signal indexing
- Parallel backend workers

### Monitoring & Metrics
- Track loading times
- Monitor cache hit rates
- User engagement metrics
- Error/timeout frequency

### Maintenance Plan
- Regular performance audits
- Backend compatibility testing
- User feedback channels
- Continuous optimization