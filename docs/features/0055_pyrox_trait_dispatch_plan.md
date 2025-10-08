# Pyrox: Refactor to Trait-Based Dynamic Dispatch

## 1. Use Cases and Requirements Analysis

### Core Functionality
Refactor Pyrox's internal architecture from enum-based dispatch to trait-based dynamic dispatch (using `dyn Trait` objects). This change will make the codebase more scalable and maintainable as additional backend formats are added.

### Current Architecture Limitations

**Problem Statement**: Pyrox currently uses Rust enums with pattern matching to dispatch between different backends (Wellen and JETS):

```rust
pub(crate) enum HierarchyBackend {
    Wellen(Arc<wellen::Hierarchy>),
    Jets(Arc<jets_loader::JetsHierarchy>),
}

pub(crate) enum ScopeBackend { ... }
pub(crate) enum VarBackend { ... }
pub(crate) enum SignalBackend { ... }
```

Every method on these types requires exhaustive pattern matching on all variants:
```rust
match &self.0 {
    HierarchyBackend::Wellen(hier) => { /* wellen logic */ }
    HierarchyBackend::Jets(jets) => { /* jets logic */ }
}
```

**Scalability Issues**:
1. Adding a new backend (e.g., VPD, FSDB, WLF) requires modifying every method in every enum
2. Code duplication across match arms with similar patterns
3. Compile-time coupling between backends
4. Difficult to test backends in isolation

### Target Architecture

**Solution**: Define pure virtual interfaces (traits) for all Pyrox concepts, with backend-specific implementations:

```rust
trait HierarchyTrait: Send + Sync {
    fn all_vars(&self) -> Box<dyn Iterator<Item = Box<dyn VarTrait>> + Send + Sync>;
    fn top_scopes(&self) -> Box<dyn Iterator<Item = Box<dyn ScopeTrait>> + Send + Sync>;
    fn find_var_by_path(&self, path: &[String]) -> Option<Box<dyn VarTrait>>;
    fn get_var_by_signal_ref(&self, handle: SignalHandle) -> Option<Box<dyn VarTrait>>;
    fn date(&self) -> String;
    fn version(&self) -> String;
    fn timescale(&self) -> Option<Timescale>;
    fn file_format(&self) -> String;
}
```

**Key Design Principles**:
1. **Fully synchronous backend traits**: All backend trait methods are synchronous
2. **Async layer at Pyrox level**: Async loading orchestrated in `lib.rs`, not in backends
3. **Backend-agnostic PyO3 wrappers**: Python-facing classes (`Hierarchy`, `Scope`, `Var`, `Signal`) wrap `Arc<dyn Trait>` objects
4. **Zero breaking changes**: Public Python API (`pyrox.pyi`) remains unchanged

### Requirements

#### 1.1 Trait Interface Specifications

**Must Define Traits For**:
- `HierarchyTrait` - Design hierarchy operations
- `ScopeTrait` - Scope/module operations
- `VarTrait` - Variable/signal reference operations
- `SignalTrait` - Signal waveform data operations
- `TimeTableTrait` - Time table access operations
- `RecordTrait` - Hierarchical objects with properties and timed events (used by trace backends)

**Trait Methods Must**:
- Return trait objects (`Box<dyn Trait>`) for complex types
- Use simple types (String, i64, bool, Option) for primitives
- Be fully synchronous (no async/await in traits)
- Support Send + Sync for multi-threading
- Be backend-agnostic (no backend-specific types or comments)

#### 1.2 Backend Implementations

**Wellen Backend** (waveform files: VCD, FST, GHW):
- `WellenHierarchy: HierarchyTrait`
- `WellenScope: ScopeTrait`
- `WellenVar: VarTrait`
- `WellenSignal: SignalTrait`
- `WellenTimeTable: TimeTableTrait`

**JETS Backend** (trace files with hierarchical events):
- `JetsHierarchy: HierarchyTrait`
- `JetsScope: ScopeTrait`
- `JetsVar: VarTrait`
- `JetsSignal: SignalTrait`
- `JetsTimeTable: TimeTableTrait`
- `JetsRecord: RecordTrait`

**Future Backends** (VPD, FSDB, UVM logs, etc.):
- Will implement same trait interface
- May include `RecordTrait` for event-based formats

#### 1.3 Async Loading Architecture

**Current Async System** (must be preserved):
- `AsyncEvent` enum for async operation events
- `AsyncRequest` enum for async operation requests
- `async_worker()` function running in background thread
- Event callbacks to Python via `set_async_callback()`

**Refactored Async Layer**:
- Async orchestration remains in `lib.rs` at the `Waveform` level
- Backend traits provide synchronous data access
- `load_signals_async()` dispatches to backend's sync method on worker thread
- Backend trait does NOT know about async operations

#### 1.4 Python API Stability

**Zero Breaking Changes**:
- All existing Python API signatures unchanged
- `pyrox.pyi` type stubs remain valid
- Existing tests must pass without modification
- Performance characteristics maintained or improved

#### 1.5 Testing Requirements

**Test Coverage**:
1. All existing tests must pass (VCD, FST, GHW, JETS files)
2. No new tests required (architecture change only)
3. Verify no performance regressions
4. Ensure memory usage remains stable

---

## 2. Codebase Research

### 2.1 Current Enum-Based Architecture (pyrox/src/lib.rs)

**Backend Enums**:
- `HierarchyBackend` (line 100-103): `Wellen(Arc<wellen::Hierarchy>) | Jets(Arc<JetsHierarchy>)`
- `ScopeBackend` (line 379-385): `Wellen(wellen::Scope) | Jets { record, clock_freq_mhz }`
- `VarBackend` (line 608-616): `Wellen(wellen::Var) | Jets { record, signal_handle, clock_freq_mhz }`
- `SignalBackend` (line 1803-1811): `Wellen { signal, all_times } | Jets { changes }`

**PyO3 Wrapper Classes**:
- `Hierarchy` (line 107): Wraps `HierarchyBackend`
- `Scope` (line 388): Wraps `ScopeBackend`
- `Var` (line 619): Wraps `VarBackend`
- `Signal` (line 1815): Wraps `SignalBackend`
- `TimeTable` (line 897): Wraps `Arc<wellen::TimeTable>` (Wellen-only, no JETS variant)

