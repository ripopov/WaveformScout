# Backend-Agnostic Waveform Loading Trait

## 1. Use Cases and Requirements Analysis

### Core Functionality

**Problem Statement**: Following the implementation of 0055_pyrox_trait_dispatch_plan.md, `pyrox/src/lib.rs` still contains Wellen-specific code in the file loading and async worker functions. The current implementation hard-codes Wellen's two-phase loading model (header → body) directly into the async worker, making it impossible for backends like JETS (which load atomically) to properly participate in the async loading infrastructure.

### Current Limitations

**Wellen-Specific Code Locations**:

1. **`async_worker()` function (lib.rs:568-695)**:
   - `AsyncRequest::LoadHeader` handler directly calls `viewers::read_header_from_file()` (Wellen API)
   - `AsyncRequest::LoadBody` handler directly calls `viewers::read_body()` (Wellen API)
   - Stores `ReadBodyContinuation` in `SharedState` (Wellen-specific type)
   - Downcasts to `WellenHierarchy` to access `inner()` method

2. **`Waveform::new()` function (lib.rs:777-900)**:
   - Branches on file extension (`.jets` vs others) with completely different loading logic
   - JETS path: Directly instantiates `JetsHierarchy` and trait wrappers
   - Wellen path: Directly calls `viewers::read_header_from_file()` and `viewers::read_body()`
   - Creates different `SharedState` depending on backend type

3. **`SharedState` structure (lib.rs:52-61)**:
   - Contains `body_continuation: Mutex<Option<Box<ReadBodyContinuation>>>` (Wellen-specific)
   - Fields like `header_loaded` and `body_loaded` assume two-phase loading model

**Architecture Issues**:

1. **No Backend Abstraction for File Loading**: No trait exists to abstract "load a waveform file into hierarchy + time table + signal source"
2. **Two-Phase Loading Hardcoded**: The header/body split is a Wellen implementation detail, not a universal concept (JETS loads atomically)
3. **Backend-Specific Branching**: File loading branches on file type with completely different code paths
4. **Downcast Required**: Async worker must downcast trait objects to access backend-specific methods

### Target Architecture

**Solution**: Introduce a `WaveformTrait` that provides a synchronous, backend-agnostic interface for waveform file loading with optional multi-phase loading support.

**Design Principles**:

1. **Synchronous Trait API**: All trait methods are synchronous; async orchestration remains in `lib.rs`
2. **Optional Multi-Phase Loading**: Backends can implement header/body separation (Wellen) or treat both as no-ops (JETS)
3. **Backend Factory Pattern**: Factory function creates appropriate backend based on file extension
4. **No Downcasting Required**: All operations go through trait methods, no access to backend internals
5. **Unified SharedState**: Same state structure works for all backends

### Requirements

#### 1.0 Non-Blocking Constructor Requirement

**Critical Constraint for GUI Applications**:

The `Waveform` constructor **must be non-blocking** when both `load_header=False` and `load_body=False`:

```python
# This must return immediately without I/O
waveform = pyrox.Waveform(path, load_header=False, load_body=False)

# Heavy I/O happens here (on async worker thread)
waveform.load_header_async()
waveform.load_body_async()
```

**Rationale**:
- GUI applications must remain responsive during file loading
- Background loading allows progress indicators and cancellation
- Large files (>1GB) can take 10+ seconds to load

**Implementation Constraint**:
- Backend constructors (`new()`) **must not perform I/O**
- Constructors only validate path and store configuration
- All file parsing happens in `load_header()` / `load_body()` methods
- JETS backend must defer `rjets::parse_trace()` to `load_header()`, not constructor

#### 1.1 WaveformTrait Interface

**Must Define**:

```rust
pub trait WaveformTrait: Send + Sync {
    /// Get the hierarchy (returns None if header not loaded)
    fn hierarchy(&self) -> Option<Arc<dyn HierarchyTrait>>;

    /// Get the time table (returns None if body not loaded)
    fn time_table(&self) -> Option<Arc<dyn TimeTableTrait>>;

    /// Load file header/hierarchy synchronously
    /// For backends like JETS, this MUST load the entire file (all data)
    /// For backends like Wellen, this loads only the hierarchy
    fn load_header(&mut self) -> Result<(), String>;

    /// Check if header is loaded
    fn header_loaded(&self) -> bool;

    /// Load signal waveform data synchronously
    /// For backends like JETS, this is a no-op (everything loaded in load_header)
    /// For backends like Wellen, this reads the body continuation
    fn load_body(&mut self) -> Result<(), String>;

    /// Check if body is loaded
    fn body_loaded(&self) -> bool;

    /// Get signal source (returns None if body not loaded)
    fn wave_source(&mut self) -> Option<&mut dyn WaveSourceTrait>;
}
```

**Trait Design Notes**:
- All methods synchronous (called from async worker thread)
- **Backend constructors must not perform I/O** (non-blocking requirement)
- All heavy file parsing deferred to `load_header()` / `load_body()`
- Backends store internal state (hierarchy, time table, signal source)
- `load_header()` and `load_body()` are idempotent (safe to call multiple times)
- **JETS backend**: `load_header()` parses entire file, `load_body()` is immediate no-op
- **Wellen backend**: `load_header()` reads hierarchy only, `load_body()` reads signal data
- Mutable references (`&mut self`) allow backends to update internal state

#### 1.2 Backend Implementations

**Wellen Backend**:
- Constructor: **No I/O** - only stores path and options
- `load_header()`: Calls `viewers::read_header_from_file()`, stores continuation
- `load_body()`: Consumes continuation, calls `viewers::read_body()`
- Returns trait objects for hierarchy, time table, signal source

**JETS Backend**:
- Constructor: **No I/O** - only stores path and options
- `load_header()`: **Parses entire JETS file** via `rjets::parse_trace()`, sets both header_loaded and body_loaded flags
- `load_body()`: No-op (returns Ok immediately, everything already loaded)
- Returns trait objects for hierarchy, time table, signal source

**Design Constraint**: Both backends must defer all file I/O to `load_header()` / `load_body()` methods to ensure non-blocking constructor.

#### 1.3 Backend Factory

**Factory Function**:
```rust
fn create_waveform_backend(
    path: &str,
    opts: &LoadOptions
) -> Result<Box<dyn WaveformTrait>, String>
```

**Responsibilities**:
- Detect file type from extension (`.jets`, `.jsonl`, `.vcd`, `.fst`, `.ghw`)
- Instantiate appropriate backend implementation
- Return boxed trait object
- Error handling for unsupported formats

#### 1.4 Async Worker Simplification

**LoadHeader Request**:
- No longer calls Wellen API directly
- Calls `backend.load_header()` through trait
- No knowledge of backend type

**LoadBody Request**:
- No longer calls Wellen API directly
- Calls `backend.load_body()` through trait
- No downcast required

**Unified Event Flow**:
- Same events (`HeaderStartLoad`, `HeaderLoaded`, etc.) for all backends
- No backend-specific event types
- Python layer unaware of backend differences

#### 1.5 Python API Stability

