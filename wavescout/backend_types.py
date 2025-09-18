"""Backend-agnostic protocol types for waveform data.

This module defines protocol types with the "W" prefix (for Waveform) that abstract
away the specific backend implementation (pyrox or pylibfst). These protocols
define the interface contract without importing any backend-specific code.

All components in the wavescout package should use these protocol types instead of
concrete backend types to maintain clean separation and enable runtime backend switching.
"""

from typing import Protocol, Optional, Tuple, Union, List, Literal, Iterator, runtime_checkable


@runtime_checkable
class WVarIndex(Protocol):
    """Protocol for variable bit range indices."""
    
    def msb(self) -> int:
        """Get the most significant bit index."""
        ...
    
    def lsb(self) -> int:
        """Get the least significant bit index."""
        ...


@runtime_checkable  
class WVar(Protocol):
    """Protocol for a variable/signal in the hierarchy."""
    
    def name(self, hier: 'WHierarchy') -> str:
        """Get the local name of the variable."""
        ...
    
    def full_name(self, hier: 'WHierarchy') -> str:
        """Get the full hierarchical path of the variable."""
        ...
    
    def bitwidth(self) -> Optional[int]:
        """Get the bit width of the variable."""
        ...
    
    def var_type(self) -> Literal[
        "Event", "Integer", "Parameter", "Real", "Reg", "Supply0", "Supply1", "Time", 
        "Tri", "TriAnd", "TriOr", "TriReg", "Tri0", "Tri1", "WAnd", "Wire", "WOr", 
        "String", "Port", "SparseArray", "RealTime", "Bit", "Logic", "Int", "ShortInt", 
        "LongInt", "Byte", "Enum", "ShortReal", "Boolean", "BitVector", "StdLogic", 
        "StdLogicVector", "StdULogic", "StdULogicVector"
    ]:
        """Get the variable type."""
        ...
    
    def enum_type(self, hier: 'WHierarchy') -> Optional[Tuple[str, List[Tuple[str, str]]]]:
        """Get enum type information if this is an enum variable."""
        ...
    
    def vhdl_type_name(self, hier: 'WHierarchy') -> Optional[str]:
        """Get VHDL type name if applicable."""
        ...
    
    def direction(self) -> Literal["Unknown", "Implicit", "Input", "Output", "InOut", "Buffer", "Linkage"]:
        """Get the port direction."""
        ...
    
    def length(self) -> Optional[int]:
        """Get the length/size of the variable."""
        ...
    
    def is_real(self) -> bool:
        """Check if this is a real-valued variable."""
        ...
    
    def is_string(self) -> bool:
        """Check if this is a string variable."""
        ...
    
    def is_bit_vector(self) -> bool:
        """Check if this is a bit vector variable."""
        ...
    
    def is_1bit(self) -> bool:
        """Check if this is a single-bit variable."""
        ...
    
    def index(self) -> Optional[WVarIndex]:
        """Get the bit range indices if applicable."""
        ...
    
    def signal_ref(self) -> int:
        """Get the signal reference index."""
        ...


@runtime_checkable
class WVarIter(Protocol):
    """Protocol for iterating over variables."""
    
    def __iter__(self) -> 'WVarIter':
        """Return iterator object."""
        ...
    
    def __next__(self) -> WVar:
        """Get next variable."""
        ...


@runtime_checkable
class WScope(Protocol):
    """Protocol for a scope (module, task, function, etc.) in the hierarchy."""
    
    def name(self, hier: 'WHierarchy') -> str:
        """Get the local name of the scope."""
        ...
    
    def full_name(self, hier: 'WHierarchy') -> str:
        """Get the full hierarchical path of the scope."""
        ...
    
    def scope_type(self) -> Literal[
        "module", "task", "function", "begin", "fork", "generate", "struct", "union", 
        "class", "interface", "package", "program", "vhdl_architecture", "vhdl_procedure", 
        "vhdl_function", "vhdl_record", "vhdl_process", "vhdl_block", "vhdl_for_generate", 
        "vhdl_if_generate", "vhdl_generate", "vhdl_package", "ghw_generic", "vhdl_array", 
        "unknown"
    ]:
        """Get the scope type."""
        ...
    
    def vars(self, hier: 'WHierarchy') -> WVarIter:
        """Get iterator over variables in this scope."""
        ...
    
    def scopes(self, hier: 'WHierarchy') -> 'WScopeIter':
        """Get iterator over child scopes."""
        ...


