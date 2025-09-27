"""Persistence module for saving and loading WaveformSession state."""

import json
import pathlib
import time
from typing import Dict, Any, List, Optional, cast
from .timing_utils import tprint
from dataclasses import asdict
from enum import Enum
from datetime import datetime
import pyrox
from .waveform_db import WaveformDB
from .data_model import (
    WaveformSession,
    SignalNode,
    SignalNodeGroup,
    SignalNodeSignal,
    DisplayFormat,
    DataFormat,
    GroupRenderMode,
    RenderType,
    Viewport,
    ViewportConfig,
    Marker,
    AnalysisMode,
)
from .waveform_db import WaveformDB


def _serialize_node(node: SignalNode) -> Dict[str, Any]:
    """Serialize a SignalNode to a dictionary, handling nested children."""
    data: Dict[str, Any] = {
        'name': node.name,
        'nickname': node.nickname,
        'is_group': node.is_group,
        'height_scaling': node.height_scaling,
        'instance_id': node.instance_id,
    }

    if isinstance(node, SignalNodeSignal):
        format_dict = asdict(node.format)
        if 'data_format' in format_dict and isinstance(format_dict['data_format'], Enum):
            format_dict['data_format'] = format_dict['data_format'].value
        if 'render_type' in format_dict and isinstance(format_dict['render_type'], Enum):
            format_dict['render_type'] = format_dict['render_type'].value
        if 'analog_scaling_mode' in format_dict and isinstance(format_dict['analog_scaling_mode'], Enum):
            format_dict['analog_scaling_mode'] = format_dict['analog_scaling_mode'].value

        data.update({
            'handle': node.handle,
            'format': format_dict,
            'is_multi_bit': node.is_multi_bit,
            'group_render_mode': None,
            'is_expanded': True,
        })
    elif isinstance(node, SignalNodeGroup):
        data.update({
            'handle': None,
            'format': None,
            'is_multi_bit': False,
            'group_render_mode': node.group_render_mode.value if node.group_render_mode else None,
            'is_expanded': node.is_expanded,
        })
    else:
        # Shouldn't happen but handle gracefully
        data.update({
            'handle': None,
            'format': None,
            'is_multi_bit': False,
            'group_render_mode': None,
            'is_expanded': True,
        })

    if isinstance(node, SignalNodeGroup) and node.children:
        data['children'] = [_serialize_node(child) for child in node.children]
    
    return data


def _resolve_signal_handles(nodes: List[SignalNode], waveform_db: WaveformDB) -> List[int]:
    """Resolve signal handles for all nodes to ensure they're correct for the current backend.

    This is crucial when loading sessions across different backends (pylibfst vs pyrox)
    since they may have different handle assignments and signal name formats.

    Returns:
        List of handles that need to be loaded asynchronously
    """
    if not waveform_db:
        return []

    handles_to_load: List[int] = []

    # Recursively resolve handles using the current backend's find_handle_by_path
    def resolve_node(node: SignalNode) -> None:
        if isinstance(node, SignalNodeSignal):
            # Always try to resolve the handle by name to ensure it's correct for this backend
            # First try with the exact name
            handle = waveform_db.find_handle_by_path(node.name)

            # If not found and name has trailing spaces, try without spaces
            # (handles the case where pylibfst adds trailing spaces but pyrox doesn't)
            if handle is None and node.name.endswith(' '):
                trimmed_name = node.name.rstrip()
                handle = waveform_db.find_handle_by_path(trimmed_name)
                if handle is not None:
                    # Update the node name to match what this backend expects
                    node.name = trimmed_name

            # Update the handle if we found it
            if handle is not None:
                node.handle = handle
                # Create AsyncLoadedSignal for the handle
                node.signal = waveform_db.load_signal(handle)
                # Check if already loaded (cached)
                if not node.signal.is_loaded():
                    handles_to_load.append(handle)
                # Also update the var field
                var = waveform_db.get_var(handle)
                if var is not None:
                    node.var = var
            # If still None, keep the existing handle (may work for aliases)

        if isinstance(node, SignalNodeGroup):
            for child in node.children:
                resolve_node(child)

    # Process all root nodes
    for node in nodes:
        resolve_node(node)

    return handles_to_load


