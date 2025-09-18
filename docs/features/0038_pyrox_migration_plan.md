# Feature Plan: Replace pywellen with pyrox Library

## 1. Use Cases and Requirements Analysis

### Core Requirements
The user requires replacing the existing `pywellen` submodule with a new PyO3-based library called `pyrox` that will:
1. Be developed inside the WaveScout repository (`<root>/pyrox/`) instead of as a submodule
2. Consume wellen directly from crates.io (`wellen = "=0.19.0"`) instead of using workspace dependencies
3. Initially be a clone of pywellen, just renamed to pyrox
4. Replace all pywellen imports and usages with pyrox throughout wavescout
5. Ensure all existing tests continue to pass after the migration

### Technical Requirements
- **PyO3 compatibility**: Maintain the same PyO3 bindings architecture as pywellen
- **API compatibility**: Keep the exact same Python API surface to minimize code changes
- **Build system integration**: Integrate with Poetry's build system and provide build scripts
- **Test compatibility**: Ensure all tests pass without modification beyond import changes

### Migration Strategy
The migration should be done in phases:
1. Create pyrox library as a clone of pywellen with renamed modules
2. Update build scripts to build pyrox instead of pywellen
3. Replace all imports throughout the codebase
4. Ensure tests pass
5. Remove the old wellen submodule

## 2. Codebase Research

### Current pywellen Structure
Based on research, pywellen consists of:

**Core Files:**
- `wellen/pywellen/Cargo.toml` - Rust package configuration using workspace dependencies
- `wellen/pywellen/src/lib.rs` - Main Rust PyO3 bindings (~816 lines)
- `wellen/pywellen/src/convert.rs` - Type conversion utilities
- `wellen/pywellen/pyproject.toml` - Python package configuration for maturin
- `wellen/pywellen/pywellen/__init__.py` - Python module re-exports

**Build Configuration:**
- Uses maturin for building Python wheels
- Part of a Cargo workspace with wellen library
- Built via `poetry run build-pywellen` command

### pywellen Import Locations
The following files import or reference pywellen:

**Production Code:**
1. `wavescout/backends/pywellen_backend.py` - Main backend implementation
2. `wavescout/backends/__init__.py` - Module imports
3. `wavescout/signal_sampling.py` - Comment reference only

**Test Code:**
1. `tests/test_waveformdb_protocol.py` - Conditional import for type checking
2. `tests/test_backend_compat.py` - Direct pywellen usage for testing

**Build Scripts:**
1. `scripts/build_pywellen.py` - Build script for pywellen
2. `Makefile` - Build targets for pywellen
3. `pyproject.toml` - Poetry script for build-pywellen

### Wellen Workspace Structure
The current setup uses a Cargo workspace:
- `wellen/Cargo.toml` - Workspace root defining shared dependencies
- `wellen/wellen/Cargo.toml` - Wellen library package
- `wellen/pywellen/Cargo.toml` - PyO3 bindings using workspace dependencies

The workspace allows pywellen to use `wellen = { workspace = true }` to reference the local wellen library.

## 3. Implementation Planning

### Phase 1: Create pyrox Library Structure

**File: `pyrox/Cargo.toml`**
- Create new Cargo.toml with direct wellen dependency from crates.io
- Set package name to "pyrox"
- Use `wellen = "=0.19.0"` instead of workspace dependency
- Copy other dependencies from pywellen (pyo3, num-bigint)

**File: `pyrox/src/lib.rs`**
- Copy entire content from `wellen/pywellen/src/lib.rs`
- Change module name from `pywellen` to `pyrox` in `#[pymodule]`
- Keep all class definitions and implementations identical

**File: `pyrox/src/convert.rs`**
- Copy from `wellen/pywellen/src/convert.rs`
- No changes needed as this is internal utility code

**File: `pyrox/pyproject.toml`**
- Copy from pywellen's pyproject.toml
- Change package name to "pyrox"
- Update description and metadata

**File: `pyrox/pyrox/__init__.py`**
- Create Python package directory
- Import from compiled Rust module: `from pyrox.pyrox import *`

**File: `pyrox/Makefile`**
- Copy from pywellen's Makefile if exists
- Adjust paths for pyrox

### Phase 2: Update Build System

**File: `scripts/build_pyrox.py`**
- Create new build script based on `build_pywellen.py`
- Change directory to `pyrox` instead of `wellen/pywellen`
- Keep maturin build command the same

**File: `pyproject.toml`**
- Add new script entry: `build-pyrox = "scripts.build_pyrox:main"`
- Keep build-pywellen temporarily for comparison

**File: `Makefile`**
- Replace `poetry run build-pywellen` with `poetry run build-pyrox`
- Update clean targets to include `pyrox/target`

### Phase 3: Create Backend Adapter

**File: `wavescout/backends/pyrox_backend.py`**
- Create as exact copy of `pywellen_backend.py`
- Replace all `pywellen` imports with `pyrox`
- Update class name to `PyroxBackend`
- Update backend type to a new `BackendType.PYROX`

**File: `wavescout/backends/base.py`**
- Add new `BackendType.PYROX` enum value
- Keep `BackendType.PYWELLEN` temporarily for testing

**File: `wavescout/backends/__init__.py`**
- Import both backends during transition
- Default to pyrox_backend

### Phase 4: Update Imports Throughout Codebase

**File: `tests/test_waveformdb_protocol.py`**
- Change `from pywellen import Var` to `from pyrox import Var`

**File: `tests/test_backend_compat.py`**
- Replace `import pywellen` with `import pyrox`
- Update all `pywellen.` references to `pyrox.`

**File: `wavescout/signal_sampling.py`**
- Update comment from "pywellen" to "pyrox"

### Phase 5: Testing and Validation

**Testing Strategy:**
1. Build pyrox with `poetry run build-pyrox`
2. Run full test suite: `make test`
3. Verify all tests pass without modification
4. Run type checking: `make typecheck`
5. Test the application: `make dev`

### Phase 6: Cleanup

**Files to Remove (after validation):**
- `wellen/` submodule directory (entire submodule)
- `scripts/build_pywellen.py`
- `wavescout/backends/pywellen_backend.py`
- Remove `BackendType.PYWELLEN` from base.py
- Remove build-pywellen script from pyproject.toml

### Algorithm Descriptions

**Build Process Flow:**
1. Poetry calls `build-pyrox` script
2. Script navigates to `pyrox/` directory
3. Maturin builds Rust code with PyO3 bindings
4. Compiled extension installed in virtual environment
5. Python code can import pyrox module

**Module Loading:**
1. Python imports pyrox
2. pyrox/__init__.py loads compiled extension
3. Extension provides all Waveform, Hierarchy, Signal classes
4. Backend instantiates these classes for waveform loading

### Performance Considerations

Since pyrox will be functionally identical to pywellen initially:
- No performance impact expected
- Same Rust backend (wellen library)
- Same PyO3 binding overhead
- Same signal loading algorithms

The main difference is using wellen from crates.io (v0.19.0) instead of the local workspace version. This may introduce minor API differences that need to be handled during implementation.