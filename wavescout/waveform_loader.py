"""Helper functions to load waveforms and create signal nodes."""

from typing import List, Dict, Literal, cast
from .backend_types import WVar, WHierarchy
from .data_model import SignalNode, SignalHandle, DisplayFormat, DataFormat, WaveformSession, RenderType
from .waveform_db import WaveformDB


def create_signal_node_from_var(var: WVar, hierarchy: WHierarchy, handle: SignalHandle) -> SignalNode:
    """Create a SignalNode from a backend variable."""
    # Get variable info
    full_name = var.full_name(hierarchy)
    local_name = var.name(hierarchy)
    
    # Determine display format based on variable type
    display_format = DisplayFormat()
    
    var_type = str(var.var_type())
    is_single_bit = var.is_1bit()
    
    # Determine render type according to specification
    if var_type == "Event":
        display_format.render_type = RenderType.EVENT
    elif is_single_bit:
        display_format.render_type = RenderType.BOOL
    else:
        display_format.render_type = RenderType.BUS
    
    # Set appropriate data format based on var_type
    if var_type == "Real":
        display_format.render_type = RenderType.BUS
        display_format.data_format = DataFormat.FLOAT
    elif var_type in ["Integer", "Int", "ShortInt"]:
        # Signed integer types
        display_format.data_format = DataFormat.SIGNED
    elif is_single_bit:
        # Single bit - show as binary
        display_format.data_format = DataFormat.BIN
    elif not is_single_bit:
        # Multi-bit signal - default to hex
        display_format.data_format = DataFormat.HEX
    else:
        # Default to unsigned
        display_format.data_format = DataFormat.UNSIGNED
    
    # Create signal node
    node = SignalNode(
        name=full_name,
        handle=handle,
        format=display_format,
        nickname="",
        is_group=False,
        is_multi_bit=not is_single_bit  # Multi-bit if NOT 1-bit
    )
    
    return node

def create_sample_session(vcd_path: str, backend_preference: Literal["pyrox", "pylibfst"] = "pyrox") -> WaveformSession:
    """Create a sample WaveformSession with signals from a waveform file.

    Args:
        vcd_path: Path to the waveform file (VCD or FST)
        backend_preference: Preferred backend for FST files ("pyrox" or "pylibfst")
    """
    from .protocols import WaveformDBProtocol
    db = WaveformDB(backend_preference=backend_preference)
    db.open(vcd_path)
    session = WaveformSession()
    session.waveform_db = cast(WaveformDBProtocol, db)
    timescale = db.get_timescale()
    if timescale:
        session.timescale = timescale
    
    # Set the total duration from the waveform's time table
    time_table = db.get_time_table()
    if time_table and len(time_table) > 0:
        # The last time in the time table is the total duration in timescale units
        session.viewport.total_duration = time_table[-1]
    
    return session