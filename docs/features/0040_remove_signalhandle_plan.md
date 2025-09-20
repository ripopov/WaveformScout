# Feature Plan: Remove SignalHandle and Use pyrox::SignalRef

## 1. Use Cases and Requirements Analysis

### Core Requirement
Replace the redundant `SignalHandle` type alias with a new `SignalRef` type alias. Both are simple `int` type aliases, but `SignalRef` better aligns with the Rust backend terminology and eliminates unnecessary mapping layers.

### Specific Changes Requested
1. Replace `SignalHandle = int` type alias with `SignalRef = int` type alias
2. Remove redundant mappings in `WaveformDB`:
   - `_signal_ref_to_handle: Dict[int, SignalHandle]` - no longer needed
   - `_handle_to_signal_ref: Dict[SignalHandle, int]` - no longer needed
3. Replace `_var_name_to_handle: Dict[str, SignalHandle]` with new Rust-side functionality for fast variable lookup by full hierarchical name
4. Update all uses of `SignalHandle` throughout the codebase to use `SignalRef`

### Benefits
- Eliminates redundant abstraction layer
- Reduces memory usage by removing duplicate mappings
- Improves performance by avoiding extra lookups
- Simplifies codebase maintenance
- Direct alignment with underlying wellen library concepts

## 2. Codebase Research

### Current SignalHandle Usage

**Core Definition (`wavescout/data_model.py`)**
- Line 55: `SignalHandle = int` type alias
- Line 96: `SignalNode.handle: Optional[SignalHandle]`
- Used as an opaque identifier for signals in the waveform database

**Primary Implementation (`wavescout/waveform_db.py`)**
- Lines 23-28: Storage and mapping structures
  - `_var_map: Dict[SignalHandle, List[pyrox.Var]]` - Maps handles to variables
  - `_signal_cache: Dict[SignalHandle, pyrox.Signal]` - Cache for loaded signals
  - `_var_name_to_handle: Dict[str, SignalHandle]` - Name to handle mapping
  - `_signal_ref_to_handle: Dict[int, SignalHandle]` - SignalRef to handle (redundant)
  - `_handle_to_signal_ref: Dict[SignalHandle, int]` - Handle to SignalRef (redundant)
- Lines 90-113: Handle assignment logic during waveform loading
- Multiple methods using SignalHandle in signatures (15+ methods)

**Protocol Definition (`wavescout/protocols.py`)**
- Lines 25-97: `WaveformDBProtocol` methods use `SignalHandle` in signatures
- Critical interface that needs updating

**UI Components Using SignalHandle**
- `wavescout/signal_renderer.py`: Uses in `SignalDrawingData`, drawing commands
- `wavescout/waveform_canvas.py`: `TransitionCache` uses SignalHandle as key
- `wavescout/waveform_loader.py`: Creates SignalNodes with handles
- `wavescout/design_tree_model.py`: Uses handles in design tree operations
- `wavescout/design_tree_view.py`: Signal selection and context menus

### Current pyrox::SignalRef Capabilities

**Rust Side (`pyrox/src/lib.rs`)**
- Line 257-259: `Var::signal_ref()` returns `usize` (the SignalRef index)
- SignalRef is used internally but not exposed as a Python class
- Line 11: SignalRef imported from wellen but not wrapped for Python
- Lines 537-548: SignalRef used for signal loading and caching with HashMap

**Missing Functionality**
1. No direct lookup of Var by full hierarchical name - needs new Rust function
2. No method to get all variables (aliases) for a given SignalRef
3. Need methods that work with 0-based integer SignalRefs

## 3. Implementation Planning

### Phase 1: Add Rust-side Support for SignalRef Operations

**SignalRef Implementation Strategy:**
- Python side: `SignalRef = int` (simple type alias, 0-based integers)
- Rust side: Convert between 0-based Python ints and 1-based Wellen `NonZeroU32`
- No PyClass wrapper needed - SignalRef remains a plain integer

**File: `pyrox/src/lib.rs`**