**Pattern Matching Locations** (Non-exhaustive sample):
- `Hierarchy::all_vars()` (line 111-173): 62 lines of match logic
- `Hierarchy::top_scopes()` (line 175-201): 26 lines
- `Hierarchy::find_var_by_path()` (line 212-312): 100 lines
- `Scope::name()` (line 392-402): 10 lines
- `Scope::vars()` (line 474-517): 43 lines
- `Var::name()` (line 623-633): 10 lines
- `Signal::value_at_time()` (line 1821-1854): 33 lines
- ... and many more (total: ~1500 lines of match statements)

### 2.2 JETS Backend Structure (pyrox/src/jets_loader.rs)

**JetsHierarchy Struct** (line 189-235):
```rust
pub(crate) struct JetsHierarchy {
    trace_data: Arc<TraceData>,
    clock_freq_mhz: f64,
    record_id_to_handle: HashMap<String, usize>,
    handle_to_record: HashMap<usize, Arc<TraceRecord>>,
}
```

**Key Methods**:
- `clock_freq_mhz()` (line 237): Get clock frequency
- `top_records()` (line 241): Get root TraceRecords
- `get_record_by_handle()` (line 245): Lookup record by handle
- `get_handle_by_id()` (line 249): Lookup handle by ID
- `generate_signal_changes()` (line 262): Create signal waveform from record
- `date()` / `version()` (line 301-312): Metadata access
- `get_max_time()` (line 315): Max timestamp in trace

**Signal Generation** (line 262-289):
- Converts JETS events to waveform signal changes
- Returns `Vec<(i64, String)>` (time, value) pairs
- Handles initial "Z", record start, events, record end

### 2.3 Wellen Backend Integration

**Wellen Types Used**:
- `wellen::Hierarchy`: Design hierarchy
- `wellen::Scope`: Module/task/function scopes
- `wellen::Var`: Variable/signal references
- `wellen::Signal`: Signal waveform data
- `wellen::TimeTable`: Compressed time indices
- `wellen::SignalSource`: Backend for loading signals
- `wellen::SignalRef`: Signal reference handle

**Wellen Ownership Model**:
- Hierarchy stored as `Arc<wellen::Hierarchy>` for shared ownership
- Scopes/Vars are **cloned** from hierarchy on access (not borrowed)
- Signals loaded from `SignalSource`, returned as owned `wellen::Signal`

**Wellen-Specific Challenges**:
- Iterator methods like `scope.vars(hier)` require lifetime parameters
- Current workaround: Collect into `Vec` and return `Box<dyn Iterator>` (line 489-495)

### 2.4 Async Loading Architecture (lib.rs:1006-1142)

**Async Worker Thread**:
- `async_worker(receiver, shared_state)` (line 1006-1142)
- Processes `AsyncRequest` messages (LoadHeader, LoadBody, LoadSignals)
- Emits `AsyncEvent` messages via Python callback
- Uses Tokio runtime for async I/O

**Async Requests**:
- `LoadHeader(LoadOptions)`: Load file header/hierarchy
- `LoadBody`: Load signal waveform data
- `LoadSignals(Vec<SignalHandle>)`: Load specific signals

**Async Events**:
- `HeaderStartLoad` / `HeaderLoaded`
- `BodyStartLoad` / `BodyLoaded`
- `SignalStartLoad(handles)` / `SignalLoaded(signals)` / `JetsSignalLoaded(signals)`
- `Error(String)`

**Shared State** (line 53-64):
```rust
struct SharedState {
    file_path: String,
    hierarchy: Mutex<Option<Arc<wellen::Hierarchy>>>,
    wave_source: Mutex<Option<wellen::SignalSource>>,
    time_table: Mutex<Option<Arc<wellen::TimeTable>>>,
    body_continuation: Mutex<Option<ReadBodyContinuation>>,
    callback: Mutex<Option<PyObject>>,
    header_loaded: AtomicBool,
    body_loaded: AtomicBool,
    jets_hierarchy: Mutex<Option<Arc<JetsHierarchy>>>,
}
```

### 2.5 Current File Loading Flow (Waveform::new)

**File Type Detection** (lib.rs:1264-1303):
1. Check extension: `.jets` or `.jsonl` → JETS loader
2. Otherwise → Wellen loader (VCD/FST/GHW)

**JETS Loading Path**:
- Call `jets_loader::load_jets_file(path)` → returns `JetsHierarchy`
- Create synthetic time table: `[0, max_time]`
- Store in `SharedState.jets_hierarchy`
- Set `header_loaded` and `body_loaded` to true (no separate phases)

**Wellen Loading Path**:
- Call `viewers::read_header_from_file(path, opts)` → returns `HeaderResult`
- Optionally call `viewers::read_body(continuation, hier)` → returns `Body`
- Store hierarchy, wave_source, time_table in `SharedState`

---

## 3. Implementation Planning

### 3.1 Architecture Design

**Three-Layer Architecture**:

```
┌─────────────────────────────────────────────────────┐
│ Python Layer (PyO3)                                 │
│ - Hierarchy/Scope/Var/Signal (wrappers)            │
│ - Async orchestration (Waveform, async_worker)     │
└─────────────────────────────────────────────────────┘
                        ↓ Arc<dyn Trait>
┌─────────────────────────────────────────────────────┐
│ Trait Layer (Pure Virtual Interface)               │
│ - HierarchyTrait, ScopeTrait, VarTrait             │
│ - SignalTrait, TimeTableTrait                      │
│ - All methods synchronous, no async/await          │
└─────────────────────────────────────────────────────┘
                        ↓ impl Trait for T
┌─────────────────────────────────────────────────────┐
│ Backend Layer (Concrete Implementations)            │
│ - WellenHierarchy, WellenScope, WellenVar          │
│ - JetsHierarchy, JetsScope, JetsVar                │
│ - Backend-specific data structures                 │
└─────────────────────────────────────────────────────┘
```

**Design Decisions**:

1. **Trait Objects Over Generic Parameters**:
   - Use `Arc<dyn HierarchyTrait>` instead of `Arc<H: HierarchyTrait>`
   - Simplifies PyO3 wrapper code (no generics in `#[pyclass]`)
   - Allows runtime backend selection based on file type

