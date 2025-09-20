"""WaveformDB implementation with backend-agnostic design."""

from __future__ import annotations
from typing import List, Tuple, Optional, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from pyrox import Scope
from pathlib import Path
import threading

import pyrox

from pyrox import SignalHandle

from .data_model import Time, Timescale, TimeUnit


class WaveformDB:
    """Waveform database with backend-agnostic design for reading VCD/FST files."""

    def __init__(self) -> None:
        self.waveform: Optional[pyrox.Waveform] = None
        self.hierarchy: Optional[pyrox.Hierarchy] = None
        self.uri: Optional[str] = None
        self._signal_cache: Dict[SignalHandle, pyrox.Signal] = {}  # Cache loaded signals
        self._timescale: Optional[Timescale] = None  # Store parsed timescale

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

        # Get file size for reporting
        file_size = os.path.getsize(uri)
        file_size_mb = file_size / (1024 * 1024)
        file_name = os.path.basename(uri)

        print(f"Loading {file_name} ({file_size_mb:.1f} MB)...")

        # Load waveform using pyrox
        load_start = time.time()
        self.waveform = pyrox.Waveform(uri)
        self.hierarchy = self.waveform.hierarchy
        load_end = time.time()

        print(f"  - Waveform loaded in {load_end - load_start:.2f} seconds")

        # Extract and store timescale
        self._extract_timescale()

        # No more mapping construction - everything is queried on-demand
        total_time = time.time() - start_time
        print(f"  - Total load time: {total_time:.2f} seconds")

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
                signal_ref = var.signal_ref()
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
        signal = self.get_signal(handle)
        if not signal:
            return []

        transitions = []
        for change_time, value in signal.all_changes():
            if t0 <= change_time <= t1:
                transitions.append((change_time, str(value)))

        return transitions

    def sample(self, handle: SignalHandle, t: Time) -> str:
        """Get signal value at specific time."""
        signal = self.get_signal(handle)
        if not signal:
            return ""

        # Use query_signal for efficient lookup
        query_result = signal.query_signal(max(0, t))
        if query_result.value is not None:
            return str(query_result.value)

        return ""

    def sample_with_next_change(self, handle: SignalHandle, t: Time) -> Tuple[str, Optional[Time]]:
        """Get signal value at specific time and the time of next change.

        Returns:
            Tuple of (value_string, next_change_time)
            next_change_time is None if there are no more changes
        """
        signal = self.get_signal(handle)
        if not signal:
            return ("", None)

        # Use query_signal for efficient lookup
        query_result = signal.query_signal(max(0, t))

        value_str = ""
        if query_result.value is not None:
            value_str = str(query_result.value)

        return (value_str, query_result.next_time)

    def close(self) -> None:
        """Close the waveform file."""
        self.waveform = None
        self.hierarchy = None
        self._signal_cache.clear()
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

    def get_all_vars_for_handle(self, handle: SignalHandle) -> List[pyrox.Var]:
        """Get all variables (including aliases) for a handle."""
        if not self.hierarchy:
            return []
        # Use the new Rust method to get all vars for signal ref
        return self.hierarchy.get_all_vars_by_signal_ref(handle)  # type: ignore[attr-defined, no-any-return]

    def get_time_table(self) -> Optional[pyrox.TimeTable]:
        """Get the time table from the waveform. Returns pyrox TimeTable object."""
        if self.waveform:
            return self.waveform.time_table
        return None

    def get_signal(self, handle: SignalHandle) -> Optional[pyrox.Signal]:
        """Get the signal object for the given handle. Returns pyrox Signal object.

        This method implements lazy loading - signals are only loaded when first requested.
        """
        # Get the first variable for this handle (all aliases have same signal)
        var = self.get_var(handle)
        if not var:
            return None

        # Load signal lazily if not cached
        if handle not in self._signal_cache:
            if self.waveform is not None:
                signal = self.waveform.get_signal(var)
                if signal is not None:
                    self._signal_cache[handle] = signal

        return self._signal_cache.get(handle)

    def var_from_handle(self, handle: SignalHandle) -> Optional[pyrox.Var]:
        """Get the variable object for the given handle.

        Returns the first variable if there are aliases.
        """
        return self.get_var(handle)

    def signal_from_handle(self, handle: SignalHandle) -> Optional[pyrox.Signal]:
        """Get the signal object for the given handle.

        This is an alias for get_signal() for consistency with var_from_handle().
        """
        return self.get_signal(handle)

    def are_signals_cached(self, handles: List[SignalHandle]) -> bool:
        """Check if all specified signals are already cached.

        Args:
            handles: List of signal handles to check

        Returns:
            True if all signals are cached, False otherwise
        """
        return all(handle in self._signal_cache for handle in handles)

    def preload_signals(self, handles: List[SignalHandle], multithreaded: bool = False) -> None:
        """Preload multiple signals using efficient batch loading.

        Loading a group of signals is more efficient than loading each signal individually,
        because we only need to scan the file once and collect all changes for listed signals.

        Args:
            handles: List of signal handles to preload
            multithreaded: Whether to use multiple threads for loading (default: False)
        """
        import time

        if not self.waveform or not self.hierarchy:
            return

        start_time = time.perf_counter()

        # Deduplicate handles first to avoid loading the same signal multiple times
        # This is important when the same handle appears multiple times in the input
        # (e.g., when multiple nodes reference the same signal as aliases)
        unique_handles = []
        seen = set()
        for h in handles:
            if h not in seen:
                unique_handles.append(h)
                seen.add(h)

        # Filter out already cached signals
        handles_to_load = [
            h for h in unique_handles
            if h not in self._signal_cache
        ]

        if not handles_to_load:
            # All signals already cached
            elapsed = time.perf_counter() - start_time
            print(f"preload_signals: {len(unique_handles)} signals already cached (took {elapsed:.3f}s)")
            return

        # Convert handles to Var objects
        vars_to_load : List[pyrox.Var] = []
        handle_to_var_map = {}
        for handle in handles_to_load:
            var = self.get_var(handle)
            if var:
                vars_to_load.append(var)
                handle_to_var_map[id(var)] = handle

        if not vars_to_load:
            elapsed = time.perf_counter() - start_time
            print(f"preload_signals: No valid signals to load (took {elapsed:.3f}s)")
            return

        # Batch load signals using pyrox API
        try:
            load_start = time.perf_counter()
            if multithreaded:
                loaded_signals = self.waveform.load_signals_multithreaded(vars_to_load)
            else:
                loaded_signals = self.waveform.load_signals(vars_to_load)
            load_time = time.perf_counter() - load_start

            # Cache the loaded signals
            cache_start = time.perf_counter()
            cached_count = 0
            for var, signal in zip(vars_to_load, loaded_signals):
                handle_or_none = handle_to_var_map.get(id(var))
                if handle_or_none is not None and signal is not None:
                    self._signal_cache[handle_or_none] = signal
                    cached_count += 1
            cache_time = time.perf_counter() - cache_start

            total_time = time.perf_counter() - start_time
            already_cached = len(unique_handles) - len(handles_to_load)

            print(f"preload_signals: Loaded {cached_count} new signals, {already_cached} already cached")
            print(f"  - Pyrox loading: {load_time:.3f}s")
            print(f"  - Cache storage: {cache_time:.3f}s")
            print(f"  - Total time: {total_time:.3f}s")
            if multithreaded:
                print(f"  - Mode: multithreaded")

        except Exception as e:
            elapsed = time.perf_counter() - start_time
            print(f"preload_signals: Failed after {elapsed:.3f}s - {str(e)}")
            # Re-raise the exception to be handled by the caller
            raise RuntimeError(f"Failed to load signals: {str(e)}")

    # Public APIs for accessing protected members

    def get_all_handles(self) -> List[SignalHandle]:
        """Get all handle IDs in the database."""
        if not self.hierarchy:
            return []
        # Get unique signal refs from all vars
        refs = set()
        for var in self.hierarchy.all_vars():
            refs.add(var.signal_ref())
        return list(refs)

    def get_handle_for_var(self, var: pyrox.Var) -> Optional[SignalHandle]:
        """Get handle for a specific variable object.

        Args:
            var: Pyrox variable object

        Returns:
            Handle ID if found, None otherwise
        """
        # SignalHandle is just the signal_ref() value
        return var.signal_ref()

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
            return var.signal_ref()  # type: ignore[no-any-return]
        return None

    def get_var_to_handle_mapping(self) -> Dict[pyrox.Var, int]:
        """Get complete variable-to-handle mapping.

        Returns:
            Dictionary mapping pyrox variable objects to handle IDs
        """
        if not self.hierarchy:
            return {}
        var_to_handle = {}
        for var in self.hierarchy.all_vars():
            var_to_handle[var] = var.signal_ref()
        return var_to_handle

    def get_next_available_handle(self) -> int:
        """Get the next available handle ID."""
        if not self.hierarchy:
            return 0
        # Count unique signal refs
        refs = set()
        for var in self.hierarchy.all_vars():
            refs.add(var.signal_ref())
        return len(refs)

    def clear_signal_cache(self) -> None:
        """Clear the signal cache. Primarily for testing."""
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
            ref = var.signal_ref()
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

    def get_var_bitwidth(self, handle: SignalHandle) -> int:
        """Get bit width for a signal.

        Args:
            handle: Signal handle

        Returns:
            Bit width of the signal (defaults to 32 if unknown)
        """
        var = self.get_var(handle)
        if var:
            width = var.bitwidth()
            if width is not None:
                return int(width)
        return 32  # Default bit width