**New Rust Methods to Add:**
```rust
// In Hierarchy implementation:
fn find_var_by_full_name(&self, name: &str) -> Option<Var>
  // Efficiently locate variable by full hierarchical path

fn get_var_by_signal_ref(&self, signal_ref: usize) -> Option<Var>
  // Get first variable that references this signal (0-based input)
  // Convert to 1-based Wellen SignalRef internally

fn get_all_vars_by_signal_ref(&self, signal_ref: usize) -> Vec<Var>
  // Get all variables (aliases) for a signal (0-based input)
  // Convert to 1-based Wellen SignalRef internally

// In Var implementation:
fn signal_ref(&self) -> usize
  // Already exists, ensure it returns 0-based index
  // Convert from 1-based Wellen SignalRef to 0-based
```

### Phase 2: Update Python Type Alias

**File: `wavescout/data_model.py`**
```python
# Line 55: Simple rename
SignalRef = int  # was: SignalHandle = int

# Line 96: Update type annotation
handle: Optional[SignalRef]  # was: Optional[SignalHandle]
```

**File: `wavescout/__init__.py`**
- Export `SignalRef` instead of `SignalHandle`

### Phase 3: Refactor WaveformDB

**File: `wavescout/waveform_db.py`**

**Major Refactoring:**
- Remove lines 23-28: All mapping dictionaries become unnecessary
  - Remove `_var_map: Dict[SignalHandle, List[pyrox.Var]]`
  - Remove `_signal_cache: Dict[SignalHandle, pyrox.Signal]`
  - Remove `_var_name_to_handle: Dict[str, SignalHandle]`
  - Remove `_signal_ref_to_handle: Dict[int, SignalHandle]`
  - Remove `_handle_to_signal_ref: Dict[SignalHandle, int]`
- Keep only `_signal_cache: Dict[pyrox.SignalRef, pyrox.Signal]` for caching loaded signals

**Remove Variable Mapping Construction (lines 62-121):**
- Delete entire mapping construction block from `mapping_start` to `mapping_end`
- Remove the recursive `collect_vars_recursive` function (lines 73-87)
- Remove all variable collection and processing logic (lines 66-113)
- Remove timing/logging for mapping construction (lines 63, 115-118)
- Keep only the waveform loading and timescale extraction

**Simplified `open()` method:**
```python
def open(self, uri: str) -> None:
    """Open a waveform file."""
    start_time = time.time()
    self.uri = uri

    # Load waveform using pyrox
    self.waveform = pyrox.Waveform(uri)
    self.hierarchy = self.waveform.hierarchy

    # Extract and store timescale
    self._extract_timescale()

    # No more mapping construction - everything is queried on-demand
    total_time = time.time() - start_time
    print(f"  - Total load time: {total_time:.2f} seconds")
```

**Method Updates:**
- Update all method signatures to use `SignalRef` (int) instead of `SignalHandle`
- Methods now work directly with pyrox objects without intermediate mappings

**New Implementation Patterns:**
```python
# Old pattern - uses pre-built mappings
def find_handle_by_name(self, name: str) -> Optional[SignalHandle]:
    return self._var_name_to_handle.get(name)

def get_var(self, handle: SignalHandle) -> Optional[pyrox.Var]:
    return self._var_map.get(handle, [None])[0]

# New pattern - direct hierarchy queries (SignalRef is int)
def find_handle_by_name(self, name: str) -> Optional[SignalRef]:
    if self.hierarchy:
        var = self.hierarchy.find_var_by_full_name(name)
        return var.signal_ref() if var else None  # Returns 0-based int
    return None

def get_var(self, handle: SignalRef) -> Optional[pyrox.Var]:
    if self.hierarchy:
        return self.hierarchy.get_var_by_signal_ref(handle)  # Pass 0-based int
    return None
```

