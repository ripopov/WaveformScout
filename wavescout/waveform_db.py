"""WaveformDB implementation with backend-agnostic design."""

from typing import List, Tuple, Optional, Dict, TYPE_CHECKING, Sequence, Iterable, Any, Union
import time as time_module
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, Signal, QThread, Qt

if TYPE_CHECKING:
    from pyrox import Scope

import pyrox

from pyrox import SignalHandle
import threading
from .data_model import Time, Timescale, TimeUnit
from .application.event_bus import EventBus
from .application.events import SignalLoadingStartedEvent, SignalLoadedEvent, SignalLoadingFailedEvent
from .timing_utils import tprint


class AsyncLoadedSignal:
    """Future-like wrapper for asynchronously loaded signals with efficient blocking."""

    def __init__(self, handle: SignalHandle, waveform_db: 'WaveformDB'):
        self._handle = handle
        self._signal: Optional[pyrox.Signal] = None
        self._loaded = threading.Event()
        self._loading = False
        self._error: Optional[str] = None

        # Fast path: Check if already cached
        if waveform_db.is_signal_cached(handle):
            self._signal = waveform_db._signal_cache[handle]
            self._loaded.set()
        else:
            # Track this AsyncLoadedSignal in the waveform_db
            waveform_db._pending_signals.append(self)
            # Trigger async loading if not already in progress
            if not waveform_db.is_signal_loading(handle):
                waveform_db.load_signals_async([handle])
            self._loading = True

    def is_loaded(self) -> bool:
        """Check if signal is loaded without blocking."""
        return self._loaded.is_set()

    def get_signal_blocking(self, timeout: Optional[float] = None) -> pyrox.Signal:
        """Get signal, blocking until loaded or timeout occurs.

        Args:
            timeout: Maximum time to wait in seconds (default: 30.0)

        Returns:
            The loaded Signal object

        Raises:
            RuntimeError: If signal loading failed
            TimeoutError: If timeout occurred before loading completed
        """
        # Fast path - already loaded
        if self._loaded.is_set():
            if self._error:
                raise RuntimeError(f"Signal {self._handle} loading failed: {self._error}")
            return self._signal  # type: ignore[return-value]

        # Slow path - wait for loading
        timeout = timeout or 30.0

        # Use threading.Event for efficient waiting without CPU spinning
        if self._loaded.wait(timeout):
            if self._error:
                raise RuntimeError(f"Signal {self._handle} loading failed: {self._error}")
            return self._signal  # type: ignore[return-value]

        raise TimeoutError(f"Signal {self._handle} loading timed out after {timeout}s")

    def _update_signal(self, signal: pyrox.Signal) -> None:
        """Called by WaveformDB when signal loads successfully."""
        self._signal = signal
        self._loading = False
        self._loaded.set()

    def _update_error(self, error: str) -> None:
        """Called by WaveformDB when signal loading fails."""
        self._error = error
        self._loading = False
        self._loaded.set()

    @property
    def handle(self) -> SignalHandle:
        """Get the signal handle."""
        return self._handle

    @classmethod
    def placeholder(cls, handle: SignalHandle) -> "AsyncLoadedSignal":
        """Create a placeholder AsyncLoadedSignal for uninitialized nodes."""
        instance = cls.__new__(cls)
        instance._handle = handle
        instance._signal = None
        instance._loaded = threading.Event()
        instance._loading = False
        instance._error = None
        return instance

    def __repr__(self) -> str:
        status = "loaded" if self._loaded.is_set() else "loading" if self._loading else "pending"
        return f"AsyncLoadedSignal(handle={self._handle}, status={status})"