**Zero Breaking Changes**:
- `Waveform.__init__()` signature unchanged
- All existing async methods (`load_header_async()`, `load_body_async()`, `load_signals_async()`) work unchanged
- Same events emitted to Python callbacks
- Performance characteristics maintained

---

## 2. Codebase Research

### 2.1 Current File Loading Flow

**Waveform::new() - Wellen Path** (lib.rs:829-900):

```rust
let opts = LoadOptions { multi_thread, remove_scopes_with_empty_name };

if load_header {
    let header_result = viewers::read_header_from_file(path, &opts).toerr()?;
    let wellen_hier = Arc::new(header_result.hierarchy);
    let hier_trait = Arc::new(WellenHierarchy::new(wellen_hier.clone()));

    if load_body {
        let body = viewers::read_body(header_result.body, &wellen_hier, None)?;
        let time_table_trait = Arc::new(WellenTimeTable { inner: Arc::new(body.time_table.clone()) });
        let wave_source_trait = Box::new(WellenSignalSource::new(body.source, ...));

        // Store in SharedState with both loaded flags = true
    } else {
        // Store continuation in SharedState with body_loaded = false
    }
} else {
    // Create SharedState with header_loaded = false
}
```

**Waveform::new() - JETS Path** (lib.rs:786-827):

```rust
if is_jets_file {
    let trace_data = rjets::parse_trace(&path)?;  // ← BLOCKING I/O
    let jets_hier = Arc::new(JetsHierarchy::new(Arc::new(trace_data)));
    let max_time = jets_hier.get_max_time();

    let hier_trait: Arc<dyn HierarchyTrait> = jets_hier.clone();
    let time_table_trait = Arc::new(JetsTimeTable::new(max_time));
    let wave_source_trait = Box::new(JetsSignalSource::new(jets_hier));

    // Store in SharedState with both loaded flags = true
}
```

**Key Observations**:
- Completely divergent code paths for JETS vs Wellen
- **JETS performs blocking I/O in constructor** (violates non-blocking requirement)
- JETS loads everything upfront (no header/body separation)
- Wellen supports incremental loading (header only, or header + body)
- Both paths construct trait objects, but through different means
- No shared abstraction for "create backend from file"

**Problem**: Current code calls `rjets::parse_trace()` in constructor, blocking GUI thread

### 2.2 Async Worker Implementation

**LoadHeader Handler** (lib.rs:577-603):

```rust
AsyncRequest::LoadHeader(opts) => {
    emit_event(&shared_state, AsyncEvent::HeaderStartLoad);

    let path = shared_state.file_path.clone();

    match viewers::read_header_from_file(&path, &opts) {  // ← Wellen-specific
        Ok(header_result) => {
            let hier_trait = Arc::new(WellenHierarchy::new(Arc::new(header_result.hierarchy)));

            *shared_state.hierarchy.lock().unwrap() = Some(hier_trait);
            *shared_state.body_continuation.lock().unwrap() = Some(Box::new(header_result.body));
            shared_state.header_loaded.store(true, Ordering::Relaxed);

            emit_event(&shared_state, AsyncEvent::HeaderLoaded);
        }
        Err(e) => emit_event(&shared_state, AsyncEvent::Error(e.to_string())),
    }
}
```

**LoadBody Handler** (lib.rs:605-659):

```rust
AsyncRequest::LoadBody => {
    emit_event(&shared_state, AsyncEvent::BodyStartLoad);

    let body_cont = shared_state.body_continuation.lock().unwrap().take();
    if let Some(body_cont) = body_cont {
        let hierarchy = shared_state.hierarchy.lock().unwrap().clone();
        if let Some(hier_trait) = hierarchy {
            // Downcast to WellenHierarchy ← Backend-specific
            if let Some(wellen_hier) = hier_trait.as_any().downcast_ref::<WellenHierarchy>() {
                match viewers::read_body(*body_cont, wellen_hier.inner(), None) {  // ← Wellen-specific
                    Ok(body) => {
                        let time_table_trait = Arc::new(WellenTimeTable { inner: Arc::new(body.time_table.clone()) });
                        let wave_source_trait = Box::new(WellenSignalSource::new(body.source, ...));

                        *shared_state.wave_source.lock().unwrap() = Some(wave_source_trait);
                        *shared_state.time_table.lock().unwrap() = Some(time_table_trait);
                        shared_state.body_loaded.store(true, Ordering::Relaxed);

                        emit_event(&shared_state, AsyncEvent::BodyLoaded);
                    }
                    Err(e) => emit_event(&shared_state, AsyncEvent::Error(e.to_string())),
                }
            }
        }
    }
}
```

**Key Observations**:
- Direct calls to Wellen API (`viewers::read_header_from_file`, `viewers::read_body`)
- Downcast required to access `wellen_hier.inner()` method
- JETS backend cannot participate in async header/body loading
- No way to add new backends without modifying `async_worker()`

### 2.3 SharedState Structure

**Current Definition** (lib.rs:52-61):

```rust
struct SharedState {
    file_path: String,
    hierarchy: Mutex<Option<Arc<dyn HierarchyTrait>>>,
    wave_source: Mutex<Option<Box<dyn WaveSourceTrait>>>,
    time_table: Mutex<Option<Arc<dyn TimeTableTrait>>>,
    body_continuation: Mutex<Option<Box<ReadBodyContinuation<...>>>>,  // ← Wellen-specific
    callback: Mutex<Option<PyObject>>,
    header_loaded: AtomicBool,
    body_loaded: AtomicBool,
}
```

**Issues**:
- `body_continuation` field only used by Wellen backend (JETS leaves it `None`)
- Two boolean flags assume all backends have two-phase loading
- Fields are populated differently depending on backend type

**Proposed Simplification**:
- Replace individual fields with single `backend: Mutex<Option<Box<dyn WaveformTrait>>>`
- Backend owns all state (hierarchy, time table, signal source, loading status)
- Remove `body_continuation`, `header_loaded`, `body_loaded` (delegated to backend)
- Keep only `file_path` and `callback` in SharedState

### 2.4 Existing Trait Implementations

**HierarchyTrait** (traits.rs:90-114):
- Already fully backend-agnostic
- Methods: `all_vars()`, `top_scopes()`, `find_var_by_path()`, etc.
- Implemented by `WellenHierarchy` and `JetsHierarchy`

**WaveSourceTrait** (traits.rs:269-281):
- Already backend-agnostic
- Method: `load_signals(&mut self, handles, hier) -> Vec<(handle, signal)>`
- Implemented by `WellenSignalSource` and `JetsSignalSource`

**TimeTableTrait** (traits.rs:216-236):
- Already backend-agnostic
- Methods: `get()`, `len()`, `binary_search()`
- Implemented by `WellenTimeTable` and `JetsTimeTable`

**No Gap**: All trait objects already exist and are fully backend-agnostic. The only missing piece is a trait for the waveform file loading itself.

### 2.5 Backend-Specific Types in lib.rs

**Wellen Dependencies** (lib.rs:22-25):

```rust
use wellen::{
    viewers::{self, ReadBodyContinuation},
    LoadOptions, SignalRef, SignalValue, TimeTableIdx,
};
```

