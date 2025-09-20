"""Timing utilities for performance profiling."""

import time
from typing import Optional

# Global startup time for the application
_startup_time: Optional[float] = None


def set_startup_time(t: float) -> None:
    """Set the global startup time."""
    global _startup_time
    _startup_time = t


def get_startup_time() -> Optional[float]:
    """Get the global startup time."""
    return _startup_time


def tprint(msg: str) -> None:
    """Print with timestamp since startup."""
    if _startup_time:
        elapsed = time.time() - _startup_time
        print(f"[{elapsed:7.3f}s] {msg}")
    else:
        print(msg)