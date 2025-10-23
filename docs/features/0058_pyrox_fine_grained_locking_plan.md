# Pyrox Fine-Grained Locking Refactor

## 1. Use Cases and Requirements Analysis

### Problem Statement
The current pyrox implementation (`pyrox/src/lib.rs`) uses coarse-grained mutex locking that holds the `backend` mutex for the entire duration of signal loading operations. This causes GUI freezes because:

1. The backend lock is held while calling `source.load_signals()`, which can take 10-100ms for large signal batches
2. During this time, any Python thread trying to access the waveform (e.g., for UI updates, queries, or other signals) blocks
3. The lock scope is unnecessarily broad - we only need mutual exclusion to access the backend state, not during the actual signal data loading

### Core Requirements

**Performance Requirements:**
- Backend mutex hold time must be < 1ms per operation (currently 10-100ms)
- Signal loading operations must not block concurrent read operations on already-loaded signals
- Python threads must be able to query loaded signals while new signals are being loaded in the background

**Functional Requirements:**
- Maintain thread safety for backend state access
- Preserve all existing async loading semantics (events, callbacks, error handling)
- Support concurrent signal loading requests from multiple Python threads
- Ensure hierarchy and wave source remain accessible during signal loads

**Compatibility Requirements:**
- No changes to Python API (pyrox module interface)
- No changes to trait definitions (traits.rs)
- No changes to backend implementations (wellen_backend.rs, jets_backend.rs)
- Maintain backward compatibility with existing waveform loading code

### Root Cause Analysis

The locking bottleneck occurs in three specific locations in `pyrox/src/lib.rs`:

1. **`AsyncRequest::LoadHeader` handler (lines 505-523)**
   - Holds `backend_guard` lock during entire `load_header()` call
   - Lock held for: Header parsing + hierarchy construction (50-200ms for large files)
   - Only needs lock for: Storing result in backend state (< 1ms)

2. **`AsyncRequest::LoadBody` handler (lines 525-543)**
   - Holds `backend_guard` lock during entire `load_body()` call
   - Lock held for: Body parsing + time table construction (100-500ms)
   - Only needs lock for: Storing result in backend state (< 1ms)

3. **`AsyncRequest::LoadSignals` handler (lines 545-577)** ⭐ **PRIMARY BOTTLENECK**
   - Holds `backend_guard` lock during entire `source.load_signals()` call
   - Lock held for: File I/O + signal decompression + value parsing (10-100ms per batch)
   - Only needs lock for: Extracting Arc references to hierarchy and wave source (< 1ms)

The last one is the most critical because:
- It's called frequently (every time signals are loaded for display)
- It blocks all concurrent access to the waveform
- The actual signal loading (`source.load_signals()`) is completely independent of backend state once we have the Arc references

### Technical Constraints

**Rust Ownership and Thread Safety:**
- `WaveformTrait::wave_source()` returns `&mut dyn WaveSourceTrait`, requiring mutable borrow
- Cannot hold immutable and mutable references simultaneously
- Must work within Rust's Send/Sync requirements for trait objects

**Arc Reference Counting:**
- `hierarchy()` and `time_table()` return `Option<Arc<dyn HierarchyTrait>>` (cheap to clone)
- `wave_source()` returns `&mut dyn WaveSourceTrait` (cannot clone, requires exclusive access)
- Solution: Wrap WaveSourceTrait in Arc<Mutex<...>> for shared ownership

**Backend State Access Patterns:**
- Header/body loading: One-time initialization, write-heavy
- Signal loading: Frequent, read-heavy on hierarchy, write-heavy on source cache
- Query operations: Very frequent, read-only on hierarchy and time table

## 2. Codebase Research

### Key Files and Their Roles

**`pyrox/src/lib.rs`** - PyO3 bindings and async orchestration
- Lines 45-50: `SharedState` struct - Shared state between main thread and worker
  - `backend: Mutex<Option<Box<dyn WaveformTrait>>>` - Coarse-grained lock
  - `callback: Mutex<Option<PyObject>>` - Callback for async events
