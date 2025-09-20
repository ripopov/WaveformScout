# SignalRef to SignalHandle Refactoring Plan

## Executive Summary

This refactoring renames `SignalRef` to `SignalHandle` to eliminate naming ambiguity between Wellen's 1-based SignalRef and wavescout's 0-based SignalRef. The new `SignalHandle` type will be declared in pyrox and imported by all wavescout modules.

**Scope**: 12-13 files need updates (mostly import changes and type annotations)
**Risk**: Low - type alias change with no runtime behavior changes
**Backward Compatibility**: Maintained by keeping `signal_ref()` method name

## 1. Use Cases and Requirements Analysis

### Core Problem
The codebase currently has an ambiguous `SignalRef` type:
- **Wellen library**: Uses `SignalRef` as a non-zero-based (1-based) index
- **Wavescout**: Uses `SignalRef = int` as a 0-based index in data_model.py
- This creates confusion and requires mental context switching when working across the Rust/Python boundary

### Requirements
1. **Remove ambiguity**: Eliminate the conflicting `SignalRef` naming between Wellen and Wavescout
2. **Rename to SignalHandle**: Use a clearer, non-conflicting name that better represents its purpose
3. **Move declaration to pyrox**: Since the concept originates from Wellen and is converted via index/from_index operations in pyrox, the type alias should be declared in pyrox
4. **Maintain compatibility**: Ensure all existing code continues to work with the renamed type
5. **Type safety**: Preserve strict typing throughout the refactoring

### Technical Details from User Requirements
- SignalHandle will be declared as a type alias in both:
  - Rust side of pyrox library
  - Python .pyi type stub file
- The conversion logic (index/from_index) remains in pyrox
- Wavescout will import and use SignalHandle from pyrox

## 2. Codebase Research

### Current SignalRef Usage

#### In data_model.py
- **Definition**: `SignalRef = int` (line 55)
- **Usage**: As optional field in SignalNode.handle (line 96)
- **Documentation**: Extensive comment explaining it as an opaque identifier for efficient signal references (lines 47-54)
- **Also defines**: `SignalNodeID = int` for unique instance identification

#### In protocols.py
- **Import**: From data_model (line 9)
- **Usage in WaveformDBProtocol methods** (15 methods total):
  - `find_handle_by_path()` returns `Optional[SignalRef]`
  - `find_handle_by_name()` returns `Optional[SignalRef]`
  - `get_handle_for_var()` returns `Optional[SignalRef]`
  - `get_var()` takes `SignalRef` parameter
  - `get_all_vars_for_handle()` takes `SignalRef` parameter
  - `iter_handles_and_vars()` returns iterator of `tuple[SignalRef, list[pyrox.Var]]`
  - `get_var_bitwidth()` takes `SignalRef` parameter
  - `get_var_to_handle_mapping()` returns `Dict[pyrox.Var, SignalRef]`
  - `get_next_available_handle()` returns `Optional[SignalRef]`
  - `get_signal()` takes `SignalRef` parameter
  - `var_from_handle()` takes `SignalRef` parameter
  - `signal_from_handle()` takes `SignalRef` parameter

#### In waveform_db.py
- **Import**: From data_model (line 13)
- **Usage**:
  - Signal cache: `Dict[SignalRef, pyrox.Signal]` (line 23)
  - Multiple method signatures using SignalRef (lines 62, 87, 100, 113, 193, 200, 213, 232, 239, 246, 257, 347, 357, 369, 413, 443, 466)

#### In pyrox Rust Implementation (lib.rs)
- **Wellen import**: `use wellen::SignalRef` (line 11)
- **Wellen's SignalRef**: Defined as `pub struct SignalRef(NonZeroU32)` in wellen/src/hierarchy.rs
  - Uses 1-based indexing internally (`from_index` adds 1, `index()` subtracts 1)
- **Conversion in Var.signal_ref()**: Returns 0-based index for Python use (lines 345-350)
  - Calls `self.0.signal_ref().index()` to convert from Wellen's 1-based to 0-based
- **Usage in signal loading**: Uses Wellen's SignalRef internally for signal operations
- **get_all_vars_by_signal_ref**: Takes 0-based index, converts to Wellen's 1-based SignalRef

#### In pyrox Python API (pyrox.pyi)
- Currently no explicit SignalRef or SignalHandle type alias
- `Var.signal_ref()` method returns `int` (line 30)
- Missing proper type annotation for the handle concept

### Other Files Using SignalRef
- **waveform_canvas.py**:
  - Imports from data_model (line 9)
  - Used in TransitionCache methods (lines 42, 50)
  - Used in _draw_row signature (line 991)
- **signal_renderer.py**:
  - Imports from data_model (line 27)
  - Used in SignalDrawingData dataclass (line 37)
  - Used in DrawCommandBundle (line 62)
  - Used in compute_global_signal_range and get_signal_range functions
- **design_tree_view.py**:
  - Imports from data_model (line 23)
  - Used in _find_signal_handle return type (line 183)
  - Used in _is_single_bit parameter (line 426)
