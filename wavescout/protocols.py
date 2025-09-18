"""Protocol definitions for decoupling UI from WaveformDB implementation."""

from typing import Protocol, Optional, Iterable, Dict, Literal
from collections.abc import Iterable as ABCIterable

# Import backend-agnostic protocol types
from .backend_types import WVar, WHierarchy, WSignal, WWaveform, WTimeTable, WTimescale

# Import our data model types
from .data_model import SignalHandle, Timescale


class WaveformDBProtocol(Protocol):
    """Protocol defining the interface for waveform database implementations.
    
    This protocol ensures clean separation between UI components and database
    internals, providing a typed interface for all waveform operations.
    """
    
    # Required attributes  
    # These are Optional because WaveformDB starts empty before open() is called
    # Components should check if waveform_db itself is None, not these attributes
    waveform: Optional[WWaveform]
    hierarchy: Optional[WHierarchy]
    
    def find_handle_by_path(self, name: str) -> Optional[SignalHandle]:
        """Find signal handle by hierarchical path.
        
        Args:
            name: Full hierarchical path (e.g., "TOP.module.signal")
        
        Returns:
            Signal handle if found, None otherwise
        """
        ...
    
    def find_handle_by_name(self, name: str) -> Optional[SignalHandle]:
        """Find signal handle by exact name.
        
        Args:
            name: Exact signal name
        
        Returns:
            Signal handle if found, None otherwise
        """
        ...
    
    def get_handle_for_var(self, var: WVar) -> Optional[SignalHandle]:
        """Get handle for a specific backend variable.
        
        Args:
            var: Backend-agnostic WVar object
        
        Returns:
            Signal handle if found, None otherwise
        """
        ...
    
    def get_var(self, handle: SignalHandle) -> Optional[WVar]:
        """Get backend variable by handle.
        
        Args:
            handle: Signal handle
        
        Returns:
            First backend WVar object for this handle, None if not found
        """
        ...
    
    def get_all_vars_for_handle(self, handle: SignalHandle) -> list[WVar]:
        """Get all variables (including aliases) for a handle.
        
        Args:
            handle: Signal handle
        
        Returns:
            List of backend WVar objects (may be empty)
        """
        ...
    
    def iter_handles_and_vars(self) -> ABCIterable[tuple[SignalHandle, list[WVar]]]:
        """Iterate over all handles and their associated variables.
        
        Returns:
            Iterable of (handle, vars_list) tuples
        """
        ...
    
    def get_var_bitwidth(self, handle: SignalHandle) -> int:
        """Get bit width for a signal.
        
        Args:
            handle: Signal handle
        
        Returns:
            Bit width of the signal (defaults to 32 if unknown)
        """
        ...
    
    def get_time_table(self) -> Optional[WTimeTable]:
        """Get the time table from the waveform.
        
        Returns:
            Backend WTimeTable object if available, None otherwise
        """
        ...
    
    def get_timescale(self) -> Optional[Timescale]:
        """Get the timescale of the waveform file.
        
        Returns:
            Timescale object if available, None otherwise
        """
        ...
    
    # Optional attributes and methods for extended functionality
    @property
    def file_path(self) -> Optional[str]:
        """Path to the loaded waveform file.
        
        Returns:
            File path if available, None otherwise
        """
        return None
    
    def get_var_to_handle_mapping(self) -> Optional[Dict[WVar, SignalHandle]]:
        """Get mapping from WVar objects to handles for persistence.
        
        Returns:
            Dictionary mapping WVar to SignalHandle if available, None otherwise
        """
        return None
    
    def get_next_available_handle(self) -> Optional[SignalHandle]:
        """Get next available handle for new signals.
        
        Returns:
            Next available SignalHandle if supported, None otherwise
        """
        return None
    
    def get_signal(self, handle: SignalHandle) -> Optional[WSignal]:
        """Get the signal object for the given handle.
        
        Args:
            handle: Signal handle
        
        Returns:
            Backend WSignal object if available, None otherwise
        """
        ...
    
    def var_from_handle(self, handle: SignalHandle) -> Optional[WVar]:
        """Get the variable object for the given handle.
        
        Args:
            handle: Signal handle
        
        Returns:
            Backend WVar object if available, None otherwise
        """
        ...
    
    def signal_from_handle(self, handle: SignalHandle) -> Optional[WSignal]:
        """Get the signal object for the given handle.
        
        This is an alias for get_signal() for consistency.
        
        Args:
            handle: Signal handle
        
        Returns:
            Backend WSignal object if available, None otherwise
        """
        ...
    
    # Backend selection capability
    def get_backend_type(self) -> Literal["pyrox", "pylibfst"]:
        """Get the current backend type.

        Returns:
            The backend type being used
        """
        ...

    def set_backend_preference(self, backend: Literal["pyrox", "pylibfst"]) -> None:
        """Set the preferred backend for next file load.

        Args:
            backend: The backend to use for next file load

        Note:
            This preference takes effect only when the next waveform file is loaded.
            VCD files always use pyrox regardless of this setting.
        """
        ...