**Methods that need complete rewrite:**
- `top_signals()`: Query hierarchy directly instead of using `_var_map`
- `get_all_vars_for_handle()`: Use hierarchy to find all aliases
- `iter_handles_and_vars()`: Iterate through hierarchy instead of `_var_map`
- `get_handle_for_var()`: Use `var.signal_ref()` directly (returns 0-based int)
- `num_vars()`: Count from hierarchy instead of summing `_var_map` lengths

### Phase 4: Update Protocol Interfaces

**File: `wavescout/protocols.py`**
```python
from wavescout.data_model import SignalRef  # was: SignalHandle

# Update all method signatures:
def find_handle_by_name(self, name: str) -> Optional[SignalRef]:
def get_var(self, handle: SignalRef) -> Optional[pyrox.Var]:
# ... etc for all methods using SignalHandle
```

### Phase 5: Update UI Components

**File: `wavescout/signal_renderer.py`**

**Changes:**
- Line 37: Update `SignalDrawingData.handle` type
- Line 62: Update dict key type in `CachedWaveDrawData`
- Update function signatures for `compute_global_signal_range`, `get_signal_range`

**File: `wavescout/waveform_canvas.py`**

**Changes:**
- Update `TransitionCache` methods to use `SignalRef` keys
- Update `_draw_row` method signature

**File: `wavescout/waveform_loader.py`**

**Changes:**
- Update `create_signal_node_from_var` signature
- Ensure SignalRef is properly passed when creating SignalNodes

**File: `wavescout/design_tree_model.py` and `wavescout/design_tree_view.py`**

**Changes:**
- Update any SignalHandle references in signal selection logic
- Ensure compatibility with new SignalRef type

### Phase 6: Update Persistence Layer

**File: `wavescout/persistence.py`**

**Current State Analysis:**
- Persistence already uses hierarchical names (node.name) as the primary identifier
- The `_resolve_signal_handles()` function (lines 52-88) re-resolves handles from names when loading
- This approach ensures correctness across different waveform file versions

**Changes Needed:**
- Line 34: No change needed - SignalRef is already an int, stores directly
- Line 123: No change needed - integer handle works as-is since SignalRef is int
- The name-based resolution in `_resolve_signal_handles()` will continue to work correctly
- Just update type imports to use SignalRef instead of SignalHandle

### Phase 7: Validate with Tests

**Testing Strategy:**
- Run `make test` after each phase to ensure no regressions
- No need to maintain backward compatibility with old session files
- Focus on ensuring all existing tests pass with the new SignalRef type

**Key Test Files to Monitor:**
- `tests/test_signal_range_cache_format_fix.py` - Simple rename SignalHandle → SignalRef
- `tests/test_session_alias_loading.py` - Tests session loading
- `tests/test_waveformdb_protocol.py` - Tests the protocol interface
- Since SignalRef = int (same as SignalHandle = int), tests should work with minimal changes

**Success Criteria:**
- All tests pass with `QT_QPA_PLATFORM=offscreen make test`
- Only change needed: rename SignalHandle → SignalRef in imports
- Performance should improve due to eliminated mappings

### Performance Considerations

**Improvements:**
- Eliminated double lookup: No need to convert SignalRef ↔ SignalHandle
- Reduced memory footprint: Removed two large dictionaries
- Faster variable lookup: Direct Rust-side search instead of Python dict
- No Python object overhead: SignalRef is just an int, not a wrapped object

**API Boundary Conversion:**
- Minimal overhead: Simple +1/-1 conversion at Rust/Python boundary
- Conversion happens in Rust code, transparent to Python users

### Implementation Summary

**Key Points:**
1. **SignalRef = int** - Simple type alias, not a class
2. **No PyClass wrapper** - Just use plain integers
3. **Rust boundary conversion** - Handle 0-based ↔ 1-based conversion in Rust
4. **Direct refactoring** - Simple rename from SignalHandle to SignalRef
5. **Remove mappings** - Eliminate redundant dictionary lookups

**Migration is straightforward:**
- Find/replace `SignalHandle` → `SignalRef` across codebase
- Remove mapping dictionaries from WaveformDB
- Add Rust methods for hierarchy queries
- Run tests to validate