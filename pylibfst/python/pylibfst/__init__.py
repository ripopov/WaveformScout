"""
pylibfst - Rust-based FST waveform reader with wellen-compatible API
"""

try:
    # Try to import from the compiled Rust module
    from .pylibfst import (
        Waveform,
        Hierarchy,
        Scope,
        Var,
        Signal,
        TimeTable,
        Timescale,
        TimescaleUnit,
        VarIndex,
        VarIter,
        ScopeIter,
        SignalChangeIter,
        QueryResult,
    )
except ImportError:
    # Fallback for development
    import pylibfst.pylibfst as _mod
    
    Waveform = _mod.Waveform
    Hierarchy = _mod.Hierarchy
    Scope = _mod.Scope
    Var = _mod.Var
    Signal = _mod.Signal
    TimeTable = _mod.TimeTable
    Timescale = _mod.Timescale
    TimescaleUnit = _mod.TimescaleUnit
    VarIndex = _mod.VarIndex
    VarIter = _mod.VarIter
    ScopeIter = _mod.ScopeIter
    SignalChangeIter = _mod.SignalChangeIter
    QueryResult = _mod.QueryResult

__all__ = [
    "Waveform",
    "Hierarchy",
    "Scope",
    "Var",
    "Signal",
    "TimeTable",
    "Timescale",
    "TimescaleUnit",
    "VarIndex",
    "VarIter",
    "ScopeIter",
    "SignalChangeIter",
    "QueryResult",
]

__version__ = "0.1.0"

# Re-export for type checking
if False:  # TYPE_CHECKING
    from .pylibfst import (
        Waveform as Waveform,
        Hierarchy as Hierarchy,
        Scope as Scope,
        Var as Var,
        Signal as Signal,
        TimeTable as TimeTable,
        Timescale as Timescale,
        TimescaleUnit as TimescaleUnit,
        VarIndex as VarIndex,
        VarIter as VarIter,
        ScopeIter as ScopeIter,
        SignalChangeIter as SignalChangeIter,
        QueryResult as QueryResult,
    )