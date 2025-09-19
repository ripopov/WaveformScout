# Project Guidelines

This document provides an overview of the WaveformScout project and concrete guidelines for 
CLAUDE, Junie, Codex, and other coding agents when making changes.

IF DEVELOPING ON WINDOWS, USE POWERSHELL FOR ALL COMMANDS. DON'T TRY TO USE BASH.

## Overview
- WaveformScout is a PySide6 (Qt6) digital/mixed-signal waveform viewer with a Rust-accelerated backend (Wellen via pywellen) for fast waveform processing.
- Primary goals: performant waveform viewing, clean dataclass-based model layer, and an efficient Qt Model/View bridge.

## Project Structure (high level)
- wavescout/ — main Python package (widgets, models, rendering, canvas, etc.)
- wellen/ — Wellen library submodule with Rust sources and Python bindings (pywellen)
- scout.py — main application entry point
- tests/ — pytest suite
- scripts/ — helper scripts (incl. build_pywellen)
- docs/, README.md — documentation and usage
- Makefile — common developer commands
- pyproject.toml — Poetry configuration
- pytest.ini, mypy.ini — testing and type-checking settings

For a detailed tree, see the Project Structure section in README.md.

## Key Dependencies
- Poetry  (uses in-project virtualenv .venv)
- Python 3.12
- PySide6 (Qt6 for Python)
- pywellen (Python bindings for Wellen waveform library)
- Rust toolchain (for building pywellen)

## Important Commands

### Initial Setup

#### Windows Setup
MSVC 2022, Rust, Python 3.12, and Poetry must be installed.
```powershell
# Open PowerShell and navigate to project directory
cd <path-to-WaveScout>

# Setup Visual Studio development environment (required for Windows)
. .\setup_env.ps1

# Install dependencies and build extensions
make install

# Run the application
make dev
```

#### Linux/macOS Setup
```bash
# Install dependencies and build pywellen
# This creates a local .venv in the project directory
make install

# Or manually:
poetry config virtualenvs.in-project true
poetry install
poetry run build-pywellen
```

## Running
- Demo application: make dev
  - Equivalent: poetry run python scout.py

### Virtual Environment
The project uses Poetry with a local virtual environment (.venv) in the project directory.
This ensures all dependencies are isolated and makes the project portable.

To activate the virtual environment:
```bash
# Linux/macOS - Direct activation (recommended)
source .venv/bin/activate

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# Or use Poetry's env activate command (all platforms)
poetry env activate

# All poetry commands automatically use the virtual environment
poetry run python scout.py
poetry run pytest
```

### Building
```bash
# Build pywellen only
poetry run build-pywellen

# Build pylibfst (FST support)
poetry run build-pylibfst

# Build entire project
make build
```

## Tests
**IMPORTANT: ALWAYS use `QT_QPA_PLATFORM=offscreen` when running tests to ensure they work in headless environments.**

- Run all tests: make test
  - Equivalent: `QT_QPA_PLATFORM=offscreen poetry run pytest tests/ --ignore=wellen/`
- For individual test execution: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_file.py`
- Pytest is configured via pytest.ini with testpaths = tests
- The offscreen QT platform ensures tests can run without a display server, which is essential for CI/CD and remote development

## Type Checking and Linting
- Type checking (strict): make typecheck
  - Equivalent: poetry run mypy wavescout/ --strict --config-file mypy.ini
- mypy.ini includes exceptions for pywellen and specific PySide6 import behaviors.
- There is no separate linter configured in this repo; follow readable, PEP8-ish style and keep type annotations accurate.

## Coding Guidelines

- DRY (Don’t Repeat Yourself) - every piece of knowledge or logic in a system should exist in a single, authoritative
  place, avoiding duplication.
- SRP (Single Responsibility Principle) - class, module, or function should have only one reason to change, i.e., it
  should focus on a single, well-defined responsibility.

### Strict Typing Requirements
This project enforces strict type safety. All code must adhere to these guidelines:

1. **No `Any` types**: Replace all `Any` types with specific type annotations
2. **Use TypedDict**: Define structured dictionaries with `TypedDict` for better type safety
3. **Explicit Optional**: Use `Optional[T]` for nullable values, never implicit `None`
4. **Type all parameters and returns**: Every function must have complete type annotations
5. **Use Union sparingly**: Prefer specific types or protocols over broad unions
6. **Leverage TypeAlias**: Create type aliases for complex types to improve readability
7. **No hasattr in production code**: Never use `hasattr` for checking object attributes (see Initialization Guidelines below)

### Type Annotation Examples
```python
from typing import Optional, TypedDict, Protocol, TypeAlias
from collections.abc import Sequence

# Use TypedDict for structured data
class SignalData(TypedDict):
    name: str
    value: int
    transitions: list[int]

# Use Protocol for interfaces
class Renderable(Protocol):
    def render(self, params: RenderParams) -> None: ...

# Use TypeAlias for complex types
SignalMap: TypeAlias = dict[str, SignalData]

# Avoid Any - be specific
# Bad:  def process(data: Any) -> Any
# Good: def process(data: SignalData) -> ProcessedSignal
```

### MyPy Configuration
The project uses strict mypy checking. Run type checks with:
```bash
make typecheck
```

Expected mypy configuration:
- `strict = true`
- `warn_return_any = true`
- `disallow_any_explicit = true`
- `disallow_untyped_defs = true`

### Qt Type Annotations
For PySide6/Qt types:
- Use specific Qt types: `QWidget`, `QEvent`, `QPaintEvent`, etc.
- Never use `Any` for Qt objects
- Import types from appropriate modules: `from PySide6.QtCore import QEvent`

## Initialization Guidelines

### No hasattr or delattr
**NEVER use `hasattr` for checking object attributes or `delattr` for removing them.** All attributes must be properly initialized in `__init__` methods.

#### Required Patterns

1. **Initialize ALL attributes in __init__** - even if initially None
2. **Use initialization flags** (`self._initialized`) for lifecycle management
3. **Use dataclasses** for complex temporary state instead of dynamic attributes
4. **Set to None** instead of delattr

#### Only Acceptable hasattr Uses
- Test code verifying protocol implementation
- Checking data model objects for optional attributes (e.g., `node.children`)
- Checking third-party objects for optional methods

## Notes
- The pywellen module provides access to VCD/FST waveform files
- Rendering is optimized using Rust-based pixel region generation
