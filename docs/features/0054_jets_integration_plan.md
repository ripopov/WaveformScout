# JETS Trace Format Integration into Pyrox

## 1. Use Cases and Requirements Analysis

### Core Functionality
Integrate JETS (JSON Event Trace Streaming) format support into the Pyrox waveform library, enabling WaveScout to visualize hardware execution traces as waveform signals. JETS traces represent hierarchical execution pipelines (from host dispatch through hardware operations) with precise clock timestamps.

### Key Requirements

#### 1.1 JETS Format Support
- **Read JETS files** (`.jets` or `.jsonl` extension) using the existing `jets/rjets` Rust parser
- **Parse hierarchical structure**: Records form tree (parent-child relationships via `parent_id`)
- **Handle all line types**: `header`, `record`, `record_end`, `annotation`, `event`, `footer`
- **Support streaming format**: JSON Lines (one object per line)
- **Clock timestamp conversion**: Convert hardware clock cycles to microseconds using metadata clock frequency

#### 1.2 Pyrox API Extensions
- **Extend Hierarchy API**:
  - `file_format()` → return `"JETS"`
  - `timescale()` → return microseconds (converted from clock cycles)
  - `top_scopes()` → return top-level Records as Scopes
  - `all_vars()` → return all Records wrapped as Vars

- **Extend Scope API**:
  - `scope_type()` → add `"record"` type
  - `name()` / `full_name()` → support Record names
  - `is_record()` → new method to identify Record scopes
  - `vars()` → return single Var representing the Record
  - `scopes()` → iterate child Records
  - `record()` → new method returning Record object

- **New Record Class**:
  - Expose all `TraceRecord` fields from JETS parser
  - Fields: `id`, `parent_id`, `record_type`, `clk`, `name`, `data`, `end_clk`, `duration`, `children`, `annotations`, `events`

- **Record-as-Signal Mapping**:
  - Records wrapped as `Var` objects with:
    - `var_type()` → `"string"`
    - `signal_handle()` → maps to record ID (integer)
  - Loadable as string signals via existing Pyrox signal loading API
  - Signal value representation:
    - **Outside record time range**: `"Z"` (High Impedance)
    - **Inside record time range**: Pretty-printed JSON of record + events
    - **Initial value**: Record JSON representation
    - **Updates**: Event JSON representations at event timestamps
    - **Timestamp conversion**: Clock ticks → microseconds using `clock_frequency_mhz` from header metadata

#### 1.3 Backward Compatibility
- **All existing Pyrox API must remain functional** for VCD/FST/GHW files
- **No breaking changes** to Waveform, Hierarchy, Scope, Var, Signal classes
- **Existing tests must pass** without modification

#### 1.4 Testing Requirements
- **New test**: `tests/test_read_jets.py`
  - Read `jets/gpu_sim.jets` file
  - Verify hierarchy parsing (Records as Scopes)
  - Verify annotations and events parsing
  - Load Record as Signal via `get_signal_by_handle()`
  - Iterate `all_changes()` and verify:
    - Timestamps match (start, end, events) in microseconds
    - Values are pretty-printed JSON strings
    - Outside record range: value is `"Z"`
- **Run all existing tests** to verify backward compatibility

---

## 2. Codebase Research

### 2.1 JETS Parser (jets/rjets/src/parser.rs)

**Key Data Structures**:
```rust
pub struct TraceHeader {
    pub version: String,
    pub metadata: serde_json::Value,  // Contains clock_frequency_mhz
}

pub struct TraceRecord {
    pub id: String,
    pub parent_id: Option<String>,
    pub record_type: String,
    pub clk: i64,                     // Start clock cycle
    pub name: String,
    pub data: Option<serde_json::Value>,
    pub end_clk: Option<i64>,         // From record_end line
    pub duration: Option<i64>,
    pub children: Vec<TraceRecord>,
    pub annotations: Vec<TraceAnnotation>,
    pub events: Vec<TraceEvent>,
}

pub struct TraceEvent {
    pub record_id: String,
    pub name: String,
    pub clk: i64,                     // Event timestamp
    pub data: Option<serde_json::Value>,
}

pub struct TraceAnnotation {
    pub record_id: String,
    pub name: String,
    pub data: serde_json::Value,
}

pub struct TraceData {
    pub header: TraceHeader,
    pub roots: Vec<TraceRecord>,      // Top-level records
    pub footer: Option<TraceFooter>,
}

pub fn parse_trace(file_path: &str) -> Result<TraceData>;
```

