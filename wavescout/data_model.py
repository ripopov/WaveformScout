"""Core data structures for WaveScout Widget.

This module defines the state of the waveform viewer widget: displayed signals,
viewport, and markers. Don't confuse this with the WaveformDB which represents
whole waveforms, while data_model represents only a view visible to the user.

Displayed signals can be grouped into a tree structure. So WaveformSession is a tree,
 but usually it flat (e.g., no groups).

    WaveformSession
    ├── root_nodes: [SignalNode]     (Top-level signals/groups)
    │   ├── SignalNode (Top-level Group)
    │   │   ├── name: "CPU"
    │   │   ├── is_group: True
    │   │   └── children: [
    │   │       ├── SignalNode (Signal)
    │   │       │   ├── name: "CPU.clk"
    │   │       │   ├── handle: 42
    │   │       │   └── format: DisplayFormat(BOOL)
    │   │       └── SignalNode (Signal)
    │   │           ├── name: "CPU.data"
    │   │           ├── handle: 43
    │   │           └── format: DisplayFormat(BUS, hex)
    │   │       ]
    │   └── SignalNode (Top-level Signal)
    │       ├── name: "reset"
    │       ├── handle: 10
    │       └── format: DisplayFormat(BOOL)
    ├── viewport: Viewport
    │   ├── left: 0.2    (20% into waveform)
    │   ├── right: 0.3   (30% into waveform)
    │   └── total_duration: 1000000 ps
    └── markers: [Marker]
        └── Marker(time=500000, label="Start")

"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, ClassVar, Dict, Tuple, TYPE_CHECKING, Any
from enum import Enum

from pyrox import SignalHandle, Var

if TYPE_CHECKING:
    from wavescout.waveform_db import AsyncLoadedSignal

if TYPE_CHECKING:
    from pyrox import Signal
    from wavescout.waveform_db import WaveformDB

Time = int  # In Timescale units

# SignalNodeID is a unique identifier for each SignalNode instance.
# This allows multiple instances of the same signal (same handle) to be displayed
# with different settings (e.g., different height_scaling) without cache conflicts.
SignalNodeID = int

class DataFormat(Enum):
    UNSIGNED = "unsigned"
    SIGNED = "signed"
    HEX = "hex"
    BIN = "bin"
    FLOAT = "float"

class GroupRenderMode(Enum):
    SEPARATE_ROWS = "separate_rows"
    OVERLAPPED = "overlapped"
    STACKED_AREA = "stacked_area"
    PIPELINE = "pipeline"

class RenderType(Enum):
    BOOL = "bool"       # 1-bit digital signals
    BUS = "bus"         # Multi-bit signals
    EVENT = "event"     # Discrete events
    ANALOG = "analog"   # Analog waveforms

class AnalogScalingMode(Enum):
    SCALE_TO_ALL_DATA = "scale_to_all"      # Use global min/max
    SCALE_TO_VISIBLE_DATA = "scale_to_visible"  # Use viewport min/max

@dataclass
class DisplayFormat:
    render_type: RenderType = RenderType.BOOL
    data_format: DataFormat = DataFormat.UNSIGNED
    color: Optional[str] = None  # None means use theme default, otherwise user-configured
    analog_scaling_mode: AnalogScalingMode = AnalogScalingMode.SCALE_TO_ALL_DATA

@dataclass(eq=False, kw_only=True)
class SignalNode(ABC):
    """Base node in the signal/group tree with shared attributes."""

    name: str
    nickname: str = ""
    parent: Optional["SignalNodeGroup"] = field(default=None, repr=False)
    height_scaling: int = 1

    # Class-level counter for generating unique instance IDs
    _id_counter: ClassVar[int] = 0

    # Unique identifier for this SignalNode instance
    instance_id: SignalNodeID = field(default_factory=lambda: SignalNode._generate_id())

    def __eq__(self, other: object) -> bool:
        """Custom equality comparison that avoids circular references through parent."""
        if type(self) is not type(other):
            return False

        assert isinstance(other, SignalNode)
        return self._comparison_state() == other._comparison_state()

    @abstractmethod
    def _comparison_state(self) -> Tuple[Any, ...]:
        """Return the tuple of fields used for equality comparison."""

    @classmethod
    def _generate_id(cls) -> SignalNodeID:
        """Generate a unique instance ID shared across all node variants."""
        SignalNode._id_counter += 1
        return SignalNode._id_counter

    @abstractmethod
    def deep_copy(self) -> "SignalNode":
        """Create a deep copy of this node with a fresh instance ID."""

    @property
    def is_group(self) -> bool:
        """Convenience discriminator compatible with legacy callers."""
        return isinstance(self, SignalNodeGroup)


@dataclass(eq=False, kw_only=True)
class SignalNodeSignal(SignalNode):
    """A signal node containing waveform data handle and formatting."""

    var: Var = field(repr=False, compare=False)  # Non-optional, must be provided
    handle: Optional[SignalHandle] = None
    signal: "AsyncLoadedSignal" = field(repr=False, compare=False)
    format: DisplayFormat = field(default_factory=DisplayFormat)
    is_multi_bit: bool = False

    def __post_init__(self) -> None:
        """Initialize with AsyncLoadedSignal if not provided."""
        if not hasattr(self, 'signal') or self.signal is None:
            # Create placeholder AsyncLoadedSignal
            from wavescout.waveform_db import AsyncLoadedSignal
            if self.handle is not None:
                self.signal = AsyncLoadedSignal.placeholder(self.handle)

    def _comparison_state(self) -> Tuple[Any, ...]:
        return (
            self.name,
            self.nickname,
            self.height_scaling,
            self.instance_id,
            self.handle,
            self.format,
            self.is_multi_bit,
            # signal excluded from comparison
        )

    def deep_copy(self) -> "SignalNodeSignal":
        format_copy = DisplayFormat(
            render_type=self.format.render_type,
            data_format=self.format.data_format,
            color=self.format.color,
            analog_scaling_mode=self.format.analog_scaling_mode,
        )

        return SignalNodeSignal(
            name=self.name,
            nickname=self.nickname,
            height_scaling=self.height_scaling,
            var=self.var,  # Pass the same var reference
            handle=self.handle,
            signal=self.signal,  # Share AsyncLoadedSignal reference
            format=format_copy,
            is_multi_bit=self.is_multi_bit,
        )


@dataclass(eq=False, kw_only=True)
class SignalNodeGroup(SignalNode):
    """A group node that can contain child signal or group nodes."""

    group_render_mode: Optional[GroupRenderMode] = None
    children: List["SignalNode"] = field(default_factory=list)
    is_expanded: bool = True

    def _comparison_state(self) -> Tuple[Any, ...]:
        return (
            self.name,
            self.nickname,
            self.height_scaling,
            self.instance_id,
            self.group_render_mode,
            self.is_expanded,
            tuple(self.children),
        )

    def deep_copy(self) -> "SignalNodeGroup":
        new_group = SignalNodeGroup(
            name=self.name,
            nickname=self.nickname,
            height_scaling=self.height_scaling,
            group_render_mode=self.group_render_mode,
            is_expanded=self.is_expanded,
        )

        if self.children:
            for child in self.children:
                child_copy = child.deep_copy()
                child_copy.parent = new_group
                new_group.children.append(child_copy)

        return new_group

class TimeUnit(Enum):
    ZEPTOSECONDS = "zs"  # 10^-21 seconds
    ATTOSECONDS = "as"   # 10^-18 seconds
    FEMTOSECONDS = "fs"  # 10^-15 seconds
    PICOSECONDS = "ps"   # 10^-12 seconds
    NANOSECONDS = "ns"   # 10^-9 seconds
    MICROSECONDS = "μs"  # 10^-6 seconds
    MILLISECONDS = "ms"  # 10^-3 seconds
    SECONDS = "s"        # 10^0 seconds

    @classmethod
    def from_string(cls, s: str) -> Optional['TimeUnit']:
        """Convert string representation to TimeUnit."""
        mapping = {
            'zs': cls.ZEPTOSECONDS,
            'as': cls.ATTOSECONDS,
            'fs': cls.FEMTOSECONDS,
            'ps': cls.PICOSECONDS,
            'ns': cls.NANOSECONDS,
            'us': cls.MICROSECONDS,  # Note: wellen uses 'us' not 'μs'
            'μs': cls.MICROSECONDS,
            'ms': cls.MILLISECONDS,
            's': cls.SECONDS
        }
        return mapping.get(s)

    def to_exponent(self) -> int:
        """Get the power of 10 exponent for this unit."""
        exponents: dict[TimeUnit, int] = {
            TimeUnit.ZEPTOSECONDS: -21,
            TimeUnit.ATTOSECONDS: -18,
            TimeUnit.FEMTOSECONDS: -15,
            TimeUnit.PICOSECONDS: -12,
            TimeUnit.NANOSECONDS: -9,
            TimeUnit.MICROSECONDS: -6,
            TimeUnit.MILLISECONDS: -3,
            TimeUnit.SECONDS: 0
        }
        return exponents[self]

@dataclass
class Timescale:
    """Represents the timescale of a waveform file."""
    factor: int  # The numeric factor (e.g., 1, 10, 100)
    unit: TimeUnit  # The time unit

@dataclass
class ViewportConfig:
    """Configuration for viewport behavior and constraints."""
    edge_space: float = 0.2             # Extra space beyond 0.0-1.0 (20% on each side)
    minimum_width_time: Time = 10       # Minimum viewport width in time units (Timescale units)
    scroll_sensitivity: float = 0.05    # Base percentage for scroll wheel panning
    zoom_wheel_factor: float = 1.1      # Zoom factor per mouse wheel notch

@dataclass
class TimeRulerConfig:
    """Configuration for time ruler and grid lines."""
    tick_density: float = 0.8           # Controls tick spacing (0.5=sparse, 1.0=dense)
    text_size: int = 10                 # Font size in pixels for tick labels
    time_unit: TimeUnit = TimeUnit.NANOSECONDS  # Preferred time unit for display
    show_grid_lines: bool = True        # Whether to draw vertical grid lines
    grid_color: str = "#3e3e42"         # Color for grid lines
    grid_style: str = "solid"           # Grid line style: "solid", "dashed", "dotted"
    grid_opacity: float = 0.4           # Grid line opacity (0.0-1.0)
    nice_numbers: List[float] = field(default_factory=lambda: [1, 2, 2.5, 5])  # Multipliers for tick intervals

@dataclass
class Viewport:
    """Viewport represents the visible portion of the waveform using normalized coordinates.
    
    The viewport uses relative coordinates where:
    - 0.0 represents the start of the waveform
    - 1.0 represents the end of the waveform
    - Values outside 0.0-1.0 represent areas beyond the waveform (edge space)
    
    The actual time values are calculated by multiplying these relative positions
    by the total waveform duration from the WaveformDB.
    """
    left: float = 0.0                   # Left edge in relative coordinates (0.0-1.0)
    right: float = 1.0                  # Right edge in relative coordinates (0.0-1.0)

    # Total waveform duration for conversions (populated from WaveformDB)
    total_duration: Time = 1000000      # Total waveform time in Timescale units

    # Configuration
    config: ViewportConfig = field(default_factory=ViewportConfig)

    @property
    def width(self) -> float:
        """Width of viewport in relative coordinates (zoom level = 1/width)."""
        return self.right - self.left

    @property
    def zoom_level(self) -> float:
        """Calculated zoom level (1.0 = entire waveform visible)."""
        return 1.0 / self.width if self.width > 0 else 1.0

    @property
    def start_time(self) -> Time:
        """Start time in Timescale units."""
        return int(self.left * self.total_duration)

    @property
    def end_time(self) -> Time:
        """End time in Timescale units."""
        return int(self.right * self.total_duration)

    def time_to_relative(self, time: Time) -> float:
        """Convert time in Timescale units to relative coordinate."""
        return time / self.total_duration if self.total_duration > 0 else 0.0

    def relative_to_time(self, relative: float) -> Time:
        """Convert relative coordinate to time in Timescale units."""
        return int(relative * self.total_duration)

@dataclass
class Marker:
    time: Time
    label: str = ""
    color: str = "#FF0000"


@dataclass
class AnalysisMode:
    """Defines the analysis mode for signal measurements."""
    mode: str = "none"  # 'none' | 'min' | 'max' | 'avg' | 'range_min' | 'range_max' | 'cursor_delta'
    range_start: Optional[Time] = None  # For range-based analysis
    range_end: Optional[Time] = None

@dataclass
class SignalRangeCache:
    """Cache for analog signal min/max ranges."""
    min: float  # Min value across all time
    max: float  # Max value across all time
    viewport_ranges: Dict[Tuple[Time, Time], Tuple[float, float]] = field(default_factory=dict)  # Cached viewport ranges
    data_format: DataFormat = DataFormat.UNSIGNED  # The data format used for computing these ranges

@dataclass
class WaveformSession:
    waveform_db: Optional['WaveformDB'] = None  # Pointer to WaveformDB instance
    root_nodes: List[SignalNode] = field(default_factory=list)
    viewport: Viewport = field(default_factory=Viewport)
    markers: List[Marker] = field(default_factory=list)
    cursor_time: Time = 0
    analysis_mode: AnalysisMode = field(default_factory=AnalysisMode)
    selected_nodes: List[SignalNode] = field(default_factory=list)  # Currently selected nodes
    time_ruler_config: TimeRulerConfig = field(default_factory=TimeRulerConfig)  # Configuration for time ruler display
    timescale: Timescale = field(default_factory=lambda: Timescale(1, TimeUnit.PICOSECONDS))  # Timescale from the waveform file, default 1 ps if waveform not specifies timescale
    clock_signal: Optional[tuple[Time, Time, SignalNode]] = None  # Clock period, phase offset, and signal node for clock-based grid display
    loading_handles: set[SignalHandle] = field(default_factory=set)  # Handles currently being loaded asynchronously
    sampling_signal: Optional[SignalNode] = None  # Signal used for sampling in signal analysis

    def is_loading(self, handle: SignalHandle) -> bool:
        """Check if a signal handle is currently being loaded.

        Args:
            handle: Signal handle to check

        Returns:
            True if the handle is being loaded, False otherwise
        """
        return handle in self.loading_handles