@runtime_checkable
class WScopeIter(Protocol):
    """Protocol for iterating over scopes."""
    
    def __iter__(self) -> 'WScopeIter':
        """Return iterator object."""
        ...
    
    def __next__(self) -> WScope:
        """Get next scope."""
        ...


@runtime_checkable
class WTimeTable(Protocol):
    """Protocol for time table with compressed time representation."""
    
    def __getitem__(self, idx: int) -> int:
        """Get time value at index."""
        ...
    
    def __len__(self) -> int:
        """Get number of time points."""
        ...


@runtime_checkable
class WHierarchy(Protocol):
    """Protocol for design hierarchy."""
    
    def all_vars(self) -> WVarIter:
        """Get iterator over all variables in the hierarchy."""
        ...
    
    def top_scopes(self) -> WScopeIter:
        """Get iterator over top-level scopes."""
        ...
    
    def date(self) -> str:
        """Get the date from the waveform file."""
        ...
    
    def version(self) -> str:
        """Get the version from the waveform file."""
        ...
    
    def timescale(self) -> Optional['WTimescale']:
        """Get the timescale if available."""
        ...
    
    def file_format(self) -> Literal["VCD", "FST", "GHW", "Unknown"]:
        """Get the file format."""
        ...


@runtime_checkable
class WSignalChangeIter(Protocol):
    """Protocol for iterating over signal changes."""
    
    def __iter__(self) -> 'WSignalChangeIter':
        """Return iterator object."""
        ...
    
    def __len__(self) -> int:
        """Get number of changes."""
        ...
    
    def __next__(self) -> Tuple[int, Union[int, str, float]]:
        """Get next change as (time, value) tuple."""
        ...


@runtime_checkable
class WQueryResult(Protocol):
    """Protocol for signal query result."""
    
    value: Optional[Union[int, str, float]]
    actual_time: Optional[int]
    next_idx: Optional[int]
    next_time: Optional[int]


@runtime_checkable
class WSignal(Protocol):
    """Protocol for signal waveform data."""
    
    def value_at_time(self, time: int) -> Union[int, str, float, None]:
        """Get signal value at specified time."""
        ...
    
    def value_at_idx(self, idx: int) -> Union[int, str, float, None]:
        """Get signal value at specified index."""
        ...
    
    def all_changes(self) -> WSignalChangeIter:
        """Get iterator over all signal changes."""
        ...
    
    def all_changes_after(self, start_time: int) -> WSignalChangeIter:
        """Get iterator over changes after specified time."""
        ...
    
    def query_signal(self, query_time: int) -> WQueryResult:
        """Query signal state at specified time."""
        ...


@runtime_checkable
class WTimescaleUnit(Protocol):
    """Protocol for timescale unit."""
    pass  # Details depend on actual implementation


@runtime_checkable
class WTimescale(Protocol):
    """Protocol for timescale information."""
    
    def to_str(self) -> str:
        """Get string representation of timescale."""
        ...
    
    def get_time_scale_factor_from_seconds(self) -> int:
        """Get the timescale factor from seconds."""
        ...


@runtime_checkable
class WWaveform(Protocol):
    """Protocol for main waveform reader."""
    
    hierarchy: WHierarchy
    time_table: Optional[WTimeTable]
    
    # Note: pylibfst uses time_range instead of time_table
    # Backends will need to adapt this difference
    
    def __init__(
        self,
        path: str,
        multi_threaded: bool = True,
        remove_scopes_with_empty_name: bool = False,
        load_body: bool = True,
    ) -> None:
        """Initialize waveform reader."""
        ...
    
    def load_body(self) -> None:
        """Load the waveform body if not already loaded."""
        ...
    
    def body_loaded(self) -> bool:
        """Check if waveform body is loaded."""
        ...
    
    def get_signal(self, var: WVar) -> WSignal:
        """Get signal data for a variable."""
        ...
    
    def get_signal_from_path(self, abs_hierarchy_path: str) -> WSignal:
        """Get signal data by hierarchical path."""
        ...
    
    def load_signals(self, vars: List[WVar]) -> List[WSignal]:
        """Load multiple signals."""
        ...
    
    def load_signals_multithreaded(self, vars: List[WVar]) -> List[WSignal]:
        """Load multiple signals using multiple threads."""
        ...
    
    def unload_signals(self, signals: List[WSignal]) -> None:
        """Unload signals to free memory."""
        ...