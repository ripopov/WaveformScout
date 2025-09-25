# Async Signal Loading Implementation Plan

## Executive Summary
WaveScout currently blocks the UI on every signal addition because `WaveformDB.get_signal()` performs synchronous I/O on the GUI thread. Pyrox now exposes an event-driven `load_signals_async()` API backed by background workers; this plan captures the application-side refactor needed to consume that API. We will wire WaveScout to fire-and-forget signal requests, hydrate `SignalNodeSignal` instances once the backend delivers `SignalLoaded` events, and keep the UI responsive while signals materialize.

## 1. Goals and Usage Scenarios

### 1.1 Product Objectives
- Prevent any GUI stalls when users double-click a variable, paste nodes, restore sessions, or instantiate snippets.
- Present signal nodes instantly in the tree while marking their rows as "Loading" until data arrives.
- Re-render affected rows the moment the backend publishes `SignalLoaded` without forcing a full tree rebuild.
- Preserve deterministic behaviour for tests by offering a blocking helper that drains the async queue during assertions.

### 1.2 Entry Points To Convert
All code paths that currently call `WaveformDB.get_signal()` proactively must migrate to the async flow:
- `DesignTreeView._create_signal_node()` and `_emit_signal_nodes_from_variables()` (`wavescout/design_tree_view.py`) for double-click, multi-select, and keyboard shortcuts.
- Session restoration in `_deserialize_node()` and `_resolve_signal_handles()` (`wavescout/persistence.py`).
- Clipboard paste inside `SignalNamesView._validate_nodes()` (`wavescout/signal_names_view.py`).
- Snippet expansion in `SnippetManager.apply_snippet()` / related dialogs.
- Any helper in `waveform_loader.py` or `WaveformSession` constructors that populates `SignalNodeSignal.signal` eagerly.

## 2. Current Behaviour and Pain Points

### 2.1 UI Thread Blocking
- `DesignTreeView._create_signal_node()` calls `waveform_db.get_signal(handle)` immediately after constructing the node, forcing disk access during double-clicks (`wavescout/design_tree_view.py:207`).
- `scout.py` still routes uncached handles through `_load_signals_async()` which uses a `QThreadPool` runnable but blocks until the worker finishes before inserting nodes (`scout.py:1347`).
- Status feedback depends on a modal `QProgressDialog`, making UX clumsy for small loads.

### 2.2 Persistence and Clipboard
- `_resolve_signal_handles()` re-fetches every signal synchronously when a session is loaded (`wavescout/persistence.py:92`), delaying restoration.
- `SignalNamesView._validate_nodes()` populates `node.signal` with `waveform_db.get_signal()` for pasted content (`wavescout/signal_names_view.py:733`).

### 2.3 Testing Limitations
- Tests assume that after an action the `SignalNodeSignal.signal` field is non-`None` (e.g., clipboard and persistence suites).
- There is no helper to wait for async events, making race-free assertions impossible today.

## 3. Target Architecture

### 3.1 Pyrox Integration Recap
Pyrox already provides `set_async_callback(Callable[[AsyncEvent], None])` and emits `SignalStartLoad` / `SignalLoaded` events via worker threads (`pyrox/pyrox.pyi`). WaveScout must register one callback per `WaveformDB` instance and translate events into application signals.

### 3.2 Application Event Model
Add new dataclasses in `wavescout/application/events.py`:
- `SignalLoadingStartedEvent(handles: list[SignalHandle])` – broadcast when a new batch dispatches.
- `SignalLoadedEvent(pairs: list[tuple[SignalHandle, Signal]])` – payload contains the actual `pyrox.Signal` objects.
- `SignalLoadingFailedEvent(handles: list[SignalHandle], error: str)` – optional failure channel for UI messaging.
These events flow through `EventBus.publish()` so the controller, status bar, and views remain loosely coupled.

### 3.3 WaveformDB Responsibilities (`wavescout/waveform_db.py`)
- Register the async callback in `open()` and clear it in `close()`.
- Maintain `_loading_handles: set[SignalHandle]` to deduplicate requests and guard cache queries.
- Provide `load_signals_async(handles: Sequence[SignalHandle])` that filters out cached or in-flight handles before delegating to `waveform.load_signals_async()`.
- Update the Python cache inside the async callback (`SignalLoadedEvent`) before publishing the application event.
- Expose helpers for higher layers:
  - `is_signal_loading(handle: SignalHandle) -> bool`
  - `pending_signal_count() -> int`
  - `wait_for_signals(handles: Iterable[SignalHandle], timeout: float = 5.0) -> bool` for tests (loops with `time.sleep(0.01)` and `QApplication.processEvents()`).