2. **Iterators Return Trait Objects**:
   - `all_vars() -> Box<dyn Iterator<Item = Box<dyn VarTrait>> + Send + Sync>`
   - Enables heterogeneous collections (mixed backend types)
   - Performance acceptable (iterator allocation already present)

3. **Synchronous Trait Methods**:
   - All trait methods return immediately (no async)
   - Async layer at `Waveform` level dispatches to trait methods on worker thread
   - Backends remain simple, testable, and composable

4. **Arc for Shared Ownership**:
   - `Arc<dyn Trait>` for all trait objects (cheap cloning across Python boundary)
   - Backends implement `Clone` where needed (by cloning Arc)

### 3.2 Trait Interface Specifications

#### File: `pyrox/src/traits.rs` (NEW)

**Purpose**: Define all backend traits for Pyrox

**Trait Definitions**:

```rust
// === Type Aliases and Structs (Backend-Agnostic) ===
/// Time in timescale units (as defined by HierarchyTrait::timescale())
/// Backends convert their native time representation to these units.
/// For example, JETS converts clock cycles to picoseconds internally.
pub type Time = u64;

/// Time table index
pub type TimeTableIdx = u32;

/// Signal handle (0-based index)
pub type SignalHandle = usize;

/// Variable bit range index (backend-agnostic)
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct VarIndex {
    pub msb: i64,
    pub lsb: i64,
}

/// Annotation is a simple name/value tuple (kept lightweight for trace overlays)
pub type Annotation = (String, String);

/// Timed annotation couples a timestamp with its annotation payload
pub type TimedAnnotation = (Time, Annotation);

/// Domain error emitted by signal accessors before PyO3 conversion
#[derive(Debug, thiserror::Error)]
pub enum SignalError {
    #[error("time {0} outside available range")]
    OutOfRange(Time),
    #[error("value format not supported by backend: {0}")]
    UnsupportedFormat(&'static str),
    #[error("backend error: {0}")]
    Backend(String),
}

/// Backend-agnostic signal value representation
#[derive(Debug, Clone, PartialEq)]
pub enum SignalValue {
    Scalar(SignalScalar),
    Vector(Vec<SignalScalar>),
    Real(f64),
    String(String),
    EnumVariant { name: String, index: u32 },
    Opaque(Vec<u8>),
    Unknown,
}

/// Individual scalar value used inside vectors/bitfields
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SignalScalar {
    Zero,
    One,
    X,
    Z,
}

/// Result returned by `query_signal` before PyO3 wrapping
#[derive(Debug, Clone)]
pub struct QueryResult {
    pub value: SignalValue,
    pub actual_time: Time,
    pub next_change: Option<Time>,
}

// === HierarchyTrait ===
pub trait HierarchyTrait: Send + Sync {
    /// Return all variables in the hierarchy
    fn all_vars(&self) -> Box<dyn Iterator<Item = Box<dyn VarTrait>> + Send + Sync>;

    /// Return top-level scopes
    fn top_scopes(&self) -> Box<dyn Iterator<Item = Box<dyn ScopeTrait>> + Send + Sync>;

    /// Find variable by hierarchical path (scope1, scope2, ..., var_name)
    fn find_var_by_path(&self, path: &[String]) -> Option<Box<dyn VarTrait>>;

    /// Get variable by signal handle (0-based index)
    fn get_var_by_signal_ref(&self, handle: SignalHandle) -> Option<Box<dyn VarTrait>>;

    /// Get file metadata
    fn date(&self) -> String;
    fn version(&self) -> String;

    /// Get timescale (factor and unit as strings, e.g., (1, "ps") for 1 picosecond)
    fn timescale(&self) -> Option<(u32, String)>;

    fn file_format(&self) -> String;
}

// === ScopeTrait ===
pub trait ScopeTrait: Send + Sync {
    /// Scope name (local)
    fn name(&self, hier: &dyn HierarchyTrait) -> String;

    /// Scope full hierarchical name
    fn full_name(&self, hier: &dyn HierarchyTrait) -> String;

    /// Scope type string ("module", "task", "record", etc.)
    fn scope_type(&self) -> String;

    /// Variables in this scope
    fn vars(&self, hier: &dyn HierarchyTrait) -> Box<dyn Iterator<Item = Box<dyn VarTrait>> + Send + Sync>;

    /// Child scopes
    fn scopes(&self, hier: &dyn HierarchyTrait) -> Box<dyn Iterator<Item = Box<dyn ScopeTrait>> + Send + Sync>;

    /// Check if this scope represents a hierarchical record with events
    /// (used by trace-based backends like JETS, VPD, UVM logs, etc.)
    fn is_record(&self) -> bool;

    /// Get Record object for trace-based backends
    /// Returns None for waveform backends (Wellen)
    fn record(&self) -> Option<Box<dyn RecordTrait>>;
}

// === VarTrait ===
pub trait VarTrait: Send + Sync {
    /// Variable name (local)
    fn name(&self, hier: &dyn HierarchyTrait) -> String;

    /// Variable full hierarchical name
    fn full_name(&self, hier: &dyn HierarchyTrait) -> String;

    /// Scope path (list of scope names from root to parent)
    fn scope_path(&self, hier: &dyn HierarchyTrait) -> Vec<String>;

    /// Signal handle for this variable (0-based)
    fn signal_handle(&self) -> SignalHandle;

    /// Type information
    fn bitwidth(&self) -> Option<u32>;
    fn var_type(&self) -> String;
    fn enum_type(&self, hier: &dyn HierarchyTrait) -> Option<(String, Vec<(String, String)>)>;
    fn vhdl_type_name(&self, hier: &dyn HierarchyTrait) -> Option<String>;
    fn direction(&self) -> String;
    fn length(&self) -> Option<u32>;
    fn is_real(&self) -> bool;
    fn is_string(&self) -> bool;
    fn is_bit_vector(&self) -> bool;
    fn is_1bit(&self) -> bool;
    fn index(&self) -> Option<VarIndex>;
}

// === SignalTrait ===
/// Signal waveform data. Backend implementations are self-contained and manage
/// their own time representation (indexed vs absolute timestamps).
pub trait SignalTrait: Send + Sync {
    /// Get signal value at a specific time
    fn value_at_time(&self, time: Time) -> Option<SignalValue>;

    /// Get signal value at time table index (converted to time internally if needed)
    fn value_at_idx(&self, idx: TimeTableIdx) -> Option<SignalValue>;

    /// Iterator over all signal changes (time, value) pairs in timescale units
    fn all_changes(&self) -> Box<dyn Iterator<Item = (Time, SignalValue)> + Send + Sync>;

    /// Iterator over changes after a specific time
    fn all_changes_after(&self, start_time: Time)
        -> Box<dyn Iterator<Item = (Time, SignalValue)> + Send + Sync>;

    /// Query signal at time (returns value, actual_time, next transition info)
    fn query_signal(&self, query_time: Time) -> Result<QueryResult, SignalError>;

    /// Compute global min/max range for analog signals
    fn get_global_range(&self, data_format: u8, bit_width: u32) -> Result<(f64, f64), SignalError>;

    /// Signal equality (same underlying signal)
    fn signal_eq(&self, other: &dyn SignalTrait) -> bool;

    /// Signal hash (for use in HashMap)
    fn signal_hash(&self) -> u64;
}

// === TimeTableTrait ===
pub trait TimeTableTrait: Send + Sync {
    /// Get time at index (in picoseconds)
    fn get(&self, idx: usize) -> Option<Time>;

    /// Length of time table
    fn len(&self) -> usize;

    /// Check if empty
    fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// Binary search for time (in picoseconds)
    fn binary_search(&self, time: Time) -> Result<usize, usize>;
}

// === RecordTrait ===
/// Represents hierarchical objects with properties and timed events.
/// Used by trace-based backends (JETS, VPD, UVM logs, etc.) to represent
/// execution records, transactions, or other time-bounded hierarchical events.
///
/// All time values are in the timescale units defined by HierarchyTrait::timescale().
/// Backends convert their native time representation (e.g., clock cycles) internally.
pub trait RecordTrait: Send + Sync {
    /// Record type classification (e.g., "HostProgram", "KernelExecution", "Transaction")
    fn record_type(&self) -> String;

    /// Record name (human-readable)
    fn name(&self) -> String;

    /// Start time in timescale units (from HierarchyTrait::timescale())
    fn start_time(&self) -> Time;

    /// End time in timescale units (None if ongoing or unbounded)
    fn end_time(&self) -> Option<Time>;

    /// Annotations attached to this record (name/value pairs)
    fn annotations(&self) -> Vec<Annotation>;

    /// Events occurring within this record's time range (timed annotations)
    fn events(&self) -> Vec<TimedAnnotation>;
}
```

