"""WaveformDB implementation with backend-agnostic design."""

from typing import List, Tuple, Optional, Dict, Literal
from pathlib import Path
import threading

from .data_model import Time, SignalHandle, Timescale, TimeUnit
from .backend_types import (
    WWaveform, WVar, WHierarchy, WSignal, WTimeTable, WScope
)
from .backends import BackendFactory, BackendType, WaveformBackend


class WaveformDB:
    """Waveform database with backend-agnostic design for reading VCD/FST files."""
    
    def __init__(self, backend_preference: Optional[Literal["pyrox", "pylibfst"]] = None) -> None:
        self.waveform: Optional[WWaveform] = None
        self.hierarchy: Optional[WHierarchy] = None
        self.uri: Optional[str] = None
        self._var_map: Dict[SignalHandle, List[WVar]] = {}  # Map handles to list of variables (for aliases)
        self._signal_cache: Dict[SignalHandle, WSignal] = {}  # Cache loaded signals
        self._timescale: Optional[Timescale] = None  # Store parsed timescale
        self._var_name_to_handle: Dict[str, SignalHandle] = {}  # Map var full name to handle
        self._signal_ref_to_handle: Dict[int, SignalHandle] = {}  # Map SignalRef to our handle (for O(1) alias detection)
        self._handle_to_signal_ref: Dict[SignalHandle, int] = {}  # Map our handle to SignalRef
        self._backend: Optional[WaveformBackend] = None  # Current backend instance
        self._backend_preference = backend_preference or "pyrox"  # Default to pyrox
        self._current_backend_type: Optional[Literal["pyrox", "pylibfst"]] = None

    @property
    def file_path(self) -> Optional[str]:
        """Get the file path of the opened waveform."""
        return self.uri

    @property
    def backend(self) -> Optional[WaveformBackend]:
        """Get the current backend instance."""
        return self._backend
        
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
        
        # Determine backend based on file type and preference
        path = Path(uri)
        ext = path.suffix.lower()
        
        if ext == '.vcd':
            # VCD files use pyrox
            backend_type = BackendType.PYROX
            self._current_backend_type = "pyrox"
            print("  - Using pyrox backend (VCD file)")
        elif ext == '.fst':
            # FST files use the preferred backend
            if self._backend_preference == "pylibfst":
                backend_type = BackendType.PYLIBFST
                self._current_backend_type = "pylibfst"
                print("  - Using pylibfst backend (FST file, user preference)")
            else:
                # Default to pyrox
                backend_type = BackendType.PYROX
                self._current_backend_type = "pyrox"
                print("  - Using pyrox backend (FST file)")
        else:
            raise ValueError(f"Unsupported file format: {ext}")
        
        # Create backend using factory
        load_start = time.time()
        self._backend = BackendFactory.create_backend(
            file_path=uri,
            backend_type=backend_type
        )
        # Load waveform
        self.waveform = self._backend.load_waveform()
        self.hierarchy = self._backend.get_hierarchy()
        load_end = time.time()
        
        print(f"  - Waveform loaded in {load_end - load_start:.2f} seconds")
        
        # Extract and store timescale
        self._extract_timescale()
        
        # Build variable mapping with lazy loading and alias detection
        mapping_start = time.time()
        handle = 0
        
        # Collect all variables to process
        all_variables = []
        seen_vars = set()
        
        # Only collect if hierarchy exists
        if self.hierarchy is not None:
            # Recursively collect all variables from the hierarchy
            def collect_vars_recursive(scope: WScope) -> None:
                # Add direct variables from this scope
                for var in scope.vars(self.hierarchy):  # type: ignore[arg-type]
                    var_id = id(var)
                    if var_id not in seen_vars:
                        all_variables.append(var)
                        seen_vars.add(var_id)
                # Recurse into child scopes
                for child_scope in scope.scopes(self.hierarchy):  # type: ignore[arg-type]
                    collect_vars_recursive(child_scope)
            
            # Start from all top scopes
            for top_scope in self.hierarchy.top_scopes():
                collect_vars_recursive(top_scope)
        
        # Process variables with alias detection using signal_ref() for O(1) lookups
        for var in all_variables:
            signal_ref = var.signal_ref()
            
            # Check if we've already seen this signal_ref
            if signal_ref in self._signal_ref_to_handle:
                # This is an alias - add to the existing handle's list
                existing_handle = self._signal_ref_to_handle[signal_ref]
                self._var_map[existing_handle].append(var)
                
                # Map var name to handle for lookup
                if self.hierarchy is not None:
                    var_full_name = var.full_name(self.hierarchy)
                    self._var_name_to_handle[var_full_name] = existing_handle
            else:
                # New signal - create new handle
                self._var_map[handle] = [var]
                self._signal_ref_to_handle[signal_ref] = handle
                self._handle_to_signal_ref[handle] = signal_ref
                
                # Map var name to handle for lookup
                if self.hierarchy is not None:
                    var_full_name = var.full_name(self.hierarchy)
                    self._var_name_to_handle[var_full_name] = handle
                handle += 1
        
        mapping_end = time.time()
        total_time = time.time() - start_time
        
        print(f"  - Variable mapping built in {mapping_end - mapping_start:.2f} seconds")
        print(f"  - Total load time: {total_time:.2f} seconds")
        print(f"  - Number of unique signals: {len(self._var_map)}")
        print(f"  - Number of variables: {self.num_vars()}")
            
    def top_signals(self) -> List[SignalHandle]:
        """Get handles for top-level signals."""
        if not self.waveform or not self.hierarchy:
            return []
            
        handles = []
        hierarchy = self.hierarchy  # Local variable for type checker
        assert hierarchy is not None  # We already checked this above
        
        # Get variables from all top scopes recursively
        def collect_vars_recursive(scope: WScope) -> None:
            # Add direct variables
            for var in scope.vars(hierarchy):
                for handle, mapped_vars in self._var_map.items():
                    if var in mapped_vars:
                        handles.append(handle)
                        break
            # Recurse into child scopes
            for child_scope in scope.scopes(hierarchy):
                collect_vars_recursive(child_scope)
        
        for scope in hierarchy.top_scopes():
            collect_vars_recursive(scope)
            
        return handles[:10]  # Return first 10 for testing
        
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
        self._var_map.clear()
        self._signal_cache.clear()
        self._timescale = None
        self._var_name_to_handle.clear()
        self._signal_ref_to_handle.clear()
        self._handle_to_signal_ref.clear()
        self._backend = None
        self._current_backend_type = None
        
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
        total = 0
        for vars_list in self._var_map.values():
            total += len(vars_list)
        return total
        
    def get_var(self, handle: SignalHandle) -> Optional[WVar]:
        """Get variable by handle. Returns backend-agnostic Var object."""
        vars_list = self._var_map.get(handle, [])
        return vars_list[0] if vars_list else None
    
    def get_all_vars_for_handle(self, handle: SignalHandle) -> List[WVar]:
        """Get all variables (including aliases) for a handle."""
        return self._var_map.get(handle, [])
    
    def get_time_table(self) -> Optional[WTimeTable]:
        """Get the time table from the waveform. Returns backend-agnostic TimeTable object."""
        if self.waveform:
            return self.waveform.time_table
        return None
    
    def get_signal(self, handle: SignalHandle) -> Optional[WSignal]:
        """Get the signal object for the given handle. Returns backend-agnostic Signal object.
        
        This method implements lazy loading - signals are only loaded when first requested.
        """
        if handle not in self._var_map:
            return None
            
        # Get the first variable for this handle (all aliases have same signal)
        vars_list = self._var_map[handle]
        if not vars_list:
            return None
        
        # Load signal lazily if not cached
        if handle not in self._signal_cache:
            if self._backend is not None:
                var = vars_list[0]
                signal = self._backend.get_signal(var)
                if signal is not None:
                    self._signal_cache[handle] = signal
            
        return self._signal_cache.get(handle)
    
    def var_from_handle(self, handle: SignalHandle) -> Optional[WVar]:
        """Get the variable object for the given handle.
        
        Returns the first variable if there are aliases.
        """
        if handle not in self._var_map:
            return None
        
        var_list = self._var_map[handle]
        if var_list:
            return var_list[0]
        return None
    
    def signal_from_handle(self, handle: SignalHandle) -> Optional[WSignal]:
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
        
        if not self._backend:
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
        
        # Filter out already cached signals and invalid handles
        handles_to_load = [
            h for h in unique_handles 
            if h not in self._signal_cache and h in self._var_map
        ]
        
        if not handles_to_load:
            # All signals already cached
            elapsed = time.perf_counter() - start_time
            print(f"preload_signals: {len(unique_handles)} signals already cached (took {elapsed:.3f}s)")
            return
            
        # Convert handles to Var objects
        vars_to_load : List[WVar] = []
        handle_to_var_map = {}
        for handle in handles_to_load:
            vars_list = self._var_map.get(handle, [])
            if vars_list:
                var = vars_list[0]  # Use first var for each handle
                vars_to_load.append(var)
                handle_to_var_map[id(var)] = handle
        
        if not vars_to_load:
            elapsed = time.perf_counter() - start_time
            print(f"preload_signals: No valid signals to load (took {elapsed:.3f}s)")
            return
            
        # Batch load signals using backend API
        try:
            load_start = time.perf_counter()
            loaded_signals = self._backend.load_signals(vars_to_load, multithreaded)
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
            print(f"  - Backend loading: {load_time:.3f}s")
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
        return list(self._var_map.keys())
    
    def get_handle_for_var(self, var: WVar) -> Optional[SignalHandle]:
        """Get handle for a specific variable object.
        
        Args:
            var: Backend-agnostic variable object
            
        Returns:
            Handle ID if found, None otherwise
        """
        # Get the full name of the var and look it up
        if self.hierarchy is None:
            return None
        var_full_name = var.full_name(self.hierarchy)
        return self._var_name_to_handle.get(var_full_name)
    
    def find_handle_by_name(self, name: str) -> Optional[SignalHandle]:
        """Find handle by variable name.
        
        Args:
            name: Variable name to search for (full hierarchical name)
            
        Returns:
            Handle ID if found, None otherwise
        """
        return self._var_name_to_handle.get(name)
    
    def get_var_to_handle_mapping(self) -> Dict[WVar, int]:
        """Get complete variable-to-handle mapping.
        
        Returns:
            Dictionary mapping backend-agnostic variable objects to handle IDs
        """
        var_to_handle = {}
        for handle, vars_list in self._var_map.items():
            for var in vars_list:
                var_to_handle[var] = handle
        return var_to_handle
    
    def get_next_available_handle(self) -> int:
        """Get the next available handle ID."""
        return len(self._var_map) if self._var_map else 0
    
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
    
    def iter_handles_and_vars(self) -> List[Tuple[int, List[WVar]]]:
        """Iterate over all handles and their associated variables.
        
        Returns:
            List of tuples (handle, vars_list)
        """
        return list(self._var_map.items())
    
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
        vars_list = self.get_all_vars_for_handle(handle)
        if vars_list:
            width = vars_list[0].bitwidth()
            if width is not None:
                return int(width)
        return 32  # Default bit width
    
    def get_backend_type(self) -> Optional[BackendType]:
        """Get the current backend type.
        
        Returns:
            Current backend type or None if no backend is loaded
        """
        if self._current_backend_type == "pyrox":
            return BackendType.PYROX
        elif self._current_backend_type == "pylibfst":
            return BackendType.PYLIBFST
        else:
            return None
    
    def set_backend_preference(self, backend: Literal["pyrox", "pylibfst"]) -> None:
        """Set the preferred backend for next file load.
        
        Args:
            backend: The backend to use for next file load
        
        Note:
            This preference takes effect only when the next waveform file is loaded.
            VCD files always use pyrox regardless of this setting.
        """
        if backend in ["pyrox", "pylibfst"]:
            self._backend_preference = backend