- Lines 496-581: `async_worker()` - Worker thread for async operations
  - Processes AsyncRequest enum (LoadHeader, LoadBody, LoadSignals)
  - Currently holds backend lock for entire operation duration
- Lines 545-577: LoadSignals handler - **PRIMARY BOTTLENECK**
  - Lines 551-564: Acquires lock, calls load_signals, releases lock
  - Lines 566-576: Processes results and emits events (without lock)
- Lines 583-648: `emit_event()` - Emits events to Python callback
  - Acquires callback lock during entire Python call (also problematic)
- Lines 716-729: `Waveform::load_body()` - Synchronous body loading
  - Uses `py.allow_threads()` to release GIL (good pattern)
  - Still holds backend lock during I/O (can be improved)

**`pyrox/src/traits.rs`** - Backend-agnostic trait definitions
- Lines 269-281: `WaveSourceTrait` - Signal loading interface
  - `fn load_signals(&mut self, handles, hier) -> Vec<...>` - Requires &mut self
- Lines 283-338: `WaveformTrait` - Main waveform interface
  - `fn hierarchy() -> Option<Arc<dyn HierarchyTrait>>` - Returns Arc (clonable)
  - `fn time_table() -> Option<Arc<dyn TimeTableTrait>>` - Returns Arc (clonable)
  - `fn wave_source() -> Option<&mut dyn WaveSourceTrait>` - Returns &mut (exclusive)
  - **KEY INSIGHT**: hierarchy and time_table are already Arc-based, only wave_source requires mut access

**`pyrox/src/wellen_backend.rs`** - Wellen backend implementation
- Lines 672-789: `WellenWaveform` implementation of WaveformTrait
  - Lines 678-680: State fields - hierarchy, time_table, wave_source
  - Lines 784-788: `wave_source()` method - Returns `&mut WellenSignalSource`
  - **KEY**: wave_source is stored as `Option<WellenSignalSource>`, not Arc<Mutex<...>>
- Lines 622-668: `WellenSignalSource` implementation of WaveSourceTrait
  - Lines 623-625: Fields - `source: wellen::SignalSource`, `time_table: Arc<WellenTimeTable>`
  - Lines 634-667: `load_signals()` implementation - Mutates source (internal caching)
  - **KEY**: Needs &mut because wellen::SignalSource caches loaded signals internally

**`pyrox/src/jets_backend.rs`** - JETS backend implementation
- Lines 729-816: `JetsWaveform` implementation of WaveformTrait
  - Lines 737: State field - `wave_source: Option<JetsSignalSource>`
- Lines 696-725: `JetsSignalSource` implementation of WaveSourceTrait
  - Lines 697-699: Field - `hierarchy: Arc<JetsHierarchy>` (immutable)
  - Lines 707-724: `load_signals()` implementation - Generates signals on-the-fly (no mutation)
  - **KEY**: Doesn't actually need &mut, only uses immutable hierarchy reference

### Current Architecture Patterns

**Shared State Pattern:**
- `SharedState` struct holds backend and callback behind Mutex
- Accessed from both async_worker thread and Python threads
- Current scope: Entire SharedState in single Mutex (coarse-grained)
- Desired scope: Separate Mutex for each field (fine-grained)

**Arc-based Trait Objects:**
- Hierarchy and TimeTable already use Arc for cheap cloning
- Enables multiple threads to hold references simultaneously
- Pattern: Clone Arc when entering critical section, use outside lock

**Mutable Wave Source:**
- WaveSourceTrait requires &mut self for internal caching
- Cannot use Arc<dyn WaveSourceTrait> (trait object not Sized)
- Solution: Arc<Mutex<dyn WaveSourceTrait>> for shared mutable access

**Event Emission Pattern:**
- Worker thread → emit_event() → Python::with_gil() → callback
- Currently holds callback lock during entire Python call
- Should clone callback Arc before calling into Python

### Locking Patterns in Rust