**Design Notes**:
- **Backend-Agnostic Types**: All trait methods use standard Rust types or Pyrox-defined types
  - `Time = u64` (timescale units, NOT `wellen::Time` or clock cycles)
  - `TimeTableIdx = u32` (NOT Wellen-specific)
  - `SignalHandle = usize` (backend-agnostic 0-based index)
  - `VarIndex` struct with `msb`/`lsb` fields (NOT `wellen::VarIndex`)
  - Timescale returned as `(u32, String)` tuple (NOT `wellen::Timescale`)
- **Time Representation**: All time values are in the units defined by `timescale()`
  - Wellen backend: Returns `wellen::Time as u64` (already in timescale units)
  - JETS backend: Converts clock cycles to timescale units (e.g., picoseconds) internally
  - RecordTrait times (`start_time()`, `end_time()`, `duration()`) are in timescale units
  - No "clock" concept exposed at trait level
- **Signal Self-Containment**: Signals are self-contained and don't require external time table
  - `SignalTrait` methods don't take `time_table` parameter
  - Backend implementations manage time representation internally:
    - `WellenSignal` stores time table reference (needed for indexed timestamps)
    - `JetsSignal` stores absolute timestamps (no time table needed)
  - PyO3 `Signal` wrapper just delegates to backend, no time table field needed
- Trait methods return `SignalValue` / `Annotation` structs; PyO3 conversion happens in wrapper layer (no GIL inside backends)
- Iterator trait objects require `Box<dyn Iterator<...> + Send + Sync>`
- `hier: &dyn HierarchyTrait` parameter avoids circular Arc dependencies
- `RecordTrait` provides backend-agnostic interface for hierarchical events
- Backends that don't support records (Wellen) return `None` from `ScopeTrait::record()`
- Record metadata is represented via `Annotation` / `TimedAnnotation`; backends convert structured fields into name/value pairs when necessary

### 3.3 Backend Implementation Structure

#### File: `pyrox/src/wellen_backend.rs` (NEW)

**Purpose**: Wellen backend trait implementations

**Structs**:

```rust
pub struct WellenHierarchy {
    inner: Arc<wellen::Hierarchy>,
}

pub struct WellenScope {
    inner: wellen::Scope,
}

pub struct WellenVar {
    inner: wellen::Var,
}

pub struct WellenSignal {
    inner: Arc<wellen::Signal>,
    time_table: Arc<WellenTimeTable>,  // Needed to resolve time table indices
}

impl SignalTrait for WellenSignal {
    fn value_at_time(&self, time: Time) -> Option<SignalValue> {
        // Use time_table internally to resolve indices and map to SignalValue
    }

    fn all_changes(&self) -> Box<dyn Iterator<Item = (Time, SignalValue)> + Send + Sync> {
        // Iterate transitions, resolve time indices via time_table, map into SignalValue
    }
    // ...
}

pub struct WellenTimeTable {
    inner: Arc<wellen::TimeTable>,
}

impl TimeTableTrait for WellenTimeTable {
    fn get(&self, idx: usize) -> Option<Time> {
        self.inner.get(idx).cloned().map(|t| t as Time)
    }
    // Wellen times are already in timescale units, just cast to u64
}
```

**Implementation Strategy**:
- Copy existing logic from `HierarchyBackend::Wellen` match arms
- Adapt to trait method signatures
- Remove Hierarchy parameter where possible (use `&dyn HierarchyTrait`)

#### File: `pyrox/src/jets_backend.rs` (NEW, refactored from jets_loader.rs)

**Purpose**: JETS backend trait implementations

**Structs**:

