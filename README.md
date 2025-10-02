# WaveformScout

PySide6 Digital/Mixed-Signal Waveform Viewer. AI-generated code.

## Overview

WaveformScout is a high-performance waveform viewer built with PySide6 (Qt6) for viewing digital and mixed-signal waveforms from VCD and FST formats. It uses a Rust backend (pyrox, based on the [Wellen library](https://github.com/ekiwi/wellen)) for fast waveform processing and async signal loading.

## Requirements

- Python 3.12+ (up to 3.13)
- Rust toolchain with `maturin` 1.7+ (for building pyrox)
- Poetry (for dependency management)
- Make (command runner)

Once all those tools are installed and in PATH, you can use the provided `Makefile` to manage the project.

## Installation

```bash
# Install dependencies and build pyrox
make install

# Or manually:
poetry config virtualenvs.in-project true
poetry install
poetry run build-pyrox
poetry run build-pylibfst  # legacy support
```

**Windows users:** Run commands from PowerShell and execute `. .\setup_env.ps1` first to initialize the MSVC environment.

## Quick Start

```bash
# Run the demo application
make dev
# or
poetry run python scout.py

# Run tests
make test

# Type checking
make typecheck
```

## Development

The project uses Poetry with a local virtual environment (`.venv`) for dependency isolation:

```bash
# Activate virtual environment (optional, Poetry auto-uses .venv)
source .venv/bin/activate  # Linux/macOS
# .\.venv\Scripts\Activate.ps1  # Windows

# Build pyrox (Rust bindings)
poetry run build-pyrox

# Run tests (always use QT_QPA_PLATFORM=offscreen)
QT_QPA_PLATFORM=offscreen poetry run pytest tests/

# Run type checking
make typecheck
```

## Project Structure

```
WaveformScout/
├── wavescout/                      # Main package
│   ├── application/                # Event bus & domain events
│   ├── core/                       # Core logic (data_model, waveform_db, persistence, etc.)
│   ├── models/                     # Qt models (waveform_item_model, scope_tree_model)
│   ├── widgets/                    # UI components (wave_scout_widget, waveform_canvas, etc.)
│   ├── rendering/                  # Rendering pipeline (signal_renderer, time_grid, etc.)
│   ├── snippets/                   # Snippet system (manager, browser, dialogs)
│   ├── dialogs/                    # Dialog windows
│   └── utils/                      # Utilities (config, theme, timing, etc.)
├── pyrox/                          # Rust extension (PyO3 + Wellen)
│   ├── src/                        # Rust source (lib.rs, convert.rs, etc.)
│   └── Cargo.toml                  # Rust manifest
├── scripts/                        # Build helpers (build_pyrox.py, build_pylibfst.py)
├── tests/                          # pytest + pytest-qt test suite
├── docs/                           # Feature plans and documentation
├── scout.py                        # Main application entry point
└── take_snapshot.py                # GUI snapshot utility
```

## Features

- **High-performance rendering**: Rust-powered waveform backend with async signal loading
- **Multiple file support**: Load and view signals from multiple VCD/FST files simultaneously
- **Rich signal analysis**: Built-in analysis tools, markers, and measurements
- **Snippets**: Save and reuse signal groups with time ranges
- **Session persistence**: Save/load complete viewing sessions as JSONC files
- **Customizable UI**: Dark/light themes, configurable colors, flexible layouts
- **Event-driven architecture**: Centralized event bus for cross-widget coordination

## Documentation

- [Project Guide](CLAUDE.md) - Development guide and conventions for contributors

## License

[License information to be added]