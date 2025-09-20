"""Protocol definitions for decoupling UI from WaveformDB implementation."""

from typing import Protocol, Optional, Iterable, Dict
from collections.abc import Iterable as ABCIterable

import pyrox

# Import our data model types
from .data_model import SignalRef, Timescale


class WaveformDBProtocol(Protocol):
    """Protocol defining the interface for waveform database implementations.
    
    This protocol ensures clean separation between UI components and database
    internals, providing a typed interface for all waveform operations.
    """
    
    # Required attributes
    # These are Optional because WaveformDB starts empty before open() is called
    # Components should check if waveform_db itself is None, not these attributes
    waveform: Optional[pyrox.Waveform]
    hierarchy: Optional[pyrox.Hierarchy]
    
    def find_handle_by_path(self, name: str) -> Optional[SignalRef]:
        """Find signal handle by hierarchical path.
        
        Args:
            name: Full hierarchical path (e.g., "TOP.module.signal")
        
        Returns:
            Signal handle if found, None otherwise
        """
        ...
    
    def find_handle_by_name(self, name: str) -> Optional[SignalRef]:
        """Find signal handle by exact name.
        
        Args:
            name: Exact signal name
        
        Returns:
            Signal handle if found, None otherwise
        """
        ...
    
    def get_handle_for_var(self, var: pyrox.Var) -> Optional[SignalRef]:
        """Get handle for a specific backend variable.

        Args:
            var: Pyrox Var object
        
        Returns:
            Signal handle if found, None otherwise
        """
        ...
    
    def get_var(self, handle: SignalRef) -> Optional[pyrox.Var]:
        """Get backend variable by handle.

        Args:
            handle: Signal handle

        Returns:
            First pyrox Var object for this handle, None if not found
        """
        ...
    
    def get_all_vars_for_handle(self, handle: SignalRef) -> list[pyrox.Var]:
        """Get all variables (including aliases) for a handle.

        Args:
            handle: Signal handle

        Returns:
            List of pyrox Var objects (may be empty)
        """
        ...
    
    def iter_handles_and_vars(self) -> ABCIterable[tuple[SignalRef, list[pyrox.Var]]]:
        """Iterate over all handles and their associated variables.
        
        Returns:
            Iterable of (handle, vars_list) tuples
        """
        ...
    
    def get_var_bitwidth(self, handle: SignalRef) -> int:
        """Get bit width for a signal.
        
        Args:
            handle: Signal handle
        
        Returns:
            Bit width of the signal (defaults to 32 if unknown)
        """
        ...
    
    def get_time_table(self) -> Optional[pyrox.TimeTable]:
        """Get the time table from the waveform.

        Returns:
            Pyrox TimeTable object if available, None otherwise
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
    
    def get_var_to_handle_mapping(self) -> Optional[Dict[pyrox.Var, SignalRef]]:
        """Get mapping from pyrox.Var objects to handles for persistence.

        Returns:
            Dictionary mapping pyrox.Var to SignalRef if available, None otherwise
        """
        return None
    
    def get_next_available_handle(self) -> Optional[SignalRef]:
        """Get next available handle for new signals.
        
        Returns:
            Next available SignalRef if supported, None otherwise
        """
        return None
    
    def get_signal(self, handle: SignalRef) -> Optional[pyrox.Signal]:
        """Get the signal object for the given handle.

        Args:
            handle: Signal handle

        Returns:
            Pyrox Signal object if available, None otherwise
        """
        ...
    
    def var_from_handle(self, handle: SignalRef) -> Optional[pyrox.Var]:
        """Get the variable object for the given handle.

        Args:
            handle: Signal handle

        Returns:
            Pyrox Var object if available, None otherwise
        """
        ...
    
    def signal_from_handle(self, handle: SignalRef) -> Optional[pyrox.Signal]:
        """Get the signal object for the given handle.

        This is an alias for get_signal() for consistency.

        Args:
            handle: Signal handle

        Returns:
            Pyrox Signal object if available, None otherwise
        """
        ...
    