**Parser Behavior**:
- Reads JSON Lines format (one JSON object per line)
- Builds hierarchical tree by linking `parent_id` references
- Computes `end_clk` and `duration` from `record_end` lines
- Attaches annotations and events to records by `record_id`
- Returns tree structure with roots at top level

### 2.2 Pyrox API Structure (pyrox/src/lib.rs, pyrox/pyrox.pyi)

**Current Architecture**:
- **Waveform class**: Main entry point, handles file loading
  - `__init__(path, multi_threaded, ...)` - creates from file
  - `hierarchy` property - returns Hierarchy
  - `time_table` property - returns TimeTable
  - Signal loading methods: `get_signal_by_handle()`, `load_signals()`, etc.

- **Hierarchy class**: Design hierarchy wrapper
  - `all_vars()` → VarIter - all variables
  - `top_scopes()` → ScopeIter - root scopes
  - `timescale()` → Timescale - time unit
  - `file_format()` → `"VCD"|"FST"|"GHW"|"Unknown"`

- **Scope class**: Represents modules/tasks/etc.
  - `name(hier)`, `full_name(hier)` - scope names
  - `scope_type()` → `"module"|"task"|...` (see lib.rs:212-241)
  - `vars(hier)` → VarIter - variables in scope
  - `scopes(hier)` → ScopeIter - child scopes

- **Var class**: Variable/signal reference
  - `name(hier)`, `full_name(hier)` - variable names
  - `var_type()` → `"Wire"|"Reg"|"Real"|...`
  - `signal_handle()` → SignalHandle (usize/int)
  - Type queries: `is_real()`, `is_string()`, `is_bit_vector()`, etc.

- **Signal class**: Waveform data
  - `all_changes()` → SignalChangeIter - (time, value) pairs
  - `value_at_time(time)` → value at specific time
  - `query_signal(time)` → QueryResult

**Wellen Backend Integration**:
- Pyrox wraps `wellen` library (Rust waveform parser)
- File format detection in `wellen::FileFormat` enum
- Hierarchy represented as `wellen::Hierarchy`
- Scopes/Vars are `wellen::Scope` and `wellen::Var`
- Signals loaded from `wellen::SignalSource` via `SignalRef`

### 2.3 Extension Points

**Where to Add JETS Support**:

1. **File Format Detection** (lib.rs:190-197)
   - Add `wellen::FileFormat::Jets` case (requires Wellen modification OR)
   - Add JETS-specific loading path that bypasses Wellen

2. **Hierarchy Construction**
   - Map JETS `TraceData` to Pyrox `Hierarchy` structure
   - Records → Scopes (with `scope_type = "record"`)
   - Records → Vars (synthetic variables representing records)

3. **Signal Generation**
   - Record ID → SignalHandle mapping (integer conversion)
   - Dynamic signal generation from Record + Events
   - JSON serialization of record/event data
   - Clock cycle → microsecond timestamp conversion

4. **Scope/Var Extensions**
   - Add `is_record()` method to Scope
   - Add `record()` method to Scope (returns Record)
   - Ensure Var from Record has `var_type() = "string"`

---

## 3. Implementation Planning

### 3.1 Architecture Design

**Two-Tier Integration Approach**:

