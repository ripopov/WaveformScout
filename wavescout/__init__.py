"""WaveScout - PySide6 Digital/Mixed-Signal Waveform Viewer Widget."""

__version__ = "0.1.0"

from pyrox import SignalHandle

from .data_model import (
    SignalNode,
    SignalNodeGroup,
    SignalNodeSignal,
    DisplayFormat,
    DataFormat,
    GroupRenderMode,
    RenderType,
    Viewport, Marker, AnalysisMode,
    WaveformSession
)
from .waveform_item_model import WaveformItemModel
from .wave_scout_widget import WaveScoutWidget
from .waveform_controller import WaveformController
from .waveform_db import WaveformDB
from .waveform_loader import create_sample_session
from .persistence import save_session, load_session
from .config import RENDERING, COLORS, UI, TIME_RULER

__all__ = [
    'SignalNode', 'SignalNodeGroup', 'SignalNodeSignal', 'SignalHandle', 'DisplayFormat', 'DataFormat', 'GroupRenderMode', 'RenderType',
    'Viewport', 'Marker', 'AnalysisMode',
    'WaveformSession', 'WaveformItemModel', 'WaveScoutWidget', 'WaveformController',
    'WaveformDB', 'create_sample_session',
    'save_session', 'load_session',
    'RENDERING', 'COLORS', 'UI', 'TIME_RULER'
]
