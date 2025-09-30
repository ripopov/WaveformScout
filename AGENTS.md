# WaveformScout Agent Guide

This playbook aligns CLAUDE, Junie, Codex, and other coding agents on the current WaveformScout codebase so changes stay accurate and intentional.

**IF YOU ARE DEVELOPING ON WINDOWS, RUN EVERY COMMAND FROM POWERSHELL. DO NOT USE BASH.**

## Current Architecture Snapshot
- PySide6/Qt6 front-end renders the waveform viewer and supporting tools (snippets, markers, analysis panes).
- Python orchestrates state via dataclasses (`wavescout/data_model.py`) and the Protocol pattern where needed.
- Rust extension `pyrox` (PyO3 bindings for the Wellen core) provides fast waveform access for VCD and FST files.
- Backend coordination is handled directly by `WaveformDB` in `wavescout/waveform_db.py`.

## Directory Orientation
- `wavescout/` — main application package. Key areas include:
  - `application/` (event bus & domain events for cross-widget coordination)
  - `config.py`, `theme.py`, `color_utils.py` (UI customization and theming)
  - `data_model.py`, `waveform_item_model.py`, `waveform_controller.py` (core state & Qt models)
  - `waveform_db.py` (async signal loading, backend coordination via pyrox)
  - `wave_scout_widget.py`, `waveform_canvas.py`, `signal_renderer.py` (main widget & rendering pipeline)
  - `snippet_*`, `markers_window.py`, `analysis_engine.py` (workflow-specific tooling)
  - `design_tree_view.py`, `signal_names_view.py`, `vars_view.py` (hierarchy and signal browsing)
  - `persistence.py` (session save/load with JSONC support)
  - `settings_manager.py`, `icon_cache.py`, `timing_utils.py`, `clock_utils.py` (utilities)
- `pyrox/` — Rust crate + maturin project that exposes the high-performance waveform API (`build-pyrox`).
  - Contains Wellen library as a submodule providing the core waveform parsing and access.
- `scripts/` — build helpers for pyrox (Linux/macOS plus Windows fallbacks).
- `tests/` — pytest + pytest-qt suite (uses `test_inputs/` waveforms for integration coverage).
- `docs/` — feature plans
- `take_snapshot.py` — utility to capture GUI snapshots during development.
- `setup_env.ps1` — initializes the MSVC developer environment required to build Rust/PyO3 on Windows.

## Toolchain & Environment
- Python 3.12+ (up to 3.13) managed by Poetry (local `.venv`).
- Rust toolchain with `maturin` 1.7+ to build PyO3 extensions.
- PySide6 6.9+, NumPy 2.x, RapidFuzz 3.14+, QDarkStyle 3.2+, and PySideSix-Frameless-Window 0.7+ for the UI.
- Make is used as the primary command runner (`Makefile` normalizes Windows vs. POSIX flows).
- Development tools: pytest 8.0+, pytest-qt 4.0+, mypy 1.16+ for type checking, Nuitka 2.7+ for compilation.

## Setup Flow
### Windows (PowerShell only)
```powershell
cd <path-to-WaveformScout>
. .\setup_env.ps1
make install  # installs Poetry deps, then builds pyrox and pylibfst
make dev      # launches the Qt application
```

### Linux / macOS
```bash
cd <path-to-WaveformScout>
make install  # installs dependencies and builds pyrox + pylibfst

# Manual path (if you need extra control)
poetry config virtualenvs.in-project true
poetry install
poetry run build-pyrox
poetry run build-pylibfst
```

The install target runs `poetry run build-pyrox` and `poetry run build-pylibfst`, so the Rust extensions are always rebuilt after dependency changes.

## Running & Developer Utilities
- Launch the viewer: `make dev` (or `poetry run python scout.py`).
- Start with a clean environment: `make clean`, `make clean-venv`.
- Generate distributables: `make build` (Poetry build) or `make compile` (Nuitka standalone binaries; auto-selects platform flags).

## Working in the Virtual Environment
Poetry auto-uses the in-project `.venv`. Direct activation is optional but available:
```bash
source .venv/bin/activate        # Linux/macOS
.\.venv\Scripts\Activate.ps1    # Windows
poetry env activate               # cross-platform alternative
```
Use `poetry run <command>` whenever unsure that the venv is active.

