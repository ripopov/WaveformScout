# Detect operating system
ifeq ($(OS),Windows_NT)
    detected_OS := Windows
    SHELL := cmd.exe
    .SHELLFLAGS := /c
    MKDIR := mkdir
    RM := del /q /f
    RMDIR := rmdir /s /q
    NULL := nul
    PATHSEP := \\
else
    detected_OS := $(shell uname -s)
    MKDIR := mkdir -p
    RM := rm -f
    RMDIR := rm -rf
    NULL := /dev/null
    PATHSEP := /
endif

.PHONY: install build clean clean-venv test help compile build-pylibfst

help:  ## Show this help
ifeq ($(detected_OS),Windows)
	@echo Available targets:
	@echo   install      - Install dependencies and build pyrox and pylibfst
	@echo   build        - Build the project
	@echo   build-pylibfst - Build pylibfst Rust extension (includes libfst)
	@echo   clean        - Clean build artifacts
	@echo   clean-venv   - Remove virtual environment
	@echo   test         - Run tests
	@echo   typecheck    - Run mypy type checker
	@echo   dev          - Run the demo application
	@echo   compile      - Compile scout.py into executable
else
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
endif

build-pylibfst:  ## Build pylibfst Rust extension (includes libfst)
	poetry run build-pylibfst

install:  ## Install dependencies and build pyrox and pylibfst
	poetry config virtualenvs.in-project true
	poetry install
	poetry run build-pyrox
	poetry run build-pylibfst

build:  ## Build the project
	poetry run build-pyrox
	poetry run build-pylibfst
	poetry build

clean:  ## Clean build artifacts
ifeq ($(detected_OS),Windows)
	@if exist dist $(RMDIR) dist 2>$(NULL) || echo.
	@if exist build $(RMDIR) build 2>$(NULL) || echo.
	@if exist pyrox$(PATHSEP)target $(RMDIR) pyrox$(PATHSEP)target 2>$(NULL) || echo.
	@if exist pylibfst$(PATHSEP)target $(RMDIR) pylibfst$(PATHSEP)target 2>$(NULL) || echo.
	@for /d /r . %%d in (__pycache__) do @if exist "%%d" $(RMDIR) "%%d" 2>$(NULL) || echo.
	@for /r . %%f in (*.pyc) do @if exist "%%f" $(RM) "%%f" 2>$(NULL) || echo.
	@for /r . %%f in (*.egg-info) do @if exist "%%f" $(RMDIR) "%%f" 2>$(NULL) || echo.
else
	$(RMDIR) dist build *.egg-info 2>$(NULL) || true
	$(RMDIR) pyrox/target 2>$(NULL) || true
	$(RMDIR) pylibfst/target 2>$(NULL) || true
	find . -type d -name __pycache__ -exec $(RMDIR) {} + 2>$(NULL) || true
	find . -type f -name "*.pyc" -delete 2>$(NULL) || true
endif

clean-venv:  ## Remove virtual environment
ifeq ($(detected_OS),Windows)
	@if exist .venv $(RMDIR) .venv 2>$(NULL) || echo.
else
	$(RMDIR) .venv 2>$(NULL) || true
endif

test:  ## Run tests
	QT_QPA_PLATFORM=offscreen poetry run pytest tests/

typecheck:  ## Run mypy type checker (strict mode)
	poetry run mypy wavescout/ --strict --config-file mypy.ini

dev: install  ## Run the demo application
	poetry run python scout.py

compile: install  ## Compile scout.py into executable using Nuitka
ifeq ($(detected_OS),Windows)
	poetry run python -m nuitka --standalone --onefile \
		--enable-plugin=pyside6 \
		--include-package=wavescout \
		--include-package=numpy \
		--include-package=yaml \
		--include-package=rapidfuzz \
		--include-package=qdarkstyle \
		--windows-console-mode=disable \
		--assume-yes-for-downloads \
		--no-progress-bar \
		--output-filename=WaveformScout.exe \
		scout.py
else
	poetry run python -m nuitka --standalone --onefile \
		--enable-plugin=pyside6 \
		--include-package=wavescout \
		--include-package=numpy \
		--include-package=yaml \
		--include-package=rapidfuzz \
		--include-package=qdarkstyle \
		--assume-yes-for-downloads \
		--no-progress-bar \
		--output-filename=WaveformScout \
		scout.py
endif