```rust
pub struct JetsHierarchy {
    trace_data: Arc<TraceData>,
    clock_freq_mhz: f64,
    record_id_to_handle: HashMap<String, usize>,
    handle_to_record: HashMap<usize, Arc<TraceRecord>>,
}

pub struct JetsScope {
    record: Arc<TraceRecord>,
    clock_freq_mhz: f64,
}

pub struct JetsVar {
    record: Arc<TraceRecord>,
    signal_handle: usize,
    clock_freq_mhz: f64,
}

pub struct JetsSignal {
    changes: Arc<Vec<(Time, SignalValue)>>,
}

impl SignalTrait for JetsSignal {
    fn value_at_time(&self, time: Time) -> Option<SignalValue> {
        // Find change at or before time in changes vector
        // No time table needed - changes have absolute timestamps
    }

    fn value_at_idx(&self, idx: TimeTableIdx) -> Option<SignalValue> {
        // JETS doesn't use indexed time tables
        // Could return change at index, or None/error
    }

    fn all_changes(&self) -> Box<dyn Iterator<Item = (Time, SignalValue)> + Send + Sync> {
        // Return iterator over changes (already have absolute times)
    }
    // ...
}

pub struct JetsTimeTable {
    times: Arc<Vec<Time>>,  // Synthetic: [0, max_time] in timescale units (picoseconds for JETS)
}

pub struct JetsRecord {
    inner: Arc<TraceRecord>,
    clock_freq_mhz: f64,
}

impl TimeTableTrait for JetsTimeTable {
    fn get(&self, idx: usize) -> Option<Time> {
        self.times.get(idx).cloned()
    }
    // Already stored as Time (u64) in timescale units
}

impl RecordTrait for JetsRecord {
    fn start_time(&self) -> Time {
        // Convert clock cycles to timescale units (picoseconds)
        clock_to_timescale(self.inner.clk, self.clock_freq_mhz)
    }

    fn end_time(&self) -> Option<Time> {
        self.inner.end_clk.map(|clk| clock_to_timescale(clk, self.clock_freq_mhz))
    }
    // ... other methods
}

// Helper function (internal to JETS backend)
fn clock_to_timescale(clk: i64, freq_mhz: f64) -> Time {
    (clk as f64 * 1_000_000.0 / freq_mhz) as Time
}
```

**Implementation Strategy**:
- Copy existing logic from `HierarchyBackend::Jets` match arms
- Adapt to trait method signatures
- **Convert JETS clock cycles to timescale units internally** (during construction)
- `generate_signal_changes()` converts clock cycles to `Time` (u64) in timescale units
- `JetsRecord` implements `RecordTrait` with all times in timescale units (no `_clk` methods exposed)
- `JetsRecord::events()` maps trace events into `TimedAnnotation` pairs (`(timestamp, (name, value))`)
- Internal JETS structs can still store raw `TraceRecord` with clock cycles

### 3.4 PyO3 Wrapper Refactoring

#### File: `pyrox/src/lib.rs` (MAJOR MODIFICATIONS)

**Hierarchy Wrapper** (line 107):

**Before**:
```rust
#[pyclass]
#[derive(Clone)]
pub(crate) struct Hierarchy(pub(crate) HierarchyBackend);
```

**After**:
```rust
#[pyclass]
#[derive(Clone)]
pub(crate) struct Hierarchy(Arc<dyn HierarchyTrait>);
```

**Changes**:
- Replace `HierarchyBackend` enum with `Arc<dyn HierarchyTrait>`
- Remove all `match &self.0` statements
- Direct method calls: `self.0.all_vars()`, `self.0.top_scopes()`, etc.

**Scope Wrapper** (line 388):

**Before**:
```rust
#[pyclass]
pub(crate) struct Scope(pub(crate) ScopeBackend);
```

**After**:
```rust
#[pyclass]
pub(crate) struct Scope(Arc<dyn ScopeTrait>);
```

**Changes**:
- Replace `ScopeBackend` enum with `Arc<dyn ScopeTrait>`
- Methods now call `self.0.name(&*hier.borrow().0)` (pass hierarchy trait ref)

**Var Wrapper** (line 619):

**Before**:
```rust
#[pyclass]
pub(crate) struct Var(pub(crate) VarBackend);
```

**After**:
```rust
#[pyclass]
pub(crate) struct Var(Arc<dyn VarTrait>);
```

**Signal Wrapper** (line 1815):

**Before**:
```rust
#[pyclass]
#[derive(Clone)]
struct Signal {
    backend: SignalBackend,
}
```

**After**:
```rust
#[pyclass]
#[derive(Clone)]
struct Signal {
    backend: Arc<dyn SignalTrait>,
}
```

**Changes**:
- Removed `time_table` field - backends manage their own time table internally
- Methods simplified: `self.backend.value_at_time(time)` (no parameter passing)
- Backend implementations store time table if needed:
  - `WellenSignal` stores time table reference
  - `JetsSignal` doesn't need time table (has absolute timestamps)

**TimeTable Wrapper** (line 897):

**Before**:
```rust
#[pyclass]
#[derive(Clone)]
struct TimeTable(Arc<wellen::TimeTable>);
```

**After**:
```rust
#[pyclass]
#[derive(Clone)]
struct TimeTable(Arc<dyn TimeTableTrait>);
```

**VarIndex Wrapper** (line 594):

**Before**:
```rust
#[pyclass]
struct VarIndex(pub(crate) wellen::VarIndex);
```

**After**:
```rust
#[pyclass]
#[derive(Clone)]
struct VarIndex(pub(crate) crate::traits::VarIndex);  // Backend-agnostic VarIndex
```

**Changes**:
- Replace `wellen::VarIndex` with Pyrox-defined `traits::VarIndex`
- Wellen backend converts `wellen::VarIndex` to `traits::VarIndex`
- JETS backend returns `None` (bit vectors not applicable to string signals)

### 3.5 File Loading Refactoring

#### File: `pyrox/src/lib.rs` (Waveform::new, line 1256-1374)

**Current Logic**:
```rust
if is_jets_file {
    let jets_hier = jets_loader::load_jets_file(&path)?;
    // Store in SharedState.jets_hierarchy
} else {
    let header_result = viewers::read_header_from_file(path, &opts)?;
    // Store in SharedState.hierarchy
}
```