Given that JETS is fundamentally different from VCD/FST/GHW (it's a trace format, not a waveform format), we'll use a parallel loading path:

1. **JETS-Specific Loader** (new module: `pyrox/src/jets_loader.rs`)
   - Uses `rjets` parser to read JETS files
   - Builds Pyrox-compatible data structures
   - Does NOT go through Wellen (JETS is not a waveform format)

2. **Unified Pyrox Interface**
   - Existing API remains unchanged
   - JETS data exposed via same Hierarchy/Scope/Var/Signal abstractions
   - File format detection routes to appropriate loader

**Data Mapping Strategy**:

```
JETS TraceRecord → Pyrox Scope (with scope_type="record")
                 → Pyrox Var (synthetic, represents record as signal)
                 → Pyrox Signal (string type, JSON values)

JETS Hierarchy:
  TraceData.roots → Hierarchy.top_scopes()
  TraceRecord.children → Scope.scopes()
  TraceRecord itself → Scope.vars() [single Var]
```

### 3.2 File-by-File Implementation Plan

#### File: `pyrox/src/jets_loader.rs` (NEW)

**Purpose**: JETS-specific loading and data structure conversion

**Key Components**:

1. **`JetsHierarchy` struct**
   - Wraps `TraceData` from rjets parser
   - Stores clock frequency for timestamp conversion
   - Maintains Record ID → index mapping for signal handles

2. **`load_jets_file(path: &str) -> Result<JetsHierarchy>`**
   - Calls `rjets::parse_trace(path)`
   - Extracts `clock_frequency_mhz` from header metadata
   - Builds Record ID → SignalHandle mapping
   - Returns wrapped hierarchy

3. **`JetsScope` struct**
   - Wraps `TraceRecord`
   - Implements scope-like interface (name, type, children)
   - Provides `record()` accessor

4. **`JetsVar` struct**
   - Synthetic variable representing a Record
   - Always `var_type = "string"`
   - `signal_handle` maps to Record ID index

5. **`JetsSignal` struct**
   - Generates string signal from Record + Events
   - Implements lazy evaluation (compute on demand)
   - Timestamp conversion: `clk * 1_000_000 / clock_freq_mhz` → microseconds
   - Value generation:
     - Before `record.clk`: `"Z"`
     - At `record.clk`: JSON of record (pretty-printed)
     - At each `event.clk`: JSON of event (pretty-printed)
     - After `record.end_clk`: `"Z"` (or extend if no end)

**Helper Functions**:
- `clock_to_microseconds(clk: i64, freq_mhz: f64) -> i64`
- `record_to_json(record: &TraceRecord) -> String`
- `event_to_json(event: &TraceEvent) -> String`

#### File: `pyrox/src/lib.rs` (MODIFICATIONS)

**Changes Required**:

1. **Module Import** (line ~2):
   ```rust
   mod jets_loader;
   ```

2. **Waveform::__init__** (around line 800):
   - Add file extension check: if `.jets` or `.jsonl`, use JETS loader
   - Store loader type in Waveform struct (enum: `Wellen` | `Jets`)
   - Initialize JETS-specific state (JetsHierarchy)

3. **Waveform::hierarchy** (line 915-923):
   - Check loader type
   - If JETS: return Hierarchy backed by JetsHierarchy
   - If Wellen: return existing implementation

4. **Waveform::get_signal_by_handle** (around line 1070):
   - Check loader type
   - If JETS: generate JetsSignal from record_id
   - If Wellen: existing implementation

5. **Hierarchy::file_format** (line 190-197):
   - Add JETS case: `"JETS".to_string()`

6. **Hierarchy::timescale** (line 185-187):
   - For JETS: return fixed microsecond timescale
   - For Wellen: existing implementation

7. **Scope::scope_type** (line 212-242):
   - Add case for Record: `"record".to_string()`

8. **Add Scope::is_record** (new method):
   ```rust
   pub fn is_record(&self) -> bool {
       self.scope_type() == "record"
   }
   ```

9. **Add Scope::record** (new method):
   ```rust
   pub fn record(&self) -> Option<Record> {
       // Return Record object if scope is JETS record
   }
   ```

10. **Export Record class** (in pymodule, line 69-86):
    ```rust
    m.add_class::<Record>()?;
    ```

#### File: `pyrox/src/jets_loader.rs` → `Record` class (NEW)

**Purpose**: Python-exposed Record class

**PyClass Definition**:
```rust
#[pyclass]
pub struct Record {
    inner: Arc<TraceRecord>,
    clock_freq_mhz: f64,
}

#[pymethods]
impl Record {
    #[getter]
    fn id(&self) -> String { ... }

    #[getter]
    fn parent_id(&self) -> Option<String> { ... }

    #[getter]
    fn record_type(&self) -> String { ... }

    #[getter]
    fn clk(&self) -> i64 { ... }

    #[getter]
    fn name(&self) -> String { ... }

    #[getter]
    fn data(&self, py: Python) -> PyObject { ... }  // JSON to Python dict

    #[getter]
    fn end_clk(&self) -> Option<i64> { ... }

    #[getter]
    fn duration(&self) -> Option<i64> { ... }

    fn annotations(&self, py: Python) -> PyObject { ... }  // List of dicts

    fn events(&self, py: Python) -> PyObject { ... }  // List of dicts

    fn children(&self) -> Vec<Record> { ... }

    // Timestamp conversions
    fn start_time_us(&self) -> i64 { ... }
    fn end_time_us(&self) -> Option<i64> { ... }
}
```

#### File: `pyrox/pyrox.pyi` (TYPE STUBS UPDATE)

**Add to imports**:
```python
from typing import Literal
```

**Update file_format return type**:
```python
def file_format(self) -> Literal["VCD", "FST", "GHW", "JETS", "Unknown"]: ...
```

**Add to Scope class**:
```python
def is_record(self) -> bool: ...
def record(self) -> Optional[Record]: ...
```

**Update scope_type return**:
```python
def scope_type(self) -> str: ...  # Can include "record"
```

**Add Record class**:
```python
class Record:
    """JETS trace record."""
    @property
    def id(self) -> str: ...
    @property
    def parent_id(self) -> Optional[str]: ...
    @property
    def record_type(self) -> str: ...
    @property
    def clk(self) -> int: ...
    @property
    def name(self) -> str: ...
    @property
    def data(self) -> Dict[str, Any]: ...
    @property
    def end_clk(self) -> Optional[int]: ...
    @property
    def duration(self) -> Optional[int]: ...

    def annotations(self) -> List[Dict[str, Any]]: ...
    def events(self) -> List[Dict[str, Any]]: ...
    def children(self) -> List[Record]: ...
    def start_time_us(self) -> int: ...
    def end_time_us(self) -> Optional[int]: ...
```

#### File: `pyrox/Cargo.toml` (DEPENDENCY UPDATE)

**Add rjets dependency**:
```toml
[dependencies]
# ... existing dependencies ...
rjets = { path = "../jets/rjets" }
serde_json = "1.0"  # For JSON serialization
```

#### File: `tests/test_read_jets.py` (NEW)

**Purpose**: Integration test for JETS support

**Test Structure**:
```python
import pytest
from pathlib import Path
import pyrox

def test_jets_file_loading():
    """Test loading JETS file and basic hierarchy access."""
    jets_file = Path(__file__).parent.parent / "jets" / "gpu_sim.jets"
    wf = pyrox.Waveform(str(jets_file))

    # Verify file format
    assert wf.hierarchy.file_format() == "JETS"

    # Verify timescale is microseconds
    ts = wf.hierarchy.timescale()
    assert ts is not None
    assert ts.to_str() == "1us"  # or similar

def test_jets_hierarchy():
    """Test JETS hierarchy structure (Records as Scopes)."""
    jets_file = Path(__file__).parent.parent / "jets" / "gpu_sim.jets"
    wf = pyrox.Waveform(str(jets_file))
    hier = wf.hierarchy

    # Get top-level scopes (should be root records)
    top_scopes = list(hier.top_scopes())
    assert len(top_scopes) > 0

    # First scope should be a record
    first_scope = top_scopes[0]
    assert first_scope.is_record()

    # Check scope type
    assert first_scope.scope_type() == "record"

    # Get Record object
    record = first_scope.record()
    assert record is not None
    assert record.id == "host_prog"  # From gpu_sim.jets

def test_jets_annotations_and_events():
    """Test annotation and event parsing."""
    jets_file = Path(__file__).parent.parent / "jets" / "gpu_sim.jets"
    wf = pyrox.Waveform(str(jets_file))
    hier = wf.hierarchy

    # Navigate to a record with annotations (e.g., "gte")
    # This requires walking the tree - implementation detail

    # Find record by ID (helper needed)
    record = find_record_by_id(hier, "gte")
    assert record is not None

    # Check annotations
    annotations = record.annotations()
    assert len(annotations) >= 3  # gpu_sim.jets has 3 for "gte"
    assert any(a["name"] == "GridDimensions" for a in annotations)

def test_jets_record_as_signal():
    """Test loading Record as Signal."""
    jets_file = Path(__file__).parent.parent / "jets" / "gpu_sim.jets"
    wf = pyrox.Waveform(str(jets_file))
    hier = wf.hierarchy

    # Get a record as a Var
    top_scopes = list(hier.top_scopes())
    first_scope = top_scopes[0]
    vars_list = list(first_scope.vars(hier))

    assert len(vars_list) == 1  # One var per record
    var = vars_list[0]

    # Verify var type
    assert var.var_type() == "String"  # or "string"

    # Load signal
    signal_handle = var.signal_handle()
    signal = wf.get_signal_by_handle(signal_handle)

    # Verify signal has changes
    changes = list(signal.all_changes())
    assert len(changes) > 0

def test_jets_signal_values_and_timestamps():
    """Test Record signal values and timestamp conversion."""
    jets_file = Path(__file__).parent.parent / "jets" / "gpu_sim.jets"
    wf = pyrox.Waveform(str(jets_file))
    hier = wf.hierarchy

    # Get a specific record (e.g., inst_warp_tb_000_1_0x0000)
    record = find_record_by_id(hier, "inst_warp_tb_000_1_0x0000")
    assert record is not None

    # Expected: clk=2181, end_clk=2186, clock_freq=1830 MHz
    # start_time_us = 2181 * 1_000_000 / 1830_000_000 = 1.19... us

    # Load as signal
    vars_list = list(get_scope_for_record(hier, record).vars(hier))
    signal_handle = vars_list[0].signal_handle()
    signal = wf.get_signal_by_handle(signal_handle)

    changes = list(signal.all_changes())

    # First change should be at record start time
    first_time, first_value = changes[0]

    # Verify timestamp conversion (clk 2181 → ~1192 us with 1830 MHz)
    expected_us = int(2181 * 1_000_000 / 1830)
    assert abs(first_time - expected_us) < 2  # Allow 1us tolerance

    # Verify value is JSON
    import json
    value_obj = json.loads(first_value)
    assert "id" in value_obj
    assert value_obj["id"] == "inst_warp_tb_000_1_0x0000"

    # Verify events appear as signal changes
    # Record has 5 events at clk 2182, 2183, 2184, 2185, 2186
    # So signal should have 6 changes: initial + 5 events
    assert len(changes) >= 6

    # Check event values are JSON with event data
    event_change = changes[1]  # First event
    event_time, event_value = event_change
    event_obj = json.loads(event_value)
    assert "name" in event_obj
    assert event_obj["name"] == "DecodeStage"

def test_jets_high_impedance_outside_record():
    """Test that signal is 'Z' outside record time range."""
    jets_file = Path(__file__).parent.parent / "jets" / "gpu_sim.jets"
    wf = pyrox.Waveform(str(jets_file))

    # Get a record with known time range
    record = find_record_by_id(wf.hierarchy, "inst_warp_tb_000_1_0x0000")

    # Load signal
    vars_list = list(get_scope_for_record(wf.hierarchy, record).vars(wf.hierarchy))
    signal_handle = vars_list[0].signal_handle()
    signal = wf.get_signal_by_handle(signal_handle)

    # Query before record start
    start_us = record.start_time_us()
    before_value = signal.value_at_time(start_us - 100)

    assert before_value == "Z"

    # Query after record end (if has end_clk)
    if record.end_clk is not None:
        end_us = record.end_time_us()
        after_value = signal.value_at_time(end_us + 100)
        assert after_value == "Z"

# Helper functions
def find_record_by_id(hier, record_id: str):
    """Helper to find record by ID in hierarchy."""
    # Implementation: traverse all scopes, check record().id
    ...

def get_scope_for_record(hier, record):
    """Helper to get Scope wrapper for a Record."""
    # Implementation: find scope where scope.record().id == record.id
    ...
```

### 3.3 Algorithm Descriptions

#### Signal Generation from Record

**Input**: TraceRecord with events, clock_frequency_mhz

**Output**: List of (timestamp_us, value_string) pairs

**Algorithm**:
```
1. Calculate start_time_us = record.clk * 1_000_000 / clock_frequency_mhz
2. Create initial change at start_time_us:
   - value = pretty_print_json(record)  // Include id, name, record_type, data, etc.

3. For each event in record.events (sorted by clk):
   - event_time_us = event.clk * 1_000_000 / clock_frequency_mhz
   - value = pretty_print_json(event)  // Include name, clk, data
   - Add (event_time_us, value) to changes list

4. If record.end_clk exists:
   - end_time_us = record.end_clk * 1_000_000 / clock_frequency_mhz
   - Add (end_time_us + 1, "Z") to mark end

5. Return sorted changes list
```

**Query Behavior**:
- `value_at_time(t)`:
  - If t < start_time_us: return "Z"
  - If t > end_time_us: return "Z"
  - Else: find latest change <= t, return its value

#### Hierarchy Construction from JETS

**Input**: TraceData (roots, header)

**Output**: JetsHierarchy with Scope/Var structure

**Algorithm**:
```
1. Extract clock_frequency_mhz from header.metadata
2. Create record_id → index mapping for signal handles
3. Build JetsScope for each root record:
   - Wrap TraceRecord
   - Recursively wrap children as child scopes
   - Create synthetic Var for the record itself
4. Store in JetsHierarchy structure
```

### 3.4 Backward Compatibility Strategy

**Isolation of JETS Code**:
- All JETS-specific code in separate module (`jets_loader.rs`)
- Waveform struct uses enum to track loader type
- Conditional dispatch in public API methods based on loader type

**No Changes to Existing Behavior**:
- VCD/FST/GHW files use existing Wellen path (unchanged)
- Existing Scope/Var/Signal implementations untouched for Wellen
- New methods (`is_record()`, `record()`) return appropriate defaults for non-JETS

**Testing Strategy**:
1. Run full existing test suite (unchanged)
2. Add new JETS-specific tests
3. Verify no regressions in VCD/FST/GHW workflows

### 3.5 Type Safety and Rust Best Practices

**Strict Typing**:
- Use `Arc<TraceRecord>` for shared ownership
- Avoid `unwrap()` in public API, use `Result<T, PyErr>`
- Explicit error handling with descriptive messages

**Memory Safety**:
- Records stored in Arc for cheap cloning across Python boundary
- No raw pointers or unsafe code needed
- Leverage Rust's ownership system for lifecycle management

**Python Interop**:
- Use `PyO3` conversion traits for JSON → Python dict
- Implement `IntoPyObject` for custom types
- Use `Bound<'_, T>` for PyO3 0.23+ compatibility

---

## 4. Testing Strategy

### 4.1 Unit Tests (Rust)

**File**: `pyrox/src/jets_loader.rs` (embedded tests)

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_clock_conversion() {
        let us = clock_to_microseconds(1830, 1830.0);
        assert_eq!(us, 1);  // 1 clock = 1us at 1MHz = 1us at 1830MHz? Check math
    }

    #[test]
    fn test_record_to_json() {
        // Create mock TraceRecord, verify JSON output
    }
}
```

### 4.2 Integration Tests (Python)

**File**: `tests/test_read_jets.py` (detailed in 3.2)

**Coverage**:
- File loading and format detection
- Hierarchy traversal (Records as Scopes)
- Annotation/Event parsing
- Record-as-Signal loading
- Timestamp conversion accuracy
- JSON value generation
- High-impedance behavior outside record range

### 4.3 Backward Compatibility Tests

**Verification**:
```bash
# Run all existing tests
pytest tests/ -k "not jets"