### 3.4 Session Model and Controller
- Extend `WaveformSession` with `loading_handles: set[SignalHandle]` and convenience queries (e.g., `is_loading(handle)`).
- Update `WaveformController.__init__` to subscribe to `SignalLoadingStartedEvent` / `SignalLoadedEvent`:
  - `SignalLoadingStartedEvent` → add handles to the session's loading set, call status callbacks, and request a canvas repaint for placeholders.
  - `SignalLoadedEvent` → update all `SignalNodeSignal` instances sharing a handle, clear the loading flag, and trigger layout/model notifications.
- Provide controller hooks for the status bar (`scout.py`) to display progress like "Loading 3 signals..." and "Signals ready" once events arrive.

### 3.5 SignalNode Construction
- `create_signal_node_from_var()` returns nodes with `signal=None` by default; callers request loads for uncached handles (`wavescout/waveform_loader.py`).
- `DesignTreeView` and `SignalNamesView` insert nodes immediately. If `waveform_db.are_signals_cached()` is true, they fill `node.signal` from cache; otherwise they leave it empty and schedule async loading.
- `scout.py` groups all new handles per action and calls `session.waveform_db.load_signals_async()` once.
- `SnippetManager` and persistence flows follow the same pattern: instantiate nodes, stash handles needing data, then fire a single async call at the end of the batch.

### 3.6 UI Feedback
- Waveform tree models should include a lightweight `node.is_loading` property derived from `session.loading_handles` so views repaint without mutating every node.
- `WaveformCanvas` shows a textual placeholder (e.g., "Loading...") when `node.signal is None` during paint (`wavescout/waveform_canvas.py`).
- Tooltips or value inspectors skip missing signals instead of raising errors.

### 3.7 Legacy Compatibility Layer
- Provide `WaveformDB.load_signals_blocking(handles)` used only by legacy tests or scripts; internally call `load_signals_async()` followed by `wait_for_signals(handles)`.
- Deprecate `_load_signals_async()` and the `QThreadPool` runnable once all call sites use the new API.

## 4. Rollout Plan
1. **Infrastructure**: Implement WaveformDB async plumbing, new events, and session/controller tracking without switching call sites yet.
2. **Design Tree & Clipboard**: Convert `DesignTreeView` and `SignalNamesView`, verify UI placeholders render correctly.
3. **Persistence & Snippets**: Update session restore and snippet insertion paths, ensuring handles resolve prior to scheduling loads.
4. **Status & Canvas Polish**: Replace the progress dialog with status bar updates and loading overlays; delete the old `_load_signals_async()` implementation.
5. **Tests & Cleanup**: Add async-aware fixtures, update assertions to tolerate `signal=None` during load, and remove obsolete synchronous helpers.

## 5. Testing & Validation
- **Unit Tests**: Extend `tests/test_async_loading.py` to simulate Python-side subscribers and verify cache updates plus duplicate suppression.
- **Qt/Integration**: Update clipboard (`tests/test_signal_names_view.py`), persistence (`tests/test_persistence.py`), and session restore suites to call `wait_for_signals()` before checking waveforms.
- **Regression**: Run `QT_QPA_PLATFORM=offscreen poetry run pytest tests/` and `make typecheck` to ensure typing changes (new events, session fields) remain strict.
- **Manual QA**: Launch `make dev`, load large VCD/FST files, double-click fast, and confirm the UI never freezes while signals populate row-by-row.

## 6. Risks and Mitigations
- **Event Ordering**: Pyrox may emit multiple `SignalLoaded` batches per request; handle accumulated updates idempotently by iterating returned pairs.
- **Handle Aliases**: Multiple UI nodes may share a handle; always fan out loaded signals to every matching node.
- **Backends Without Async**: Guard `load_signals_async` calls with feature detection and fall back to the existing synchronous loader (logging a warning) when running against legacy backends.
- **Testing Flakiness**: Rely on the new `wait_for_signals()` helper in tests to avoid timing races; keep timeouts generous on CI.
- **UI State Drift**: Ensure controllers clear loading flags if a failure event arrives or when sessions close to avoid stuck "Loading" indicators.

## 7. Success Criteria
- UI responds instantly to signal additions; progress appears in the status bar instead of a modal dialog.
- `SignalNodeSignal.signal` fields remain `None` until the async event arrives, but tests stay stable thanks to the blocking helper.
- Legacy workflows (clipboard, snippets, persistence) continue to function with zero manual refreshes, and no duplicate loads appear in backend logs.
