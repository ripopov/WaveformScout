"""Persistence module for saving and loading WaveformSession state."""

import json
import pathlib
import time
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional

from .data_model import (
    WaveformSession,
    TreeNode,
    GroupNode,
    SignalNode,
    DisplayFormat,
    DataFormat,
    GroupRenderMode,
    RenderType,
    Viewport,
    ViewportConfig,
    Marker,
    AnalysisMode,
    WaveformFileReference,
    Timescale,
    TimeUnit,
)
from ..utils.timing_utils import tprint
from .waveform_db import WaveformDB


def _serialize_node(node: TreeNode) -> Dict[str, Any]:
    """Serialize a SignalNode to a dictionary, handling nested children."""
    data: Dict[str, Any] = {
        'local_name': node.local_name,
        'scope_path': list(node.scope_path()),  # Convert tuple to list for JSON
        'nickname': node.nickname,
        'is_group': node.is_group,
        'height_scaling': node.height_scaling,
        'instance_id': node.instance_id,
    }

    if isinstance(node, SignalNode):
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
            'file_id': node.file_id,
            'group_render_mode': None,
            'is_expanded': True,
        })
    elif isinstance(node, GroupNode):
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

    if isinstance(node, GroupNode) and node.children:
        data['children'] = [_serialize_node(child) for child in node.children]
    
    return data


def _resolve_signal_handles(nodes: List[TreeNode], waveform_db: WaveformDB) -> List[int]:
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
    def resolve_node(node: TreeNode) -> None:
        if isinstance(node, SignalNode):
            # Always try to resolve the handle by path to ensure it's correct for this backend
            # Use path() to get the full path segments
            path_segments = node.path()
            handle = waveform_db.find_handle_by_path(path_segments)

            # If not found and local name has trailing spaces, try without spaces
            # (handles the case where pylibfst adds trailing spaces but pyrox doesn't)
            if handle is None and node.local_name.endswith(' '):
                trimmed_local_name = node.local_name.rstrip()
                trimmed_path = list(node.scope_path()) + [trimmed_local_name]
                handle = waveform_db.find_handle_by_path(trimmed_path)
                if handle is not None:
                    # Update the node local_name to match what this backend expects
                    # Need to create a new object since dataclass fields are supposed to be immutable
                    object.__setattr__(node, 'local_name', trimmed_local_name)

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

        if isinstance(node, GroupNode):
            for child in node.children:
                resolve_node(child)

    # Process all root nodes
    for node in nodes:
        resolve_node(node)

    return handles_to_load


def _deserialize_node(data: Dict[str, Any], waveform_db: Optional[WaveformDB], parent: Optional[GroupNode]) -> TreeNode:
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
        instance_id = TreeNode._generate_id()

    # Handle backward compatibility for old sessions with 'name' field
    # New sessions have 'local_name' and 'scope_path'
    if 'local_name' in data:
        local_name = data['local_name']
        scope_path = tuple(data.get('scope_path', []))
    else:
        # Old session format - split the name
        old_name = data['name']
        parts = old_name.split('.')
        if len(parts) > 1:
            local_name = parts[-1]
            scope_path = tuple(parts[:-1])
        else:
            local_name = old_name
            scope_path = ()

    if data.get('is_group', False):
        group_node = GroupNode(
            local_name=local_name,
            # Note: scope_path is computed from parent chain, not stored
            nickname=data.get('nickname', ''),
            parent=parent,
            height_scaling=data.get('height_scaling', 1),
            group_render_mode=group_render_mode,
            is_expanded=data.get('is_expanded', True),
            instance_id=instance_id,
        )

        children_data = data.get('children', [])
        for child_data in children_data:
            child = _deserialize_node(child_data, waveform_db=waveform_db, parent=group_node)
            group_node.children.append(child)

        return group_node

    # Get var from waveform_db if available
    handle = data.get('handle')

    # Import here to avoid circular dependency
    from .waveform_db import AsyncLoadedSignal, Var

    if waveform_db and handle is not None:
        var_from_db = waveform_db.get_var(handle)
        var = var_from_db if var_from_db is not None else Var.placeholder()
        signal = waveform_db.load_signal(handle)
    else:
        # Use placeholders when waveform_db is None or handle is None
        var = Var.placeholder()
        signal = AsyncLoadedSignal.placeholder(handle if handle is not None else -1)

    signal_node = SignalNode(
        local_name=local_name,
        _waveform_scope=scope_path,
        nickname=data.get('nickname', ''),
        parent=parent,
        height_scaling=data.get('height_scaling', 1),
        handle=handle,
        signal=signal,
        format=display_format if display_format is not None else DisplayFormat(),
        is_multi_bit=data.get('is_multi_bit', False),
        instance_id=instance_id,
        var=var,
        file_id=data.get('file_id', 0),  # Default to 0 for backward compatibility
    )

    return signal_node