def _deserialize_node(data: Dict[str, Any], parent: Optional[SignalNodeGroup] = None, waveform_db: Optional['WaveformDB'] = None) -> SignalNode:
    """Deserialize a dictionary to a SignalNode, handling nested children."""
    # Create display format if present
    format_data = data.get('format')
    display_format = None
    if format_data:
        # Convert string enum values back to enums
        if 'data_format' in format_data and isinstance(format_data['data_format'], str):
            format_data['data_format'] = DataFormat(format_data['data_format'])
        if 'render_type' in format_data and isinstance(format_data['render_type'], str):
            format_data['render_type'] = RenderType(format_data['render_type'])
        if 'analog_scaling_mode' in format_data and isinstance(format_data['analog_scaling_mode'], str):
            from .data_model import AnalogScalingMode
            format_data['analog_scaling_mode'] = AnalogScalingMode(format_data['analog_scaling_mode'])
        display_format = DisplayFormat(**format_data)
    
    # Convert group_render_mode string back to enum
    group_render_mode = None
    if data.get('group_render_mode'):
        group_render_mode = GroupRenderMode(data['group_render_mode'])
    
    # Create node - handle backward compatibility for instance_id
    # If instance_id is not present in saved data, generate a new one
    if 'instance_id' in data:
        instance_id = data['instance_id']
    else:
        # For backward compatibility, generate a new ID
        instance_id = SignalNode._generate_id()

    if data.get('is_group', False):
        group_node = SignalNodeGroup(
            name=data['name'],
            nickname=data.get('nickname', ''),
            parent=parent,
            height_scaling=data.get('height_scaling', 1),
            group_render_mode=group_render_mode,
            is_expanded=data.get('is_expanded', True),
            instance_id=instance_id,
        )

        children_data = data.get('children', [])
        for child_data in children_data:
            child = _deserialize_node(child_data, parent=group_node, waveform_db=waveform_db)
            group_node.children.append(child)

        return group_node

    # Get var from waveform_db if available
    handle = data.get('handle')
    var = None
    if waveform_db and handle is not None:
        var = waveform_db.get_var(handle)

    signal = waveform_db.load_signal(handle)

    signal_node = SignalNodeSignal(
        name=data['name'],
        nickname=data.get('nickname', ''),
        parent=parent,
        height_scaling=data.get('height_scaling', 1),
        handle=handle,
        signal=signal,
        format=display_format if display_format is not None else DisplayFormat(),
        is_multi_bit=data.get('is_multi_bit', False),
        instance_id=instance_id,
        var=var,  # type: ignore[arg-type]  # Will be resolved in resolve_node
    )

    return signal_node


def serialize_snippet_nodes(nodes: List[SignalNode], parent_scope: str) -> List[Dict[str, Any]]:
    """
    Serialize nodes for snippet storage, stripping absolute paths and setting handles to -1.
    
    Args:
        nodes: List of SignalNode objects to serialize
        parent_scope: Common parent scope to strip from signal names
    
    Returns:
        List of serialized node dictionaries with relative names and invalid handles
    """
    serialized_nodes = []
    
    def serialize_for_snippet(node: SignalNode) -> Dict[str, Any]:
        """Serialize a single node for snippet storage."""
        format_dict = None
        if isinstance(node, SignalNodeSignal):
            format_dict = asdict(node.format)
            if 'data_format' in format_dict and isinstance(format_dict['data_format'], Enum):
                format_dict['data_format'] = format_dict['data_format'].value
            if 'render_type' in format_dict and isinstance(format_dict['render_type'], Enum):
                format_dict['render_type'] = format_dict['render_type'].value
            if 'analog_scaling_mode' in format_dict and isinstance(format_dict['analog_scaling_mode'], Enum):
                format_dict['analog_scaling_mode'] = format_dict['analog_scaling_mode'].value
        
        name = node.name
        if isinstance(node, SignalNodeSignal) and parent_scope:
            if name.startswith(parent_scope + "."):
                name = name[len(parent_scope) + 1:]
        
        data: Dict[str, Any] = {
            'name': name,
            'handle': -1 if isinstance(node, SignalNodeSignal) else None,
            'format': format_dict,
            'nickname': node.nickname,
            'is_group': node.is_group,
            'group_render_mode': node.group_render_mode.value if isinstance(node, SignalNodeGroup) and node.group_render_mode else None,
            'is_expanded': node.is_expanded if isinstance(node, SignalNodeGroup) else True,
            'height_scaling': node.height_scaling,
            'is_multi_bit': node.is_multi_bit if isinstance(node, SignalNodeSignal) else False,
        }
        
        if isinstance(node, SignalNodeGroup) and node.children:
            data['children'] = [serialize_for_snippet(child) for child in node.children]
        
        return data
    
    for node in nodes:
        serialized_nodes.append(serialize_for_snippet(node))
    
    return serialized_nodes


