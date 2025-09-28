"""WaveformController: A thin non-Qt view-model/controller for UI coordination.

This controller owns the current WaveformSession and exposes basic operations
for viewport manipulation, selection updates, cursor updates, and benchmark mode.

It uses a simple callback-based notification mechanism (no Qt dependencies) so
it can be unit-tested easily. UI widgets (like WaveScoutWidget) can subscribe to
these callbacks and update their views accordingly.
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Iterable, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from pyrox import Signal

from .data_model import (
    WaveformSession,
    Viewport,
    SignalNode,
    SignalNodeGroup,
    SignalNodeSignal,
    Marker,
    Time,
    SignalNodeID,
    DataFormat,
    GroupRenderMode,
    DisplayFormat,
    RenderType,
)
from .clock_utils import calculate_clock_period, is_valid_clock_signal
from . import config
MARKER_LABELS = config.MARKER_LABELS
RENDERING = config.RENDERING
from .application.event_bus import EventBus
from .application.events import (
    Event, StructureChangedEvent, FormatChangedEvent, ViewportChangedEvent,
    CursorMovedEvent, SelectionChangedEvent, MarkerAddedEvent, MarkerRemovedEvent,
    MarkerMovedEvent, SessionLoadedEvent, SessionClosedEvent, FormatChanges,
    SignalLoadingStartedEvent, SignalLoadedEvent, SignalLoadingFailedEvent
)
from pyrox import SignalHandle
from .timing_utils import tprint


Callback = Callable[[], None]


@dataclass
class WaveformController:
    """Non-Qt controller for coordinating waveform UI state.

    Responsibilities:
    - Own and expose current session reference.
    - Own and manipulate viewport through operations (zoom/pan/fit/start/end).
    - Track selection (by SignalNode instance IDs) and benchmark mode flag.
    - Provide simple callback hooks to notify views of state changes.

    Notes:
    - Selection is stored as a set of node instance IDs to decouple the view
      from holding object references. The Session still maintains selected_nodes
      (List[SignalNode]) for backward compatibility; this controller will
      synchronize it when set_selection_by_ids is used.
    """

    session: Optional[WaveformSession] = None
    _selected_ids: Set[int] = field(default_factory=set)
    event_bus: EventBus = field(default_factory=EventBus)

    # Simple event callbacks registry (kept for backward compatibility)
    _callbacks: Dict[str, List[Callback]] = field(default_factory=lambda: {
        "session_changed": [],
        "viewport_changed": [],
        "selection_changed": [],
        "cursor_changed": [],
        "markers_changed": [],
        "signals_loading": [],
        "signals_loaded": [],
    })

    def __post_init__(self) -> None:
        """Subscribe to async loading events."""
        self.event_bus.subscribe(SignalLoadingStartedEvent, self._on_signal_loading_started)
        self.event_bus.subscribe(SignalLoadedEvent, self._on_signal_loaded)
        self.event_bus.subscribe(SignalLoadingFailedEvent, self._on_signal_loading_failed)

    # ---- Subscription API ----
    def on(self, event_name: str, callback: Callback) -> None:
        if event_name not in self._callbacks:
            self._callbacks[event_name] = []
        self._callbacks[event_name].append(callback)

    def off(self, event_name: str, callback: Callback) -> None:
        if event_name in self._callbacks:
            try:
                self._callbacks[event_name].remove(callback)
            except ValueError:
                pass

    def _emit(self, event_name: str) -> None:
        for cb in self._callbacks.get(event_name, []):
            try:
                cb()
            except Exception:
                # Fail-safe: do not propagate exceptions from UI callbacks
                pass

    # ---- Session / selection ----
    def set_session(self, session: WaveformSession) -> None:
        tprint("[CONTROLLER] set_session called")
        self.session = session

        # Hook up event bus to WaveformDB if it doesn't have one
        # This is crucial for sessions loaded in background threads
        if session and session.waveform_db:
            tprint("[CONTROLLER] Session has waveform_db")
            # We need to access internal WaveformDB attributes, so check if it's the actual class
            # not just the protocol
            from wavescout.waveform_db import WaveformDB, AsyncEventBridge
            if isinstance(session.waveform_db, WaveformDB):
                waveform_db = session.waveform_db
                tprint("[CONTROLLER] WaveformDB instance detected")
                tprint(f"[CONTROLLER] WaveformDB._event_bus = {waveform_db._event_bus}")
                tprint(f"[CONTROLLER] WaveformDB._event_bridge = {waveform_db._event_bridge}")

                # Check if WaveformDB lacks an event bridge
                if hasattr(waveform_db, '_event_bus') and waveform_db._event_bus is None:
                    tprint("[CONTROLLER] WaveformDB lacks event bus, hooking up...")
                    # Hook up our event bus
                    waveform_db._event_bus = self.event_bus
                    # Create event bridge for thread-safe async callbacks
                    waveform_db._event_bridge = AsyncEventBridge(self.event_bus)
                    # Re-register async callback if waveform is loaded
                    if waveform_db.waveform:
                        tprint("[CONTROLLER] Re-registering async callback")
                        waveform_db.waveform.set_async_callback(waveform_db._on_async_event)

                    # If there are signals that were supposed to load async but didn't
                    # because there was no event bus, re-trigger their loading
                    if hasattr(waveform_db, '_loading_handles') and waveform_db._loading_handles:
                        # Handles that are marked as loading but haven't loaded yet
                        handles_to_reload = list(waveform_db._loading_handles)
                        if handles_to_reload:
                            tprint(f"[CONTROLLER] Re-triggering loading for {len(handles_to_reload)} handles")
                            # Clear the loading set and re-trigger
                            waveform_db._loading_handles.clear()
                            waveform_db.load_signals_async(handles_to_reload)
                else:
                    tprint("[CONTROLLER] WaveformDB already has event bus, skipping hookup")

        # Sync selected IDs from session.selected_nodes
        self._selected_ids = {n.instance_id for n in session.selected_nodes}
        self._emit("session_changed")
        # Also emit viewport and cursor to allow immediate refresh
        self._emit("viewport_changed")
        self._emit("cursor_changed")

    def set_selection_by_ids(self, ids: Iterable[int]) -> None:
        """Set selection given node instance IDs; sync Session.selected_nodes."""
        if not self.session:
            return
        new_ids = set(ids)
        if new_ids == self._selected_ids:
            return
        old_ids = list(self._selected_ids)
        self._selected_ids = new_ids
        # Rebuild session.selected_nodes in document order
        selected: List[SignalNode] = []
        for node in self._iter_all_nodes():
            if node.instance_id in self._selected_ids:
                selected.append(node)
        self.session.selected_nodes = selected
        self.event_bus.publish(SelectionChangedEvent(
            old_selection=old_ids,
            new_selection=list(new_ids)
        ))
        self._emit("selection_changed")

    def get_selected_ids(self) -> Set[int]:
        return set(self._selected_ids)

    # ---- Cursor / benchmark ----
    def set_cursor_time(self, time_value: int) -> None:
        if not self.session:
            return
        old_time = self.session.cursor_time
        if old_time != time_value:
            self.session.cursor_time = int(time_value)
            self.event_bus.publish(CursorMovedEvent(
                old_time=old_time,
                new_time=int(time_value)
            ))
            self._emit("cursor_changed")

    # ---- Marker operations ----
    def add_marker(self, index: int, time: Time, color: Optional[str] = None) -> None:
        """Add or update a marker at the specified index (0-8)."""
        if not self.session or index < 0 or index >= len(MARKER_LABELS):
            return
        
        # Ensure markers list is large enough
        while len(self.session.markers) <= index:
            # Extend with placeholder markers
            self.session.markers.append(Marker(time=0, label="", color=""))
        
        # Use default color if not specified
        if color is None:
            # Use existing marker color if updating, otherwise use default
            existing = self.session.markers[index]
            if existing and existing.color:
                color = existing.color
            else:
                color = config.COLORS.MARKER_DEFAULT_COLOR
        
        # Create or update marker
        label = MARKER_LABELS[index]
        self.session.markers[index] = Marker(time=time, label=label, color=color)
        self._emit("markers_changed")
    
    def remove_marker(self, index: int) -> None:
        """Remove marker at the specified index."""
        if not self.session or index < 0 or index >= len(self.session.markers):
            return
        
        if index < len(self.session.markers):
            # Replace with placeholder instead of None
            self.session.markers[index] = Marker(time=-1, label="", color="")
            self._emit("markers_changed")
    
    def update_marker_time(self, index: int, time: Time) -> None:
        """Update the timestamp of a marker."""
        if not self.session or index < 0 or index >= len(self.session.markers):
            return
        
        if index < len(self.session.markers):
            marker = self.session.markers[index]
            if marker and marker.time >= 0:  # Check if it's a valid marker
                marker.time = time
                self._emit("markers_changed")
    
    def update_marker_color(self, index: int, color: str) -> None:
        """Update the color of a marker."""
        if not self.session or index < 0 or index >= len(self.session.markers):
            return
        
        if index < len(self.session.markers):
            marker = self.session.markers[index]
            if marker and marker.time >= 0:  # Check if it's a valid marker
                marker.color = color
                self._emit("markers_changed")
    
    def get_marker(self, index: int) -> Optional[Marker]:
        """Get marker at the specified index."""
        if not self.session or index < 0 or index >= len(MARKER_LABELS):
            return None
        
        if index < len(self.session.markers):
            marker = self.session.markers[index]
            # Return None for placeholder markers
            if marker and marker.time >= 0:
                return marker
        return None
    
    def toggle_marker_at_cursor(self, index: int) -> None:
        """Toggle a marker at the current cursor position."""
        if not self.session or index < 0 or index >= len(MARKER_LABELS):
            return
        
        cursor_time = self.session.cursor_time
        existing_marker = self.get_marker(index)
        
        # Toggle behavior: remove if exists at same time, otherwise add/update
        if existing_marker and existing_marker.time == cursor_time:
            self.remove_marker(index)
        else:
            self.add_marker(index, cursor_time)
    
    def navigate_to_marker(self, index: int, pixel_offset: Optional[int] = None, canvas_width: Optional[int] = None) -> None:
        """Navigate viewport to show marker at specified pixel offset from left edge.
        
        Args:
            index: Marker index (0-8)
            pixel_offset: Distance in pixels from left edge of viewport (uses MARKER_NAVIGATION_OFFSET if None)
            canvas_width: Current canvas width in pixels for accurate offset calculation (uses DEFAULT_CANVAS_WIDTH if None)
        """
        if pixel_offset is None:
            pixel_offset = RENDERING.MARKER_NAVIGATION_OFFSET
        if canvas_width is None:
            canvas_width = RENDERING.DEFAULT_CANVAS_WIDTH
        if not self.session or index < 0 or index >= len(MARKER_LABELS):
            return
        
        marker = self.get_marker(index)
        if not marker:
            return  # No marker at this index
        
        vp = self.session.viewport
        if not vp or vp.total_duration <= 0:
            return
        
        # Get current viewport width in normalized units
        viewport_width = vp.right - vp.left
        
        # Convert pixel offset to normalized time units
        # Use actual canvas width for accurate conversion
        offset_normalized = (pixel_offset / float(canvas_width)) * viewport_width
        
        # Convert marker time to normalized position (0-1)
        marker_normalized = marker.time / vp.total_duration
        
        # Calculate new viewport position
        new_left = marker_normalized - offset_normalized
        new_right = new_left + viewport_width
        
        # Clamp to valid bounds with edge space
        edge_space = vp.config.edge_space
        min_allowed_left = -(viewport_width * edge_space)
        max_allowed_right = 1.0 + (viewport_width * edge_space)
        
        if new_left < min_allowed_left:
            offset = min_allowed_left - new_left
            new_left = min_allowed_left
            new_right = new_right + offset
        elif new_right > max_allowed_right:
            offset = new_right - max_allowed_right
            new_left = new_left - offset
            new_right = max_allowed_right
        
        # Update viewport
        vp.left, vp.right = new_left, new_right
        self._emit("viewport_changed")

    # ---- Viewport operations ----
    def zoom_to_fit(self) -> None:
        if not self.session:
            return
        vp = self.session.viewport
        old_left, old_right = vp.left, vp.right
        vp.left, vp.right = 0.0, 1.0
        self.event_bus.publish(ViewportChangedEvent(
            old_left=old_left,
            old_right=old_right,
            new_left=0.0,
            new_right=1.0
        ))
        self._emit("viewport_changed")

    def go_to_start(self) -> None:
        if not self.session:
            return
        vp = self.session.viewport
        width = vp.width
        vp.left = 0.0
        vp.right = width
        self._emit("viewport_changed")

    def go_to_end(self) -> None:
        if not self.session:
            return
        vp = self.session.viewport
        width = vp.width
        vp.left = 1.0 - width
        vp.right = 1.0
        self._emit("viewport_changed")

    def pan_viewport(self, pan_distance: float) -> None:
        if not self.session:
            return
        vp = self.session.viewport
        old_left, old_right = vp.left, vp.right
        new_left = vp.left + pan_distance
        new_right = vp.right + pan_distance
        width = vp.width
        edge_space = vp.config.edge_space
        min_allowed_left = -(width * edge_space)
        max_allowed_right = 1.0 + (width * edge_space)
        if new_left < min_allowed_left:
            offset = min_allowed_left - new_left
            new_left = min_allowed_left
            new_right = new_right + offset
        elif new_right > max_allowed_right:
            offset = new_right - max_allowed_right
            new_left = new_left - offset
            new_right = max_allowed_right
        vp.left, vp.right = new_left, new_right
        if old_left != new_left or old_right != new_right:
            self.event_bus.publish(ViewportChangedEvent(
                old_left=old_left,
                old_right=old_right,
                new_left=new_left,
                new_right=new_right
            ))
        self._emit("viewport_changed")

    def zoom_viewport(self, zoom_factor: float, mouse_relative: Optional[float] = None) -> None:
        """Zoom viewport around a relative position (0..1), or center if None.
        zoom_factor < 1.0 zooms in, > 1.0 zooms out.
        """
        if not self.session:
            return
        vp = self.session.viewport
        old_left, old_right = vp.left, vp.right
        center = mouse_relative if mouse_relative is not None else (vp.left + vp.right) / 2.0
        left_distance = center - vp.left
        right_distance = vp.right - center
        new_left = center - (left_distance * zoom_factor)
        new_right = center + (right_distance * zoom_factor)
        # Minimum zoom width
        min_width = self._get_minimum_zoom_width()
        if new_right - new_left < min_width:
            half = min_width / 2.0
            new_left = center - half
            new_right = center + half
        # Maximum width with edge space
        max_width = 1.0 + 2 * vp.config.edge_space
        if new_right - new_left > max_width:
            new_left = -vp.config.edge_space
            new_right = 1.0 + vp.config.edge_space
        vp.left, vp.right = new_left, new_right
        if old_left != new_left or old_right != new_right:
            self.event_bus.publish(ViewportChangedEvent(
                old_left=old_left,
                old_right=old_right,
                new_left=new_left,
                new_right=new_right
            ))
        self._emit("viewport_changed")

    def zoom_to_roi(self, start_time: int, end_time: int) -> None:
        """Zoom viewport to exactly cover the given time ROI.

        Args:
            start_time: Start time in timescale units (inclusive)
            end_time: End time in timescale units (inclusive/exclusive semantics not critical here)
        """
        if not self.session:
            return
        vp = self.session.viewport
        if vp.total_duration <= 0:
            return
        # Order times
        t0 = min(start_time, end_time)
        t1 = max(start_time, end_time)
        # Enforce minimum width in time units
        min_width_time = max(1, vp.config.minimum_width_time)
        if t1 - t0 < min_width_time:
            center = (t0 + t1) // 2
            half = min_width_time // 2
            t0 = center - half
            t1 = t0 + min_width_time
        # Clamp to [-(edge_space)*duration, (1+edge_space)*duration]
        edge = vp.config.edge_space
        min_time_allowed = int(-edge * vp.total_duration)
        max_time_allowed = int((1.0 + edge) * vp.total_duration)
        if t0 < min_time_allowed:
            shift = min_time_allowed - t0
            t0 = min_time_allowed
            t1 += shift
        if t1 > max_time_allowed:
            shift = t1 - max_time_allowed
            t1 = max_time_allowed
            t0 -= shift
        # Convert to relative
        new_left = t0 / float(vp.total_duration)
        new_right = t1 / float(vp.total_duration)
        old_left, old_right = vp.left, vp.right
        vp.left, vp.right = new_left, new_right
        if old_left != new_left or old_right != new_right:
            self.event_bus.publish(ViewportChangedEvent(
                old_left=old_left,
                old_right=old_right,
                new_left=new_left,
                new_right=new_right
            ))
        self._emit("viewport_changed")

    # ---- Helpers ----
    def _iter_all_nodes(self) -> Iterable[SignalNode]:
        if not self.session:
            return
        def walk(node: SignalNode) -> Iterable[SignalNode]:
            yield node
            if isinstance(node, SignalNodeGroup):
                for ch in node.children:
                    yield from walk(ch)
        for root in list(self.session.root_nodes):
            yield from walk(root)

    def _get_minimum_zoom_width(self) -> float:
        if not self.session:
            return 1e-4
        vp = self.session.viewport
        if vp.total_duration <= 0:
            return 1e-4
        min_width = vp.config.minimum_width_time / vp.total_duration
        # timescale-based limit: 1 time unit -> half viewport
        timescale_min_width = (1.0 / vp.total_duration) * 2
        return max(min_width, timescale_min_width)
    
    def _find_node_by_id(self, node_id: SignalNodeID) -> Optional[SignalNode]:
        """Find a node by its instance ID."""
        for node in self._iter_all_nodes():
            if node.instance_id == node_id:
                return node
        return None
    
    # ---- Structural Mutations (NEW) ----
    
    def delete_nodes_by_ids(self, ids: Iterable[SignalNodeID]) -> None:
        """Delete nodes from the signal tree."""
        if not self.session:
            return
        
        ids_list = list(ids)
        if not ids_list:
            return
        
        # Collect nodes to delete
        nodes_to_delete = []
        for node in self._iter_all_nodes():
            if node.instance_id in ids_list:
                nodes_to_delete.append(node)
        
        # Remove from tree
        for node in nodes_to_delete:
            if node.parent:
                node.parent.children.remove(node)
            elif node in self.session.root_nodes:
                self.session.root_nodes.remove(node)
        
        # Update selection if needed
        self._selected_ids -= set(ids_list)
        self.session.selected_nodes = [n for n in self.session.selected_nodes if n.instance_id not in ids_list]
        
        # Emit events
        self.event_bus.publish(StructureChangedEvent(
            change_kind='delete',
            affected_ids=ids_list
        ))
        self._emit("session_changed")
        if set(ids_list) & self._selected_ids:
            self._emit("selection_changed")
    
    def filter_nodes_for_grouping(self, nodes: List[SignalNode]) -> List[SignalNode]:
        """Filter out nodes whose parent is also in the list.
        
        This prevents flattening when grouping groups - if a parent group
        and its children are both selected, only the parent should be grouped.
        
        Args:
            nodes: List of nodes to filter
            
        Returns:
            List of nodes that should actually be grouped
        """
        nodes_to_group = []
        
        for node in nodes:
            # Check if any ancestor is in the selected list
            has_selected_ancestor = False
            current = node.parent
            while current:
                if current in nodes:
                    has_selected_ancestor = True
                    break
                current = current.parent
            
            # Only include nodes that don't have a selected ancestor
            if not has_selected_ancestor:
                nodes_to_group.append(node)
                
        return nodes_to_group
    
    def get_default_group_name(self) -> str:
        """Generate a default group name based on existing groups."""
        if not self.session:
            return "Group 1"
        
        group_count = len([n for n in self.session.root_nodes if n.is_group]) + 1
        return f"Group {group_count}"
    
    def create_group_from_nodes(
        self,
        nodes: List[SignalNode],
        group_name: Optional[str] = None,
        mode: GroupRenderMode = GroupRenderMode.SEPARATE_ROWS
    ) -> SignalNodeID:
        """Create a group from a list of nodes with proper filtering.
        
        This is a high-level method that handles filtering and default naming.
        
        Args:
            nodes: List of nodes to group
            group_name: Optional group name (will use default if None)
            mode: Group render mode
            
        Returns:
            ID of the created group, or -1 if failed
        """
        if not nodes:
            return -1
            
        # Filter nodes to prevent flattening
        filtered_nodes = self.filter_nodes_for_grouping(nodes)
        if not filtered_nodes:
            return -1
            
        # Get node IDs
        node_ids = [node.instance_id for node in filtered_nodes]
        
        # Use default name if not provided
        if group_name is None:
            group_name = self.get_default_group_name()
            
        # Create the group
        return self.group_nodes(node_ids, group_name, mode)
    
    def group_nodes(
        self,
        ids: Iterable[SignalNodeID],
        group_name: str,
        mode: GroupRenderMode
    ) -> SignalNodeID:
        """Create a new group containing specified nodes (low-level method)."""
        if not self.session:
            return -1
        
        ids_list = list(ids)
        if not ids_list:
            return -1
        
        # Find nodes to group
        nodes_to_group = []
        for node in self._iter_all_nodes():
            if node.instance_id in ids_list:
                nodes_to_group.append(node)
        
        if not nodes_to_group:
            return -1
        
        # Create new group
        group = SignalNodeGroup(
            name=group_name,
            group_render_mode=mode,
            children=[]
        )
        
        # Determine parent and position
        first_node = nodes_to_group[0]
        parent = first_node.parent
        
        if parent:
            # Insert group at position of first node
            index = parent.children.index(first_node)
            parent.children.insert(index, group)
            group.parent = parent
        else:
            # Add to root at position of first node
            index = self.session.root_nodes.index(first_node)
            self.session.root_nodes.insert(index, group)
        
        # Move nodes into group
        for node in nodes_to_group:
            if node.parent:
                node.parent.children.remove(node)
            elif node in self.session.root_nodes:
                self.session.root_nodes.remove(node)
            
            node.parent = group
            group.children.append(node)
        
        # Emit event
        self.event_bus.publish(StructureChangedEvent(
            change_kind='group',
            affected_ids=ids_list,
            parent_id=group.instance_id
        ))
        self._emit("session_changed")
        
        return group.instance_id
    
    def move_nodes(
        self,
        node_ids: List[SignalNodeID],
        target_parent_id: Optional[SignalNodeID],
        insert_row: int
    ) -> None:
        """Move nodes to new position in tree."""
        if not self.session:
            return
        
        # Find nodes to move
        nodes_to_move = []
        for node_id in node_ids:
            node = self._find_node_by_id(node_id)
            if node:
                nodes_to_move.append(node)
        
        if not nodes_to_move:
            return
        
        # Find target parent
        target_parent = None
        if target_parent_id is not None:
            target_parent = self._find_node_by_id(target_parent_id)
            if not target_parent or not isinstance(target_parent, SignalNodeGroup):
                return  # Invalid target
        
        # Remove nodes from current positions
        for node in nodes_to_move:
            if node.parent:
                node.parent.children.remove(node)
            elif node in self.session.root_nodes:
                self.session.root_nodes.remove(node)
        
        # Insert at new position
        if target_parent:
            # Insert into group
            assert isinstance(target_parent, SignalNodeGroup)  # We checked this above
            for i, node in enumerate(nodes_to_move):
                node.parent = target_parent
                target_parent.children.insert(insert_row + i, node)
        else:
            # Insert at root level
            for i, node in enumerate(nodes_to_move):
                node.parent = None
                self.session.root_nodes.insert(insert_row + i, node)
        
        # Emit event
        self.event_bus.publish(StructureChangedEvent(
            change_kind='move',
            affected_ids=node_ids,
            parent_id=target_parent_id,
            insert_row=insert_row
        ))
        self._emit("session_changed")
    
    def insert_nodes(self, nodes: List[SignalNode], after_id: Optional[SignalNodeID] = None) -> None:
        """Insert nodes after specified node ID.

        Args:
            nodes: List of SignalNode objects to insert (should have new instance IDs)
            after_id: ID of node to insert after. If None, append to end of root_nodes
        """
        from wavescout.timing_utils import tprint
        tprint(f"[CONTROLLER] insert_nodes called with {len(nodes) if nodes else 0} nodes, after_id={after_id}")

        if not self.session or not nodes:
            tprint(f"[CONTROLLER] Early return: session={self.session is not None}, nodes={len(nodes) if nodes else 0}")
            return
        
        # Find insertion point
        if after_id is not None:
            after_node = self._find_node_by_id(after_id)
            if not after_node:
                # If node not found, append to end
                after_id = None
        else:
            after_node = None
        
        # Determine parent and insertion index
        if after_node:
            parent = after_node.parent
            if parent:
                # Insert into parent's children after the target node
                insert_index = parent.children.index(after_node) + 1
                for i, node in enumerate(nodes):
                    node.parent = parent
                    parent.children.insert(insert_index + i, node)
            else:
                # Insert into root_nodes after the target node
                insert_index = self.session.root_nodes.index(after_node) + 1
                for i, node in enumerate(nodes):
                    node.parent = None
                    self.session.root_nodes.insert(insert_index + i, node)
        else:
            # No insertion point specified, append to end of root_nodes
            for node in nodes:
                node.parent = None
                self.session.root_nodes.append(node)
        
        # Update selection to newly inserted nodes
        new_ids = [node.instance_id for node in nodes]
        self.set_selection_by_ids(new_ids)
        
        # Emit events
        tprint(f"[CONTROLLER] Successfully inserted {len(nodes)} nodes, new count: {len(self.session.root_nodes)}")
        self.event_bus.publish(StructureChangedEvent(
            change_kind='insert',
            affected_ids=new_ids,
            parent_id=after_node.parent.instance_id if after_node and after_node.parent else None
        ))
        self._emit("session_changed")
    
    def instantiate_snippet(
        self, 
        snippet_nodes: List[SignalNode], 
        after_id: Optional[SignalNodeID] = None
    ) -> bool:
        """
        Instantiate snippet nodes in the current session.
        
        Args:
            snippet_nodes: List of remapped SignalNode objects from snippet
            after_id: ID of node to insert after. If None, append to end
            
        Returns:
            True if successful, False otherwise
        """
        if not self.session or not snippet_nodes:
            return False
        
        try:
            # Ensure all nodes have valid handles and unique instance IDs
            for node in snippet_nodes:
                if isinstance(node, SignalNodeSignal) and node.handle == -1:
                    tprint(f"Warning: Signal {node.name} has invalid handle")
                    return False
            
            # Insert the nodes
            self.insert_nodes(snippet_nodes, after_id)
            
            return True
            
        except Exception as e:
            tprint(f"Error instantiating snippet: {e}")
            return False
    
    def ungroup_nodes(self, group_ids: Iterable[SignalNodeID]) -> None:
        """Ungroup the specified groups, moving their children to parent level."""
        if not self.session:
            return
        
        ids_list = list(group_ids)
        groups_to_ungroup: List[SignalNodeGroup] = []

        for node_id in ids_list:
            node = self._find_node_by_id(node_id)
            if node and isinstance(node, SignalNodeGroup):
                groups_to_ungroup.append(node)

        for group in groups_to_ungroup:
            parent = group.parent
            children = list(group.children)
            
            if parent:
                # Insert children at group's position
                index = parent.children.index(group)
                parent.children.remove(group)
                for i, child in enumerate(children):
                    child.parent = parent
                    parent.children.insert(index + i, child)
            else:
                # Insert at root level
                index = self.session.root_nodes.index(group)
                self.session.root_nodes.remove(group)
                for i, child in enumerate(children):
                    child.parent = None
                    self.session.root_nodes.insert(index + i, child)
        
        # Emit event
        self.event_bus.publish(StructureChangedEvent(
            change_kind='ungroup',
            affected_ids=ids_list
        ))
        self._emit("session_changed")
    
    # ---- Format/Property Mutations (NEW) ----
    
    def set_node_format(self, node_id: SignalNodeID, **kwargs: object) -> None:
        """Update display format properties."""
        node = self._find_node_by_id(node_id)
        if not node:
            return

        # Groups don't have format
        if not isinstance(node, SignalNodeSignal):
            return

        changes: FormatChanges = {}

        # Handle each possible format property
        if 'data_format' in kwargs:
            value = kwargs['data_format']
            if isinstance(value, (DataFormat, str)):
                if isinstance(value, str):
                    # Convert string to DataFormat if needed
                    try:
                        value = DataFormat(value)
                    except ValueError:
                        return
                if node.format.data_format != value:
                    node.format.data_format = value
                    changes['data_format'] = value.value if isinstance(value, DataFormat) else value
        
        if 'render_type' in kwargs:
            value = kwargs['render_type']
            if isinstance(value, (RenderType, str)):
                if isinstance(value, str):
                    try:
                        value = RenderType(value)
                    except ValueError:
                        return
                if node.format.render_type != value:
                    node.format.render_type = value
                    changes['render_type'] = value.value if isinstance(value, RenderType) else value
        
        if 'color' in kwargs:
            value = kwargs['color']
            if isinstance(value, str) and node.format.color != value:
                node.format.color = value
                changes['color'] = value
        
        if 'height_scaling' in kwargs:
            value = kwargs['height_scaling']
            if isinstance(value, int) and node.height_scaling != value:
                node.height_scaling = value
                changes['height'] = value
        
        if 'analog_scaling_mode' in kwargs:
            from .data_model import AnalogScalingMode
            value = kwargs['analog_scaling_mode']
            if isinstance(value, (AnalogScalingMode, str)):
                if isinstance(value, str):
                    try:
                        value = AnalogScalingMode(value)
                    except ValueError:
                        return
                if node.format.analog_scaling_mode != value:
                    node.format.analog_scaling_mode = value
                    changes['analog_scaling_mode'] = value.value if isinstance(value, AnalogScalingMode) else value
        
        if changes:
            self.event_bus.publish(FormatChangedEvent(
                node_id=node_id,
                changes=changes
            ))
            self._emit("session_changed")
    
    def rename_node(self, node_id: SignalNodeID, nickname: str) -> None:
        """Set user-defined nickname for node."""
        node = self._find_node_by_id(node_id)
        if not node:
            return
        
        if node.nickname != nickname:
            node.nickname = nickname
            self.event_bus.publish(FormatChangedEvent(
                node_id=node_id,
                changes={'nickname': nickname}
            ))
            self._emit("session_changed")
    
    def set_node_expanded(self, node_id: SignalNodeID, expanded: bool) -> None:
        """Set whether a group node is expanded."""
        node = self._find_node_by_id(node_id)
        if not node or not isinstance(node, SignalNodeGroup):
            return

        if node.is_expanded != expanded:
            node.is_expanded = expanded
            self._emit("session_changed")
    
    def set_group_render_mode(self, node_id: SignalNodeID, mode: GroupRenderMode) -> None:
        """Set the render mode for a group and apply required side-effects.
        
        - Only flat groups (no subgroup children) are allowed for OVERLAPPED.
        - When switching to OVERLAPPED:
          * Force all direct child signals to Analog render_type
          * Set analog_scaling_mode to SCALE_TO_ALL_DATA
          * Assign distinct rainbow colors to children (if color is None)
        """
        from .data_model import AnalogScalingMode
        from .color_utils import generate_rainbow_colors

        node = self._find_node_by_id(node_id)
        if not node or not isinstance(node, SignalNodeGroup):
            return

        # Validate flat group for OVERLAPPED
        if mode == GroupRenderMode.OVERLAPPED:
            if any(isinstance(child, SignalNodeGroup) for child in node.children):
                # Disallow overlapped on nested groups; keep or reset to SEPARATE_ROWS
                mode = GroupRenderMode.SEPARATE_ROWS

        if node.group_render_mode == mode:
            return

        node.group_render_mode = mode

        # Apply side effects when enabling OVERLAPPED
        if mode == GroupRenderMode.OVERLAPPED:
            # Collect direct child signals
            child_signals = [c for c in node.children if isinstance(c, SignalNodeSignal) and c.handle is not None]
            # Assign rainbow colors deterministically
            colors = generate_rainbow_colors(len(child_signals)) if child_signals else []
            for idx, child in enumerate(child_signals):
                # Force analog rendering and scaling to all data
                if child.format.render_type != RenderType.ANALOG:
                    child.format.render_type = RenderType.ANALOG
                if child.format.analog_scaling_mode != AnalogScalingMode.SCALE_TO_ALL_DATA:
                    child.format.analog_scaling_mode = AnalogScalingMode.SCALE_TO_ALL_DATA
                # Assign color only if not set by user
                if child.format.color is None and idx < len(colors):
                    child.format.color = colors[idx]

        # Notify views
        self.event_bus.publish(FormatChangedEvent(
            node_id=node_id,
            changes={'render_type': mode.value}
        ))
        # Publish structure change so views rebuild layout (virtual overlapped row)
        self.event_bus.publish(StructureChangedEvent(
            change_kind='group',
            affected_ids=[node_id]
        ))
        self._emit("session_changed")
    
    # ---- Clock Signal Management ----
    
    def set_clock_signal(self, node: Optional[SignalNode]) -> None:
        """Set a signal as the clock for grid display.

        Calculates the clock period based on signal type and updates
        the session's clock_signal field.
        """
        if not self.session:
            return

        if node is None:
            self.clear_clock_signal()
            return

        # Groups can't be clock signals
        if not isinstance(node, SignalNodeSignal):
            return

        # Get the waveform database
        db = self.session.waveform_db
        if not db or node.handle is None:
            return

        # Get the variable and signal
        if not is_valid_clock_signal(node.var):
            return
        
        # Get signal (blocking since we need it immediately for calculations)
        async_signal = db.load_signal(node.handle)
        if not async_signal.is_loaded():
            try:
                signal = async_signal.get_signal_blocking(timeout=5.0)
            except (RuntimeError, TimeoutError):
                return
        else:
             signal = async_signal.get_signal_blocking()
        
        # Calculate clock period and phase offset
        result = calculate_clock_period(signal, node.var)
        if result is None:
            return
        
        period, phase_offset = result
        
        # Update session with period, phase offset, and node
        self.session.clock_signal = (period, phase_offset, node)
        
        # Emit viewport changed to trigger grid redraw
        self._emit("viewport_changed")
    
    def clear_clock_signal(self) -> None:
        """Clear the clock signal selection."""
        if not self.session:
            return
        
        if self.session.clock_signal is not None:
            self.session.clock_signal = None
            self._emit("viewport_changed")
    
    def is_clock_signal(self, node: SignalNode) -> bool:
        """Check if a node is the current clock signal."""
        if not self.session or not self.session.clock_signal:
            return False
        
        _, _, clock_node = self.session.clock_signal  # Now (period, phase, node)
        return clock_node.instance_id == node.instance_id
    
    # ---- Sampling Signal Management (for Signal Analysis) ----
    
    def set_sampling_signal(self, node: Optional[SignalNode]) -> None:
        """Set the signal to be used for sampling in signal analysis."""
        if not self.session:
            return
        
        # Only allow non-group signals as sampling signals
        if node and node.is_group:
            return
        
        self.session.sampling_signal = node
        
        # Emit a custom event for sampling signal changes
        if "sampling_signal_changed" not in self._callbacks:
            self._callbacks["sampling_signal_changed"] = []
        self._emit("sampling_signal_changed")
        self._emit("session_changed")
    
    def get_sampling_signal(self) -> Optional[SignalNode]:
        """Get the current sampling signal."""
        if not self.session:
            return None
        return self.session.sampling_signal
    
    def clear_sampling_signal(self) -> None:
        """Clear the current sampling signal."""
        self.set_sampling_signal(None)
    
    def is_sampling_signal(self, node: SignalNode) -> bool:
        """Check if a node is the current sampling signal."""
        if not self.session or not self.session.sampling_signal:
            return False
        return self.session.sampling_signal.instance_id == node.instance_id
    
    # ---- Time/Clock Navigation ----
    
    def navigate_to_time(self, time: Time, pixel_offset: Optional[int] = None, canvas_width: Optional[int] = None) -> None:
        """Navigate to a specific timestamp in the waveform.
        
        Args:
            time: Absolute time in simulation units
            pixel_offset: Distance in pixels from left edge of viewport (uses MARKER_NAVIGATION_OFFSET if None)
            canvas_width: Current canvas width in pixels for accurate offset calculation (uses DEFAULT_CANVAS_WIDTH if None)
        """
        if pixel_offset is None:
            pixel_offset = RENDERING.MARKER_NAVIGATION_OFFSET
        if canvas_width is None:
            canvas_width = RENDERING.DEFAULT_CANVAS_WIDTH
        if not self.session:
            return
        
        vp = self.session.viewport
        if not vp or vp.total_duration <= 0:
            return
        
        # Clamp time to valid range
        time = max(0, min(time, vp.total_duration))
        
        # Get current viewport width in normalized units
        viewport_width = vp.right - vp.left
        
        # Convert pixel offset to normalized time units
        offset_normalized = (pixel_offset / float(canvas_width)) * viewport_width
        
        # Convert time to normalized position (0-1)
        time_normalized = time / vp.total_duration
        
        # Calculate new viewport position
        new_left = time_normalized - offset_normalized
        new_right = new_left + viewport_width
        
        # Clamp to valid bounds with edge space
        edge_space = vp.config.edge_space
        min_allowed_left = -(viewport_width * edge_space)
        max_allowed_right = 1.0 + (viewport_width * edge_space)
        
        if new_left < min_allowed_left:
            offset = min_allowed_left - new_left
            new_left = min_allowed_left
            new_right = new_right + offset
        elif new_right > max_allowed_right:
            offset = new_right - max_allowed_right
            new_left = new_left - offset
            new_right = max_allowed_right
        
        # Update viewport
        old_left, old_right = vp.left, vp.right
        vp.left, vp.right = new_left, new_right
        
        if old_left != new_left or old_right != new_right:
            self.event_bus.publish(ViewportChangedEvent(
                old_left=old_left,
                old_right=old_right,
                new_left=new_left,
                new_right=new_right
            ))
        self._emit("viewport_changed")
    
    def navigate_to_clock_cycle(self, cycle: int, pixel_offset: Optional[int] = None, canvas_width: Optional[int] = None) -> None:
        """Navigate to a specific clock cycle.
        
        Args:
            cycle: Clock cycle number (non-negative)
            pixel_offset: Distance in pixels from left edge of viewport (uses MARKER_NAVIGATION_OFFSET if None)
            canvas_width: Current canvas width in pixels for accurate offset calculation (uses DEFAULT_CANVAS_WIDTH if None)
        """
        if not self.session or not self.session.clock_signal:
            return
        
        if cycle < 0:
            return
        
        # Get clock information
        period, phase_offset, _ = self.session.clock_signal
        
        # Calculate time from clock cycle
        time = phase_offset + (cycle * period)
        
        # Navigate to calculated time
        self.navigate_to_time(time, pixel_offset, canvas_width)
    
    def get_clock_info(self) -> Optional[tuple[Time, Time, SignalNode]]:
        """Get the current clock signal information.

        Returns:
            Tuple of (period, phase_offset, node) if clock is set, None otherwise
        """
        if not self.session or not self.session.clock_signal:
            return None
        return self.session.clock_signal

    # ---- Async Signal Loading Event Handlers ----

    def _on_signal_loading_started(self, event: SignalLoadingStartedEvent) -> None:
        """Handle signal loading started event."""
        tprint(f"[CONTROLLER] _on_signal_loading_started: {len(event.handles)} handles")
        if not self.session:
            tprint("[CONTROLLER] No session, returning")
            return

        # Add handles to session loading state
        self.session.loading_handles.update(event.handles)

        # Emit callback for UI updates
        self._emit("signals_loading")

    def _on_signal_loaded(self, event: SignalLoadedEvent) -> None:
        """Handle signal loaded event."""
        tprint(f"[CONTROLLER] _on_signal_loaded: {len(event.pairs)} signals")
        if not self.session:
            tprint("[CONTROLLER] No session, returning")
            return

        # Update loading state (AsyncLoadedSignal handles updates directly)
        for handle, signal in event.pairs:
            # Remove from loading state
            self.session.loading_handles.discard(handle)

        # Emit callback for UI updates
        tprint("[CONTROLLER] Emitting signals_loaded and session_changed callbacks")
        self._emit("signals_loaded")
        self._emit("session_changed")

    def _on_signal_loading_failed(self, event: SignalLoadingFailedEvent) -> None:
        """Handle signal loading failed event."""
        if not self.session:
            return

        # Clear loading state for failed handles
        for handle in event.handles:
            self.session.loading_handles.discard(handle)

        # Emit callback for UI updates
        self._emit("signals_loaded")  # Still emit to update UI

        # Log error
        tprint(f"Signal loading failed: {event.error}")

    def load_signals_async(self, handles: List[SignalHandle]) -> None:
        """Request async loading of signals.

        Args:
            handles: List of signal handles to load
        """
        if not self.session or not self.session.waveform_db:
            return

        # Delegate to WaveformDB
        self.session.waveform_db.load_signals_async(handles)