def serialize_snippet_nodes(nodes: List[TreeNode], parent_scope: str) -> List[Dict[str, Any]]:
    """
    Serialize nodes for snippet storage, stripping absolute paths and setting handles to -1.

    Uses the new format with explicit local_name and scope_path fields to properly
    handle signals with dotted names.

    Args:
        nodes: List of SignalNode objects to serialize
        parent_scope: Common parent scope to strip from signal names

    Returns:
        List of serialized node dictionaries with relative names and invalid handles
    """
    serialized_nodes = []

    def serialize_for_snippet(node: TreeNode) -> Dict[str, Any]:
        """Serialize a single node for snippet storage."""
        format_dict = None
        if isinstance(node, SignalNode):
            format_dict = asdict(node.format)
            if 'data_format' in format_dict and isinstance(format_dict['data_format'], Enum):
                format_dict['data_format'] = format_dict['data_format'].value
            if 'render_type' in format_dict and isinstance(format_dict['render_type'], Enum):
                format_dict['render_type'] = format_dict['render_type'].value
            if 'analog_scaling_mode' in format_dict and isinstance(format_dict['analog_scaling_mode'], Enum):
                format_dict['analog_scaling_mode'] = format_dict['analog_scaling_mode'].value

        # Use new format with local_name and scope_path
        local_name = node.local_name
        scope_path_list = list(node.scope_path())

        # Make scope_path relative to parent_scope for snippets
        if parent_scope and isinstance(node, SignalNode):
            parent_parts = parent_scope.split('.')
            # Remove parent_scope prefix from scope_path if it matches
            if len(scope_path_list) >= len(parent_parts):
                if scope_path_list[:len(parent_parts)] == parent_parts:
                    scope_path_list = scope_path_list[len(parent_parts):]

        data: Dict[str, Any] = {
            'local_name': local_name,
            'scope_path': scope_path_list,
            'handle': -1 if isinstance(node, SignalNode) else None,
            'format': format_dict,
            'nickname': node.nickname,
            'is_group': node.is_group,
            'group_render_mode': node.group_render_mode.value if isinstance(node, GroupNode) and node.group_render_mode else None,
            'is_expanded': node.is_expanded if isinstance(node, GroupNode) else True,
            'height_scaling': node.height_scaling,
            'is_multi_bit': node.is_multi_bit if isinstance(node, SignalNode) else False,
        }

        if isinstance(node, GroupNode) and node.children:
            data['children'] = [serialize_for_snippet(child) for child in node.children]

        return data

    for node in nodes:
        serialized_nodes.append(serialize_for_snippet(node))

    return serialized_nodes


def deserialize_snippet_nodes_simple(data: List[Dict[str, Any]]) -> List[TreeNode]:
    """
    Deserialize snippet nodes without handle resolution (for loading snippets from disk).

    Args:
        data: List of serialized node dictionaries

    Returns:
        List of SignalNode objects with relative names
    """
    nodes = []
    for node_data in data:
        node = _deserialize_node(node_data, waveform_db=None, parent=None)
        nodes.append(node)
    return nodes


