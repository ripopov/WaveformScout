"""Helper functions to load waveforms and create signal nodes."""

import pyrox
from pyrox import SignalHandle

from .data_model import TreeNode, SignalNode, DisplayFormat, DataFormat, WaveformSession, RenderType
from .waveform_db import WaveformDB, AsyncLoadedSignal, Var


def create_signal_node_from_var(var: Var, hierarchy: pyrox.Hierarchy, handle: SignalHandle, waveform_db: WaveformDB) -> TreeNode:
    """Create a SignalNode from a backend variable."""
    # Get variable info using new path-based API
    local_name = var.name(hierarchy)  # Local identifier (may contain dots in VCD)
    scope_path = tuple(var.scope_path(hierarchy))  # Scope hierarchy as immutable tuple

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

    async_signal = AsyncLoadedSignal(handle, waveform_db)

    node = SignalNode(
        local_name=local_name,
        _waveform_scope=scope_path,  # Store waveform hierarchy scope
        var=var,  # Pass the var object directly
        handle=handle,
        signal=async_signal,
        format=display_format,
        nickname="",
        is_multi_bit=not is_single_bit  # Multi-bit if NOT 1-bit
    )

    return node

def create_sample_session(vcd_path: str) -> WaveformSession:
    """Create a sample WaveformSession with signals from a waveform file.

    Args:
        vcd_path: Path to the waveform file (VCD or FST)
    """
    from .waveform_db import WaveformDB
    db = WaveformDB()
    db.open(vcd_path)
    session = WaveformSession()

    # Use the new multi-file structure
    file_ref = session.add_waveform_file(vcd_path, db)

    # Set timescale from the file
    timescale = db.get_timescale()
    if timescale:
        session.timescale = timescale

    # Set the total duration from the waveform's time table
    # For VCD/FST: time_table contains all timestamps
    # For JETS: time_table is synthetic [0, max_time_from_capture_end_clk]
    time_table = db.get_time_table()
    if time_table and len(time_table) > 0:
        # The last time in the time table is the total duration in timescale units
        session.viewport.total_duration = time_table[-1]

    return session
