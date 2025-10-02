"""WaveScout - PySide6 Digital/Mixed-Signal Waveform Viewer Widget."""

__version__ = "0.1.0"

from pyrox import SignalHandle

from .core.data_model import (
    TreeNode,
    GroupNode,
    SignalNode,
    DisplayFormat,
    DataFormat,
    GroupRenderMode,
    RenderType,
    Viewport, Marker, AnalysisMode,
    WaveformSession
)
from .models.waveform_item_model import WaveformItemModel
from .widgets.wave_scout_widget import WaveScoutWidget
from .core.waveform_controller import WaveformController
from .core.waveform_db import WaveformDB
from .core.waveform_loader import create_sample_session
from .core.persistence import save_session, load_session
from .utils.config import RENDERING, COLORS, UI, TIME_RULER

__all__ = [
    'TreeNode', 'GroupNode', 'SignalNode', 'SignalHandle', 'DisplayFormat', 'DataFormat', 'GroupRenderMode', 'RenderType',
    'Viewport', 'Marker', 'AnalysisMode',
    'WaveformSession', 'WaveformItemModel', 'WaveScoutWidget', 'WaveformController',
    'WaveformDB', 'create_sample_session',
    'save_session', 'load_session',
    'RENDERING', 'COLORS', 'UI', 'TIME_RULER'
]
