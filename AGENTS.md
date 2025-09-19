# WaveformScout Agent Guide

This playbook aligns CLAUDE, Junie, Codex, and other coding agents on the current WaveformScout codebase so changes stay accurate and intentional.

**IF YOU ARE DEVELOPING ON WINDOWS, RUN EVERY COMMAND FROM POWERSHELL. DO NOT USE BASH.**

## Current Architecture Snapshot
- PySide6/Qt6 front-end renders the waveform viewer and supporting tools (snippets, markers, analysis panes).
- Python orchestrates state via dataclasses and protocols (`wavescout/data_model.py`, `wavescout/protocols.py`).
- Rust extensions provide fast waveform access:
  - `pyrox` (PyO3 bindings for the Wellen core) handles VCD and FST ingest.
  - `pylibfst` supplies an alternative FST backend with a pywellen-compatible API.
- Backend selection is coordinated through `wavescout/backends` and the `BackendFactory` in `wavescout/backends/base.py`.

## Directory Orientation
- `wavescout/` — main application package. Key areas include:
  - `application/` (event bus & domain events for cross-widget coordination)
  - `backends/` (pyrox & pylibfst adapters plus typed backend contracts)
  - `config.py`, `theme.py`, `color_utils.py` (UI customization and theming)
  - `data_model.py`, `waveform_item_model.py`, `waveform_controller.py` (core state & Qt models)
  - `wave_scout_widget.py`, `waveform_canvas.py`, `signal_renderer.py` (main widget & rendering pipeline)
  - `snippet_*`, `markers_window.py`, `analysis_engine.py` (workflow-specific tooling)
- `pyrox/` — Rust crate + maturin project that exposes the high-performance waveform API (`build-pyrox`).
- `pylibfst/` — Rust crate that wraps the bundled `libfst` sources (`build-pylibfst`).
- `libfst/` — vendored FST C implementation leveraged by `pylibfst` (with its own tests and PowerShell helpers).
- `scripts/` — build helpers for pyrox and pylibfst (Linux/macOS plus Windows fallbacks).
- `tests/` — pytest + pytest-qt suite (uses `test_inputs/` waveforms for integration coverage).
- `docs/` — feature plans and technical notes (search here before inventing new patterns).
- `take_snapshot.py` — utility to capture GUI snapshots during development.
- `setup_env.ps1` — initializes the MSVC developer environment required to build Rust/PyO3 on Windows.

## Toolchain & Environment
- Python ≥ 3.12 managed by Poetry (local `.venv`).
- Rust toolchain with `maturin` to build PyO3 extensions.
- PySide6 6.9.x, NumPy 2.x, RapidFuzz, QDarkStyle, and PySideSix-Frameless-Window for the UI.
- Make is used as the primary command runner (`Makefile` normalizes Windows vs. POSIX flows).

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
- When touching Rust backends, run the relevant integration tests (`tests/test_backend_compat.py`, `tests/test_dual_fst_backend.py`, `tests/test_fst_loading.py`).

## Coding Standards
- Preserve DRY and Single Responsibility principles; prefer shared helpers in `wavescout/` over duplicating logic in widgets.
- Follow repository style (PEP 8 leaning, explicit imports, module-level `__all__` where appropriate).
- Qt widgets should derive from the existing base classes and plug into the event bus where possible instead of emitting ad-hoc signals.

### Strict Typing Expectations
1. Do not introduce `Any`; use precise protocols or concrete types from `wavescout.backend_types` and `wavescout.protocols`.
2. Use `TypedDict`, `Protocol`, and `TypeAlias` for structured data instead of loose dicts.
3. Annotate every parameter and return type; express optionality explicitly with `Optional[T]`.
4. Prefer domain-specific aliases (`SignalHandle`, `Timescale`, etc.) over primitive types in signatures.
5. Keep unions narrow—consider protocols or dataclasses before widening types.

### Initialization Contracts
- Initialize every attribute in `__init__` (set to `None` or a default) and avoid `hasattr`/`delattr` in production code.
- Use lifecycle flags (`self._initialized`, `self._ui_ready`) instead of probing for attributes.
- For transient bundles of state, prefer dataclasses or small `NamedTuple`s declared next to their usage.

## Backend & Data Flow Guidance
- `WaveformDB` implements `WaveformDBProtocol` and mediates access to backend signals; keep protocol definitions in sync with backend adapters.
- `BackendFactory` should be updated whenever new formats or backends are introduced; ensure `supports_file_format` handles file extensions consistently.
- Pyrox is the default for VCD (and primary FST) support; pylibfst remains available for compatibility and dual-backend testing. Update both when changing waveform abstractions.
- When modifying Rust crates, rerun `poetry run build-pyrox` / `poetry run build-pylibfst` and keep Cargo manifests locked. Commit generated `.pyd`/`.so` binaries **only** if the project already tracks them.

## Additional References
- `docs/features/` captures historical plans (e.g., pyrox migration, dual FST backend) and is useful for understanding intent before altering implementations.
- `pytest.ini` and `mypy.ini` document current test paths and typing exceptions—review before tweaking test discovery or type ignores.
- `test_inputs/` contains canonical waveform samples (e.g., `swerv1.vcd`, `vicuna.fst`); reuse these in new tests to avoid bloating the repo.

Stay aligned with these guardrails and surface ambiguities before coding—they usually have historical context captured in the docs directory.
