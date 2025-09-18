"""Base classes and factory for waveform backend implementations."""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, List, Literal, TYPE_CHECKING
from pathlib import Path

from ..backend_types import (
    WWaveform, WHierarchy, WSignal, WVar, WTimeTable
)
from ..data_model import SignalHandle

if TYPE_CHECKING:
    from ..protocols import WaveformDBProtocol


class BackendType(Enum):
    """Supported waveform backend types."""
    PYROX = "pyrox"
    PYLIBFST = "pylibfst"


class WaveformBackend(ABC):
    """Abstract base class for waveform backend implementations.
    
    Each backend must provide adapters that wrap native types to implement
    the W-prefixed protocol types defined in backend_types.py.
    """
    
    def __init__(self, file_path: str):
        """Initialize the backend with a waveform file path.
        
        Args:
            file_path: Path to the waveform file
        """
        self.file_path = file_path
        self._waveform: Optional[WWaveform] = None
        self._backend_type: BackendType  # Must be set by subclasses
        
    @abstractmethod
    def load_waveform(
        self,
        multi_threaded: bool = True,
        remove_scopes_with_empty_name: bool = False,
        load_body: bool = True
    ) -> WWaveform:
        """Load the waveform file.
        
        Args:
            multi_threaded: Whether to use multi-threading for signal loading
            remove_scopes_with_empty_name: Whether to filter out unnamed scopes
            load_body: Whether to immediately load the waveform body
            
        Returns:
            Loaded waveform object conforming to WWaveform protocol
        """
        ...
    
    @abstractmethod
    def get_hierarchy(self) -> Optional[WHierarchy]:
        """Get the hierarchy from the loaded waveform.
        
        Returns:
            Hierarchy object conforming to WHierarchy protocol, or None if not loaded
        """
        ...
    
    @abstractmethod
    def get_time_table(self) -> Optional[WTimeTable]:
        """Get the time table from the loaded waveform.
        
        Returns:
            TimeTable object conforming to WTimeTable protocol, or None if not available
        """
        ...
    
    @abstractmethod
    def get_signal(self, var: WVar) -> Optional[WSignal]:
        """Get signal data for a variable.
        
        Args:
            var: Variable to get signal for
            
        Returns:
            Signal object conforming to WSignal protocol, or None if not available
        """
        ...
    
    @abstractmethod
    def load_signals(self, vars: List[WVar], multithreaded: bool = False) -> List[WSignal]:
        """Load multiple signals.
        
        Args:
            vars: List of variables to load signals for
            multithreaded: Whether to use multiple threads for loading (default: False)
            
        Returns:
            List of Signal objects conforming to WSignal protocol
        """
        ...
    
    @abstractmethod
    def supports_file_format(self, file_path: str) -> bool:
        """Check if this backend supports the given file format.
        
        Args:
            file_path: Path to the waveform file
            
        Returns:
            True if this backend can read the file, False otherwise
        """
        ...
    
    @property
    def backend_type(self) -> BackendType:
        """Get the type of this backend.
        
        Returns:
            The backend type enum value
        """
        return self._backend_type
    
    @property  
    def waveform(self) -> Optional[WWaveform]:
        """Get the loaded waveform object.
        
        Returns:
            The waveform object if loaded, None otherwise
        """
        return self._waveform
        

class BackendFactory:
    """Factory for creating waveform backend instances."""
    
    _backends: dict[BackendType, type[WaveformBackend]] = {}
    
    @classmethod
    def register_backend(cls, backend_type: BackendType, backend_class: type[WaveformBackend]) -> None:
        """Register a backend implementation.
        
        Args:
            backend_type: The type of backend
            backend_class: The backend class to register
        """
        cls._backends[backend_type] = backend_class
    
    @classmethod
    def create_backend(
        cls,
        file_path: str,
        backend_type: Optional[BackendType] = None,
        preferred_backend: Optional[BackendType] = None
    ) -> WaveformBackend:
        """Create a backend instance for the given file.
        
        Args:
            file_path: Path to the waveform file
            backend_type: Explicitly specify which backend to use
            preferred_backend: Preferred backend if file supports multiple
            
        Returns:
            Backend instance appropriate for the file
            
        Raises:
            ValueError: If no suitable backend is found
        """
        path = Path(file_path)
        ext = path.suffix.lower()
        
        # If backend explicitly specified, use it
        if backend_type:
            if backend_type not in cls._backends:
                raise ValueError(f"Backend {backend_type} not registered")
            return cls._backends[backend_type](file_path)
        
        # VCD files use pyrox
        if ext == '.vcd':
            if BackendType.PYROX in cls._backends:
                return cls._backends[BackendType.PYROX](file_path)
            else:
                raise ValueError("No backend available for VCD files (pyrox required)")
        
        # FST files can use either backend based on preference
        if ext == '.fst':
            # Use preferred backend if specified and available
            if preferred_backend and preferred_backend in cls._backends:
                backend_class = cls._backends[preferred_backend]
                if backend_class(file_path).supports_file_format(file_path):
                    return backend_class(file_path)
            
            # Try each registered backend
            for backend_type, backend_class in cls._backends.items():
                backend = backend_class(file_path)
                if backend.supports_file_format(file_path):
                    return backend
        
        raise ValueError(f"No suitable backend found for file: {file_path}")
    
    @classmethod
    def get_available_backends(cls) -> List[BackendType]:
        """Get list of available backend types.
        
        Returns:
            List of registered backend types
        """
        return list(cls._backends.keys())