**Refactored Logic**:
```rust
let hierarchy: Arc<dyn HierarchyTrait> = if is_jets_file {
    Arc::new(jets_backend::load_jets_hierarchy(&path)?)
} else {
    Arc::new(wellen_backend::load_wellen_hierarchy(&path, &opts)?)
};

let time_table: Arc<dyn TimeTableTrait> = hierarchy.get_time_table();

// Store in SharedState.hierarchy (now trait object)
```

**SharedState Changes**:
```rust
struct SharedState {
    file_path: String,
    hierarchy: Mutex<Option<Arc<dyn HierarchyTrait>>>,
    time_table: Mutex<Option<Arc<dyn TimeTableTrait>>>,
    wave_source: Mutex<Option<Arc<dyn WaveSourceTrait>>>,  // New trait for signal loading
    // Remove: body_continuation, jets_hierarchy (backend-specific)
    callback: Mutex<Option<PyObject>>,
    header_loaded: AtomicBool,
    body_loaded: AtomicBool,
}
```

**New Trait: WaveSourceTrait**:
```rust
pub trait WaveSourceTrait: Send + Sync {
    fn load_signals(
        &mut self,
        handles: &[SignalHandle],
        hier: &dyn HierarchyTrait,
    ) -> Vec<Arc<dyn SignalTrait>>;
}
```

### 3.6 Async Worker Refactoring

#### File: `pyrox/src/lib.rs` (async_worker, line 1006-1142)

**LoadSignals Request Handling**:

**Before**:
```rust
AsyncRequest::LoadSignals(handles) => {
    if let Some(jets_hier) = shared_state.jets_hierarchy.lock().unwrap().as_ref() {
        // JETS-specific loading
    } else {
        // Wellen-specific loading
    }
}
```

**After**:
```rust
AsyncRequest::LoadSignals(handles) => {
    let hierarchy = shared_state.hierarchy.lock().unwrap().clone();
    if let Some(hier) = hierarchy {
        let mut wave_source = shared_state.wave_source.lock().unwrap();
        if let Some(source) = wave_source.as_mut() {
            // Backend-agnostic signal loading
            let signals = source.load_signals(&handles, &*hier);
            emit_event(&shared_state, AsyncEvent::SignalLoaded(signals));
        }
    }
}
```

**Design**:
- `WaveSourceTrait` abstracts signal loading for all backends
- Worker thread doesn't know about backend types
- Trait method is synchronous (executed on worker thread)

### 3.7 Migration Strategy

**Phase 1: Trait Definitions and Wellen Backend**
1. Create `src/traits.rs` with all trait definitions
2. Create `src/wellen_backend.rs` with Wellen trait implementations
3. Add `WellenTimeTable` implementation
4. Write unit tests for Wellen backend (in `wellen_backend.rs`)

**Phase 2: JETS Backend Migration**
1. Create `src/jets_backend.rs` (refactor from `jets_loader.rs`)
2. Implement all JETS traits
3. Add `JetsTimeTable` implementation
4. Keep `Record` class and helper functions

**Phase 3: PyO3 Wrapper Updates**
1. Update `Hierarchy`, `Scope`, `Var`, `Signal` wrappers to use trait objects
2. Remove all `match` statements on backend enums
3. Update `Waveform::new` to create trait objects
4. Update `SharedState` to store trait objects

**Phase 4: Async Worker Updates**
1. Add `WaveSourceTrait` definition
2. Implement `WaveSourceTrait` for Wellen and JETS
3. Refactor `async_worker` to use trait methods
4. Update async event handling

**Phase 5: Cleanup**
1. Delete old enum types (`HierarchyBackend`, `ScopeBackend`, etc.)
2. Remove `jets_loader.rs` (logic moved to `jets_backend.rs`)
3. Remove unused imports and dead code
4. Run full test suite

---

## 4. Performance Considerations

### 4.1 Trait Object Overhead

**Virtual Dispatch Cost**:
- Trait object method calls use vtable lookup (~1-3 CPU cycles overhead)
- Negligible compared to I/O and data processing costs
- Existing enum dispatch already prevents inlining in many cases

**Memory Overhead**:
- `Arc<dyn Trait>` = 16 bytes (pointer + vtable)
- Previous `enum` variants = 16-32 bytes (depends on largest variant)
- **Net change**: Neutral to slight improvement

### 4.2 Iterator Performance

**Current**:
```rust
VarIter(Box<dyn Iterator<Item = Var> + Send + Sync>)
```

**After Refactoring**:
```rust
VarIter(Box<dyn Iterator<Item = Box<dyn VarTrait>> + Send + Sync>)
```

**Impact**:
- One additional heap allocation per Var (wrapping in `Box<dyn VarTrait>`)
- Allocation already present for `Box<dyn Iterator>`
- **Mitigation**: Iterators are typically consumed once, not cached

### 4.3 Clone Operations

**Arc Cloning**:
- `Arc::clone(&hierarchy)` only increments ref count (atomic operation)
- Cheap crossing of Python boundary (already used extensively)
- No deep copying of backend data structures

### 4.4 Expected Performance

**No Regressions Expected**:
- Signal loading: Backend logic unchanged, same I/O patterns
- Rendering: Signal data access identical (same underlying data)
- Memory: Slight reduction from smaller wrapper types

**Potential Improvements**:
- Better CPU cache utilization (smaller wrapper structs)
- Easier to add backend-specific optimizations (isolated implementations)

---

## 5. Testing Strategy

### 5.1 Existing Test Coverage

**Must Pass Without Changes**:
- `tests/test_read_jets.py` - JETS file loading and hierarchy
- `tests/test_fst_loading.py` - FST/VCD file loading
- `tests/test_async_loading.py` - Async signal loading
- `tests/test_persistence.py` - Session save/load
- `tests/test_waveformdb_protocol.py` - WaveformDB interface

**Test Execution**:
```bash
QT_QPA_PLATFORM=offscreen poetry run pytest tests/ -v
```

### 5.2 Incremental Testing During Migration

**After Phase 1** (Wellen backend):
- Run tests with only Wellen backend active
- Verify VCD/FST/GHW files load correctly
- Check signal loading and rendering

