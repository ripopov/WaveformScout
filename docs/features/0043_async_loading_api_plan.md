# Async Loading API for Pyrox

## 1. Use Cases and Requirements Analysis

### Core Requirements
The feature request identifies critical performance requirements for waveform loading:

1. **Non-blocking Loading**: Loading header, body, and signals must be asynchronous
2. **Incremental loading**:
   - First load header to display design tree
   - Then load body to get timestamps
   - Finally load selected signals on-demand
3. **Async architecture constraints**:
   - No direct Rust futures exposure to Python (FFI complexity)
   - Keep async boundary on Rust side
   - Simple instant-return API to Python with fire-and-forget events
   - Callback system for event notification
4. **GIL management**: Never hold Python GIL during long-running operations
5. **Worker thread model**: All heavy I/O happens on Rust worker threads
6. **Event-driven updates**: Python callbacks for event notification (UI integration not in scope)

### Specific API Requirements

#### Waveform Class Changes
1. `Waveform::new()` - Conditional loading (header/body can be disabled)
2. `body_loaded()`, `header_loaded()` - State inspection methods
3. `set_async_callback(callback: Optional<PyObject>)` - Register single callback for all async events
4. `load_header_async()` - Async header loading (uses registered callback)
5. `load_body_async()` - Async body loading (uses registered callback)
6. `load_signals_async(handles: Vec<SignalHandle>)` - Batch signal loading (uses registered callback)

#### Event System
Events to be generated:
- `HeaderStartLoad` - Header loading initiated
- `HeaderLoaded` - Header loading completed
- `BodyStartLoad` - Body loading initiated
- `BodyLoaded` - Body loading completed
- `SignalStartLoad(Vec<SignalHandle>)` - Signal loading initiated
- `SignalLoaded(Vec<SignalHandle>)` - Signals loaded successfully

#### API Design Rationale
**Single Callback Registration Model:**
- One callback handles all events (simpler than per-request callbacks)
- Avoids ambiguity when batching requests on worker thread
- Python side can implement event dispatching logic
- Callback can be changed or removed at any time
- Worker thread always uses the currently registered callback

#### Performance Optimizations
- Batch signal loading (more efficient than one-by-one)
- Skip already cached signals
- Queue coalescing on worker thread

### Test Requirements
- Use `test_inputs/swerv1.vcd` for testing
- Submit all async requests without waiting
- Verify callback execution order
- Test cache behavior (skip cached signals)
- No PySide/Qt integration testing at this stage (API only)

## 2. Codebase Research

### Current Architecture Analysis

#### Rust Side (`pyrox/src/lib.rs`)
Current `Waveform` class structure:
- **Line 445-459**: Contains hierarchy, wave_source, time_table, body_continuation
- **Line 466-497**: Constructor loads both header and body synchronously
- **Line 499-524**: `load_body()` method for deferred body loading (synchronous)
- **Line 527-529**: `body_loaded()` method checks if body is loaded
- **Line 453-458**: Signal caches (Rust and Python object caches)
- **Line 652-701**: `preload_signals_by_handles()` for batch loading
- **Line 536-560**: `get_signal()` loads single signal synchronously

Key observations:
- Already has deferred body loading capability via `body_continuation`
- Uses `Python::with_gil()` and `py.allow_threads()` for GIL management
- Maintains both Rust signal cache and Python object cache for identity
- Signal loading releases GIL during I/O operations

#### Python Side (`wavescout/waveform_db.py`)
Current integration:
- **Line 33-62**: `open()` method loads waveform synchronously
- **Line 208-221**: `get_signal()` uses cached loading via `get_signal_by_ref`
- **Line 249-349**: `preload_signals()` batch loads signals with timing metrics
- **Line 276-293**: Attempts to use `preload_signals_by_handles` if available

Key observations:
- Already has infrastructure for batch loading
- Timing and performance metrics built-in
- Falls back gracefully when new methods unavailable

### Threading Model
Current implementation already uses:
- `py.allow_threads()` to release GIL during I/O
- Rust Arc for thread-safe sharing of hierarchy and signals
- FxHashMap for caching (needs thread safety for async)

## 3. Implementation Planning

### File-by-File Changes