**Current Pattern (Coarse-Grained):**
```rust
let result = {
    let mut guard = shared_state.backend.lock().unwrap();
    // Lock held during entire operation
    guard.as_mut()?.load_signals(...)
}; // Lock released
```

**Desired Pattern (Fine-Grained):**
```rust
// 1. Clone Arc references while holding lock (< 1ms)
let (hier, source_arc) = {
    let guard = shared_state.backend.lock().unwrap();
    (guard.hierarchy()?.clone(), guard.wave_source_arc()?.clone())
}; // Lock released immediately

// 2. Perform expensive work without holding lock (10-100ms)
let result = {
    let mut source = source_arc.lock().unwrap();
    source.load_signals(..., &*hier)
}; // Only wave_source mutex held (not backend mutex)
```

**Key Insight:** The backend mutex only needs to protect access to the backend state fields, not the actual operations on those fields. Once we clone the Arc references, we can work with them independently.

## 3. Implementation Planning

### Strategy Overview

The refactor involves three main changes:

1. **Wrap WaveSourceTrait in Arc<Mutex<...>>** - Enable shared ownership and concurrent access
2. **Add `wave_source_arc()` method to WaveformTrait** - Return clonable Arc instead of &mut reference
3. **Minimize backend lock scope in async_worker** - Clone Arc references, release lock, then perform operations

This approach:
- ✅ Maintains backward compatibility (old methods still work)
- ✅ Requires minimal changes to backend implementations
- ✅ Enables 100x reduction in lock hold time (100ms → < 1ms)
- ✅ Allows concurrent signal queries while loading new signals

### File-by-File Changes

#### `pyrox/src/traits.rs`

**Changes Required:**

1. **Add new trait method to `WaveformTrait`** (after line 337)
   - **Method**: `fn wave_source_arc(&mut self) -> Option<Arc<Mutex<dyn WaveSourceTrait>>>`
   - **Purpose**: Return Arc-wrapped wave source for concurrent access
   - **Rationale**: Enables cloning the wave source reference without holding backend lock
   - **Default Implementation**: Return None (backends override if they support concurrent access)
   - **Integration**: async_worker uses this instead of wave_source() for fine-grained locking

**Code Location:**
```rust
// After line 337 (after wave_source() method)
/// Get shared reference to wave source (for concurrent access).
///
/// Returns an Arc<Mutex<...>> that can be cloned and held without
/// blocking access to the backend. Backends that support concurrent
/// signal loading should override this method.
fn wave_source_arc(&mut self) -> Option<Arc<Mutex<dyn WaveSourceTrait>>> {
    None  // Default: not supported
}
```

#### `pyrox/src/wellen_backend.rs`

**Changes Required:**

1. **Update `WellenWaveform` struct** (line 673)
   - **Change**: Wrap wave_source in Arc<Mutex<...>>
   - **Old**: `wave_source: Option<WellenSignalSource>`
   - **New**: `wave_source: Option<Arc<Mutex<WellenSignalSource>>>`
   - **Rationale**: Enable cloning for concurrent access

2. **Update `WellenWaveform::new()` constructor** (line 696)
   - **Change**: Initialize wave_source as None (no change needed)
   - **Rationale**: wave_source still created in load_body()

3. **Update `WellenWaveform::load_body()` method** (lines 744-778)
   - **Change**: Wrap WellenSignalSource in Arc<Mutex<...>>
   - **Old** (line 769): `self.wave_source = Some(WellenSignalSource::new(...))`
   - **New**: `self.wave_source = Some(Arc::new(Mutex::new(WellenSignalSource::new(...))))`
   - **Rationale**: Create Arc wrapper at initialization time

4. **Update `wave_source()` method** (lines 784-788)
   - **Change**: Return mutable reference by locking the Arc<Mutex<...>>
   - **Challenge**: Cannot return &mut from Mutex guard (lifetime issue)
   - **Solution**: Keep old behavior but add deprecation comment
   - **New approach**: Callers use wave_source_arc() instead

