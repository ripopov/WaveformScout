"""Backend implementations for waveform reading.

This package provides adapter implementations for different waveform file readers
(pyrox and pylibfst) that conform to the backend-agnostic protocol types defined
in wavescout.backend_types.
"""

from .base import WaveformBackend, BackendFactory, BackendType

# Import backend implementations to trigger their registration
# Try to import all available backends
try:
    from . import pyrox_backend
except ImportError:
    pass  # pyrox not built yet

try:
    from . import pylibfst_backend
except ImportError:
    pass  # pylibfst not built yet

__all__ = [
    'WaveformBackend',
    'BackendFactory', 
    'BackendType',
]