def deserialize_snippet_nodes(
    data: List[Dict[str, Any]],
    parent_scope: str,
    waveform_db: Optional[WaveformDB]
) -> Optional[tuple[List[TreeNode], List[int]]]:
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
        # When no waveform_db, just deserialize without resolving
        nodes = deserialize_snippet_nodes_simple(data)
        return (nodes, [])
    
    def deserialize_snippet_node(
        node_data: Dict[str, Any],
        parent: Optional[GroupNode] = None
    ) -> Optional[TreeNode]:
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
        # Handle backward compatibility for old snippets with 'name' field
        if 'local_name' in node_data:
            local_name = node_data['local_name']
            scope_path_list = list(node_data.get('scope_path', []))
        else:
            # Old snippet format - split the name
            old_name = node_data['name']
            parts = old_name.split('.')
            if len(parts) > 1:
                local_name = parts[-1]
                scope_path_list = parts[:-1]
            else:
                local_name = old_name
                scope_path_list = []

        is_group = node_data.get('is_group', False)
        handle: Optional[int] = None

        if not is_group:
            # Build full path with new parent scope
            if parent_scope:
                parent_scope_parts = parent_scope.split('.')
                full_path = parent_scope_parts + scope_path_list + [local_name]
            else:
                full_path = scope_path_list + [local_name]

            # Resolve handle from waveform database
            resolved_handle = waveform_db.find_handle_by_path(full_path)
            if resolved_handle is None:
                # Signal not found in waveform
                return None
            handle = resolved_handle

            # Update scope_path based on remapping
            if parent_scope:
                scope_path = tuple(parent_scope.split('.') + scope_path_list)
            else:
                scope_path = tuple(scope_path_list)
        else:
            # For groups, also update scope_path if parent_scope provided
            if parent_scope:
                scope_path = tuple(parent_scope.split('.') + scope_path_list)
            else:
                scope_path = tuple(scope_path_list)

        if is_group:
            group_node = GroupNode(
                local_name=local_name,
                # Note: scope_path is computed from parent chain, not stored
                nickname=node_data.get('nickname', ''),
                parent=parent,
                height_scaling=node_data.get('height_scaling', 1),
                group_render_mode=group_render_mode,
                is_expanded=node_data.get('is_expanded', True),
                instance_id=TreeNode._generate_id(),
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
        if handle is not None and waveform_db is not None:
            var = waveform_db.get_var(handle)

        if var is None:
            # Signal not found in waveform
            return None

        # Create AsyncLoadedSignal for the handle
        # waveform_db is guaranteed to be non-None here because we checked above
        # handle is also guaranteed to be non-None here due to the logic above
        assert waveform_db is not None
        assert handle is not None
        signal = waveform_db.load_signal(handle)

        signal_node = SignalNode(
            local_name=local_name,
            _waveform_scope=scope_path,
            nickname=node_data.get('nickname', ''),
            parent=parent,
            height_scaling=node_data.get('height_scaling', 1),
            handle=handle,
            signal=signal,
            format=display_format if display_format is not None else DisplayFormat(),
            is_multi_bit=node_data.get('is_multi_bit', False),
            instance_id=TreeNode._generate_id(),
            var=var,
        )

        return signal_node
    
    # Deserialize all root nodes
    result_nodes = []
    handles_to_load = []

    def collect_handles(node: TreeNode) -> None:
        """Collect handles that need async loading."""
        if isinstance(node, SignalNode) and node.handle is not None:
            # Create AsyncLoadedSignal for the handle
            if waveform_db:
                node.signal = waveform_db.load_signal(node.handle)
                # Track handles that need async loading
                if not node.signal.is_loaded():
                    handles_to_load.append(node.handle)
        if isinstance(node, GroupNode):
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

    # Serialize waveform files (multi-file format)
    waveform_files = []
    for file_ref in session.waveform_files:
        waveform_files.append({
            'file_id': file_ref.file_id,
            'file_path': file_ref.file_path,
            'timescale': {
                'factor': file_ref.timescale.factor,
                'unit': file_ref.timescale.unit.value
            }
        })

    # Serialize data
    data = {
        'waveform_files': waveform_files,
        'next_file_id': session.next_file_id,
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
        'version': '3.0',  # Bumped to 3.0 for multi-file support
        'generated': datetime.now().isoformat()
    }

    # Write JSON with indentation for readability
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def load_session(path: pathlib.Path) -> WaveformSession:
    """
    Deserialize JSON to dataclasses and reconnect to waveform DB.
    Supports both legacy (db_uri) and new multi-file format.

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

    # Detect format: new multi-file format or legacy single-file format
    waveform_files: List[WaveformFileReference] = []
    next_file_id = 0
    missing_files: List[str] = []
    max_duration = 0
    file_id_to_db: Dict[int, WaveformDB] = {}

    from wavescout.application.event_bus import EventBus
    event_bus = EventBus()

    if 'waveform_files' in data:
        # New multi-file format
        db_start = time.time()
        for file_data in data.get('waveform_files', []):
            file_id = file_data['file_id']
            file_path = file_data['file_path']

            if not pathlib.Path(file_path).exists():
                missing_files.append(file_path)
                tprint(f"  Warning: File not found: {file_path}")
                continue

            try:
                # Open WaveformDB
                waveform_db = WaveformDB(event_bus=event_bus)
                waveform_db.open(file_path)

                # Validate timescale against first file
                timescale_data = file_data['timescale']
                unit = TimeUnit.from_string(timescale_data['unit'])
                if not unit:
                    tprint(f"  Warning: Invalid timescale unit in file data: {timescale_data['unit']}")
                    continue

                expected_timescale = Timescale(factor=timescale_data['factor'], unit=unit)

                actual_timescale = waveform_db.get_timescale()
                if actual_timescale is None:
                    tprint(f"  Warning: No timescale available for {file_path}")
                    continue

                if waveform_files and (actual_timescale.factor != expected_timescale.factor or
                                       actual_timescale.unit != expected_timescale.unit):
                    tprint(f"  Error: Timescale mismatch for {file_path}")
                    continue

                # Create file reference
                file_ref = WaveformFileReference(
                    file_id=file_id,
                    file_path=file_path,
                    waveform_db=waveform_db,
                    timescale=actual_timescale
                )
                waveform_files.append(file_ref)
                file_id_to_db[file_id] = waveform_db

                # Track max duration
                time_table = waveform_db.get_time_table()
                if time_table and len(time_table) > 0:
                    end_time = time_table[-1]
                    if end_time > max_duration:
                        max_duration = end_time

            except Exception as e:
                tprint(f"  Error loading file {file_path}: {e}")
                missing_files.append(file_path)

        next_file_id = data.get('next_file_id', len(waveform_files))
        tprint(f"  load_session.open_waveform_dbs: {time.time() - db_start:.3f}s")

    else:
        # Legacy single-file format - convert to multi-file format
        tprint("  Detected legacy session format, upgrading...")
        db_uri = data.get('db_uri')
        if db_uri and pathlib.Path(db_uri).exists():
            db_start = time.time()
            waveform_db = WaveformDB(event_bus=event_bus)
            waveform_db.open(db_uri)

            timescale = waveform_db.get_timescale()
            if timescale is None:
                # Default to picoseconds if no timescale available
                timescale = Timescale(1, TimeUnit.PICOSECONDS)

            file_ref = WaveformFileReference(
                file_id=0,
                file_path=db_uri,
                waveform_db=waveform_db,
                timescale=timescale
            )
            waveform_files.append(file_ref)
            file_id_to_db[0] = waveform_db
            next_file_id = 1

            time_table = waveform_db.get_time_table()
            if time_table and len(time_table) > 0:
                max_duration = time_table[-1]

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

    # Deserialize nodes - pass None for waveform_db, will resolve handles later per file
    nodes_start = time.time()
    root_nodes = []
    for node_data in data.get('root_nodes', []):
        node = _deserialize_node(node_data, waveform_db=None, parent=None)
        root_nodes.append(node)
    tprint(f"  load_session.deserialize_nodes ({len(root_nodes)} root nodes): {time.time() - nodes_start:.3f}s")

    # Create session
    session_start = time.time()
    session = WaveformSession(
        waveform_files=waveform_files,
        next_file_id=next_file_id,
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
        unit = TimeUnit.from_string(timescale_data['unit'])
        if unit:
            session.timescale = Timescale(
                factor=timescale_data['factor'],
                unit=unit
            )
    # If timescale not in saved data but waveform_files is loaded, get it from first file
    elif waveform_files:
        session.timescale = waveform_files[0].timescale

    # Resolve signal handles per file
    handles_to_load_by_file: Dict[int, List[int]] = {}

    def resolve_node_handles(node: TreeNode) -> None:
        """Resolve handles for a node, looking up the correct WaveformDB by file_id."""
        if isinstance(node, SignalNode):
            file_id = node.file_id
            waveform_db = file_id_to_db.get(file_id)

            if waveform_db:
                # Try to resolve the handle by path
                path_segments = node.path()
                handle = waveform_db.find_handle_by_path(path_segments)

                # If not found and local name has trailing spaces, try without spaces
                if handle is None and node.local_name.endswith(' '):
                    trimmed_local_name = node.local_name.rstrip()
                    trimmed_path = list(node.scope_path()) + [trimmed_local_name]
                    handle = waveform_db.find_handle_by_path(trimmed_path)
                    if handle is not None:
                        # Update the node local_name to match what this backend expects
                        object.__setattr__(node, 'local_name', trimmed_local_name)

                # Update the handle if we found it
                if handle is not None:
                    node.handle = handle
                    node.signal = waveform_db.load_signal(handle)

                    # Track handles that need async loading
                    if not node.signal.is_loaded():
                        if file_id not in handles_to_load_by_file:
                            handles_to_load_by_file[file_id] = []
                        handles_to_load_by_file[file_id].append(handle)

                    # Update the var field
                    var = waveform_db.get_var(handle)
                    if var is not None:
                        node.var = var

        if isinstance(node, GroupNode):
            for child in node.children:
                resolve_node_handles(child)

    # Process all root nodes
    for node in root_nodes:
        resolve_node_handles(node)

    # Trigger async loading for all handles
    for file_id, handles in handles_to_load_by_file.items():
        db = file_id_to_db.get(file_id)
        if db and handles:
            for handle in handles:
                db.load_signal(handle)

    # Update viewport total_duration from max of all loaded files
    if max_duration > 0:
        session.viewport.total_duration = max_duration
    
    # Update the SignalNode counter to avoid ID conflicts
    # Find the maximum instance_id in all loaded nodes
    def find_max_instance_id(nodes: List[TreeNode]) -> int:
        max_id = 0
        for node in nodes:
            if getattr(node, 'instance_id', None) is not None:
                max_id = max(max_id, node.instance_id)
            if isinstance(node, GroupNode):
                max_id = max(max_id, find_max_instance_id(node.children))
        return max_id
    
    max_instance_id = find_max_instance_id(root_nodes)
    if max_instance_id > 0:
        TreeNode._id_counter = max_instance_id
    
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


def _find_node_by_id(nodes: List[TreeNode], node_id: int) -> Optional[TreeNode]:
    """Find a node by its instance ID in a tree of nodes."""
    for node in nodes:
        if node.instance_id == node_id:
            return node
        if isinstance(node, GroupNode):
            found = _find_node_by_id(node.children, node_id)
            if found:
                return found
    return None