- **design_tree_model.py**:
  - Imports from data_model (line 65)
  - Used in DesignTreeItem.var_handle type (line 91)
  - Used in _var_to_handle mapping (line 165)
- **waveform_loader.py**:
  - Imports from data_model (line 5)
  - Used in create_signal_node_from_var parameter (line 9)
- **__init__.py**: Exports SignalRef (lines 6, 20)
- **test_signal_range_cache_format_fix.py**: Uses SignalRef in test fixtures

## 3. Implementation Planning

### File-by-File Changes

#### 1. pyrox/src/lib.rs
- **Add type alias**: At the top of the file, add:
  ```rust
  pub type SignalHandle = usize;  // 0-based index for Python use
  ```
- **Keep Var.signal_ref() method name**: For backward compatibility, but update documentation
- **Update method documentation**: Clarify that it returns SignalHandle (0-based)
- **Note**: Continue using wellen::SignalRef internally for Wellen API calls

#### 2. pyrox/pyrox/pyrox.pyi
- **Add type alias** at module level:
  ```python
  SignalHandle = int  # 0-based index for signal identification
  ```
- **Update Var.signal_ref() return type**:
  ```python
  def signal_ref(self) -> SignalHandle: ...
  ```
- **Add to __all__ exports** if present

#### 3. wavescout/data_model.py
- **Remove SignalRef definition**: Delete line 55 (`SignalRef = int`)
- **Import SignalHandle**: Add to imports:
  ```python
  from pyrox import SignalHandle
  ```
- **Update SignalNode.handle**: Change line 96:
  ```python
  handle: Optional[SignalHandle] = None
  ```
- **Update comments**: Lines 47-54, replace "SignalRef" with "SignalHandle"

#### 4. wavescout/protocols.py
- **Update import**: Line 9, change:
  ```python
  from .data_model import Timescale  # Remove SignalRef
  from pyrox import SignalHandle
  ```
- **Update all 15 method signatures**: Replace all `SignalRef` with `SignalHandle`

#### 5. wavescout/waveform_db.py
- **Update import**: Line 13, change:
  ```python
  from .data_model import Time, Timescale, TimeUnit  # Remove SignalRef
  from pyrox import SignalHandle
  ```
- **Update cache type** (line 23): `Dict[SignalHandle, pyrox.Signal]`
- **Update all method signatures**: Replace SignalRef with SignalHandle (17 occurrences)

#### 6. wavescout/waveform_canvas.py
- **Update import**: Line 9, change to import SignalHandle from pyrox
- **Update TransitionCache methods** (lines 42, 50)
- **Update _draw_row signature** (line 991)

#### 7. wavescout/signal_renderer.py
- **Update import**: Line 27, import SignalHandle from pyrox
- **Update SignalDrawingData.handle** (line 37)
- **Update DrawCommandBundle.draw_commands** (line 62)
- **Update function signatures**: compute_global_signal_range, get_signal_range

#### 8. wavescout/design_tree_view.py
- **Update import**: Line 23, import SignalHandle from pyrox
- **Update _find_signal_handle return type** (line 183)
- **Update _is_single_bit parameter** (line 426)

#### 9. wavescout/design_tree_model.py
- **Update import**: Line 65, import SignalHandle from pyrox
- **Update DesignTreeItem.var_handle type** (line 91)
- **Update _var_to_handle mapping type** (line 165)

#### 10. wavescout/waveform_loader.py
- **Update import**: Line 5, import SignalHandle from pyrox
- **Update create_signal_node_from_var parameter** (line 9)

#### 11. wavescout/__init__.py
- **Update imports**: Line 6, import SignalHandle from pyrox instead of data_model
- **Update exports**: Line 20, export SignalHandle instead of SignalRef

#### 12. tests/test_signal_range_cache_format_fix.py
- **Update import**: Import SignalHandle from wavescout
- **Update all usage**: Replace SignalRef with SignalHandle (5 occurrences)

#### 13. pylibfst (Optional - if still in use)
- **Note**: The pylibfst backend has its own internal SignalRef struct in Rust
- **No changes needed**: pylibfst's internal SignalRef is isolated from Python API
- **Consider future alignment**: May want to align naming in a future refactor

### Integration Points

1. **Type Import Chain**:
   - pyrox defines SignalHandle → wavescout modules import from pyrox → tests import from wavescout
   - Single source of truth for the type alias (pyrox)

2. **Backend Compatibility**:
   - pylibfst uses its own internal SignalRef struct but doesn't expose it to Python
   - Both backends will work with the same SignalHandle type from Python perspective

3. **Session Persistence**:
   - The YAML serialization should continue to work since SignalHandle remains an int
   - No changes needed to persistence logic

4. **Backward Compatibility**:
   - Keeping `signal_ref()` method name ensures no breaking changes
   - Type alias change is transparent to runtime behavior

### Testing Strategy

1. **Type Checking**: Run mypy to ensure all type annotations are correct
2. **Unit Tests**: Verify all existing tests pass with the renamed type
3. **Integration Tests**: Test signal loading, caching, and rendering workflows
4. **Backend Tests**: Ensure both pyrox and pylibfst backends work correctly