class AsyncEventBridge(QObject):
    """Bridge to safely pass async events from worker threads to main Qt thread."""

    loading_started = Signal(list)  # List of handles
    loaded = Signal(list)  # List of (handle, signal) pairs
    loading_failed = Signal(list, str)  # List of handles, error message

    def __init__(self, event_bus: EventBus):
        super().__init__()
        self._event_bus = event_bus

        # Connect signals to event bus on main thread with queued connections for thread safety
        self.loading_started.connect(self._emit_loading_started, Qt.ConnectionType.QueuedConnection)
        self.loaded.connect(self._emit_loaded, Qt.ConnectionType.QueuedConnection)
        self.loading_failed.connect(self._emit_loading_failed, Qt.ConnectionType.QueuedConnection)

    def _emit_loading_started(self, handles: List[SignalHandle]) -> None:
        """Emit loading started event on main thread."""
        tprint(
            f"[ASYNC_BRIDGE] _emit_loading_started on thread {threading.current_thread().name} with {len(handles)} handles")
        self._event_bus.publish(SignalLoadingStartedEvent(handles=handles))

    def _emit_loaded(self, pairs: List[Tuple[SignalHandle, pyrox.Signal]]) -> None:
        """Emit loaded event on main thread."""
        tprint(f"[ASYNC_BRIDGE] _emit_loaded on thread {threading.current_thread().name} with {len(pairs)} pairs")
        self._event_bus.publish(SignalLoadedEvent(pairs=pairs))

    def _emit_loading_failed(self, handles: List[SignalHandle], error: str) -> None:
        """Emit loading failed event on main thread."""
        tprint(
            f"[ASYNC_BRIDGE] _emit_loading_failed on thread {threading.current_thread().name} with {len(handles)} handles, error: {error}")
        self._event_bus.publish(SignalLoadingFailedEvent(handles=handles, error=error))