5. **Add `wave_source_arc()` implementation** (after line 788)
   - **Method**: `fn wave_source_arc() -> Option<Arc<Mutex<dyn WaveSourceTrait>>>`
   - **Implementation**: Clone and upcast the Arc
   - **Code**:
     ```rust
     fn wave_source_arc(&mut self) -> Option<Arc<Mutex<dyn WaveSourceTrait>>> {
         self.wave_source
             .as_ref()
             .map(|ws| ws.clone() as Arc<Mutex<dyn WaveSourceTrait>>)
     }
     ```

**Integration Points:**
- Existing synchronous code continues using wave_source() (requires refactoring later)
- Async worker uses wave_source_arc() for fine-grained locking
- No changes to WellenSignalSource implementation (WaveSourceTrait impl stays same)

#### `pyrox/src/jets_backend.rs`

**Changes Required:**

1. **Update `JetsWaveform` struct** (line 730)
   - **Change**: Wrap wave_source in Arc<Mutex<...>>
   - **Old**: `wave_source: Option<JetsSignalSource>`
   - **New**: `wave_source: Option<Arc<Mutex<JetsSignalSource>>>`

2. **Update `JetsWaveform::load_header()` method** (lines 774-794)
   - **Change**: Wrap JetsSignalSource in Arc<Mutex<...>>
   - **Old** (line 791): `self.wave_source = Some(JetsSignalSource::new(...))`
   - **New**: `self.wave_source = Some(Arc::new(Mutex::new(JetsSignalSource::new(...))))`

3. **Update `wave_source()` method** (lines 811-815)
   - **Change**: Keep old signature but note limitation
   - **Note**: Same lifetime issue as Wellen backend

4. **Add `wave_source_arc()` implementation** (after line 815)
   - **Method**: Same as Wellen backend
   - **Implementation**: Clone and upcast the Arc

**Integration Points:**
- JETS backend follows same pattern as Wellen for consistency
- No changes to JetsSignalSource implementation

#### `pyrox/src/lib.rs`

**Changes Required:**

1. **Update `SharedState` struct** (lines 45-50) - **OPTIONAL ENHANCEMENT**
   - **Current**: Single Mutex around entire backend
   - **Enhanced**: Separate Mutex for backend state vs callback
   - **Change**:
     ```rust
     struct SharedState {
         file_path: String,
         backend: Mutex<Option<Box<dyn WaveformTrait>>>,
         callback: Mutex<Option<PyObject>>,
         // No changes - current structure already fine-grained enough
     }
     ```
   - **Rationale**: callback lock is already separate, no change needed

2. **Update `async_worker()` - LoadHeader handler** (lines 505-523)
   - **Change**: Minimize backend lock scope
   - **Before**:
     ```rust
     let result = {
         let mut backend_guard = shared_state.backend.lock().unwrap();
         backend_guard.as_mut()
             .ok_or_else(...)
             .and_then(|b| b.load_header())
     }; // Lock released after entire operation
     ```
   - **After**:
     ```rust
     // 1. Acquire lock just to call load_header (still needs &mut)
     let result = {
         let mut backend_guard = shared_state.backend.lock().unwrap();
         backend_guard.as_mut()
             .ok_or_else(...)
             .and_then(|b| b.load_header())
     }; // Lock released after load_header returns
     // Note: load_header is already reasonably fast, but this ensures
     // the lock is released immediately after it completes
     ```
   - **Rationale**: load_header() cannot be easily split because it needs &mut access to store results. Current pattern is acceptable.

3. **Update `async_worker()` - LoadBody handler** (lines 525-543)
   - **Change**: Same as LoadHeader - current pattern acceptable
   - **Rationale**: load_body() also needs &mut to store results