def deserialize_snippet_nodes(
    data: List[Dict[str, Any]],
    parent_scope: str,
    waveform_db: Optional[WaveformDB]
) -> Optional[tuple[List[SignalNode], List[int]]]:
    """
    Deserialize snippet nodes with scope remapping and handle resolution.
    
    Args:
        data: List of serialized node dictionaries
        parent_scope: New parent scope to prepend to signal names
        waveform_db: WaveformDB instance to resolve handles from
    
    Returns:
        Tuple of (List of SignalNode objects with remapped names and resolved handles,
        List of handles that need async loading), or None if any signal cannot be found
    """
    if not waveform_db:
        return None
    
    def deserialize_snippet_node(
        node_data: Dict[str, Any],
        parent: Optional[SignalNodeGroup] = None
    ) -> Optional[SignalNode]:
        """Deserialize a single snippet node with remapping."""
        # Create display format if present
        format_data = node_data.get('format')
        display_format = None
        if format_data:
            # Convert string enum values back to enums
            if 'data_format' in format_data and isinstance(format_data['data_format'], str):
                format_data['data_format'] = DataFormat(format_data['data_format'])
            if 'render_type' in format_data and isinstance(format_data['render_type'], str):
                format_data['render_type'] = RenderType(format_data['render_type'])
            if 'analog_scaling_mode' in format_data and isinstance(format_data['analog_scaling_mode'], str):
                from .data_model import AnalogScalingMode
                format_data['analog_scaling_mode'] = AnalogScalingMode(format_data['analog_scaling_mode'])
            display_format = DisplayFormat(**format_data)
        
        # Convert group_render_mode string back to enum
        group_render_mode = None
        if node_data.get('group_render_mode'):
            group_render_mode = GroupRenderMode(node_data['group_render_mode'])
        
        # Remap name and resolve handle for non-group nodes
        name = node_data['name']
        is_group = node_data.get('is_group', False)
        handle: Optional[int] = None
        
        if not is_group:
            # Build full name with new parent scope
            if parent_scope:
                name = f"{parent_scope}.{name}"
            
            # Resolve handle from waveform database
            resolved_handle = waveform_db.find_handle_by_path(name)
            if resolved_handle is None:
                # Signal not found in waveform
                return None
            handle = resolved_handle

        if is_group:
            group_node = SignalNodeGroup(
                name=name,
                nickname=node_data.get('nickname', ''),
                parent=parent,
                height_scaling=node_data.get('height_scaling', 1),
                group_render_mode=group_render_mode,
                is_expanded=node_data.get('is_expanded', True),
                instance_id=SignalNode._generate_id(),
            )

            children_data = node_data.get('children', [])
            for child_data in children_data:
                child = deserialize_snippet_node(child_data, parent=group_node)
                if child is None:
                    return None
                group_node.children.append(child)

            return group_node

        # Get var from waveform_db (we know it's available in this context)
        var = None
        if handle is not None:
            var = waveform_db.get_var(handle)

        if var is None:
            # Signal not found in waveform
            return None

        # Create AsyncLoadedSignal for the handle
        signal = waveform_db.load_signal(handle)

        signal_node = SignalNodeSignal(
            name=name,
            nickname=node_data.get('nickname', ''),
            parent=parent,
            height_scaling=node_data.get('height_scaling', 1),
            handle=handle,
            signal=signal,
            format=display_format if display_format is not None else DisplayFormat(),
            is_multi_bit=node_data.get('is_multi_bit', False),
            instance_id=SignalNode._generate_id(),
            var=var,
        )

        return signal_node
    
    # Deserialize all root nodes
    result_nodes = []
    handles_to_load = []

    def collect_handles(node: SignalNode) -> None:
        """Collect handles that need async loading."""
        if isinstance(node, SignalNodeSignal) and node.handle is not None:
            # Create AsyncLoadedSignal for the handle
            if waveform_db:
                node.signal = waveform_db.load_signal(node.handle)
                # Track handles that need async loading
                if not node.signal.is_loaded():
                    handles_to_load.append(node.handle)
        if isinstance(node, SignalNodeGroup):
            for child in node.children:
                collect_handles(child)

    for node_data in data:
        node = deserialize_snippet_node(node_data)
        if node is None:
            return None  # At least one signal not found
        collect_handles(node)
        result_nodes.append(node)

    return result_nodes, handles_to_load