**After Refactoring**:
- Move `ReadBodyContinuation` into `wellen_backend.rs` (internal to Wellen backend)
- Keep `LoadOptions` (used in factory function parameter)
- Remove direct `viewers` module usage from `lib.rs`
- `SignalRef`, `SignalValue`, `TimeTableIdx` already replaced by trait equivalents

### 2.6 File Format Detection

**Current Logic** (lib.rs:787):

```rust
let is_jets_file = path.ends_with(".jets") || path.ends_with(".jsonl");
```

**Extensions to Support**:
- `.jets`, `.jsonl` → JETS backend
- `.vcd` → Wellen backend (VCD format)
- `.fst` → Wellen backend (FST format)
- `.ghw` → Wellen backend (GHDL waveform format)
- Future: `.vpd`, `.fsdb`, `.wlf`, etc.

**Factory Function Responsibility**:
- Centralize file extension detection
- Return appropriate backend instance
- Error for unsupported extensions

---

## 3. Implementation Planning

### 3.1 Architecture Design

**Three-Layer Architecture** (unchanged):

```
┌─────────────────────────────────────────────────────┐
│ Python Layer (PyO3)                                 │
│ - Waveform class (async orchestration)             │
│ - Hierarchy/Signal wrappers (trait delegation)     │
└─────────────────────────────────────────────────────┘
                        ↓ Arc<dyn Trait>
┌─────────────────────────────────────────────────────┐
│ Trait Layer (Pure Virtual Interface)               │
│ - HierarchyTrait, SignalTrait, WaveSourceTrait     │
│ - WaveformTrait ← NEW                              │
└─────────────────────────────────────────────────────┘
                        ↓ impl Trait for T
┌─────────────────────────────────────────────────────┐
│ Backend Layer (Concrete Implementations)            │
│ - WellenWaveform, JetsWaveform ← NEW               │
│ - WellenHierarchy, JetsHierarchy (existing)        │
└─────────────────────────────────────────────────────┘
```

**New Component**: `WaveformTrait` sits at the same abstraction level as `HierarchyTrait`, providing backend-agnostic file loading.

**Ownership Model**:
- `WaveformTrait` implementation owns all backend state
- Returns borrowed trait objects (`&dyn HierarchyTrait`) or Arc-wrapped objects
- Mutable access required for loading operations (`&mut self`)
- SharedState stores `Box<dyn WaveformTrait>` with interior mutability

### 3.2 WaveformTrait Definition

#### File: `pyrox/src/traits.rs` (ADD)

**Location**: After `WaveSourceTrait` definition (line 282+)

**Trait Definition**:

```rust
/// Backend-agnostic waveform file loading interface.
///
/// This trait abstracts the process of loading waveform files into their constituent parts:
/// hierarchy (design structure), time table (timestamp index), and signal source (waveform data).
///
/// Backends may implement different loading strategies:
/// - **Two-phase loading** (Wellen): `load_header()` reads hierarchy, `load_body()` reads signal data
/// - **Atomic loading** (JETS): `load_header()` loads everything, `load_body()` is a no-op
///
/// All methods are synchronous; async orchestration is handled by the PyO3 layer.
pub trait WaveformTrait: Send + Sync {
    /// Get the hierarchy (returns None if header not loaded)
    fn hierarchy(&self) -> Option<Arc<dyn HierarchyTrait>>;

    /// Get the time table (returns None if body not loaded)
    fn time_table(&self) -> Option<Arc<dyn TimeTableTrait>>;

    /// Load file header/hierarchy synchronously.
    ///
    /// For backends with two-phase loading (Wellen), this reads the hierarchy and prepares
    /// for body loading. For backends with atomic loading (JETS), this may load everything.
    ///
    /// This method is idempotent: calling multiple times has no additional effect.
    ///
    /// Returns: Ok(()) on success, Err(msg) on failure
    fn load_header(&mut self) -> Result<(), String>;

    /// Check if header is loaded
    fn header_loaded(&self) -> bool;

    /// Load signal waveform data synchronously.
    ///
    /// For backends with two-phase loading (Wellen), this reads the signal data using
    /// a continuation from the header phase. For backends with atomic loading (JETS),
    /// this is a no-op (returns immediately).
    ///
    /// This method is idempotent: calling multiple times has no additional effect.
    ///
    /// Returns: Ok(()) on success, Err(msg) on failure
    fn load_body(&mut self) -> Result<(), String>;

    /// Check if body is loaded
    fn body_loaded(&self) -> bool;

    /// Get mutable access to signal source (returns None if body not loaded).
    ///
    /// Mutable access is required because signal loading may update internal caches.
    fn wave_source(&mut self) -> Option<&mut dyn WaveSourceTrait>;
}
```

**Design Notes**:
- All methods are synchronous (called from async worker thread)
- `&mut self` for state-modifying operations (`load_header()`, `load_body()`, `wave_source()`)
- Returns `Option` for state-dependent getters (None if not yet loaded)
- Returns `Result<(), String>` for operations that can fail
- Idempotent loading methods (safe to call multiple times)

### 3.3 Backend Factory Function

#### File: `pyrox/src/lib.rs` (ADD)

**Location**: Before `async_worker()` function (around line 567)

**Factory Function**:

```rust
/// Create a waveform backend based on file extension
fn create_waveform_backend(
    path: &str,
    opts: LoadOptions,
) -> Result<Box<dyn traits::WaveformTrait>, String> {
    // Detect file type from extension
    let path_lower = path.to_lowercase();

    if path_lower.ends_with(".jets") || path_lower.ends_with(".jsonl") {
        // JETS backend
        Ok(Box::new(jets_backend::JetsWaveform::new(path.to_string(), opts)))
    } else if path_lower.ends_with(".vcd") || path_lower.ends_with(".fst") || path_lower.ends_with(".ghw") {
        // Wellen backend
        Ok(Box::new(wellen_backend::WellenWaveform::new(path.to_string(), opts)))
    } else {
        Err(format!("Unsupported file format: {}", path))
    }
}
```

**Responsibilities**:
- Centralize file type detection (single source of truth)
- Return appropriate backend based on extension
- Error for unsupported formats
- Pass `LoadOptions` to backend constructor

### 3.4 Wellen Backend Implementation

#### File: `pyrox/src/wellen_backend.rs` (ADD)

**New Struct**: `WellenWaveform`