4. **Update `async_worker()` - LoadSignals handler** (lines 545-577) ⭐ **PRIMARY FIX**
   - **Change**: Clone Arc references, release lock, then load signals
   - **Before**:
     ```rust
     let result = {
         let mut backend_guard = shared_state.backend.lock().unwrap();
         if let Some(backend) = backend_guard.as_mut() {
             match (backend.hierarchy(), backend.wave_source()) {
                 (Some(hier_trait), Some(source)) => {
                     // Load signals while holding the lock
                     Ok(source.load_signals(&handles, &*hier_trait))
                 }
                 // ...
             }
         } else {
             Err("Backend not initialized".to_string())
         }
     }; // backend_guard dropped here (lock held entire time)
     ```
   - **After**:
     ```rust
     // 1. Clone Arc references while holding lock (< 1ms)
     let (hier_arc, source_arc) = {
         let mut backend_guard = shared_state.backend.lock().unwrap();
         if let Some(backend) = backend_guard.as_mut() {
             match (backend.hierarchy(), backend.wave_source_arc()) {
                 (Some(h), Some(s)) => Ok((h, s)),
                 (None, _) => Err("Hierarchy not loaded".to_string()),
                 (_, None) => Err("Wave source not available".to_string()),
             }
         } else {
             Err("Backend not initialized".to_string())
         }
     }?; // backend_guard dropped here (lock released in < 1ms)

     // 2. Load signals without holding backend lock (10-100ms)
     let result = {
         let mut source_guard = source_arc.lock().unwrap();
         source_guard.load_signals(&handles, &*hier_arc)
     }; // Only wave_source lock held during actual loading
     ```
   - **Rationale**: This is the key optimization - backend lock released immediately after cloning Arc references, allowing concurrent access

5. **Update `emit_event()` function** (lines 583-648)
   - **Change**: Clone callback before calling into Python
   - **Before**:
     ```rust
     if let Some(callback) = shared_state.callback.lock().unwrap().as_ref() {
         Python::with_gil(|py| {
             // Build event_dict...
             let _ = callback.call1(py, (event_dict,));
         });
     }
     ```
   - **After**:
     ```rust
     // Clone callback while holding lock (< 1μs)
     let callback_opt = {
         shared_state.callback.lock().unwrap().clone()
     }; // callback lock released immediately

     // Call Python without holding lock
     if let Some(callback) = callback_opt {
         Python::with_gil(|py| {
             // Build event_dict...
             let _ = callback.call1(py, (event_dict,));
         });
     }
     ```
   - **Rationale**: Callback lock should not be held during Python call (GIL interactions)

6. **Update `Waveform::get_signal_by_handle()` method** (lines 929-966)
   - **Change**: Use wave_source_arc() instead of wave_source()
   - **Before**:
     ```rust
     let mut signals = py.allow_threads(|| -> Result<...> {
         let mut backend_guard = self.shared_state.backend.lock().unwrap();
         let backend = backend_guard.as_mut()...;
         let wave_source = backend.wave_source()...;
         Ok(wave_source.load_signals(&[handle], &*hier_trait))
     })...
     ```
   - **After**:
     ```rust
     let mut signals = py.allow_threads(|| -> Result<...> {
         // Get Arc references with minimal lock scope
         let (hier_arc, source_arc) = {
             let mut backend_guard = self.shared_state.backend.lock().unwrap();
             let backend = backend_guard.as_mut()...;
             (backend.hierarchy()?, backend.wave_source_arc()?)
         }; // backend lock released

         // Load signals without backend lock
         let mut source = source_arc.lock().unwrap();
         Ok(source.load_signals(&[handle], &*hier_arc))
     })...
     ```
   - **Rationale**: Consistent with async_worker pattern, reduces lock contention

7. **Update `Waveform::load_signals()` method** (lines 871-924)
   - **Change**: Same pattern as get_signal_by_handle()
   - **Apply same Arc extraction pattern**

**Integration Points:**
- All async operations use wave_source_arc() for fine-grained locking
- Synchronous Python API methods also benefit from reduced lock scope
- Backward compatibility maintained (old wave_source() method still exists)

### Algorithm Descriptions

**Fine-Grained Locking Pattern:**

