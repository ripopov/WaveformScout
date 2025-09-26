"""Event classes for the controller-centric architecture."""

from dataclasses import dataclass, field
from typing import Literal, Optional, TypedDict
import time

from pyrox import SignalHandle, Signal
from wavescout.data_model import Time, SignalNodeID


@dataclass(frozen=True, kw_only=True)
class Event:
    """Base class for all events."""
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, kw_only=True)
class StructureChangedEvent(Event):
    """Emitted when signal tree structure changes."""
    change_kind: Literal['insert', 'delete', 'move', 'group', 'ungroup']
    affected_ids: list[SignalNodeID]
    parent_id: Optional[SignalNodeID] = None
    insert_row: Optional[int] = None


class FormatChanges(TypedDict, total=False):
    """Type-safe dictionary for format changes."""
    data_format: str
    render_type: str
    scale: float
    offset: float
    color: str
    nickname: str
    height: int
    analog_scaling_mode: str


@dataclass(frozen=True, kw_only=True)
class FormatChangedEvent(Event):
    """Emitted when signal display format changes."""
    node_id: SignalNodeID
    changes: FormatChanges


@dataclass(frozen=True, kw_only=True)
class ViewportChangedEvent(Event):
    """Emitted when viewport bounds change."""
    old_left: float
    old_right: float
    new_left: float
    new_right: float


@dataclass(frozen=True, kw_only=True)
class CursorMovedEvent(Event):
    """Emitted when cursor position changes."""
    old_time: Time
    new_time: Time


@dataclass(frozen=True, kw_only=True)
class SelectionChangedEvent(Event):
    """Emitted when node selection changes."""
    old_selection: list[SignalNodeID]
    new_selection: list[SignalNodeID]


@dataclass(frozen=True, kw_only=True)
class MarkerAddedEvent(Event):
    """Emitted when a new marker is added."""
    marker_name: str
    time: Time


@dataclass(frozen=True, kw_only=True)
class MarkerRemovedEvent(Event):
    """Emitted when a marker is removed."""
    marker_name: str


@dataclass(frozen=True, kw_only=True)
class MarkerMovedEvent(Event):
    """Emitted when a marker position changes."""
    marker_name: str
    old_time: Time
    new_time: Time


@dataclass(frozen=True, kw_only=True)
class SessionLoadedEvent(Event):
    """Emitted when a new waveform session is loaded."""
    file_path: str


@dataclass(frozen=True, kw_only=True)
class SessionClosedEvent(Event):
    """Emitted when the current session is closed."""
    pass


@dataclass(frozen=True, kw_only=True)
class SignalLoadingStartedEvent(Event):
    """Emitted when signal loading begins."""
    handles: list[SignalHandle]


@dataclass(frozen=True, kw_only=True)
class SignalLoadedEvent(Event):
    """Emitted when signals are loaded from the backend."""
    pairs: list[tuple[SignalHandle, Signal]]


@dataclass(frozen=True, kw_only=True)
class SignalLoadingFailedEvent(Event):
    """Emitted when signal loading fails."""
    handles: list[SignalHandle]
    error: str