```rust
pub struct WellenWaveform {
    path: String,
    opts: wellen::LoadOptions,

    // State management
    hierarchy: Option<Arc<WellenHierarchy>>,
    time_table: Option<Arc<WellenTimeTable>>,
    wave_source: Option<WellenSignalSource>,

    // Internal Wellen state
    body_continuation: Option<wellen::viewers::ReadBodyContinuation<std::io::BufReader<std::fs::File>>>,

    // Loading status
    header_loaded: bool,
    body_loaded: bool,
}

impl WellenWaveform {
    /// Create a new Wellen waveform backend.
    ///
    /// IMPORTANT: This constructor performs NO I/O and returns immediately.
    /// All file parsing is deferred to load_header() / load_body() to ensure
    /// non-blocking construction for GUI applications.
    pub fn new(path: String, opts: wellen::LoadOptions) -> Self {
        Self {
            path,
            opts,
            hierarchy: None,
            time_table: None,
            wave_source: None,
            body_continuation: None,
            header_loaded: false,
            body_loaded: false,
        }
    }
}

impl traits::WaveformTrait for WellenWaveform {
    fn hierarchy(&self) -> Option<Arc<dyn traits::HierarchyTrait>> {
        self.hierarchy.as_ref().map(|h| h.clone() as Arc<dyn traits::HierarchyTrait>)
    }

    fn time_table(&self) -> Option<Arc<dyn traits::TimeTableTrait>> {
        self.time_table.as_ref().map(|tt| tt.clone() as Arc<dyn traits::TimeTableTrait>)
    }

    fn load_header(&mut self) -> Result<(), String> {
        if self.header_loaded {
            return Ok(()); // Idempotent
        }

        let header_result = wellen::viewers::read_header_from_file(&self.path, &self.opts)
            .map_err(|e| e.to_string())?;

        self.hierarchy = Some(Arc::new(WellenHierarchy::new(Arc::new(header_result.hierarchy))));
        self.body_continuation = Some(header_result.body);
        self.header_loaded = true;

        Ok(())
    }

    fn header_loaded(&self) -> bool {
        self.header_loaded
    }

    fn load_body(&mut self) -> Result<(), String> {
        if self.body_loaded {
            return Ok(()); // Idempotent
        }

        if !self.header_loaded {
            return Err("Header must be loaded before body".to_string());
        }

        let body_cont = self.body_continuation.take()
            .ok_or_else(|| "Body continuation not available".to_string())?;

        let hierarchy = self.hierarchy.as_ref()
            .ok_or_else(|| "Hierarchy not available".to_string())?;

        let body = wellen::viewers::read_body(body_cont, hierarchy.inner(), None)
            .map_err(|e| e.to_string())?;

        self.time_table = Some(Arc::new(WellenTimeTable { inner: Arc::new(body.time_table.clone()) }));
        self.wave_source = Some(WellenSignalSource::new(
            body.source,
            Arc::new(WellenTimeTable { inner: Arc::new(body.time_table) }),
        ));
        self.body_loaded = true;

        Ok(())
    }

    fn body_loaded(&self) -> bool {
        self.body_loaded
    }

    fn wave_source(&mut self) -> Option<&mut dyn traits::WaveSourceTrait> {
        self.wave_source.as_mut().map(|ws| ws as &mut dyn traits::WaveSourceTrait)
    }
}
```

**Design Notes**:
- Encapsulates all Wellen-specific types (`ReadBodyContinuation`)
- Two-phase loading: `load_header()` stores continuation, `load_body()` consumes it
- Idempotent methods check flags before re-loading
- `hierarchy()` / `time_table()` return trait objects (upcast from concrete types)
- `inner()` method on `WellenHierarchy` is now private (only used within backend)

### 3.5 JETS Backend Implementation

#### File: `pyrox/src/jets_backend.rs` (ADD)

**New Struct**: `JetsWaveform`

```rust
pub struct JetsWaveform {
    path: String,
    _opts: wellen::LoadOptions,  // Unused by JETS, but kept for API consistency

    // State management
    hierarchy: Option<Arc<JetsHierarchy>>,
    time_table: Option<Arc<JetsTimeTable>>,
    wave_source: Option<JetsSignalSource>,

    // Loading status (both set to true after load_header)
    loaded: bool,
}

impl JetsWaveform {
    /// Create a new JETS waveform backend.
    ///
    /// IMPORTANT: This constructor performs NO I/O and returns immediately.
    /// All file parsing is deferred to load_header() to ensure non-blocking
    /// construction for GUI applications.
    pub fn new(path: String, opts: wellen::LoadOptions) -> Self {
        Self {
            path,
            _opts: opts,
            hierarchy: None,
            time_table: None,
            wave_source: None,
            loaded: false,
        }
    }
}

impl traits::WaveformTrait for JetsWaveform {
    fn hierarchy(&self) -> Option<Arc<dyn traits::HierarchyTrait>> {
        self.hierarchy.as_ref().map(|h| h.clone() as Arc<dyn traits::HierarchyTrait>)
    }

    fn time_table(&self) -> Option<Arc<dyn traits::TimeTableTrait>> {
        self.time_table.as_ref().map(|tt| tt.clone() as Arc<dyn traits::TimeTableTrait>)
    }

    fn load_header(&mut self) -> Result<(), String> {
        if self.loaded {
            return Ok(()); // Idempotent
        }

        // JETS loads ENTIRE FILE in load_header() (all data in one shot)
        // This is the ONLY place where rjets::parse_trace() is called
        let trace_data = rjets::parse_trace(&self.path)
            .map_err(|e| format!("Failed to load JETS file: {}", e))?;

        let jets_hier = Arc::new(JetsHierarchy::new(Arc::new(trace_data)));
        let max_time = jets_hier.get_max_time();

        self.hierarchy = Some(jets_hier.clone());
        self.time_table = Some(Arc::new(JetsTimeTable::new(max_time)));
        self.wave_source = Some(JetsSignalSource::new(jets_hier));
        self.loaded = true;

        Ok(())
    }

    fn header_loaded(&self) -> bool {
        self.loaded
    }

    fn load_body(&mut self) -> Result<(), String> {
        // JETS loads everything in load_header(), so this is a no-op
        // Returns Ok immediately (no error if header not loaded - backend decision)
        Ok(())
    }

    fn body_loaded(&self) -> bool {
        self.loaded
    }

    fn wave_source(&mut self) -> Option<&mut dyn traits::WaveSourceTrait> {
        self.wave_source.as_mut().map(|ws| ws as &mut dyn traits::WaveSourceTrait)
    }
}
```