```
BEFORE (Coarse-Grained):
1. Acquire backend.lock()
2. Get &mut reference to wave_source
3. Call wave_source.load_signals() [10-100ms]
4. Release backend.lock()
Total lock time: 10-100ms ❌

AFTER (Fine-Grained):
1. Acquire backend.lock()
2. Clone Arc<HierarchyTrait>
3. Clone Arc<Mutex<WaveSourceTrait>>
4. Release backend.lock() [< 1ms]
5. Acquire source_arc.lock()
6. Call wave_source.load_signals() [10-100ms]
7. Release source_arc.lock()
Total backend lock time: < 1ms ✅
Total wave_source lock time: 10-100ms (unavoidable)
```

**Key Benefit:** Other threads can access backend (hierarchy, time_table) while signals are loading. Only wave_source is locked during actual loading, which is minimal contention since different threads load different signals.

**Arc Reference Semantics:**

```rust
// Arc::clone() is cheap (just increments reference count)
let hier1: Arc<dyn HierarchyTrait> = backend.hierarchy()?;
let hier2 = hier1.clone();  // < 1μs, no deep copy
// Both hier1 and hier2 point to same underlying hierarchy

// Arc<Mutex<T>> enables shared ownership with interior mutability
let source_arc: Arc<Mutex<dyn WaveSourceTrait>> = backend.wave_source_arc()?;
let source_arc2 = source_arc.clone();  // < 1μs, both share same mutex
{
    let mut source = source_arc.lock().unwrap();
    source.load_signals(...);  // Exclusive access via mutex
}
```

**Concurrent Access Pattern:**

```
Thread 1 (Python - UI query):
1. Lock backend (< 1ms)
2. Get hierarchy Arc
3. Unlock backend
4. Query signal value via hierarchy
5. Return result to UI

Thread 2 (Async Worker - Loading signals):
1. Lock backend (< 1ms) - May briefly wait for Thread 1
2. Get hierarchy Arc and wave_source Arc
3. Unlock backend - Thread 1 can now access backend again ✅
4. Lock wave_source
5. Load signals from file (10-100ms)
6. Unlock wave_source
7. Emit events

Benefit: Thread 1 is NOT blocked for 10-100ms, only for < 1ms overlap
```

### Performance Considerations

**Lock Contention Reduction:**
- Current: Backend lock held 10-100ms per signal batch load
- New: Backend lock held < 1ms per signal batch load
- Improvement: **100x reduction in lock hold time**

**Concurrent Operations Enabled:**
- UI can query signals while background loading occurs
- Multiple async load requests can proceed concurrently (each loads different signals)
- Hierarchy traversal (design tree browsing) no longer blocked by signal loading

**Memory Overhead:**
- Arc wrapper: +8 bytes per reference (negligible)
- Mutex wrapper: +40 bytes per WaveSourceTrait (one per open waveform file)
- Total: < 1KB additional memory for typical sessions

**CPU Overhead:**
- Arc::clone(): +1-2 CPU cycles per clone (< 1μs)
- Mutex lock/unlock: +10-20 CPU cycles (< 1μs)
- Total: < 5μs additional CPU time per operation (negligible)

**Worst-Case Scenarios:**
- **High lock contention**: Multiple threads requesting different signals simultaneously
  - Current: All threads serialize on backend lock (one at a time)
  - New: All threads serialize on wave_source lock (one at a time)
  - Net change: Same serialization but shorter critical sections
- **Cache thrashing**: Rapidly switching between threads
  - Arc reference counting is atomic (cache coherency traffic)
  - Impact: Negligible for < 10 concurrent threads
- **Deadlock risk**: None introduced (no lock ordering issues, single-level locking)

### Testing Strategy

**Unit Tests (Rust):**

1. **Test Arc wrapping preserves functionality**
   - Create WellenWaveform with Arc<Mutex<WaveSourceTrait>>
   - Load signals via wave_source_arc()
   - Verify results match original wave_source() behavior

