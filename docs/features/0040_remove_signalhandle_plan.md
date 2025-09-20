# Feature Plan: Remove SignalHandle and Use pyrox::SignalRef

## 1. Use Cases and Requirements Analysis

### Core Requirement
Replace the redundant `SignalHandle` type (currently just `int`) with the existing `pyrox::SignalRef` from the wellen library. This eliminates duplicate mapping layers and simplifies the codebase by relying on the Rust backend's signal reference system.

### Specific Changes Requested
1. Replace `SignalHandle = int` type alias with direct use of `pyrox::SignalRef`
2. Remove redundant mappings in `WaveformDB`:
   - `_signal_ref_to_handle: Dict[int, SignalHandle]`
   - `_handle_to_signal_ref: Dict[SignalHandle, int]`
3. Replace `_var_name_to_handle: Dict[str, SignalHandle]` with new Rust-side functionality for fast variable lookup by full hierarchical name
4. Update all uses of `SignalHandle` throughout the codebase to use `SignalRef` directly

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
1. SignalRef is not exposed as a Python class - needs PyClass wrapper
2. No direct lookup of Var by full hierarchical name - needs new Rust function
3. SignalRef comparison and hashing not available in Python
4. No method to create SignalRef from index for backward compatibility

## 3. Implementation Planning

### Phase 1: Expose SignalRef to Python

**File: `pyrox/src/lib.rs`**

**Changes Needed:**
- Add `SignalRef` as a PyClass wrapper around wellen::SignalRef with:
  - `index() -> usize` - to get underlying index value (for serialization)
  - `__eq__`, `__hash__` implementations for Python dict usage
  - `__repr__` for debugging (e.g., `SignalRef(42)`)
- Add module registration for SignalRef class in the module initialization
- Note: No backward compatibility methods needed

**File: `pyrox/src/lib.rs` (Extended functionality)**

**New Functions to Add:**
- `Hierarchy::find_var_by_full_name(name: &str) -> Option<Var>`
  - Efficiently locate variable by full hierarchical path
  - Use internal hierarchy structures for O(log n) or better lookup
- `Hierarchy::get_var_by_signal_ref(signal_ref: SignalRef) -> Option<Var>`
  - Get the first variable that references this signal
  - Needed for `get_var()` method in WaveformDB
- `Hierarchy::get_all_vars_by_signal_ref(signal_ref: SignalRef) -> Vec<Var>`
  - Get all variables (aliases) that reference this signal
  - Needed for `get_all_vars_for_handle()` method
- `Var::signal_ref_wrapped() -> SignalRef`
  - Return wrapped SignalRef object instead of raw usize

### Phase 2: Update Data Model

**File: `wavescout/data_model.py`**

**Changes:**
- Remove line 55: `SignalHandle = int`
- Line 96: Change `handle: Optional[SignalHandle]` to `handle: Optional[pyrox.SignalRef]`
- Import `SignalRef` from pyrox
- Update all type annotations throughout the file

**File: `wavescout/__init__.py`**

**Changes:**
- Remove `SignalHandle` from exports
- Add `SignalRef` import from pyrox if needed for public API

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

    total_time = time.time() - start_time
    print(f"  - Total load time: {total_time:.2f} seconds")
    # Note: Signal counting now happens on-demand via hierarchy
```

**Method Updates:**
- Update all method signatures to use `pyrox.SignalRef` instead of `SignalHandle`
- Methods now work directly with pyrox objects without intermediate mappings

**New Implementation Patterns:**
```python
# Old pattern - uses pre-built mappings
def find_handle_by_name(self, name: str) -> Optional[SignalHandle]:
    return self._var_name_to_handle.get(name)

def get_var(self, handle: SignalHandle) -> Optional[pyrox.Var]:
    return self._var_map.get(handle, [None])[0]

# New pattern - direct hierarchy queries
def find_handle_by_name(self, name: str) -> Optional[pyrox.SignalRef]:
    if self.hierarchy:
        var = self.hierarchy.find_var_by_full_name(name)
        return var.signal_ref_wrapped() if var else None
    return None

def get_var(self, handle: pyrox.SignalRef) -> Optional[pyrox.Var]:
    if self.hierarchy:
        return self.hierarchy.get_var_by_signal_ref(handle)
    return None
```

**Methods that need complete rewrite:**
- `top_signals()`: Query hierarchy directly instead of using `_var_map`
- `get_all_vars_for_handle()`: Use hierarchy to find all aliases
- `iter_handles_and_vars()`: Iterate through hierarchy instead of `_var_map`
- `get_handle_for_var()`: Use `var.signal_ref_wrapped()` directly
- `num_vars()`: Count from hierarchy instead of summing `_var_map` lengths

### Phase 4: Update Protocol Interfaces

**File: `wavescout/protocols.py`**

**Changes:**
- Import `SignalRef` from pyrox
- Update all method signatures in `WaveformDBProtocol`
- Ensure type consistency across protocol definition

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
- Line 34: Update to store `node.handle.index()` if handle is SignalRef (for JSON compatibility)
- Line 123: When loading, the integer handle will be used directly to get SignalRef from waveform_db
- The name-based resolution in `_resolve_signal_handles()` will continue to work correctly

### Phase 7: Validate with Tests

**Testing Strategy:**
- Run `make test` after each phase to ensure no regressions
- No need to maintain backward compatibility with old session files
- Focus on ensuring all existing tests pass with the new SignalRef type

**Key Test Files to Monitor:**
- `tests/test_signal_range_cache_format_fix.py` - Uses SignalHandle directly
- `tests/test_session_alias_loading.py` - Tests session loading
- `tests/test_waveformdb_protocol.py` - Tests the protocol interface
- Any test that saves/loads sessions or uses SignalHandle

**Success Criteria:**
- All tests pass with `QT_QPA_PLATFORM=offscreen make test`
- No test modifications needed except updating SignalHandle to SignalRef imports
- Performance should remain the same or improve

### Performance Considerations

**Improvements:**
- Eliminated double lookup: No need to convert SignalRef ↔ SignalHandle
- Reduced memory footprint: Removed two large dictionaries
- Faster variable lookup: Direct Rust-side search instead of Python dict

**Potential Issues:**
- SignalRef objects have slight overhead vs raw integers
- Mitigation: SignalRef is a thin wrapper around NonZeroU32, minimal impact

### Implementation Approach

**Clean Refactoring:**
- No backward compatibility required for session files
- Make clean, direct replacements of SignalHandle with SignalRef
- Remove all redundant mapping code without preserving legacy paths
- Validation through test suite (`make test`) is sufficient

**Simplified Migration:**
- Since we don't need backward compatibility, we can:
  - Directly replace SignalHandle type alias with SignalRef imports
  - Remove all mapping dictionaries in one pass
  - Update serialization to use SignalRef.index() without migration code
  - Trust the test suite to catch any issues