## Testing & Quality Gates
- **Always** set `QT_QPA_PLATFORM=offscreen` for any pytest invocation to avoid GUI requirements.
  - Full suite: `QT_QPA_PLATFORM=offscreen make test`
  - Direct Pytest: `QT_QPA_PLATFORM=offscreen poetry run pytest tests/`
  - Targeted test: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_file.py -k scenario`
- Type checking: `make typecheck` → `poetry run mypy wavescout/ --strict --config-file mypy.ini`
- GUI snapshot helper: `poetry run python take_snapshot.py --help`
- When touching waveform loading or pyrox, run the relevant integration tests (`tests/test_fst_loading.py`, `tests/test_async_loaded_signal.py`, `tests/test_async_loading.py`).

## Coding Standards
- Preserve DRY and Single Responsibility principles; prefer shared helpers in `wavescout/` over duplicating logic in widgets.
- Follow repository style (PEP 8 leaning, explicit imports, module-level `__all__` where appropriate).
- Qt widgets should derive from the existing base classes and plug into the event bus where possible instead of emitting ad-hoc signals.

### Strict Typing Expectations
1. Do not introduce `Any`; use precise protocols or concrete types from `wavescout.data_model`.
2. Use `TypedDict`, `Protocol`, and `TypeAlias` for structured data instead of loose dicts.
3. Annotate every parameter and return type; express optionality explicitly with `Optional[T]`.
4. Prefer domain-specific types (`SignalHandle` from pyrox, `Time`, `Timescale`, etc.) over primitive types in signatures.
5. Keep unions narrow—consider protocols or dataclasses before widening types.
6. All code must pass `mypy --strict` type checking as enforced by `make typecheck`.

### Initialization Contracts
- Initialize every attribute in `__init__` (set to `None` or a default) and avoid `hasattr`/`delattr` in production code.
- Use lifecycle flags (`self._initialized`, `self._ui_ready`) instead of probing for attributes.
- For transient bundles of state, prefer dataclasses or small `NamedTuple`s declared next to their usage.

## Backend & Data Flow Guidance
- `WaveformDB` in `wavescout/waveform_db.py` is the primary interface to waveform data, providing async signal loading via `AsyncLoadedSignal`.
- Backend is exclusively pyrox; pylibfst support is deprecated and should not be used for new features.
- Signals are loaded asynchronously using `get_async_signal(var: Var)` which returns an `AsyncLoadedSignal` with loading state and completion signals.
- The `Var` wrapper (from `waveform_db.py`) provides a uniform interface over raw `SignalHandle` and hierarchical path strings.
- When modifying pyrox, rerun `poetry run build-pyrox` and ensure Cargo manifests remain locked. Do not commit binaries (`.pyd`/`.so`).

## Key Subsystems

### Signal Loading (Async API)
- `AsyncLoadedSignal` wraps signal data with loading state (`is_loading`, `is_loaded`, `has_failed`).
- Emits `loading_started`, `loading_completed`, `loading_failed` Qt signals for UI updates.
- `SignalNode` in `data_model.py` holds references to `AsyncLoadedSignal` instances via the `Var` wrapper.
- Rendering code checks `is_loaded` before accessing signal data; shows loading indicators otherwise.

### Event Bus Architecture
- `application/event_bus.py` provides centralized pub/sub for cross-widget coordination.
- `application/events.py` defines domain events (e.g., `SignalAdded`, `ViewportChanged`, `MarkerCreated`).
- Widgets subscribe to events instead of connecting point-to-point signals.

### Persistence and Sessions
- `persistence.py` handles save/load of complete waveform sessions as JSONC files.
- Saves viewport, signal list, markers, snippets, display formats, and signal colors.
- Aliases are preserved and restored correctly on session load.
- Clock signal designation is saved and restored.

### Snippets System
- Snippets capture reusable signal groups with optional time ranges.
- `snippet_manager.py` coordinates snippet CRUD operations.
- `snippet_browser_widget.py` provides browsing UI with preview and search.
- Snippets stored as JSON files in user-configurable directory (default: `~/.wavescout/snippets`).

## Additional References
- `docs/features/` captures historical plans and implementation notes.
- `pytest.ini` and `mypy.ini` document current test paths and typing configuration.
- `test_inputs/` contains canonical waveform samples (e.g., `swerv1.vcd`, `aubload_wave_timed.fst`, `apb_sim.fst`); reuse these in new tests to avoid bloating the repo.

Stay aligned with these guardrails and surface ambiguities before coding—they usually have historical context captured in the docs directory.
