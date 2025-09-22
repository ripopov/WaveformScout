# Signal Cache Reference Counting Refactoring Plan

## 1. Use Cases and Requirements Analysis

### Core Problem
The current signal cache implementation in pyrox has two critical issues:
1. **Inconsistent cache usage**: Some methods like `get_signal()` bypass the cache entirely, leading to redundant loads
2. **Memory leak**: Signals are never removed from the cache, causing unbounded memory growth

### Requirements
- Implement reference counting for cached signals to enable automatic cleanup when no longer needed
- Ensure consistent cache usage across all signal loading methods
- Maintain Python object identity for the same signal (important for UI consistency)
- Support async loading with proper reference counting
- Eliminate redundant `get_signal()` method that duplicates `get_signal_by_ref()`

### Solution Overview
Implement a reference-counted cache system where:
- Each cache entry tracks how many Python `Signal` objects reference it
- When the last Python `Signal` is destroyed, the cache entry is removed
- SignalNodes take ownership of Signal objects rather than just storing handles
- All signal access goes through the cache consistently

## 2. Codebase Research

### Current Cache Architecture in pyrox/src/lib.rs

#### SharedState Structure
- `signal_cache: Mutex<FxHashMap<SignalHandle, Arc<wellen::Signal>>>` - Rust signal cache
- `python_signal_cache: Mutex<FxHashMap<SignalHandle, Py<Signal>>>` - Python object cache

#### Signal Loading Methods
1. `get_signal()` - Bypasses cache, loads directly
2. `get_signal_by_ref()` - Uses both caches properly
3. `load_signals()` - Batch loading without caching
4. `preload_signals_by_handles()` - Batch loading with caching
5. Async loading via `AsyncEvent::SignalLoaded` - Returns handles only

#### Python Signal Struct
```rust
struct Signal {
    signal: Arc<wellen::Signal>,
    all_times: TimeTable,
}
```

### WaveScout Data Model Usage

#### SignalNode Structure (wavescout/data_model.py)
- `handle: Optional[SignalHandle]` - Current design stores only handle
- Signals are loaded on-demand via `WaveformDB.get_signal(handle)`

#### Signal Access Patterns
- `waveform_canvas.py`: Loads signals for rendering
- `signal_sampling.py`: Loads signals for data sampling
- `analysis_engine.py`: Loads signals for analysis operations
- `waveform_controller.py`: Loads signals for value inspection

## 3. Implementation Planning

### Phase 1: Rust-side Cache Refactoring

#### File: pyrox/src/lib.rs

**New Structure: SignalCacheEntry**
```rust
struct SignalCacheEntry {
    signal: Arc<wellen::Signal>,
    reference_count: usize,
}
```

**Modified SharedState**
- Change `signal_cache` type to `Mutex<FxHashMap<SignalHandle, SignalCacheEntry>>`
- Keep `python_signal_cache` unchanged for Python object identity

**Modified Signal Struct**
- Add `handle: SignalHandle` field to track which cache entry it references
- Implement `Drop` trait to decrement reference count and clean up cache

**Method Changes**
1. **Remove `get_signal()` method entirely** - duplicates `get_signal_by_ref()`
2. **Update `get_signal_by_ref()`**:
   - Increment reference count when creating new Signal
   - Handle cache miss by loading and caching with count=1
3. **Update `load_signals()` and `load_signals_multithreaded()`**:
   - Return cached signals if available
   - Add to cache with proper reference counting
   - `load_signals_multithreaded()` becomes primary batch loading method
4. **Remove `preload_signals_by_handles()`** - No longer needed
5. **Update async loading**:
   - Change `AsyncEvent::SignalLoaded` to return `Vec<Py<Signal>>` instead of `Vec<SignalHandle>`
   - Create Python Signal objects with proper reference counting

**New Methods**
- `increment_signal_ref(handle: SignalHandle)` - Helper for reference counting
- `decrement_signal_ref(handle: SignalHandle)` - Helper with cache cleanup

### Phase 2: Python Data Model Refactoring (Breaking Change)

#### File: wavescout/data_model.py

**SignalNode Changes**
```python
@dataclass
class SignalNode:
    name: str
    var: Optional[pyrox.Var] = None  # Quick access to Var properties
    signal: Optional[pyrox.Signal] = None  # Owned signal data
    # Remove: handle: Optional[SignalHandle] = None
    format: DisplayFormat = field(default_factory=DisplayFormat)
    # ... rest unchanged
```