def save_session(session: WaveformSession, path: pathlib.Path) -> None:
    """
    Serialize session to JSON, excluding waveform_db pointer
    but preserving its URI for reconnection.
    """
    # Ensure .json extension
    if not path.suffix.lower() == '.json':
        path = path.with_suffix('.json')
    
    # Get database URI if available (file_path is an optional property)
    db_uri = None
    if session.waveform_db:
        db_uri = getattr(session.waveform_db, 'file_path', None)
    
    # Serialize data
    data = {
        'db_uri': db_uri,
        'root_nodes': [_serialize_node(node) for node in session.root_nodes],
        'viewport': asdict(session.viewport),
        'markers': [asdict(marker) for marker in session.markers],
        'cursor_time': session.cursor_time,
        'analysis_mode': asdict(session.analysis_mode),
        # Note: selected_nodes are not persisted as they are transient UI state
    }
    
    # Add timescale if available
    if session.timescale:
        data['timescale'] = {
            'factor': session.timescale.factor,
            'unit': session.timescale.unit.value
        }
    
    # Add clock signal if available
    if session.clock_signal:
        clock_period, phase_offset, clock_node = session.clock_signal
        data['clock_signal'] = {
            'period': clock_period,
            'phase_offset': phase_offset,
            'node_id': clock_node.instance_id  # Store node ID for reconnection
        }
    
    # Add sampling signal if available
    if session.sampling_signal:
        data['sampling_signal'] = {
            'node_id': session.sampling_signal.instance_id  # Store node ID for reconnection
        }
    
    # Add metadata
    data['_metadata'] = {
        'version': '2.0',
        'generated': datetime.now().isoformat()
    }
    
    # Write JSON with indentation for readability
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def load_session(path: pathlib.Path) -> WaveformSession:
    """
    Deserialize JSON to dataclasses and reconnect to waveform DB.

    Args:
        path: Path to the session file
    """
    load_start = time.time()

    # Check file extension
    if not path.suffix.lower() == '.json':
        raise ValueError(f"Expected .json file, got {path.suffix}")

    # Read JSON
    json_start = time.time()
    with open(path, 'r') as f:
        data = json.load(f)
    tprint(f"  load_session.read_json: {time.time() - json_start:.3f}s")

    # Reconnect to waveform database if URI is provided
    waveform_db = None
    db_uri = data.get('db_uri')
    if db_uri and pathlib.Path(db_uri).exists():
        db_start = time.time()
        # Create WaveformDB with EventBus for async loading to work
        from wavescout.application.event_bus import EventBus
        event_bus = EventBus()
        waveform_db = WaveformDB(event_bus=event_bus)
        waveform_db.open(db_uri)
        tprint(f"  load_session.open_waveform_db: {time.time() - db_start:.3f}s")

    # Deserialize viewport
    viewport_start = time.time()
    viewport_data = data.get('viewport', {})
    # Extract config data and create ViewportConfig object
    config_data = viewport_data.pop('config', {})
    viewport_config = ViewportConfig(**config_data)
    # Create viewport with proper config object
    viewport = Viewport(**viewport_data, config=viewport_config)
    tprint(f"  load_session.deserialize_viewport: {time.time() - viewport_start:.3f}s")

    # Deserialize markers
    markers_start = time.time()
    markers = []
    for marker_data in data.get('markers', []):
        markers.append(Marker(**marker_data))
    tprint(f"  load_session.deserialize_markers: {time.time() - markers_start:.3f}s")

    # Deserialize analysis mode
    analysis_data = data.get('analysis_mode', {})
    analysis_mode = AnalysisMode(**analysis_data)

    # Deserialize nodes
    nodes_start = time.time()
    root_nodes = []
    for node_data in data.get('root_nodes', []):
        node = _deserialize_node(node_data, waveform_db=waveform_db)
        root_nodes.append(node)
    tprint(f"  load_session.deserialize_nodes ({len(root_nodes)} root nodes): {time.time() - nodes_start:.3f}s")

    # Create session
    session_start = time.time()
    session = WaveformSession(
        waveform_db=waveform_db if waveform_db else None,
        root_nodes=root_nodes,
        viewport=viewport,
        markers=markers,
        cursor_time=data.get('cursor_time', 0),
        analysis_mode=analysis_mode,
        selected_nodes=[]  # Start with empty selection
    )
    tprint(f"  load_session.create_session: {time.time() - session_start:.3f}s")

    # Restore timescale if available
    timescale_data = data.get('timescale')
    if timescale_data:
        from .data_model import TimeUnit, Timescale
        unit = TimeUnit.from_string(timescale_data['unit'])
        if unit:
            session.timescale = Timescale(
                factor=timescale_data['factor'],
                unit=unit
            )
    # If timescale not in saved data but waveform_db is loaded, get it from there
    elif waveform_db:
        timescale = waveform_db.get_timescale()
        if timescale:
            session.timescale = timescale
    
    # Resolve signal handles if waveform_db is available
    handles_to_load: List[int] = []
    if waveform_db:
        handles_to_load = _resolve_signal_handles(session.root_nodes, waveform_db)

        if handles_to_load:
            for handle in handles_to_load:
                waveform_db.load_signal(handle)

        # Update viewport total_duration from the waveform's time table
        time_table = waveform_db.get_time_table()
        if time_table and len(time_table) > 0:
            # The last time in the time table is the total duration in timescale units
            session.viewport.total_duration = time_table[-1]
    
    # Update the SignalNode counter to avoid ID conflicts
    # Find the maximum instance_id in all loaded nodes
    def find_max_instance_id(nodes: List[SignalNode]) -> int:
        max_id = 0
        for node in nodes:
            if getattr(node, 'instance_id', None) is not None:
                max_id = max(max_id, node.instance_id)
            if isinstance(node, SignalNodeGroup):
                max_id = max(max_id, find_max_instance_id(node.children))
        return max_id
    
    max_instance_id = find_max_instance_id(root_nodes)
    if max_instance_id > 0:
        SignalNode._id_counter = max_instance_id
    
    # Restore clock signal if available
    clock_data = data.get('clock_signal')
    if clock_data:
        clock_period = clock_data.get('period')
        phase_offset = clock_data.get('phase_offset', 0)  # Default to 0 for old sessions
        clock_node_id = clock_data.get('node_id')
        
        # Find the node by ID
        if clock_period is not None and clock_node_id is not None:
            clock_node = _find_node_by_id(root_nodes, clock_node_id)
            if clock_node:
                session.clock_signal = (clock_period, phase_offset, clock_node)
    
    # Restore sampling signal if available
    sampling_data = data.get('sampling_signal')
    if sampling_data:
        sampling_node_id = sampling_data.get('node_id')
        
        # Find the node by ID
        if sampling_node_id is not None:
            sampling_node = _find_node_by_id(root_nodes, sampling_node_id)
            if sampling_node:
                session.sampling_signal = sampling_node
    
    tprint(f"  load_session TOTAL: {time.time() - load_start:.3f}s")
    return session


def _find_node_by_id(nodes: List[SignalNode], node_id: int) -> Optional[SignalNode]:
    """Find a node by its instance ID in a tree of nodes."""
    for node in nodes:
        if node.instance_id == node_id:
            return node
        if isinstance(node, SignalNodeGroup):
            found = _find_node_by_id(node.children, node_id)
            if found:
                return found
    return None