#### `pyrox/src/lib.rs`

**Structural Changes:**
1. Add async runtime infrastructure:
   - Worker thread with tokio runtime
   - Channel for request queue (mpsc)
   - Callback wrapper type

2. Modify `Waveform` struct:
   - Add loading state flags (header_loaded, body_loaded)
   - Add request sender channel
   - Add registered callback: `Option<PyObject>`
   - Convert caches to thread-safe types (Arc<Mutex<>>)

3. New async methods:
   - `set_async_callback(callback: Option<PyObject>)` - Register/unregister callback
   - `load_header_async()` - Queue header load request
   - `load_body_async()` - Queue body load request
   - `load_signals_async(handles: Vec<SignalHandle>)` - Queue signal load request

4. Event callback system:
   - Define Event enum (as specified in requirements)
   - Single registered callback receives all events
   - Callback wrapper that acquires GIL only for notification
   - Queue request types (LoadHeader, LoadBody, LoadSignals)

**Algorithm for Async Loading:**

```
Worker Thread Loop:
1. Wait for requests from channel
2. Batch collect all pending requests of same type
3. For LoadSignals: merge all handle lists
4. Execute load operation (no GIL held)
5. Update internal state (hierarchy, wave_source, caches)
6. Check if callback is registered
7. If callback exists:
   a. Acquire GIL briefly
   b. Call registered Python callback with event
   c. Release GIL
8. Continue loop
```

**Callback Registration:**
```
set_async_callback(callback):
1. Store callback in Arc<Mutex<Option<PyObject>>>
2. Worker thread reads this before each event emission
3. If None, events are silently dropped
4. If Some(callback), event is delivered
```

**Thread Safety Requirements:**
- Signal cache: `Arc<Mutex<FxHashMap<SignalHandle, Arc<Signal>>>>`
- Python cache: `Arc<Mutex<FxHashMap<SignalHandle, Py<Signal>>>>`
- Loading states: AtomicBool for header_loaded, body_loaded
- Wave source: Arc<Mutex<Option<SignalSource>>>

#### `tests/test_async_loading.py` (New File)

**Test Coverage:**
1. Basic async loading flow (header → body → signals)
2. Callback registration and unregistration
3. Callback execution verification for all event types
4. Changing callbacks mid-operation
5. Cache behavior (skip cached signals)
6. Queue coalescing (multiple signal requests)
7. Error handling (missing files, corrupt data)
8. State consistency (header_loaded, body_loaded)
9. Thread safety (concurrent requests)
10. Operation without callback (no crash, silent operation)

### Performance Considerations

**Memory Management:**
- Lazy signal loading reduces memory footprint
- Cache eviction strategy needed for large files
- Consider memory-mapped file access for very large waveforms

**Queue Optimization:**
- Coalesce signal loading requests on worker thread
- Priority queue for UI-visible signals
- Batch size limits to maintain responsiveness

**Progress Reporting:**
- Event system includes progress information
- Estimated time remaining for large operations
- Cancellation support for long-running loads

### Testing Strategy

**Unit Tests:**
1. Test each async method independently
2. Verify state transitions
3. Test callback execution
4. Test error conditions

**Integration Tests:**
1. Full loading workflow with swerv1.vcd
2. Multiple concurrent requests
3. Large file handling
4. Memory usage monitoring

**Performance Tests:**
1. Measure loading time improvements
2. UI responsiveness metrics
3. Memory usage comparison
4. Cache hit rates

### Migration Path

**Phase 1: Add Async API to Pyrox (Current Task)**
- Implement async methods alongside sync methods
- Sync methods continue to work unchanged
- Test async API independently without UI integration
- Ensure backwards compatibility

**Future Phases (Not Part of This Task):**
- Integration with PySide/Qt UI components
- Migration of existing sync callers
- Deprecation of sync methods

### Error Handling

**Rust Side:**
- Wrap errors in Result types
- Send error events through callback
- Maintain consistent state on error

**Python Side:**
- Handle error events gracefully
- Retry logic for transient failures
- User notification for fatal errors

### Documentation Requirements

1. API documentation with examples
2. Migration guide from sync to async
3. Performance tuning guidelines
4. Threading model explanation