**After Phase 2** (JETS backend):
- Run JETS-specific tests (`tests/test_read_jets.py`)
- Verify record hierarchy and signal generation

**After Phase 3** (PyO3 wrappers):
- Run full test suite
- Check for any API breakage

**After Phase 4** (Async worker):
- Test async signal loading (`tests/test_async_loading.py`)
- Verify callback events fire correctly

### 5.3 Performance Benchmarking

**Benchmark Scenarios**:
1. **Large VCD file loading** (e.g., `test_inputs/swerv1.vcd`)
   - Measure: Time to load hierarchy + 100 signals
   - Baseline: Current implementation
   - Target: Within 5% of baseline

2. **JETS file with many records** (e.g., `jets/gpu_sim.jets`)
   - Measure: Time to load + iterate all vars
   - Baseline: Current implementation
   - Target: Within 5% of baseline

3. **Signal rendering**:
   - Measure: Time to render 50 signals at 1000 transitions each
   - Baseline: Current implementation
   - Target: Within 5% of baseline

**Benchmark Script**:
```bash
poetry run python -m pytest tests/test_performance.py --benchmark-only
```

---

## 6. Risks and Mitigations

### 6.1 Python GIL and Trait Methods

**Risk (Resolved)**: Earlier drafts allowed trait methods to return Python objects, which would have required holding the GIL inside backend implementations.

**Issue**: Trait methods cannot expose `Python<'_>` lifetimes, and embedding GIL acquisition inside backends makes them harder to test.

**Final Mitigation**: Traits now return backend-neutral Rust values (`SignalValue`, `Annotation`). PyO3 wrappers acquire the GIL and perform conversions at the API boundary, keeping trait implementations purely Rust and testable without Python.

### 6.2 Wellen Lifetime Issues

**Risk**: Wellen types use lifetimes extensively (`Scope<'a>`, `Var<'a>`)

**Current Workaround**: Clone scopes/vars from hierarchy (owned data)

**Mitigation**: Continue cloning strategy, no change needed for trait refactor

### 6.3 Backward Compatibility

**Risk**: Subtle API behavior changes break existing code

**Mitigation**:
- No changes to `pyrox.pyi` type stubs
- Identical Python method signatures
- Comprehensive test coverage
- Gradual migration with testing at each phase

### 6.4 Trait Object Limitations

**Risk**: Cannot use generic methods or associated types in trait objects

**Example**:
```rust
// NOT ALLOWED in trait object:
trait Foo {
    fn bar<T>(&self) -> T;  // Generic method
    type Item;              // Associated type
}
```

**Mitigation**: All trait methods use concrete types or `Box<dyn Trait>` returns

---

## 7. Future Extensibility

### 7.1 Adding New Backends

**Process**:
1. Implement all traits in new module (e.g., `src/vpd_backend.rs`)
2. Add file extension detection in `Waveform::new`
3. Instantiate backend hierarchy: `Arc::new(VpdHierarchy::load(path)?)`
4. **No changes needed** to PyO3 wrappers or async worker

**Example** (VPD backend):
```rust
// src/vpd_backend.rs
pub struct VpdHierarchy { /* ... */ }

impl HierarchyTrait for VpdHierarchy {
    fn all_vars(&self) -> Box<dyn Iterator<Item = Box<dyn VarTrait>> + Send + Sync> {
        // VPD-specific implementation
    }
    // ... other methods
}

// In Waveform::new:
let hierarchy: Arc<dyn HierarchyTrait> = if is_jets_file {
    Arc::new(jets_backend::load_jets_hierarchy(&path)?)
} else if is_vpd_file {
    Arc::new(vpd_backend::load_vpd_hierarchy(&path)?)
} else {
    Arc::new(wellen_backend::load_wellen_hierarchy(&path, &opts)?)
};
```

### 7.2 Plugin Architecture (Future)

**Potential Enhancement**: Dynamic backend loading via plugin system

```rust
trait BackendPlugin: Send + Sync {
    fn name(&self) -> &str;
    fn supported_extensions(&self) -> &[&str];
    fn load(&self, path: &str) -> Result<Arc<dyn HierarchyTrait>, String>;
}

// Registry of plugins
static BACKEND_REGISTRY: Lazy<Vec<Box<dyn BackendPlugin>>> = Lazy::new(|| {
    vec![
        Box::new(WellenPlugin),
        Box::new(JetsPlugin),
        // ... user-provided plugins
    ]
});
```

**Benefits**:
- Third-party backends without modifying Pyrox core
- Runtime backend discovery
- Easier testing (mock backends)

---

## 8. Success Criteria

**Must Have**:
- ✅ All trait definitions implemented (Hierarchy, Scope, Var, Signal, TimeTable, Record)
- ✅ Wellen backend fully migrated to traits (with `record()` returning `None`)
- ✅ JETS backend fully migrated to traits (with `RecordTrait` implementation)
- ✅ PyO3 wrappers use trait objects (no enums)
- ✅ Async worker uses trait methods (backend-agnostic)
- ✅ All existing tests pass (23 tests in `test_read_jets.py`, all other test files)
- ✅ No performance regressions (within 5% of baseline)
- ✅ Zero breaking changes to Python API (`pyrox.pyi` unchanged)

**Nice to Have**:
- Improved code organization (backend logic isolated)
- Easier to understand code (less match statement complexity)
- Documentation of trait interface (Rust docs)

---

## 9. Open Questions

### Q1: Should SignalTrait return raw data or Python objects?

**Option A**: Return raw data (e.g., `SignalValue` enum)
```rust
enum SignalValue {
    Binary(Vec<u8>, u32),
    Real(f64),
    String(String),
}
```
- Pro: No GIL required in trait methods
- Con: Extra conversion step in PyO3 wrapper

**Option B**: Return Python objects directly (via PyO3 `PyObject`)
- Pro: No conversion layer in wrappers
- Con: Requires hidden GIL handling inside traits and breaks pure-Rust testing

**Recommendation**: Option A (raw data) — adopted as the final design. All trait methods return Rust-native types and wrappers handle conversion.

### Q2: Should TimeTable be a method or a separate object?

**Option A**: Hierarchy method
```rust
trait HierarchyTrait {
    fn get_time_table(&self) -> Arc<dyn TimeTableTrait>;
}
```

