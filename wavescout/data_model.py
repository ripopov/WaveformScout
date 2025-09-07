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

from dataclasses import dataclass, field
from typing import List, Optional, ClassVar, Dict, Tuple, TYPE_CHECKING
from enum import Enum

if TYPE_CHECKING:
    from wavescout.protocols import WaveformDBProtocol

Time = int  # In Timescale units

# SignalHandle is an opaque identifier used to efficiently reference signals in the waveform database.
# Instead of using full hierarchical names (e.g., "top.cpu.core.alu.result[31:0]") for every
# database query, which would be slow for string comparisons, we use integer handles that act
# as primary keys. In addition, multiple hierarchical names can reference the same Signal,
# so using SignalHandle is less ambiguous.
# The handle is obtained when first querying a signal by name, then reused for all subsequent
# operations like getting transitions, sampling values, etc.
# Important: Multiple Variables with different hierarchical names can reference the same Signal.
SignalHandle = int

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

@dataclass
class SignalNode:
    """A node in the signal/group tree. Can be a signal or a group."""
    name: str                          # Full hierarchical name (e.g., "top.tb.axi_bfm.clk")
    handle: Optional[SignalHandle] = None        # identifier understood by WaveformDB (None for groups)
    format: DisplayFormat = field(default_factory=DisplayFormat)
    nickname: str = ""                  # User-defined display name
    children: List["SignalNode"] = field(default_factory=list)
    parent: Optional["SignalNode"] = field(default=None, repr=False)
    is_group: bool = False
    group_render_mode: Optional[GroupRenderMode] = None  # Only for groups
    is_expanded: bool = True            # Whether group is expanded (only relevant for groups)
    height_scaling: int = 1             # Relative row height (1, 2, 3, 4, 8)
    is_multi_bit: bool = False         # Whether signal has multiple bits (for render type selection)

    # Class-level counter for generating unique instance IDs
    _id_counter: ClassVar[int] = 0

    # Unique identifier for this SignalNode instance
    instance_id: SignalNodeID = field(default_factory=lambda: SignalNode._generate_id())
    
    def __eq__(self, other: object) -> bool:
        """Custom equality comparison that avoids circular reference through parent field.
        
        We compare all fields except 'parent' to prevent infinite recursion when
        comparing nodes in a tree structure. The parent field is excluded because:
        1. It creates circular references (parent->children->parent)
        2. Two nodes are equal if their content is the same, regardless of position in tree
        3. The instance_id already provides unique identification
        """
        if not isinstance(other, SignalNode):
            return False
        
        # Compare all fields except parent to avoid circular reference
        return (
            self.name == other.name and
            self.handle == other.handle and
            self.format == other.format and
            self.nickname == other.nickname and
            self.children == other.children and  # This is safe because children don't compare parents
            # parent field explicitly excluded
            self.is_group == other.is_group and
            self.group_render_mode == other.group_render_mode and
            self.is_expanded == other.is_expanded and
            self.height_scaling == other.height_scaling and
            self.is_multi_bit == other.is_multi_bit and
            self.instance_id == other.instance_id
        )

    @classmethod
    def _generate_id(cls) -> SignalNodeID:
        """Generate a unique instance ID."""
        cls._id_counter += 1
        return cls._id_counter
    
    def deep_copy(self) -> "SignalNode":
        """Create a deep copy of this node with new instance IDs.
        
        Recursively copies children for groups, generates new instance_ids,
        and clears parent references (to be set by insertion logic).
        """
        # Create a new DisplayFormat copy
        format_copy = DisplayFormat(
            render_type=self.format.render_type,
            data_format=self.format.data_format,
            color=self.format.color,
            analog_scaling_mode=self.format.analog_scaling_mode
        )
        
        # Create the new node with a new instance ID
        new_node = SignalNode(
            name=self.name,
            handle=self.handle,
            format=format_copy,
            nickname=self.nickname,
            children=[],  # Will be filled below
            parent=None,  # Parent will be set by insertion logic
            is_group=self.is_group,
            group_render_mode=self.group_render_mode,
            is_expanded=self.is_expanded,
            height_scaling=self.height_scaling,
            is_multi_bit=self.is_multi_bit,
            instance_id=self._generate_id()  # Generate new ID
        )
        
        # Recursively copy children for groups
        if self.children:
            for child in self.children:
                child_copy = child.deep_copy()
                child_copy.parent = new_node
                new_node.children.append(child_copy)
        
        return new_node

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
            'us': cls.MICROSECONDS,  # Note: pywellen uses 'us' not 'μs'
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

@dataclass
class WaveformSession:
    waveform_db: Optional['WaveformDBProtocol'] = None  # Pointer to WaveformDB instance
    root_nodes: List[SignalNode] = field(default_factory=list)
    viewport: Viewport = field(default_factory=Viewport)
    markers: List[Marker] = field(default_factory=list)
    cursor_time: Time = 0
    analysis_mode: AnalysisMode = field(default_factory=AnalysisMode)
    selected_nodes: List[SignalNode] = field(default_factory=list)  # Currently selected nodes
    time_ruler_config: TimeRulerConfig = field(default_factory=TimeRulerConfig)  # Configuration for time ruler display
    timescale: Timescale = field(default_factory=lambda: Timescale(1, TimeUnit.PICOSECONDS))  # Timescale from the waveform file, default 1 ps if waveform not specifies timescale
    clock_signal: Optional[tuple[Time, Time, SignalNode]] = None  # Clock period, phase offset, and signal node for clock-based grid display
    sampling_signal: Optional[SignalNode] = None  # Signal used for sampling in signal analysis