**Design Notes**:
- **Constructor performs NO I/O** (critical for non-blocking requirement)
- **Atomic loading**: `load_header()` loads entire file, `load_body()` is a no-op
- Single `loaded` flag (both header and body loaded together)
- Idempotent `load_header()` returns immediately if already loaded
- Same trait interface as Wellen, but different implementation strategy
- `load_body()` is permissive (returns Ok even if nothing loaded - backend's choice)

### 3.6 SharedState Refactoring

#### File: `pyrox/src/lib.rs` (MODIFY)

**Before** (lib.rs:52-61):

```rust
struct SharedState {
    file_path: String,
    hierarchy: Mutex<Option<Arc<dyn HierarchyTrait>>>,
    wave_source: Mutex<Option<Box<dyn WaveSourceTrait>>>,
    time_table: Mutex<Option<Arc<dyn TimeTableTrait>>>,
    body_continuation: Mutex<Option<Box<ReadBodyContinuation<...>>>>,
    callback: Mutex<Option<PyObject>>,
    header_loaded: AtomicBool,
    body_loaded: AtomicBool,
}
```

**After**:

```rust
struct SharedState {
    file_path: String,
    backend: Mutex<Option<Box<dyn traits::WaveformTrait>>>,
    callback: Mutex<Option<PyObject>>,
}
```

**Changes**:
- Replace 5 fields (`hierarchy`, `wave_source`, `time_table`, `body_continuation`, `header_loaded`, `body_loaded`) with single `backend` field
- Backend owns all state (accessed via trait methods)
- Simplified structure works for all backends
- No backend-specific fields

**Migration Notes**:
- All places that access `shared_state.hierarchy.lock()` → `shared_state.backend.lock().unwrap().as_ref().unwrap().hierarchy()`
- All places that access `shared_state.time_table.lock()` → `shared_state.backend.lock().unwrap().as_ref().unwrap().time_table()`
- All places that access `shared_state.wave_source.lock()` → `shared_state.backend.lock().unwrap().as_mut().unwrap().wave_source()`
- `header_loaded` / `body_loaded` checks → `backend.header_loaded()` / `backend.body_loaded()`

### 3.7 Async Worker Refactoring

#### File: `pyrox/src/lib.rs` (MODIFY)

**LoadHeader Handler** (BEFORE - lib.rs:577-603):

```rust
AsyncRequest::LoadHeader(opts) => {
    emit_event(&shared_state, AsyncEvent::HeaderStartLoad);

    let path = shared_state.file_path.clone();

    match viewers::read_header_from_file(&path, &opts) {  // ← Wellen-specific
        Ok(header_result) => {
            let hier_trait = Arc::new(WellenHierarchy::new(Arc::new(header_result.hierarchy)));
            *shared_state.hierarchy.lock().unwrap() = Some(hier_trait);
            *shared_state.body_continuation.lock().unwrap() = Some(Box::new(header_result.body));
            shared_state.header_loaded.store(true, Ordering::Relaxed);
            emit_event(&shared_state, AsyncEvent::HeaderLoaded);
        }
        Err(e) => emit_event(&shared_state, AsyncEvent::Error(e.to_string())),
    }
}
```

**LoadHeader Handler** (AFTER):

```rust
AsyncRequest::LoadHeader(opts) => {
    emit_event(&shared_state, AsyncEvent::HeaderStartLoad);

    // Get or create backend
    let mut backend_guard = shared_state.backend.lock().unwrap();
    let backend = backend_guard.as_mut()
        .ok_or_else(|| "Backend not initialized".to_string());

    match backend.and_then(|b| b.load_header()) {
        Ok(()) => {
            emit_event(&shared_state, AsyncEvent::HeaderLoaded);
        }
        Err(e) => {
            emit_event(&shared_state, AsyncEvent::Error(e));
        }
    }
}
```

**LoadBody Handler** (BEFORE - lib.rs:605-659):

```rust
AsyncRequest::LoadBody => {
    emit_event(&shared_state, AsyncEvent::BodyStartLoad);

    let body_cont = shared_state.body_continuation.lock().unwrap().take();
    if let Some(body_cont) = body_cont {
        let hierarchy = shared_state.hierarchy.lock().unwrap().clone();
        if let Some(hier_trait) = hierarchy {
            // Downcast to WellenHierarchy ← Backend-specific
            if let Some(wellen_hier) = hier_trait.as_any().downcast_ref::<WellenHierarchy>() {
                match viewers::read_body(*body_cont, wellen_hier.inner(), None) {
                    Ok(body) => {
                        // Store time_table and wave_source
                        emit_event(&shared_state, AsyncEvent::BodyLoaded);
                    }
                    Err(e) => emit_event(&shared_state, AsyncEvent::Error(e.to_string())),
                }
            }
        }
    }
}
```

**LoadBody Handler** (AFTER):

```rust
AsyncRequest::LoadBody => {
    emit_event(&shared_state, AsyncEvent::BodyStartLoad);

    let mut backend_guard = shared_state.backend.lock().unwrap();
    let backend = backend_guard.as_mut()
        .ok_or_else(|| "Backend not initialized".to_string());

    match backend.and_then(|b| b.load_body()) {
        Ok(()) => {
            emit_event(&shared_state, AsyncEvent::BodyLoaded);
        }
        Err(e) => {
            emit_event(&shared_state, AsyncEvent::Error(e));
        }
    }
}
```

**Key Changes**:
- No direct calls to Wellen API (`viewers::read_header_from_file`, `viewers::read_body`)
- No downcast required (all operations via trait)
- Identical logic for all backends
- Backend-agnostic error handling

### 3.8 Waveform::new() Refactoring

#### File: `pyrox/src/lib.rs` (MODIFY)

**BEFORE** (lib.rs:777-900):
- 124 lines of branching logic
- Separate code paths for JETS vs Wellen
- Conditional loading based on `load_header` and `load_body` flags
- Manual construction of SharedState with different fields populated

**AFTER**:

```rust
#[new]
#[pyo3(signature = (path, multi_threaded = true, remove_scopes_with_empty_name = false, load_header = true, load_body = true))]
fn new(
    path: String,
    multi_threaded: bool,
    remove_scopes_with_empty_name: bool,
    load_header: bool,
    load_body: bool,
) -> PyResult<Self> {
    let opts = LoadOptions {
        multi_thread: multi_threaded,
        remove_scopes_with_empty_name,
    };

    // Create backend using factory function
    let mut backend = create_waveform_backend(&path, opts)
        .map_err(|e| PyRuntimeError::new_err(e))?;

    // Optionally load header and/or body
    if load_header {
        backend.load_header()
            .map_err(|e| PyRuntimeError::new_err(e))?;

        if load_body {
            backend.load_body()
                .map_err(|e| PyRuntimeError::new_err(e))?;
        }
    }

    // Create shared state
    let shared_state = Arc::new(SharedState {
        file_path: path.clone(),
        backend: Mutex::new(Some(backend)),
        callback: Mutex::new(None),
    });

    // Create async worker
    let (sender, receiver) = unbounded();
    let shared_state_clone = shared_state.clone();
    let worker_handle = thread::spawn(move || {
        async_worker(receiver, shared_state_clone);
    });

    Ok(Self {
        shared_state,
        request_sender: Some(sender),
        _worker_handle: Some(worker_handle),
    })
}
```

**Key Changes**:
- 60+ lines shorter (50% reduction)
- No branching on file type (handled by factory)
- Unified loading logic for all backends
- Same SharedState structure for all backends
- Cleaner separation of concerns

### 3.9 Waveform Instance Methods Refactoring

#### File: `pyrox/src/lib.rs` (MODIFY)

**Methods to Update**:

1. **`hierarchy()` getter** (lib.rs:946-950):
   - Before: `self.shared_state.hierarchy.lock().unwrap().as_ref().map(...)`
   - After: `self.shared_state.backend.lock().unwrap().as_ref().and_then(|b| b.hierarchy()).map(...)`

2. **`time_table()` getter** (lib.rs:1035-1039):
   - Before: `self.shared_state.time_table.lock().unwrap().as_ref().map(...)`
   - After: `self.shared_state.backend.lock().unwrap().as_ref().and_then(|b| b.time_table()).map(...)`

3. **`header_loaded()` getter** (lib.rs:952-955):
   - Before: `self.shared_state.header_loaded.load(Ordering::Relaxed)`
   - After: `self.shared_state.backend.lock().unwrap().as_ref().map_or(false, |b| b.header_loaded())`

4. **`body_loaded()` getter** (lib.rs:957-960):
   - Before: `self.shared_state.body_loaded.load(Ordering::Relaxed)`
   - After: `self.shared_state.backend.lock().unwrap().as_ref().map_or(false, |b| b.body_loaded())`

5. **`load_signals()` method** (lib.rs:1080-1172):
   - Replace `shared_state.hierarchy.lock()` with `backend.hierarchy()`
   - Replace `shared_state.wave_source.lock().unwrap().as_mut()` with `backend.wave_source()`
   - Remove downcast to `JetsHierarchy` (handled internally by backend)

6. **`get_signal_by_handle()` method** (lib.rs:1177-1223):
   - Replace `shared_state.hierarchy.lock()` with `backend.hierarchy()`
   - Remove downcast to `JetsHierarchy` (use `wave_source()` trait method)

7. **`load_header()` / `load_body()` sync methods** (lib.rs:919-945):
   - Replace direct calls to Wellen API with `backend.load_header()` / `backend.load_body()`

**Pattern for All Methods**:
```rust
// Access backend through SharedState
let backend_guard = self.shared_state.backend.lock().unwrap();
let backend = backend_guard.as_ref()
    .ok_or_else(|| PyRuntimeError::new_err("Backend not initialized"))?;

// Use trait methods
let hier = backend.hierarchy()
    .ok_or_else(|| PyRuntimeError::new_err("Hierarchy not loaded"))?;
```

### 3.10 File-by-File Implementation Summary

**Files to Create**:
1. None (all traits added to existing files)

**Files to Modify**:

1. **`pyrox/src/traits.rs`**:
   - Add `WaveformTrait` definition after `WaveSourceTrait` (line 282+)
   - ~50 lines of trait definition + documentation

2. **`pyrox/src/wellen_backend.rs`**:
   - Add `WellenWaveform` struct and `impl WaveformTrait`
   - Move `ReadBodyContinuation` usage here (remove from lib.rs)
   - ~120 lines of implementation

3. **`pyrox/src/jets_backend.rs`**:
   - Add `JetsWaveform` struct and `impl WaveformTrait`
   - ~80 lines of implementation

4. **`pyrox/src/lib.rs`**:
   - Add `create_waveform_backend()` factory function (~20 lines)
   - Modify `SharedState` structure (simplify to 3 fields)
   - Refactor `async_worker()` function (simplify handlers)
   - Refactor `Waveform::new()` (reduce from 124 to ~60 lines)
   - Update `Waveform` instance methods (7 methods)
   - Remove Wellen-specific imports (keep only `LoadOptions`)
   - ~200 lines modified, ~100 lines removed (net: -100 lines)

**Files to Delete**: None

**Total Changes**:
- Lines added: ~270
- Lines removed: ~100
- Net change: +170 lines
- Complexity reduction: Significant (eliminates branching, downcasts, backend-specific logic)

---

## 4. Performance Considerations

### 4.1 No Performance Regressions Expected

**Loading Performance**:
- Same underlying I/O operations (Wellen API unchanged)
- Same multi-threading strategy (inside Wellen backend)
- Additional trait method call is negligible (~1-3 CPU cycles)
- Backend state owned by trait object (no extra allocations)

**Memory Overhead**:
- `Box<dyn WaveformTrait>` = 16 bytes (pointer + vtable)
- Previous SharedState fields = ~120 bytes total
- **Net change**: Reduction of ~100 bytes per Waveform instance
- Backend structs slightly larger (store all state), but only one backend per waveform

**Runtime Overhead**:
- Trait method dispatch: 1-3 CPU cycles (vtable lookup)
- Occurs only during loading (not during rendering)
- Loading is I/O bound, CPU overhead is negligible

### 4.2 Mutex Contention

**Before**:
- 5 separate Mutex locks (`hierarchy`, `wave_source`, `time_table`, `body_continuation`, `callback`)
- Potential for fine-grained locking

**After**:
- 2 Mutex locks (`backend`, `callback`)
- Coarser locking, but:
  - Loading operations are rare (startup + user-initiated)
  - Async worker is the only writer to `backend`
  - Rendering uses `hierarchy()` / `time_table()` which return Arc (cheap clones)

**Mitigation**: Loading operations release lock after cloning Arc objects, so rendering is not blocked.

### 4.3 Backend State Cloning

**Trait Methods Return Arc**:
- `hierarchy()` → `Option<Arc<dyn HierarchyTrait>>`
- `time_table()` → `Option<Arc<dyn TimeTableTrait>>`

**Cloning Strategy**:
- Python methods clone Arc when accessing backend state
- Arc clone = atomic ref count increment (~5 CPU cycles)
- No deep copying of hierarchy or time table data

**Example**:
```rust
// In Waveform::hierarchy() getter
let backend_guard = self.shared_state.backend.lock().unwrap();
let hier = backend_guard.as_ref()
    .and_then(|b| b.hierarchy()) // Returns Arc (cheap clone)
    .map(|h| Hierarchy(h));      // Wrap in PyO3 class
// Lock released here, hierarchy remains accessible
```

---

## 5. Testing Strategy

### 5.1 Existing Test Coverage (Must Pass)

**All existing tests must pass without modification**:

1. **`tests/test_read_jets.py`**: JETS file loading and hierarchy
   - 23 tests covering JETS backend
   - Tests hierarchy, signals, time tables, records

2. **`tests/test_fst_loading.py`**: FST/VCD file loading
   - Tests Wellen backend (FST format)
   - Signal loading, hierarchy traversal

3. **`tests/test_async_loading.py`**: Async signal loading
   - Tests async worker with header/body loading
   - Event callbacks, multi-threaded loading

4. **`tests/test_persistence.py`**: Session save/load
   - Tests WaveformDB integration
   - Includes JETS and Wellen waveforms

5. **`tests/test_waveformdb_protocol.py`**: WaveformDB interface
   - Tests protocol compliance
   - Signal loading, hierarchy access

**Test Execution**:
```bash
QT_QPA_PLATFORM=offscreen poetry run pytest tests/ -v
```

### 5.2 Incremental Testing During Implementation

**Phase 1**: After `WaveformTrait` definition and Wellen backend
- Create unit test for `WellenWaveform` in Rust
- Test header loading, body loading, idempotency
- Run: `cargo test -p pyrox --lib`

**Phase 2**: After JETS backend implementation
- Create unit test for `JetsWaveform` in Rust
- Test atomic loading, idempotency
- Run: `cargo test -p pyrox --lib`

**Phase 3**: After factory function
- Test file extension detection
- Test unsupported format error handling
- Run: `cargo test -p pyrox --lib`

**Phase 4**: After `lib.rs` refactoring
- Run full Python test suite
- Verify no regressions in async loading
- Check event emission correctness

### 5.3 Test Scenarios to Verify

**Wellen Backend**:
1. Load header only → verify hierarchy available, time table None
2. Load header + body → verify both available
3. Load body before header → verify error
4. Call `load_header()` twice → verify idempotent
5. Call `load_body()` twice → verify idempotent

**JETS Backend**:
1. Load header → verify hierarchy, time table, and wave source all available
2. Call `load_body()` after header → verify no-op (no error)
3. Call `load_header()` twice → verify idempotent

**Factory Function**:
1. Test `.jets` file → returns JetsWaveform
2. Test `.vcd` file → returns WellenWaveform
3. Test `.fst` file → returns WellenWaveform
4. Test `.ghw` file → returns WellenWaveform
5. Test `.unknown` file → returns error

**Async Worker**:
1. Send LoadHeader request → verify HeaderLoaded event
2. Send LoadBody request → verify BodyLoaded event
3. Send LoadSignals request → verify SignalLoaded event
4. Verify events fired in correct order
5. Verify backend-agnostic (same events for JETS and Wellen)

---

## 6. Implementation Checklist

### Phase 1: Trait Definition
- [ ] Add `WaveformTrait` to `pyrox/src/traits.rs` (after line 281)
- [ ] Write documentation for each trait method
- [ ] Ensure trait is `Send + Sync` for multi-threading

### Phase 2: Wellen Backend
- [ ] Create `WellenWaveform` struct in `wellen_backend.rs`
- [ ] Implement `new()` constructor - **MUST NOT perform file I/O** (non-blocking requirement)
- [ ] Implement `load_header()` (calls `viewers::read_header_from_file`)
- [ ] Implement `load_body()` (calls `viewers::read_body`)
- [ ] Implement getters (`hierarchy()`, `time_table()`, `wave_source()`)
- [ ] Implement status methods (`header_loaded()`, `body_loaded()`)
- [ ] Test idempotency of loading methods
- [ ] **Verify constructor is non-blocking** (no I/O)
- [ ] Add unit tests in `wellen_backend.rs`

### Phase 3: JETS Backend
- [ ] Create `JetsWaveform` struct in `jets_backend.rs`
- [ ] Implement `new()` constructor - **MUST NOT call rjets::parse_trace()** (non-blocking requirement)
- [ ] Implement `load_header()` - calls `rjets::parse_trace()`, loads entire file
- [ ] Implement `load_body()` (no-op, returns Ok immediately)
- [ ] Implement getters (return cloned Arc objects)
- [ ] Implement status methods (both return same `loaded` flag)
- [ ] Test atomic loading behavior
- [ ] **Verify constructor is non-blocking** (no I/O)
- [ ] Add unit tests in `jets_backend.rs`

### Phase 4: Factory Function
- [ ] Add `create_waveform_backend()` to `lib.rs` (before `async_worker`)
- [ ] Implement file extension detection
- [ ] Map extensions to backend constructors
- [ ] Return error for unsupported formats
- [ ] Add unit test for factory function

### Phase 5: SharedState Refactoring
- [ ] Replace 5 fields with `backend: Mutex<Option<Box<dyn WaveformTrait>>>`
- [ ] Remove `body_continuation`, `header_loaded`, `body_loaded` fields
- [ ] Update struct definition in `lib.rs` (line 52-61)

### Phase 6: Async Worker Refactoring
- [ ] Refactor `LoadHeader` handler (line 577-603)
  - [ ] Remove `viewers::read_header_from_file` call
  - [ ] Call `backend.load_header()` via trait
  - [ ] Remove `body_continuation` storage
  - [ ] Remove direct hierarchy storage
- [ ] Refactor `LoadBody` handler (line 605-659)
  - [ ] Remove `body_continuation` retrieval
  - [ ] Remove downcast to `WellenHierarchy`
  - [ ] Call `backend.load_body()` via trait
  - [ ] Remove direct wave_source/time_table storage
- [ ] Verify `LoadSignals` handler still works (no changes needed)
- [ ] Test async worker with both backends

### Phase 7: Waveform::new() Refactoring
- [ ] Remove JETS-specific branching (line 786-827) - **removes blocking rjets::parse_trace() call**
- [ ] Remove Wellen-specific branching (line 829-900)
- [ ] Call `create_waveform_backend()` factory - **returns immediately (non-blocking)**
- [ ] Conditionally call `backend.load_header()` if `load_header == true`
- [ ] Conditionally call `backend.load_body()` if `load_body == true`
- [ ] Create simplified SharedState with backend field
- [ ] **Test non-blocking constructor** with `load_header=False, load_body=False`
- [ ] Test with JETS files
- [ ] Test with Wellen files (VCD, FST, GHW)

### Phase 8: Waveform Instance Methods
- [ ] Update `hierarchy()` getter (use `backend.hierarchy()`)
- [ ] Update `time_table()` getter (use `backend.time_table()`)
- [ ] Update `header_loaded()` getter (use `backend.header_loaded()`)
- [ ] Update `body_loaded()` getter (use `backend.body_loaded()`)
- [ ] Update `load_header()` sync method (call `backend.load_header()`)
- [ ] Update `load_body()` sync method (call `backend.load_body()`)
- [ ] Update `load_signals()` (replace `wave_source.lock()` with `backend.wave_source()`)
- [ ] Update `get_signal_by_handle()` (remove JETS downcast)
- [ ] Test all methods with both backends

### Phase 9: Import Cleanup
- [ ] Remove `use wellen::viewers::{self, ReadBodyContinuation}` from lib.rs
- [ ] Keep `use wellen::LoadOptions` (used by factory)
- [ ] Verify no other Wellen imports in lib.rs
- [ ] Add `use traits::WaveformTrait` if needed

### Phase 10: Testing and Validation
- [ ] Run full Python test suite: `QT_QPA_PLATFORM=offscreen poetry run pytest tests/ -v`
- [ ] Verify all 23 tests in `test_read_jets.py` pass
- [ ] Verify async loading tests pass
- [ ] Verify persistence tests pass
- [ ] Run manual smoke tests with VCD, FST, JETS files
- [ ] Check for memory leaks or performance regressions

### Phase 11: Documentation
- [ ] Add Rust doc comments to `WaveformTrait`
- [ ] Add doc comments to `WellenWaveform` and `JetsWaveform`
- [ ] Update CLAUDE.md if needed (architecture changes)
- [ ] No changes to Python API docs (public API unchanged)

---

## 7. Success Criteria

**Must Have**:
- ✅ `WaveformTrait` defined in `traits.rs` with all required methods
- ✅ `WellenWaveform` implements `WaveformTrait` (two-phase loading)
- ✅ `JetsWaveform` implements `WaveformTrait` (atomic loading)
- ✅ **Backend constructors perform NO I/O** (non-blocking requirement)
- ✅ **Waveform constructor is non-blocking** when `load_header=False, load_body=False`
- ✅ `create_waveform_backend()` factory function works for all extensions
- ✅ `SharedState` simplified to 3 fields (remove 5 backend-specific fields)
- ✅ `async_worker()` is backend-agnostic (no Wellen-specific calls)
- ✅ `Waveform::new()` simplified and unified (no branching on backend type)
- ✅ All 23 tests in `test_read_jets.py` pass
- ✅ All tests in `test_async_loading.py` pass
- ✅ All other existing tests pass without modification
- ✅ No performance regressions (loading time within 5% of baseline)
- ✅ Zero breaking changes to Python API

**Nice to Have**:
- Code size reduction in `lib.rs` (target: -100 lines)
- Easier to add new backends (no changes to `lib.rs` required)
- Better error messages from backend trait methods
- Unit tests for backend implementations in Rust

---

## 8. Risks and Mitigations

### 8.1 Trait Method Lifetimes

**Risk**: Returning references from trait objects can cause lifetime issues

**Mitigation**:
- Return `Option<Arc<dyn Trait>>` instead of references
- Arc cloning is cheap (atomic ref count increment)
- No borrow checker issues with Arc-wrapped trait objects

### 8.2 Mutable Access to WaveSourceTrait

**Risk**: `wave_source(&mut self)` requires mutable borrow of entire backend

**Issue**: Cannot call multiple trait methods simultaneously (borrow checker)

**Mitigation**:
- Design ensures sequential access (load hierarchy → load body → load signals)
- Mutex in SharedState already prevents concurrent access
- Interior mutability not needed (operations are sequential by design)

### 8.3 Backend State Ownership

**Risk**: Who owns hierarchy, time table, signal source?

**Decision**: Backend owns all state
- Trait methods return cloned Arc objects (cheap)
- Backend stores internal state in fields
- No shared ownership issues

**Alternative Considered**: SharedState owns everything, backend just provides loading logic
- **Rejected**: Would require moving state out of backend after loading (complex)
- Current design is cleaner: backend encapsulates everything

### 8.4 Error Handling

**Risk**: Trait methods return `Result<(), String>` (loses error type information)

**Mitigation**:
- String errors are sufficient for user display
- Backend-specific errors converted to strings via `.to_string()`
- Python layer converts to `PyRuntimeError` (no loss of information)
- Alternative (thiserror Error trait) considered but rejected as overkill

### 8.5 Idempotency Testing

**Risk**: Loading methods must be idempotent (safe to call multiple times)

**Mitigation**:
- Methods check internal flags before loading
- Early return if already loaded
- Rust unit tests verify idempotency
- Python tests also verify (may call load_header twice)

---

## 9. Future Extensibility

### 9.1 Adding New Backends

**Process** (unchanged from 0055 plan):

1. Implement `WaveformTrait` in new module (e.g., `vpd_backend.rs`)
2. Add file extension to `create_waveform_backend()` factory
3. **No changes needed** to `lib.rs`, `async_worker()`, or `Waveform` class

**Example** (VPD backend):

```rust
// src/vpd_backend.rs
pub struct VpdWaveform { /* ... */ }

impl traits::WaveformTrait for VpdWaveform {
    fn load_header(&mut self) -> Result<(), String> {
        // VPD-specific loading
    }
    // ... other methods
}

// In lib.rs, update factory:
fn create_waveform_backend(path: &str, opts: LoadOptions) -> Result<Box<dyn WaveformTrait>, String> {
    if path.ends_with(".vpd") {
        Ok(Box::new(vpd_backend::VpdWaveform::new(path.to_string(), opts)))
    } else if /* ... */ {
        // ... existing backends
    }
}
```

### 9.2 Async Loading Variants

**Potential Future Enhancement**: Backend-specific async loading strategies

**Current Design**: Async orchestration in `lib.rs`, synchronous trait methods
- Works well for Wellen (I/O bound, benefits from thread pool)
- Works well for JETS (fast parsing, thread overhead acceptable)

**Future Alternative**: Trait methods return `Future` (async methods)
- Would require `async-trait` crate
- Would allow backend-specific async strategies (e.g., streaming, pipelining)
- **Not needed now**: Current design is sufficient for all existing backends

### 9.3 Lazy Loading / Streaming

**Potential Enhancement**: Load hierarchy incrementally (stream from file)

**Current Design**: Header loaded fully, then body loaded fully
- Simple, predictable
- Works well for typical file sizes (<1GB)

**Future Design**: Add `load_scope_lazy()` method to trait
- Load individual scopes on demand
- Useful for very large hierarchies (>100k signals)
- Would require backend support (not all formats support partial loading)

---

## 10. Open Questions

### Q1: Should factory function be public or private?

**Option A**: Public function in `traits.rs`
```rust
pub fn create_waveform(path: &str, opts: LoadOptions) -> Result<Box<dyn WaveformTrait>, String>
```
- Pro: Can be used by other Rust code
- Con: Exposes implementation detail

**Option B**: Private function in `lib.rs`
```rust
fn create_waveform_backend(path: &str, opts: LoadOptions) -> Result<Box<dyn WaveformTrait>, String>
```
- Pro: Encapsulation (internal implementation detail)
- Con: Not reusable by other crates

**Recommendation**: Option B (private) - only used by `Waveform::new()`, no need for public API

### Q2: Should WaveformTrait provide a default implementation for load_body()?

**Option A**: No default implementation (current plan)
- Backends must implement (explicit)

**Option B**: Default implementation returns `Err("Not supported")`
```rust
fn load_body(&mut self) -> Result<(), String> {
    Err("This backend does not support separate body loading".to_string())
}
```
- Pro: Backends can skip implementation if not supported
- Con: Error at runtime instead of compile time

**Recommendation**: Option A (no default) - forces backends to be explicit about behavior

### Q3: Should backends implement Clone?

**Current Design**: Backends stored as `Box<dyn WaveformTrait>` (not cloneable)

**Alternative**: Require `Clone` bound on trait
```rust
pub trait WaveformTrait: Send + Sync + Clone { /* ... */ }
```
- Pro: Can clone waveform backends (e.g., for forking async workers)
- Con: Not needed by current design (SharedState is Arc, not cloned)

**Recommendation**: No `Clone` bound (YAGNI - not needed now, can add later if needed)

---

## 11. Appendix: Code Deletion Summary

**Lines to Delete from lib.rs**:

1. **Import cleanup**:
   - `use wellen::viewers::{self, ReadBodyContinuation}` → Remove `viewers`, `ReadBodyContinuation`

2. **SharedState fields** (line 56-61):
   - `hierarchy: Mutex<...>` → Delete
   - `wave_source: Mutex<...>` → Delete
   - `time_table: Mutex<...>` → Delete
   - `body_continuation: Mutex<...>` → Delete
   - `header_loaded: AtomicBool` → Delete
   - `body_loaded: AtomicBool` → Delete

3. **async_worker LoadHeader handler** (line 577-603):
   - Direct `viewers::read_header_from_file` call → Delete
   - Manual hierarchy trait object creation → Delete
   - Body continuation storage → Delete
   - Header flag update → Delete

4. **async_worker LoadBody handler** (line 605-659):
   - Body continuation retrieval → Delete
   - Downcast to `WellenHierarchy` → Delete
   - Direct `viewers::read_body` call → Delete
   - Manual time table trait object creation → Delete
   - Manual wave source trait object creation → Delete
   - Body flag update → Delete

5. **Waveform::new JETS branch** (line 786-827):
   - Entire JETS-specific loading block → Delete (~40 lines)

6. **Waveform::new Wellen branch** (line 829-900):
   - Entire Wellen-specific loading block → Delete (~70 lines)

**Total Lines Deleted**: ~200 lines

**Total Lines Added**: ~270 lines (trait + backends + factory + refactored code)

**Net Change**: +70 lines (but significantly simpler and more maintainable)

---

**Document Version**: 1.0
**Author**: Claude (AI Coding Agent)
**Date**: 2025-10-08
**Status**: Planning Complete - Ready for Implementation
**Builds On**: 0055_pyrox_trait_dispatch_plan.md
