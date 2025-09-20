# Remove pylibfst Backend Support Plan

## 1. Use Cases and Requirements Analysis

### Core Requirements
- Remove all pylibfst backend support from WaveformScout
- Make pyrox the sole waveform backend for both VCD and FST files
- Remove backend selection menu from UI
- Remove backend abstraction layer (`wavescout/backends/` directory)
- Remove protocol types (`wavescout/backend_types.py`) and use pyrox types directly
- Remove all tests that compare pyrox and pylibfst backends
- Ensure the application continues to work after refactoring (make install & make test)

### Rationale
- Simplifies codebase by removing abstraction layer that's no longer needed
- Pyrox has proven to be more reliable and performant
- Reduces maintenance burden of supporting multiple backends
- Direct use of pyrox types improves type checking and IDE support

## 2. Codebase Research

### Backend Architecture Overview
The current architecture uses an abstraction layer to support multiple backends:

1. **Protocol Types** (`wavescout/backend_types.py`):
   - Defines `W`-prefixed protocol types (WWaveform, WVar, WSignal, etc.)
   - Allows backend-agnostic code throughout the application

2. **Backend Factory** (`wavescout/backends/base.py`):
   - `BackendFactory` class creates appropriate backend based on file type and preference
   - `BackendType` enum defines PYROX and PYLIBFST options
   - `WaveformBackend` abstract base class

3. **Backend Implementations**:
   - `wavescout/backends/pyrox_backend.py`: Pyrox adapter (mostly pass-through)
   - `wavescout/backends/pylibfst_backend.py`: Pylibfst adapter with various adapters

4. **WaveformDB** (`wavescout/waveform_db.py`):
   - Uses BackendFactory to create backend instances
   - Stores backend preference
   - Methods like `get_backend_type()` and `set_backend_preference()`

### UI Components
- **Main Window** (`scout.py`):
  - Lines 718-737: FST Loader menu with Pyrox/libfst selection
  - Line 122-124: FST backend preference initialization
  - Line 969, 1143: Pass backend preference to loaders
  - Lines 1462-1484: `_set_fst_backend()` method

- **Settings Manager** (`wavescout/settings_manager.py`):
  - Lines 102-113: FST backend preference storage

### Test Files to Remove
- `tests/test_dual_fst_backend.py`: Compares both backends
- `tests/test_backend_compat.py`: Backend compatibility tests

### Files Using Backend Types
Files importing from `backend_types.py`:
- `wavescout/waveform_db.py`
- `wavescout/design_tree_model.py`
- `wavescout/signal_renderer.py`
- `wavescout/scope_tree_model.py`
- `wavescout/protocols.py`
- `wavescout/clock_utils.py`
- `wavescout/backends/*.py`

## 3. Implementation Planning

### Phase 1: Update Core Components to Use Pyrox Directly

#### File: `wavescout/waveform_db.py`
**Changes Required:**
- Remove imports from `backend_types` and `backends`
- Import pyrox types directly
- Remove `_backend` attribute and related backend management
- Remove `get_backend_type()` and `set_backend_preference()` methods
- Replace all `W`-prefixed types with pyrox types
- Simplify `load_waveform()` to always use pyrox.Waveform directly
- Remove backend preference parameter from `__init__()`

#### File: `wavescout/protocols.py`
**Changes Required:**
- Remove imports from `backend_types`
- Import pyrox types directly
- Update `WaveformDBProtocol` to use pyrox types
- Remove `get_backend_type()` method from protocol

#### File: `wavescout/design_tree_model.py` and `wavescout/scope_tree_model.py`
**Changes Required:**
- Replace imports of WVar, WScope from backend_types with pyrox.Var, pyrox.Scope

#### File: `wavescout/signal_renderer.py` and `wavescout/clock_utils.py`
**Changes Required:**
- Update any references to backend types to use pyrox types directly

### Phase 2: Remove UI Backend Selection

#### File: `scout.py`
**Changes Required:**
- Remove lines 718-737 (FST Loader menu and actions)
- Remove lines 122-124 (backend preference initialization)
- Remove lines 1462-1484 (`_set_fst_backend()` method)
- Remove backend preference parameters from line 969 and 1143
- Remove `fst_backend_preference` attribute
- Remove `pyrox_action` and `pylibfst_action` attributes

#### File: `wavescout/settings_manager.py`
**Changes Required:**
- Remove `get_fst_backend()` method (lines 102-107)
- Remove `set_fst_backend()` method (lines 109-114)
- Remove `_fst_backend_cache` attribute

#### File: `wavescout/waveform_loader.py`
**Changes Required:**
- Remove `backend_preference` parameter from `create_sample_session()`

#### File: `wavescout/persistence.py`
**Changes Required:**
- Remove `backend_preference` parameter from `load_session()`
- Update comments about backend differences

### Phase 3: Remove Backend Infrastructure

#### Files to Delete:
1. `wavescout/backends/` directory (entire directory)
2. `wavescout/backend_types.py`
3. `tests/test_dual_fst_backend.py`
4. `tests/test_backend_compat.py`

### Phase 4: Update Build System

#### File: `Makefile`
**Changes Required:**
- Remove any references to pylibfst build commands in targets
- Keep only pyrox build commands
- Note: Keep pylibfst directory for now (may be removed in future)

#### File: `pyproject.toml`
**Changes Required:**
- Keep `build-pylibfst` script entry (in case needed for future testing)
- Keep pylibfst directory structure

#### Files to Keep:
- `pylibfst/` directory - Keep for potential future use
- `scripts/` directory pylibfst build scripts - Keep but won't be used by default

### Phase 5: Update Tests

#### File: `tests/test_fst_loading.py`
**Changes Required:**
- Remove any tests that use pylibfst backend
- Update to use pyrox directly

#### Other Test Files:
- Search for and update any tests importing from `backend_types` or `backends`
- Update to import pyrox types directly

### Migration Strategy for Type Changes

**Type Mapping:**
- `WWaveform` → `pyrox.Waveform`
- `WHierarchy` → `pyrox.Hierarchy`
- `WVar` → `pyrox.Var`
- `WSignal` → `pyrox.Signal`
- `WScope` → `pyrox.Scope`
- `WTimeTable` → `pyrox.TimeTable`
- `WTimescale` → `pyrox.Timescale`

### Testing Plan
1. Run `make clean` to remove old build artifacts
2. Run `make install` to rebuild (will still build both pyrox and pylibfst but only pyrox will be used)
3. Run `make test` to ensure all tests pass
4. Test loading VCD files
5. Test loading FST files
6. Test session save/load functionality
7. Verify UI no longer shows backend selection menu

### Potential Issues and Solutions
1. **Import errors**: Some files may have indirect dependencies on backend types
   - Solution: Search and replace all imports systematically

2. **Type checker errors**: mypy may complain about type mismatches
   - Solution: Update type hints to use pyrox types directly

3. **Test failures**: Some tests may depend on backend abstraction
   - Solution: Update tests to work with pyrox directly or remove if no longer relevant