**Option B**: Signal carries time table
```rust
struct Signal {
    backend: Arc<dyn SignalTrait>,
    time_table: Arc<dyn TimeTableTrait>,
}
```

**Recommendation**: Option B (Signal carries time table) - reduces parameter passing

### Q3: Should WaveSourceTrait be separate from HierarchyTrait?

**Option A**: Separate traits
```rust
trait HierarchyTrait { /* ... */ }
trait WaveSourceTrait { /* ... */ }
```
- Pro: Clear separation of concerns
- Con: More trait objects to manage

**Option B**: Combined trait
```rust
trait HierarchyTrait {
    fn load_signals(&mut self, handles: &[SignalHandle]) -> Vec<Arc<dyn SignalTrait>>;
}
```
- Pro: Single trait object
- Con: Mixes hierarchy and signal loading concerns

**Recommendation**: Option A (separate) - better separation, matches current architecture

---

## 10. Implementation Checklist

### Phase 1: Trait Definitions and Core Types
- [ ] Define shared data types (`SignalValue`, `SignalScalar`, `SignalError`, `QueryResult`, `Annotation`, `TimedAnnotation`)
- [ ] Ensure `thiserror` dependency is available in `pyrox/Cargo.toml`
- [ ] Create `pyrox/src/traits.rs` with all trait definitions (`HierarchyTrait`, `ScopeTrait`, `VarTrait`, `SignalTrait`, `TimeTableTrait`, `RecordTrait`)
- [ ] Create `pyrox/src/wellen_backend.rs`
- [ ] Implement `WellenHierarchy: HierarchyTrait`
- [ ] Implement `WellenScope: ScopeTrait` (returns `None` for `record()`)
- [ ] Implement `WellenVar: VarTrait`
- [ ] Implement `WellenSignal: SignalTrait`
- [ ] Implement `WellenTimeTable: TimeTableTrait`
- [ ] Write unit tests for Wellen backend
- [ ] Run subset of tests with Wellen backend only

### Phase 2: JETS Backend Migration
- [ ] Create `pyrox/src/jets_backend.rs`
- [ ] Implement `JetsHierarchy: HierarchyTrait`
- [ ] Implement `JetsScope: ScopeTrait` (returns `Some(Box<dyn RecordTrait>)` for `record()`)
- [ ] Implement `JetsVar: VarTrait`
- [ ] Implement `JetsSignal: SignalTrait`
- [ ] Implement `JetsTimeTable: TimeTableTrait`
- [ ] Implement `JetsRecord: RecordTrait` (wraps `TraceRecord` from rjets)
- [ ] Migrate helper functions from `jets_loader.rs`
- [ ] Run `tests/test_read_jets.py` with new backend

### Phase 3: PyO3 Wrapper Updates
- [ ] Update `Hierarchy` to use `Arc<dyn HierarchyTrait>`
- [ ] Update `Scope` to use `Arc<dyn ScopeTrait>`
- [ ] Update `Var` to use `Arc<dyn VarTrait>`
- [ ] Update `Signal` to use `Arc<dyn SignalTrait>` + `Arc<dyn TimeTableTrait>`
- [ ] Update `TimeTable` to use `Arc<dyn TimeTableTrait>`
- [ ] Remove all `match` statements on backend enums
- [ ] Update `Waveform::new` to create trait objects
- [ ] Update `SharedState` structure
- [ ] Run full test suite

### Phase 4: Async Worker Updates
- [ ] Define `WaveSourceTrait` in `traits.rs`
- [ ] Implement `WaveSourceTrait` for Wellen
- [ ] Implement `WaveSourceTrait` for JETS
- [ ] Refactor `async_worker` to use trait methods
- [ ] Update async event handling
- [ ] Test async signal loading

### Phase 5: Cleanup and Documentation
- [ ] Delete `HierarchyBackend`, `ScopeBackend`, `VarBackend`, `SignalBackend` enums
- [ ] Remove `pyrox/src/jets_loader.rs` (logic moved to `jets_backend.rs`)
- [ ] Remove unused imports and dead code
- [ ] Add Rust documentation comments to all traits
- [ ] Run full test suite (all files)
- [ ] Performance benchmarking
- [ ] Update `pyrox/Cargo.toml` if needed

---

**Document Version**: 1.1
**Author**: Claude (AI Coding Agent)
**Date**: 2025-10-07
**Status**: Planning Complete - Ready for Implementation

**Updates in v1.1**:
- Added `RecordTrait` for backend-agnostic hierarchical event support
- Removed backend-specific references ("JETS only") from trait layer
- Updated `ScopeTrait::record()` to return `Option<Box<dyn RecordTrait>>`
- Clarified that Records are a general concept for trace backends (JETS, VPD, UVM logs, etc.)
- **Removed ALL backend-specific types from trait layer** (critical architectural fix):
  - Replaced `wellen::Time` with `Time = u64` (timescale units)
  - Replaced `wellen::Timescale` with `(u32, String)` tuple
  - Replaced `wellen::VarIndex` with Pyrox-defined `VarIndex` struct
  - Replaced `wellen::TimeTableIdx` with `TimeTableIdx = u32`
  - All trait method signatures now use only standard Rust types or Pyrox-defined types
- **Removed clock concept from trait layer**:
  - `Time = u64` represents timescale units (NOT picoseconds, NOT clock cycles)
  - Timescale units defined by `HierarchyTrait::timescale()` (e.g., "ps", "ns", "fs")
  - `RecordTrait` uses `start_time()` / `end_time()` in timescale units (NOT `start_clk()`)
  - Backends convert native time to timescale units internally:
    - Wellen: `wellen::Time` → `Time` (simple cast)
    - JETS: clock cycles → timescale units (using clock frequency)
- **Removed time_table from SignalTrait methods**:
  - Signals are now self-contained
  - Backend implementations manage their own time representation
  - No need to pass time_table to every signal method
  - PyO3 `Signal` wrapper simplified (no time_table field)
- Updated PyO3 wrappers to use backend-agnostic types
- Updated implementation checklist to include `RecordTrait` implementation for JETS backend
- **All trait interfaces are now fully backend-agnostic** ✅
