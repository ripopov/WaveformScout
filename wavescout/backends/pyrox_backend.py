"""Pyrox backend implementation with adapters for protocol types."""

from typing import Optional, List, cast
from pathlib import Path

from typing import TYPE_CHECKING

try:
    import pyrox
except ImportError:
    if not TYPE_CHECKING:
        raise ImportError("pyrox is required for the pyrox backend. Install it with: poetry run build-pyrox")
    else:
        # For type checking only, create mock
        pyrox = None  # type: ignore[assignment]

from .base import WaveformBackend, BackendType, BackendFactory
from ..backend_types import (
    WWaveform, WHierarchy, WSignal, WVar, WTimeTable, WTimescale,
    WScope, WScopeIter, WVarIter, WVarIndex, WSignalChangeIter, WQueryResult
)


# Since pyrox types already match our protocol interfaces exactly,
# we can use them directly without adapter wrappers. The protocol types
# will structurally match at runtime due to Python's duck typing.
# This avoids unnecessary overhead while maintaining type safety.

class PyroxBackend(WaveformBackend):
    """Backend implementation using pyrox library.

    This backend supports both VCD and FST file formats using the
    Rust-based wellen library through Python bindings.
    """

    def __init__(self, file_path: str):
        """Initialize the pyrox backend.

        Args:
            file_path: Path to the waveform file
        """
        super().__init__(file_path)
        self._backend_type = BackendType.PYROX

    def load_waveform(
        self,
        multi_threaded: bool = True,
        remove_scopes_with_empty_name: bool = False,
        load_body: bool = True
    ) -> WWaveform:
        """Load the waveform file using pyrox.

        Args:
            multi_threaded: Whether to use multi-threading for signal loading
            remove_scopes_with_empty_name: Whether to filter out unnamed scopes
            load_body: Whether to immediately load the waveform body

        Returns:
            Loaded waveform object (pyrox.Waveform implements WWaveform protocol)
        """
        self._waveform = pyrox.Waveform(  # type: ignore[attr-defined]
            self.file_path,
            multi_threaded=multi_threaded,
            remove_scopes_with_empty_name=remove_scopes_with_empty_name,
            load_body=load_body
        )
        # pyrox.Waveform directly implements our WWaveform protocol
        return cast(WWaveform, self._waveform)

    def get_hierarchy(self) -> Optional[WHierarchy]:
        """Get the hierarchy from the loaded waveform.

        Returns:
            Hierarchy object (pyrox.Hierarchy implements WHierarchy protocol)
        """
        if self._waveform is None:
            return None
        # pyrox.Hierarchy directly implements our WHierarchy protocol
        return self._waveform.hierarchy

    def get_time_table(self) -> Optional[WTimeTable]:
        """Get the time table from the loaded waveform.

        Returns:
            TimeTable object (pyrox.TimeTable implements WTimeTable protocol)
        """
        if self._waveform is None:
            return None
        # pyrox.TimeTable directly implements our WTimeTable protocol
        time_table = self._waveform.time_table
        return time_table if time_table else None

    def get_signal(self, var: WVar) -> Optional[WSignal]:
        """Get signal data for a variable.

        Args:
            var: Variable to get signal for (must be a pyrox.Var)

        Returns:
            Signal object (pyrox.Signal implements WSignal protocol)
        """
        if self._waveform is None:
            return None
        try:
            # var should be a pyrox.Var object that implements WVar protocol
            signal = self._waveform.get_signal(var)
            # pyrox.Signal directly implements our WSignal protocol
            return signal
        except Exception:
            return None

    def load_signals(self, vars: List[WVar], multithreaded: bool = False) -> List[WSignal]:
        """Load multiple signals.

        Args:
            vars: List of variables to load signals for
            multithreaded: Whether to use multiple threads for loading (default: False)

        Returns:
            List of Signal objects (pyrox.Signal implements WSignal protocol)
        """
        if self._waveform is None:
            return []
        # vars should be pyrox.Var objects that implement WVar protocol
        if multithreaded:
            signals = self._waveform.load_signals_multithreaded(vars)
        else:
            signals = self._waveform.load_signals(vars)
        # pyrox.Signal objects directly implement our WSignal protocol
        return list(signals)

    def supports_file_format(self, file_path: str) -> bool:
        """Check if pyrox supports the given file format.

        Args:
            file_path: Path to the waveform file

        Returns:
            True for VCD and FST files, False otherwise
        """
        path = Path(file_path)
        ext = path.suffix.lower()
        return ext in ['.vcd', '.fst']


# Register the pyrox backend with the factory
BackendFactory.register_backend(BackendType.PYROX, PyroxBackend)