**New Properties**
- Add property `handle` that returns `self.var.signal_handle()` if var exists
- Add method `load_signal(waveform_db)` to populate signal field

### Phase 3: WaveformDB and Protocol Updates

#### File: wavescout/protocols.py

**Remove SignalHandle from Imports**
- Signal access will be through Signal objects directly

**Update Protocol Methods (Breaking Change)**
- Change all methods that accept `SignalHandle` to accept `Signal` objects
- Remove handle-based methods entirely

#### File: wavescout/waveform_db.py

**Method Updates (Breaking Change)**
1. **Remove `get_signal()` method** - No longer needed
2. **Add `load_signal_for_node(node: SignalNode)`** - Loads and assigns signal to node
3. **Remove `preload_signals()`** - Use `load_signals_multithreaded()` directly
4. **Update all methods** to accept Signal objects instead of handles

### Phase 4: UI Component Updates

#### Files to Update
1. **waveform_canvas.py**
   - Update cache key from handle to instance_id
   - Pass Signal objects to rendering functions
   - Update TransitionCache to use instance_id

2. **signal_sampling.py**
   - Accept Signal objects in sampling functions
   - Remove handle-based lookups

3. **analysis_engine.py**
   - Update to work with Signal objects from nodes

4. **waveform_controller.py**
   - Update signal loading to populate node.signal field
   - Remove handle-based operations

5. **signal_names_view.py**
   - Update context menu operations to use node.signal

6. **persistence.py**
   - Update session loading to use `load_signals_multithreaded()`
   - Collect handles from SignalNodes, batch load Signals
   - Assign loaded Signals directly to SignalNodes
   - Store handle for persistence, load Signal on restore

### Phase 5: Testing

#### Test Updates Required
1. Update cache tests to verify reference counting
2. Test memory cleanup when signals are removed
3. Verify async loading returns Signal objects
4. Test signal identity preservation

#### Implementation Strategy (Breaking Change)
1. Implement all Rust and Python changes simultaneously
2. Update all components in a single commit
3. No deprecation period - direct migration
4. All tests must pass after the single atomic change

### Performance Considerations

#### Memory Management
- Reference counting ensures timely cleanup
- Cache size bounded by active SignalNodes
- Python object identity preserved for UI consistency

#### Loading Optimization
- Batch loading still efficient with caching
- Async loading properly manages references
- No redundant loads with consistent cache usage

### Algorithm Description

**Signal Loading Flow**
1. SignalNode requests signal via `load_signal()`
2. WaveformDB checks if node already has signal
3. If not, calls Rust `get_signal_by_ref()` with var's handle
4. Rust checks cache, increments refcount if found
5. If not cached, loads signal and adds with refcount=1
6. Python Signal object created and stored in node
7. When SignalNode deleted or signal replaced, Python Signal destroyed
8. Signal.__del__ calls Rust to decrement refcount
9. If refcount reaches 0, remove from cache

**Batch Loading Flow (Persistence)**
1. Collect handles from all SignalNodes during session restore
2. Call `load_signals_multithreaded()` with collected handles
3. Rust loads signals in parallel, adds to cache with refcount=1
4. Returns list of Python Signal objects
5. Map Signals back to corresponding SignalNodes
6. Each SignalNode takes ownership of its Signal

**Async Loading Flow**
1. Request signals with list of handles
2. Worker loads signals and creates Python Signal objects
3. AsyncEvent returns Signal objects (not handles)
4. UI assigns Signal objects to corresponding nodes
5. Reference counting maintained throughout

## Implementation Order

Since this is a breaking change, all phases must be implemented together:

1. **Simultaneous Implementation**: (8-10 hours)
   - Rust cache refactoring with reference counting
   - Python data model updates (SignalNode changes)
   - WaveformDB and protocol updates
   - All UI component updates
   - Test updates

2. **Testing and Validation**: (2 hours)
   - Verify reference counting works correctly
   - Ensure memory cleanup on signal deletion
   - Validate async loading with Signal objects
   - Confirm signal identity preservation

Total estimated time: 10-12 hours (single atomic change)

## Notes

- This is a breaking change requiring simultaneous updates to Rust and Python code
- No backward compatibility or deprecation period
- Signal identity is preserved for consistent UI behavior
- The design supports future optimizations like weak references for preview operations
- All components must be updated in a single commit to maintain consistency