class WaveformDB:
    """Waveform database with backend-agnostic design for reading VCD/FST files."""

    def __init__(self, event_bus: Optional[EventBus] = None) -> None:
        self.waveform: Optional[pyrox.Waveform] = None
        self.hierarchy: Optional[pyrox.Hierarchy] = None
        self.uri: Optional[str] = None
        self._timescale: Optional[Timescale] = None  # Store parsed timescale
        self._signal_cache: Dict[SignalHandle, pyrox.Signal] = {}  # Python-side cache
        self._loading_handles: set[SignalHandle] = set()  # Track handles being loaded
        self._event_bus = event_bus  # Event bus for async notifications
        self._event_bridge: Optional[AsyncEventBridge] = None  # Qt signal bridge for thread safety
        self._pending_signals: List[AsyncLoadedSignal] = []  # Track AsyncLoadedSignal instances waiting for loading

        # Create event bridge if event bus is provided
        if self._event_bus:
            self._event_bridge = AsyncEventBridge(self._event_bus)

    @property
    def file_path(self) -> Optional[str]:
        """Get the file path of the opened waveform."""
        return self.uri


    def open(self, uri: str) -> None:
        """Open a waveform file using the configured backend."""
        import time
        import os

        start_time = time.time()
        self.uri = uri
        # Clear the signal cache and loading state when opening a new file
        self._signal_cache.clear()
        self._loading_handles.clear()

        # Get file size for reporting
        file_size = os.path.getsize(uri)
        file_size_mb = file_size / (1024 * 1024)
        file_name = os.path.basename(uri)

        tprint(f"Loading {file_name} ({file_size_mb:.1f} MB)...")

        # Load waveform using pyrox
        load_start = time.time()
        self.waveform = pyrox.Waveform(uri)
        self.hierarchy = self.waveform.hierarchy
        load_end = time.time()

        tprint(f"  - Waveform loaded in {load_end - load_start:.2f} seconds")

        # Register async callback if event bus is available
        if self._event_bus and self.waveform:
            self.waveform.set_async_callback(self._on_async_event)

        # Extract and store timescale
        self._extract_timescale()

        # No more mapping construction - everything is queried on-demand
        total_time = time.time() - start_time
        tprint(f"  - Total load time: {total_time:.2f} seconds")

    def top_signals(self) -> List[SignalHandle]:
        """Get handles for top-level signals."""
        if not self.waveform or not self.hierarchy:
            return []

        refs = []
        hierarchy = self.hierarchy  # Local variable for type checker
        assert hierarchy is not None  # We already checked this above

        # Get variables from all top scopes recursively
        def collect_vars_recursive(scope: Scope) -> None:
            # Add direct variables
            for var in scope.vars(hierarchy):
                signal_ref = var.signal_handle()
                if signal_ref not in refs:
                    refs.append(signal_ref)
            # Recurse into child scopes
            for child_scope in scope.scopes(hierarchy):
                collect_vars_recursive(child_scope)

        for scope in hierarchy.top_scopes():
            collect_vars_recursive(scope)

        return refs[:10]  # Return first 10 for testing

    def transitions(self, handle: SignalHandle, t0: Time, t1: Time) -> List[Tuple[Time, str]]:
        """Get signal transitions in time range."""
        # Use the new async API
        async_signal = self.load_signal(handle)
        if not async_signal.is_loaded():
            try:
                signal = async_signal.get_signal_blocking(timeout=5.0)
            except (RuntimeError, TimeoutError):
                return []
        else:
            signal = async_signal.get_signal_blocking()

        if not signal:
            return []

        transitions = []
        for change_time, value in signal.all_changes():
            if t0 <= change_time <= t1:
                transitions.append((change_time, str(value)))

        return transitions

    def close(self) -> None:
        """Close the waveform file."""
        # Clear async callback before closing
        if self.waveform:
            self.waveform.set_async_callback(None)

        self.waveform = None
        self.hierarchy = None
        self._signal_cache.clear()
        self._loading_handles.clear()
        self._timescale = None

    def _extract_timescale(self) -> None:
        """Extract timescale from the hierarchy."""
        if not self.hierarchy:
            return

        backend_timescale = self.hierarchy.timescale()
        if backend_timescale:
            # Import our TimeUnit and Timescale classes
            from .data_model import TimeUnit, Timescale

            # Backend's Timescale has unit and factor attributes
            # but we need to access them carefully to satisfy the type checker
            try:
                # Try to get unit and factor attributes
                unit_str = str(getattr(backend_timescale, 'unit', ''))
                factor = getattr(backend_timescale, 'factor', 1)

                time_unit = TimeUnit.from_string(unit_str)
                if time_unit:
                    self._timescale = Timescale(
                        factor=int(factor),
                        unit=time_unit
                    )
            except (AttributeError, TypeError):
                # If attributes don't exist or conversion fails, skip
                pass

    def get_timescale(self) -> Optional[Timescale]:
        """Get the timescale of the waveform file."""
        return self._timescale

    def get_metadata(self) -> Dict[str, Optional[object]]:
        """Get metadata about the waveform file."""
        if not self.hierarchy:
            return {}

        return {
            'date': self.hierarchy.date(),
            'version': self.hierarchy.version(),
            'file_format': self.hierarchy.file_format(),
            'timescale': self._timescale
        }

    def num_vars(self) -> int:
        """Get total number of unique variables (counting all aliases)."""
        if not self.hierarchy:
            return 0
        # Count all variables in hierarchy
        count = 0
        for var in self.hierarchy.all_vars():
            count += 1
        return count

    def get_var(self, handle: SignalHandle) -> Optional[pyrox.Var]:
        """Get variable by handle. Returns pyrox Var object."""
        if not self.hierarchy:
            return None
        # Use the new Rust method to get var by signal ref
        return self.hierarchy.get_var_by_signal_ref(handle)  # type: ignore[attr-defined, no-any-return]


    def get_time_table(self) -> Optional[pyrox.TimeTable]:
        """Get the time table from the waveform. Returns pyrox TimeTable object."""
        if self.waveform:
            return self.waveform.time_table
        return None

    def var_from_handle(self, handle: SignalHandle) -> Optional[pyrox.Var]:
        """Get the variable object for the given handle.

        Returns the first variable if there are aliases.
        """
        return self.get_var(handle)

    # Public APIs for accessing protected members

    def get_all_handles(self) -> List[SignalHandle]:
        """Get all handle IDs in the database."""
        if not self.hierarchy:
            return []
        # Get unique signal refs from all vars
        refs = set()
        for var in self.hierarchy.all_vars():
            refs.add(var.signal_handle())
        return list(refs)


    def find_handle_by_name(self, name: str) -> Optional[SignalHandle]:
        """Find handle by variable name.

        Args:
            name: Variable name to search for (full hierarchical name)

        Returns:
            Handle ID if found, None otherwise
        """
        if not self.hierarchy:
            return None
        # Use the new Rust method to find var by full name
        var = self.hierarchy.find_var_by_full_name(name)  # type: ignore[attr-defined]
        if var:
            return var.signal_handle()  # type: ignore[no-any-return]
        return None

    def clear_signal_cache(self) -> None:
        """Clear the signal cache. Primarily for testing.

        Note: Caching is now handled in Python.
        """
        self._signal_cache.clear()

    def is_signal_cached(self, handle: SignalHandle) -> bool:
        """Check if signal is cached for the given handle.

        Used in tests to verify caching behavior.

        Args:
            handle: Handle ID to check

        Returns:
            True if signal is cached, False otherwise
        """
        return handle in self._signal_cache

    def iter_handles_and_vars(self) -> List[Tuple[int, List[pyrox.Var]]]:
        """Iterate over all handles and their associated variables.

        Returns:
            List of tuples (handle, vars_list)
        """
        if not self.hierarchy:
            return []
        # Group vars by signal ref
        handle_to_vars: Dict[int, List[pyrox.Var]] = {}
        for var in self.hierarchy.all_vars():
            ref = var.signal_handle()
            if ref not in handle_to_vars:
                handle_to_vars[ref] = []
            handle_to_vars[ref].append(var)
        return list(handle_to_vars.items())

    def find_handle_by_path(self, path: str) -> Optional[SignalHandle]:
        """Find handle by hierarchical path.

        First tries to find by exact name. If not found and path doesn't
        contain a dot, tries with 'TOP.' prefix.

        Args:
            path: Signal path (e.g., "signal" or "TOP.module.signal")

        Returns:
            Handle ID if found, None otherwise
        """
        # First try exact match
        handle = self.find_handle_by_name(path)
        if handle is not None:
            return handle

        # If not found and no dot in path, try with TOP prefix
        if '.' not in path:
            return self.find_handle_by_name(f"TOP.{path}")

        return None


    # Async loading methods

    def _on_async_event(self, event: Any) -> None:
        """Handle async events from pyrox backend.

        This callback is invoked from worker threads, so we need to be
        thread-safe and post events to the Qt thread when updating UI.
        """
        tprint(f"[WAVEFORM_DB] _on_async_event called from thread {threading.current_thread().name}")
        tprint(f"[WAVEFORM_DB] Event: {event}")

        if not self._event_bridge:
            tprint("[WAVEFORM_DB] No event bridge, returning")
            return

        event_type = event.get("type")
        tprint(f"[WAVEFORM_DB] Event type: {event_type}")

        if event_type == "SignalStartLoad":
            # Track handles being loaded
            handles = event.get("handles", [])
            tprint(f"[WAVEFORM_DB] SignalStartLoad: {len(handles)} handles")
            self._loading_handles.update(handles)
            # Emit via Qt signal (thread-safe)
            tprint("[WAVEFORM_DB] Emitting loading_started signal")
            self._event_bridge.loading_started.emit(handles)

        elif event_type == "SignalLoaded":
            # Process loaded signals
            signals_data = event.get("signals", [])
            tprint(f"[WAVEFORM_DB] SignalLoaded: {len(signals_data)} signals")
            loaded_pairs = []

            for handle, signal in signals_data:
                tprint(f"[WAVEFORM_DB] Caching signal for handle {handle}")
                # Update Python cache
                self._signal_cache[handle] = signal
                # Remove from loading set
                self._loading_handles.discard(handle)
                loaded_pairs.append((handle, signal))

                # NEW: Update pending AsyncLoadedSignal objects
                for async_signal in self._pending_signals[:]:
                    if async_signal.handle == handle:
                        async_signal._update_signal(signal)
                        self._pending_signals.remove(async_signal)

            # Emit via Qt signal (thread-safe)
            if loaded_pairs:
                tprint(f"[WAVEFORM_DB] Emitting loaded signal with {len(loaded_pairs)} pairs")
                self._event_bridge.loaded.emit(loaded_pairs)

        elif event_type == "Error":
            # Handle loading errors
            error_msg = event.get("error", "Unknown error")
            # Clear all loading handles on error
            failed_handles = list(self._loading_handles)
            self._loading_handles.clear()

            # NEW: Update pending AsyncLoadedSignal objects with error
            for handle in failed_handles:
                for async_signal in self._pending_signals[:]:
                    if async_signal.handle == handle:
                        async_signal._update_error(error_msg)
                        self._pending_signals.remove(async_signal)

            if failed_handles:
                self._event_bridge.loading_failed.emit(failed_handles, error_msg)

    def load_signals_async(self, handles: Sequence[SignalHandle]) -> None:
        """Load signals asynchronously using pyrox backend.

        Args:
            handles: Sequence of signal handles to load
        """
        tprint(f"[WAVEFORM_DB] load_signals_async called with {len(handles)} handles")
        if not self.waveform:
            tprint("[WAVEFORM_DB] No waveform, returning")
            return

        # Filter out already cached and currently loading signals
        handles_to_load = [
            h for h in handles
            if h not in self._signal_cache and h not in self._loading_handles
        ]

        tprint(f"[WAVEFORM_DB] After filtering: {len(handles_to_load)} handles need loading")
        tprint(f"[WAVEFORM_DB] Cached: {len(self._signal_cache)}, Loading: {len(self._loading_handles)}")

        if not handles_to_load:
            # All signals are either cached or being loaded
            tprint("[WAVEFORM_DB] All signals cached or loading, returning")
            return

        # Mark handles as loading
        self._loading_handles.update(handles_to_load)
        tprint(f"[WAVEFORM_DB] Marked {len(handles_to_load)} handles as loading")

        # Trigger async load via pyrox
        tprint("[WAVEFORM_DB] Calling pyrox load_signals_async")
        self.waveform.load_signals_async(list(handles_to_load))

    def is_signal_loading(self, handle: SignalHandle) -> bool:
        """Check if a signal is currently being loaded.

        Args:
            handle: Signal handle to check

        Returns:
            True if signal is being loaded, False otherwise
        """
        return handle in self._loading_handles

    def pending_signal_count(self) -> int:
        """Get count of signals currently being loaded.

        Returns:
            Number of signals in loading state
        """
        return len(self._loading_handles)

    def wait_for_signals(self, handles: Iterable[SignalHandle], timeout: float = 5.0) -> bool:
        """Wait for specific signals to finish loading (for testing).

        Args:
            handles: Handles to wait for
            timeout: Maximum time to wait in seconds

        Returns:
            True if all signals loaded, False if timeout reached
        """
        start_time = time_module.perf_counter()
        handles_set = set(handles)

        while time_module.perf_counter() - start_time < timeout:
            # Check if all requested handles are loaded
            if all(h in self._signal_cache or h not in self._loading_handles
                   for h in handles_set):
                return True

            # Process Qt events to allow async callbacks
            if QApplication.instance():
                QApplication.processEvents()

            # Small sleep to avoid busy waiting
            time_module.sleep(0.01)

        return False

    def load_signal(self, handle: SignalHandle) -> AsyncLoadedSignal:
        """Load a signal asynchronously, returning an AsyncLoadedSignal wrapper.

        This is the new unified API for signal loading that eliminates race conditions
        and provides future-like semantics.
        """
        async_signal = AsyncLoadedSignal(handle, self)
        # Note: AsyncLoadedSignal constructor already handles tracking in _pending_signals
        return async_signal