# Should all pass without modification
```

**Critical Test Files**:
- `test_fst_loading.py` - FST format
- `test_waveformdb_protocol.py` - Waveform DB interface
- `test_async_loading.py` - Async signal loading
- `test_persistence.py` - Session save/load

### 4.4 Edge Cases

**Test Scenarios**:
1. JETS file with no records → empty hierarchy
2. Records without `end_clk` → signal extends indefinitely
3. Events outside record time range → filter or error?
4. Clock frequency missing from metadata → error or default?
5. Malformed JSON in JETS file → graceful error

---

## 5. Performance Considerations

### 5.1 Lazy Signal Generation

**Strategy**: Generate signal values on-demand, not at load time

**Implementation**:
- Store TraceRecord + clock_freq in JetsSignal
- Compute changes list in `all_changes()` iterator
- Cache computed changes after first access

### 5.2 JSON Serialization

**Optimization**:
- Use `serde_json::to_string_pretty` for readability (acceptable for string signals)
- For very large records, consider truncation or summary
- Annotations/events serialized individually (not nested in record JSON)

### 5.3 Memory Footprint

**Efficiency**:
- Arc-based sharing of TraceRecord data
- No duplication between Scope/Var/Signal
- Python objects are lightweight wrappers

**Trade-offs**:
- String signals may be large (JSON text)
- Consider compression for display (WaveScout concern, not Pyrox)

### 5.4 Large File Handling

**JETS files can be large** (millions of records/events):
- Parser is streaming (JSON Lines)
- Tree construction is O(n) where n = record count
- Signal generation is O(e) where e = event count per record
- Total: O(n + e) which is acceptable

---

## 6. Future Enhancements (Out of Scope)

**Potential Future Work**:
1. **Incremental JETS loading**: Stream records as file is written
2. **Binary JETS format**: More efficient than JSON Lines
3. **Query optimization**: Index records by time range
4. **Aggregation signals**: Summary statistics across record groups
5. **Event filtering**: Show only specific event types

---

## 7. Implementation Phases

### Phase 1: Core JETS Loading (Week 1)
- Implement `jets_loader.rs` module
- File loading and hierarchy construction
- Record → Scope/Var mapping
- Basic signal generation (without events)
- Unit tests for loader

### Phase 2: Signal Generation (Week 1)
- Event processing and timestamp conversion
- JSON value generation
- Query methods (`value_at_time`, etc.)
- High-impedance handling

### Phase 3: API Integration (Week 2)
- Modify `lib.rs` to support dual loader
- Add `is_record()`, `record()` methods to Scope
- Export Record class to Python
- Update type stubs

### Phase 4: Testing & Refinement (Week 2)
- Write `test_read_jets.py` integration test
- Run full test suite for regression check
- Fix edge cases and errors
- Documentation updates

### Phase 5: Performance Tuning (Week 3)
- Profile signal generation
- Optimize JSON serialization
- Add caching where beneficial
- Large file testing

---

## 8. Success Criteria

**Must Have**:
- ✅ Load `jets/gpu_sim.jets` successfully
- ✅ Hierarchy reflects JETS record structure
- ✅ Records accessible as Scopes with `scope_type="record"`
- ✅ Records loadable as string signals
- ✅ Signal timestamps converted to microseconds
- ✅ Signal values are pretty-printed JSON
- ✅ All existing tests pass (backward compatibility)
- ✅ New test `test_read_jets.py` passes all assertions

**Nice to Have**:
- Detailed Record Python class with all fields accessible
- Efficient caching for repeated signal queries
- Comprehensive error messages for malformed JETS files

---

## 9. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| JETS format differs significantly from waveforms | High | Parallel loader path isolates JETS logic |
| Timestamp conversion errors | Medium | Extensive unit tests with known values |
| JSON serialization performance | Low | Lazy evaluation, caching |
| Backward compatibility breakage | High | Isolated changes, comprehensive regression testing |
| Large JETS files cause memory issues | Medium | Streaming parser, Arc-based sharing |

---

## 10. Open Questions

1. **Should Records without `end_clk` have infinite duration signals?**
   - Proposal: Extend to file end 

2. **How to handle events outside record time range?**
   - This is not allowed in valid JETS files, record them as undefined String

3. **Should annotations be part of signal value?**
   - No, annotations won't be displayed in signal values

4. **Clock frequency missing from metadata - default value?**
   - Proposal: Require frequency, error if missing (JETS spec mandates it)

5. **Should we support JETS without rjets dependency?**
   - Proposal: No, rjets is canonical parser. Maintain single implementation.

---

---

## 11. Implementation Status

### Integration Test Added (2025-10-06)

**Test**: `test_jets_wavescout_main_window_integration` in `tests/test_read_jets.py`

**What it validates**:
- ✅ JETS file loads into WaveScoutMainWindow without errors
- ✅ DesignTreeView is visible and populated with record tree
- ✅ Tree contains expected number of nodes (1141 nodes from gpu_sim.jets)
- ✅ Root node has correct display name ("flash_attention_fwd")
- ✅ Tree is expandable with child nodes accessible
- ✅ Hierarchy API exposes records correctly:
  - `file_format()` returns "JETS"
  - `top_scopes()` returns record scopes
  - `scope.is_record()` returns True
  - `scope.scope_type()` returns "record"
  - `scope.record()` returns Record object with correct properties
- ✅ Record properties accessible:
  - `record.id` = "host_prog"
  - `record.name` = "flash_attention_fwd"
  - `record.record_type` = "HostProgram"
  - `record.parent_id` correctly references parent
- ✅ Child records navigable via `scope.scopes(hier)`
- ✅ Vars accessible via `scope.vars(hier)`
- ✅ Record var has String type

**Test execution**:
```bash
QT_QPA_PLATFORM=offscreen poetry run pytest tests/test_read_jets.py::test_jets_wavescout_main_window_integration -v
```

**Results**: All 15 JETS tests passing, including the new integration test.

**Note**: No changes to WaveScout code were needed. Pyrox handles JETS files the same way it handles waveforms, proving the abstraction layer works correctly.

---

**Document Version**: 1.1
**Author**: Claude (AI Coding Agent)
**Date**: 2025-10-06 (Updated)
**Status**: Integration Test Implemented