2. **Test concurrent access doesn't deadlock**
   - Spawn 10 threads
   - Each calls wave_source_arc() and load_signals() concurrently
   - Verify all complete without hanging

3. **Test lock is released after Arc clone**
   - Mock backend with lock tracking
   - Call async_worker LoadSignals handler
   - Verify backend lock is released before load_signals() completes

**Integration Tests (Python):**

1. **Test concurrent signal loading and querying**
   ```python
   # Thread 1: Load 100 signals asynchronously
   # Thread 2: Query hierarchy while loading
   # Verify: Thread 2 doesn't block for full load duration
   ```

2. **Test session loading doesn't freeze**
   ```python
   # Load session with 500 signals
   # Poll QApplication.processEvents() during load
   # Verify: Events processed regularly (< 100ms gaps)
   ```

3. **Test existing tests still pass**
   - Run full pytest suite
   - Verify no regressions in signal loading behavior

**Performance Benchmarks:**

1. **Measure lock hold time**
   - Instrument backend lock with timestamps
   - Load 1000 signals in batches of 50
   - Verify: Average lock hold time < 1ms (currently ~50ms)

2. **Measure concurrent throughput**
   - Load same 1000 signals with varying thread counts (1, 2, 4, 8)
   - Compare: Total wall time vs serial time
   - Expected: Near-linear scaling up to 4 threads (file I/O bound after that)

**Manual Testing:**

1. **Large session load responsiveness**
   - Load session with 500+ signals from multiple files
   - Try to interact with UI during load (scroll, click)
   - Verify: UI remains responsive throughout

2. **Concurrent file access**
   - Open 3 waveform files in same session
   - Load signals from all 3 files simultaneously
   - Verify: No deadlocks, all signals load successfully

### Rollback Plan

**Incremental Deployment:**

Phase 1: Add wave_source_arc() method to traits and backends
- Add new trait method with default None implementation
- Implement in WellenWaveform and JetsWaveform
- No behavior change yet (method exists but unused)
- Risk: None (no existing code calls it)

Phase 2: Update async_worker to use wave_source_arc()
- Modify LoadSignals handler to use new method
- Keep old synchronous methods unchanged
- Test async loading works with new path
- Risk: Low (only affects async path, synchronous still works)

Phase 3: Update synchronous Python API methods
- Modify get_signal_by_handle(), load_signals() to use wave_source_arc()
- Test all signal loading scenarios
- Risk: Medium (affects all signal loading, but pattern is proven from Phase 2)

**Rollback Procedure:**

If issues found in Phase 2 or 3:
1. Revert changes to async_worker / Python API methods
2. Keep wave_source_arc() implementations (harmless)
3. System returns to original behavior
4. No data loss or corruption (locking changes don't affect persistence)

**Monitoring:**

- Add debug logging for lock acquisition times (if performance issues persist)
- Track number of concurrent signal loads (to verify contention is reduced)
- Monitor for any deadlock scenarios (instrument with timeout warnings)

### Future Enhancements

**Read-Write Lock for Backend:**
- Current: Mutex allows one reader OR one writer
- Future: RwLock allows many readers OR one writer
- Benefit: Multiple queries can read hierarchy simultaneously
- Implementation: Replace `Mutex<Option<Box<dyn WaveformTrait>>>` with `RwLock<...>`

**Lock-Free Signal Cache:**
- Current: WaveSourceTrait.load_signals() caches in Mutex-protected structure
- Future: Use concurrent HashMap for cache (e.g., DashMap)
- Benefit: Cache lookups don't block cache insertions
- Implementation: Modify wellen::SignalSource to use concurrent data structures

**Per-Signal Fine-Grained Locking:**
- Current: Loading any signal locks entire WaveSourceTrait
- Future: Lock individual signals during load (e.g., per-SignalRef Mutex)
- Benefit: Loading signal A doesn't block loading signal B
- Implementation: Change WaveSourceTrait cache to HashMap<SignalRef, Mutex<Signal>>

These enhancements are beyond the scope of this refactor but become feasible once fine-grained locking is established.
