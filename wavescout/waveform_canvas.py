"""Optimized waveform canvas widget with offline rendering pipeline."""

from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Optional, Union, Set

from PySide6.QtCore import Qt, Signal, QModelIndex, QTimer, QRectF, QRect
from PySide6.QtGui import QPainter, QPen, QColor, QFont, QFontMetrics, QImage, QResizeEvent, QPaintEvent, QShowEvent, \
    QMouseEvent, QCloseEvent, QKeyEvent, QBrush
from PySide6.QtWidgets import QWidget, QScrollBar
from pyrox import SignalHandle

from . import config
from .canvas_layout import CanvasLayout, build_layout, VisibleRow
from .data_model import (
    TreeNode,
    SignalNode,
    SignalNodeID,
    Time,
    TimeRulerConfig,
    RenderType,
)
from .signal_renderer import (
    draw_digital_signal, draw_bus_signal, draw_analog_signal, draw_event_signal,
    NodeInfo, RenderParams, GROUP_RENDERERS, GroupDrawingPayload
)
from .signal_sampling import (
    SignalDrawingData,
    generate_signal_draw_commands
)
from .waveform_item_model import WaveformItemModel

RENDERING = config.RENDERING
MARKER_LABELS = config.MARKER_LABELS
import time as time_module
import time
import math
from .timing_utils import tprint
from .data_model import SignalRangeCache
from .time_grid_renderer import TimeGridRenderer, TickInfo

@dataclass
class CachedWaveDrawData:
    """Cached drawing data for all visible signals."""
    draw_commands: Dict[SignalNodeID, SignalDrawingData] = field(default_factory=dict)  # instance_id -> commands
    viewport_hash: str = ""  # To check if cache is valid


class TransitionCache:
    """Cache for signal transitions to avoid repeated database queries."""

    def __init__(self, max_entries: int = RENDERING.TRANSITION_CACHE_MAX_ENTRIES):
        self.cache: Dict[Tuple[int, Time, Time], List[Tuple[Time, str]]] = {}
        self.access_times: Dict[Tuple[int, Time, Time], float] = {}
        self.max_entries = max_entries

    def get(self, handle: SignalHandle, start_time: Time, end_time: Time) -> Optional[List[Tuple[Time, str]]]:
        """Get transitions from cache if available."""
        key = (handle, start_time, end_time)
        if key in self.cache:
            self.access_times[key] = time_module.time()
            return self.cache[key]
        return None

    def put(self, handle: SignalHandle, start_time: Time, end_time: Time, transitions: List[Tuple[Time, str]]) -> None:
        """Store transitions in cache."""
        # Evict old entries if cache is full
        if len(self.cache) >= self.max_entries:
            self._evict_lru()

        key = (handle, start_time, end_time)
        self.cache[key] = transitions
        self.access_times[key] = time_module.time()

    def _evict_lru(self) -> None:
        """Evict least recently used entry."""
        if not self.access_times:
            return

        lru_key = min(self.access_times, key=lambda k: self.access_times.get(k, 0))
        del self.cache[lru_key]
        del self.access_times[lru_key]

    def clear(self) -> None:
        """Clear the cache."""
        self.cache.clear()
        self.access_times.clear()


class WaveformCanvas(QWidget):
    """Optimized widget for drawing waveforms with caching."""

    cursorMoved = Signal(object)  # Emitted when cursor is moved (using object to handle large integers)
    roiSelected = Signal(object, object)  # Emitted on ROI selection release: (start_time, end_time)

    def __init__(self, model: Optional[WaveformItemModel], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._model = model
        self._row_height = RENDERING.DEFAULT_ROW_HEIGHT  # Default/base row height
        self._header_height = RENDERING.DEFAULT_HEADER_HEIGHT  # Default header height - standard QTreeView header height
        self._time_scale = 1.0  # pixels per time unit
        self._start_time = 0
        self._end_time = 1000000
        self._cursor_time = 0
        self._shared_scrollbar: Optional[QScrollBar] = None
        self._layout: CanvasLayout = CanvasLayout()  # Replace visible_nodes with layout
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumWidth(RENDERING.MIN_CANVAS_WIDTH)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # Accept keyboard focus for V key shortcut
        
        # Grid drawing state
        self._last_tick_positions: List[TickInfo] = []
        self._last_ruler_config: Optional[TimeRulerConfig] = None
        # Always initialize time grid renderer with defaults
        self._time_grid_renderer: TimeGridRenderer = TimeGridRenderer()

        # Caching
        self._transition_cache = TransitionCache()
        self._signal_range_cache: Dict[SignalNodeID, SignalRangeCache] = {}  # Cache for analog signal ranges
        
        # Single-threaded rendering - no thread pool needed

        # Deferred updates
        self._update_timer = QTimer()
        self._update_timer.setSingleShot(True)
        self._update_timer.timeout.connect(self._do_update)
        self._pending_update = False
        
        # Rendered image cache
        self._rendered_image: Optional[QImage] = None
        self._render_generation = 0  # Track render requests
        self._last_render_params_hash: Optional[int] = None  # Track last rendered params

        # Debug counters and timing
        self._paint_frame_counter = 0  # Incremented on every paintEvent
        self._render_complete_counter = 0  # Incremented when render completes
        self._last_paint_time_ms = 0.0  # Time taken by last paintEvent
        self._last_render_time_ms = 0.0  # Time taken by last render

        # ROI selection state
        self._roi_selection_active: bool = False
        self._roi_start_x: Optional[int] = None
        self._roi_current_x: Optional[int] = None
        
        # Value tooltip state
        self._value_tooltips_enabled: bool = False  # Toggle state from menu/settings
        self._value_tooltips_force_enabled: bool = False  # Temporary V key override
        
        # Highlight selected state
        self._highlight_selected: bool = False  # Toggle state for highlighting selected signals
    
    def __del__(self) -> None:
        """Clean up on destruction."""
        pass

    def setSharedScrollBar(self, scrollbar: QScrollBar) -> None:
        """Set the shared vertical scrollbar."""
        self._shared_scrollbar = scrollbar
        if scrollbar:
            scrollbar.valueChanged.connect(lambda _: self.update())

    def setHeaderHeight(self, height: int) -> None:
        """Set the header height to match the tree view's header."""
        # Ensure minimum header height
        height = max(height, RENDERING.DEFAULT_HEADER_HEIGHT)
        if self._header_height != height:
            self._header_height = height
            self.update()  # Trigger a repaint if header height changes

    def setRowHeight(self, height: int) -> None:
        """Set the row height to match other views."""
        self._row_height = height
        self.update()
        
    def set_value_tooltips_enabled(self, enabled: bool) -> None:
        """Enable or disable value tooltips at cursor."""
        self._value_tooltips_enabled = enabled
        self.update()
    
    def set_highlight_selected(self, enabled: bool) -> None:
        """Enable or disable highlighting of selected signals."""
        self._highlight_selected = enabled
        # Clear the render cache to force re-render with new highlighting
        self._rendered_image = None
        self.update()
    

    def setTimeRange(self, start_time: Time, end_time: Time) -> None:
        """Set the visible time range."""
        
        # Check if viewport changed significantly
        viewport_changed = (abs(self._start_time - start_time) > 1 or
                          abs(self._end_time - end_time) > 1)

        self._start_time = start_time
        self._end_time = end_time
        self._update_time_scale()

        # Clear cache if viewport changed significantly
        if viewport_changed:
            self._transition_cache.clear()
            # Don't clear rendered image - keep showing old one until new render completes

        self.update()

    def setCursorTime(self, time: Time) -> None:
        """Set the cursor position."""
        old_time = self._cursor_time
        self._cursor_time = time
        
        # If we have a rendered image and cursor is just moving within visible range,
        # do a minimal update by just repainting the cursor areas
        if (self._rendered_image and not self._rendered_image.isNull() and
            old_time >= self._start_time and old_time <= self._end_time and
            time >= self._start_time and time <= self._end_time):
            # Calculate the rectangles that need updating (old and new cursor positions)
            old_x = int((old_time - self._start_time) * self.width() / (self._end_time - self._start_time))
            new_x = int((time - self._start_time) * self.width() / (self._end_time - self._start_time))
            
            # Update regions around both cursor positions (with some padding)
            padding = RENDERING.CURSOR_PADDING
            width = RENDERING.CURSOR_WIDTH + 2 * padding + 1
            self.update(old_x - padding, 0, width, self.height())
            self.update(new_x - padding, 0, width, self.height())
        else:
            # Full update needed
            self.update()
        
    def setModel(self, model: Optional[WaveformItemModel]) -> None:
        """Set the data model and connect to its signals."""
        setmodel_start = time.time()
        # Disconnect from old model and controller if exists
        if self._model:
            try:
                self._model.layoutChanged.disconnect(self._on_model_layout_changed)
                self._model.rowsInserted.disconnect(self._on_model_rows_changed)
                self._model.rowsRemoved.disconnect(self._on_model_rows_changed)
                self._model.dataChanged.disconnect(self._on_model_data_changed)
                self._model.modelReset.disconnect(self._on_model_reset)
                # Disconnect from controller's selection changes
                if self._model._controller:
                    self._model._controller.off("selection_changed", self._on_selection_changed)
            except:
                pass
        
        self._model = model
        
        # Connect to new model
        if self._model:
            self._model.layoutChanged.connect(self._on_model_layout_changed)
            self._model.rowsInserted.connect(self._on_model_rows_changed)
            self._model.rowsRemoved.connect(self._on_model_rows_changed)
            self._model.dataChanged.connect(self._on_model_data_changed)
            self._model.modelReset.connect(self._on_model_reset)
            
            # Connect to controller's selection changes
            if self._model._controller:
                self._model._controller.on("selection_changed", self._on_selection_changed)
            
            # Update visible nodes
            update_start = time.time()
            self.updateVisibleNodes()
            tprint(f"      WaveformCanvas.updateVisibleNodes: {time.time() - update_start:.3f}s")
        tprint(f"      WaveformCanvas.setModel total: {time.time() - setmodel_start:.3f}s")
    
    def _on_model_layout_changed(self) -> None:
        """Handle model layout changes."""
        
        # Update visible nodes (this will also update row heights)
        self.updateVisibleNodes()
        
        # Always invalidate and update when layout changes
        # This ensures changes like height scaling are properly reflected
        self._rendered_image = None  # Invalidate rendered image
        self._last_render_params_hash = None  # Force re-render
        self.update()
    
    def _on_model_rows_changed(self, parent: QModelIndex, first: int, last: int) -> None:
        """Handle model row insertion/removal."""
        self.updateVisibleNodes()
        self._rendered_image = None  # Invalidate rendered image
        self._last_render_params_hash = None  # Force re-render
        self.update()
    
    def _on_model_data_changed(self, topLeft: QModelIndex, bottomRight: QModelIndex, roles: Optional[List[int]] = None) -> None:
        """Handle model data changes."""
        # Update if display data changed or if no roles specified (assume all changed)
        if roles is None or not roles or Qt.ItemDataRole.DisplayRole in roles or Qt.ItemDataRole.UserRole in roles:
            self._rendered_image = None  # Invalidate rendered image
            self._last_render_params_hash = None  # Force re-render
            self.update()
    
    def _on_model_reset(self) -> None:
        """Handle model reset (typically after beginResetModel/endResetModel)."""
        self.updateVisibleNodes()
        self._rendered_image = None  # Invalidate rendered image
        self._last_render_params_hash = None  # Force re-render
        self.update()
    
    def _on_selection_changed(self) -> None:
        """Handle selection changes from controller."""
        # Only update if highlighting is enabled
        if self._highlight_selected:
            self._rendered_image = None  # Invalidate rendered image
            self._last_render_params_hash = None  # Force re-render
            self.update()

    def updateVisibleNodes(self) -> None:
        """Update the layout based on expansion state."""
        if not self._model:
            self._layout = CanvasLayout()
            return

        # Build new layout from model
        self._layout = build_layout(self._model, self._row_height)

        # Don't automatically generate draw commands here - let paintEvent handle it
        # This prevents generating commands with wrong viewport before setTimeRange is called

    def _update_time_scale(self) -> None:
        """Update time scale based on widget width and time range."""
        if self._end_time > self._start_time and self.width() > 0:
            self._time_scale = self.width() / (self._end_time - self._start_time)
        else:
            self._time_scale = 1.0

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Handle widget resize with deferred update."""
        super().resizeEvent(event)

        self._update_time_scale()
        
        # Don't clear rendered image - it will be stretched but that's better than flickering

        # Defer update to avoid multiple repaints during resize
        self._pending_update = True
        self._update_timer.stop()
        self._update_timer.start(RENDERING.UPDATE_TIMER_DELAY)  # delay for smoother resize
        
    def showEvent(self, event: QShowEvent) -> None:
        """Handle widget show event."""
        super().showEvent(event)
        # Trigger initial render when widget is shown
        if self.width() > 0 and self.height() > 0:
            self.update()

    def _do_update(self) -> None:
        """Perform the actual update after timer expires."""
        if self._pending_update:
            self._pending_update = False
            self.update()


    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint the waveforms with caching."""
        # Start timing
        paint_start_time = time_module.time()

        # Log first paint event
        if not hasattr(self, '_first_paint_logged'):
            self._first_paint_logged = True
            tprint(f"  WaveformCanvas: First paintEvent triggered")

        # Increment frame counter
        self._paint_frame_counter += 1
        
        painter = QPainter(self)
        # Enable high-quality text rendering; disable geometry antialiasing for crisp 1px lines
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        
        # Check if this is a partial update
        is_partial_update = self._should_do_partial_update(event)
        
        if is_partial_update:
            self._paint_partial_update(painter, event.rect())
        else:
            self._paint_full_update(painter)
        
        # Draw overlays (cursor, etc.)
        self._paint_overlays(painter, event.rect(), is_partial_update)
        
        # Calculate paint time
        self._last_paint_time_ms = (time_module.time() - paint_start_time) * 1000
        
        # Draw debug info if enabled
        self._paint_debug_info(painter, is_partial_update)
    
    def _should_do_partial_update(self, event: QPaintEvent) -> bool:
        """Determine if this is a partial update (cursor only)."""
        update_rect = event.rect()
        cursor_region_width = RENDERING.CURSOR_WIDTH + 2 * RENDERING.CURSOR_PADDING + 1
        return bool(update_rect.width() < cursor_region_width * 2 and 
                    self._rendered_image and 
                    not self._rendered_image.isNull())
    
    def _paint_partial_update(self, painter: QPainter, update_rect: QRect) -> None:
        """Handle partial update by redrawing only the affected region."""
        if self._rendered_image is not None:
            painter.drawImage(update_rect, self._rendered_image, update_rect)
    
    def _paint_full_update(self, painter: QPainter) -> None:
        """Handle full update by redrawing everything."""
        # Paint background
        self._paint_background(painter)
        
        # Render and draw waveforms
        self._paint_waveforms(painter)
        
        # Draw grid on top of waveforms (but will be under overlays)
        self._paint_grid(painter)
    
    def _paint_background(self, painter: QPainter) -> None:
        """Paint the background with different colors for valid/invalid time ranges."""
        self._paint_background_with_boundaries(painter)
    
    def _paint_grid(self, painter: QPainter) -> None:
        """Draw grid lines on top of waveforms but below overlays."""
        # Calculate time ruler positions first (needed for grid)
        self._calculate_and_store_ruler_info()
        
        # Draw grid lines if enabled
        if self._last_ruler_config and self._last_ruler_config.show_grid_lines and self._last_tick_positions:
            self._time_grid_renderer.render_grid(
                painter, self._last_tick_positions, self.width(), self.height(), self._header_height
            )
    
    def _paint_waveforms(self, painter: QPainter) -> None:
        """Render and paint the waveforms."""
        # Check if we need to render
        render_params = self._collect_render_params()
        param_hash = self._hash_render_params(render_params)
        
        if param_hash != self._last_render_params_hash:
            # Parameters changed, need to re-render
            self._last_render_params_hash = param_hash
            self._render_generation += 1
            
            # Render synchronously
            image, generation, render_time_ms = self._render_to_image(render_params, self._render_generation)
            self._rendered_image = image
            self._render_complete_counter += 1
            self._last_render_time_ms = render_time_ms
        
        # Draw the rendered image if available
        if self._rendered_image and not self._rendered_image.isNull():
            painter.drawImage(0, 0, self._rendered_image)
    
    def _paint_overlays(self, painter: QPainter, update_rect: QRect, is_partial_update: bool) -> None:
        """Paint overlays on top of waveforms (boundary lines, ruler, markers, cursor, ROI)."""
        # Draw boundary lines
        if not is_partial_update:
            self._draw_boundary_lines(painter)
        
        # Draw time ruler
        if not is_partial_update:
            self._draw_time_ruler(painter)
        
        # Draw ROI overlay before markers and cursor for proper layering
        self._paint_roi_overlay(painter)
        
        # Draw markers (before cursor so cursor is always on top)
        self._paint_markers(painter, update_rect, is_partial_update)
        
        # Draw cursor
        self._paint_cursor(painter, update_rect, is_partial_update)
        
        # Draw value tooltips (after cursor so they appear on top)
        self._paint_value_tooltips(painter)
    
    def _paint_markers(self, painter: QPainter, update_rect: QRect, is_partial_update: bool) -> None:
        """Draw markers if they're visible."""
        if not self._model or not self._model._session:
            return
            
        markers = self._model._session.markers
        if not markers:
            return
            
        for i, marker in enumerate(markers):
            # Skip placeholder markers (time < 0)
            if marker and marker.time >= 0 and marker.time >= self._start_time and marker.time <= self._end_time:
                x = int((marker.time - self._start_time) * self.width() / 
                       (self._end_time - self._start_time))
                
                # Only draw marker if it's in the update region (or full update)
                marker_padding = RENDERING.MARKER_WIDTH + 2
                if not is_partial_update or (x >= update_rect.left() - marker_padding and 
                                            x <= update_rect.right() + marker_padding):
                    # Draw the vertical line
                    pen = QPen(QColor(marker.color))
                    pen.setWidth(RENDERING.MARKER_WIDTH)
                    painter.setPen(pen)
                    painter.drawLine(x, 0, x, self.height())
                    
                    # Draw the label at the top
                    if i < len(MARKER_LABELS):
                        label = MARKER_LABELS[i]
                        font = QFont(RENDERING.FONT_FAMILY, RENDERING.FONT_SIZE_SMALL)
                        painter.setFont(font)
                        
                        # Draw label background for readability
                        fm = QFontMetrics(font)
                        text_rect = fm.boundingRect(label)
                        text_rect.moveTopLeft(QRect(x - text_rect.width() // 2, 2, 0, 0).topLeft())
                        
                        # Semi-transparent background
                        painter.fillRect(text_rect.adjusted(-2, -1, 2, 1), 
                                       QColor(0, 0, 0, 180))
                        
                        # Draw the label text
                        painter.setPen(QColor(marker.color))
                        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, label)
    
    def _paint_cursor(self, painter: QPainter, update_rect: QRect, is_partial_update: bool) -> None:
        """Draw the cursor if it's visible."""
        if self._cursor_time >= self._start_time and self._cursor_time <= self._end_time:
            x = int((self._cursor_time - self._start_time) * self.width() / 
                   (self._end_time - self._start_time))
            
            # Only draw cursor if it's in the update region (or full update)
            if not is_partial_update or (x >= update_rect.left() - RENDERING.CURSOR_PADDING and 
                                        x <= update_rect.right() + RENDERING.CURSOR_PADDING):
                pen = QPen(QColor(config.COLORS.CURSOR))
                pen.setWidth(0)  # cosmetic 1 device-pixel
                painter.setPen(pen)
                painter.drawLine(x, 0, x, self.height())
    
    def _paint_value_tooltips(self, painter: QPainter) -> None:
        """Draw value tooltips at cursor position if enabled."""
        # Check if tooltips should be shown
        if not (self._value_tooltips_enabled or self._value_tooltips_force_enabled):
            return
            
        # Check if cursor is visible
        if self._cursor_time < self._start_time or self._cursor_time > self._end_time:
            return
            
        # Check if we have model and layout
        if not self._model or not self._layout.rows:
            return
            
        # Get cursor x position
        cursor_x = int((self._cursor_time - self._start_time) * self.width() / 
                      (self._end_time - self._start_time))
        
        # Get scroll position
        scroll_value = self._shared_scrollbar.value() if self._shared_scrollbar else 0
        
        # Import parse_signal_value for formatting
        from .signal_sampling import parse_signal_value
        
        # Set up font for tooltips
        font = QFont(RENDERING.FONT_FAMILY_MONO, RENDERING.VALUE_TOOLTIP_FONT_SIZE)
        painter.setFont(font)
        fm = QFontMetrics(font)
        
        # Prepare colors
        bg_color = QColor(*config.COLORS.VALUE_TOOLTIP_BACKGROUND)
        text_color = QColor(config.COLORS.VALUE_TOOLTIP_TEXT)
        border_color = QColor(config.COLORS.VALUE_TOOLTIP_BORDER)
        
        # Iterate through layout rows and draw tooltips for signals
        for row_idx, row in enumerate(self._layout.rows):
            # Skip non-signal rows - they don't have direct values
            if row.kind != 'signal':
                continue

            node = row.source
            # Skip groups - they don't have values
            if not isinstance(node, SignalNode):
                continue

            signal_node = node

            # Get row Y position from layout
            if row_idx >= len(self._layout.row_offsets):
                continue
            row_y = self._layout.row_offsets[row_idx] + self._header_height - scroll_value
            row_height = row.height_px

            # Skip if row is outside visible area
            if row_y + row_height < 0 or row_y > self.height():
                continue

            # Get value at cursor
            if signal_node.handle is None:
                continue

            try:
                # Skip if signal not loaded yet (avoid blocking)
                if not signal_node.signal.is_loaded():
                    continue
                # Use already loaded signal object
                signal_obj = signal_node.signal.get_signal_blocking(timeout=0.001)
                query = signal_obj.query_signal(max(0, self._cursor_time))
                raw_value = query.value

                # Determine bit width
                bit_width = signal_node.var.bitwidth() or 32

                # Format value using same logic as Values panel
                value_str, _, _ = parse_signal_value(raw_value, signal_node.format.data_format, bit_width)
                if not value_str:
                    continue
                    
                # Calculate tooltip position (to the right of cursor)
                tooltip_x = cursor_x + RENDERING.VALUE_TOOLTIP_MARGIN
                tooltip_y = row_y + row_height // 2  # Use scaled height for centering
                
                # Measure text size
                text_rect = fm.boundingRect(value_str)
                tooltip_width = max(text_rect.width() + 2 * RENDERING.VALUE_TOOLTIP_PADDING,
                                  RENDERING.VALUE_TOOLTIP_MIN_WIDTH)
                tooltip_height = text_rect.height() + 2 * RENDERING.VALUE_TOOLTIP_PADDING
                
                # Adjust position if tooltip would go off right edge
                if tooltip_x + tooltip_width > self.width():
                    tooltip_x = cursor_x - tooltip_width - RENDERING.VALUE_TOOLTIP_MARGIN
                
                # Create tooltip rectangle
                tooltip_rect = QRectF(tooltip_x, 
                                     tooltip_y - tooltip_height // 2,
                                     tooltip_width, 
                                     tooltip_height)
                
                # Draw tooltip background with rounded corners
                painter.setPen(QPen(border_color, 1))
                painter.setBrush(QBrush(bg_color))
                painter.drawRoundedRect(tooltip_rect, 
                                       RENDERING.VALUE_TOOLTIP_BORDER_RADIUS,
                                       RENDERING.VALUE_TOOLTIP_BORDER_RADIUS)
                
                # Draw text
                painter.setPen(QPen(text_color))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                text_pos = tooltip_rect.adjusted(RENDERING.VALUE_TOOLTIP_PADDING,
                                                RENDERING.VALUE_TOOLTIP_PADDING,
                                                -RENDERING.VALUE_TOOLTIP_PADDING,
                                                -RENDERING.VALUE_TOOLTIP_PADDING)
                painter.drawText(text_pos, Qt.AlignmentFlag.AlignCenter, value_str)
                
            except Exception:
                # Skip this signal if we can't get its value
                continue
    
    def _paint_debug_info(self, painter: QPainter, is_partial_update: bool) -> None:
        """Draw debug information if not a partial update."""
        if not is_partial_update:
            self._draw_debug_counters(painter)
    
    
    def _hash_render_params(self, params: RenderParams) -> int:
        """Create a hash of render parameters for quick comparison."""
        # Build key params list
        key_params: List[Union[float, int, bool, tuple[object, ...]]] = [
            params['width'],
            params['height'],
            params.get('dpr', 1.0),
            params['start_time'],
            params['end_time'],
            # Don't include cursor_time - cursor is drawn separately
            params['scroll_value'],
            params.get('header_height', 35),  # Include header height
        ]
        
        # Add visible nodes info
        key_params.append(len(params.get('visible_nodes', [])))
        # Include node handles, height scaling, data format, and COLOR to detect changes
        if 'visible_nodes' in params:
            key_params.append(
                tuple((node.handle if isinstance(node, SignalNode) else None,
                       node.name,
                       node.height_scaling,
                       node.format.data_format if isinstance(node, SignalNode) else None,
                       node.format.color if isinstance(node, SignalNode) else None)  # Include color for theme changes
                      for node in params['visible_nodes'])
            )
        
        return hash(tuple(key_params))
    
    def _collect_render_params(self) -> RenderParams:
        """Collect all parameters needed for rendering."""
        # Get scroll position
        scroll_value = 0
        if self._shared_scrollbar:
            scroll_value = self._shared_scrollbar.value()

        # Get selected IDs from controller
        selected_ids: Set[int] = set()
        if self._model and self._model._controller:
            selected_ids = self._model._controller._selected_ids

        visible_nodes: List[TreeNode] = []
        for row in self._layout.rows:
            node = row.source
            visible_nodes.append(node)

        # Get session reference if available
        session = None
        if self._model and self._model._session:
            session = self._model._session

        return RenderParams(
            width=self.width(),
            height=self.height(),
            dpr=float(self.devicePixelRatioF()),
            start_time=self._start_time,
            end_time=self._end_time,
            cursor_time=self._cursor_time,
            scroll_value=scroll_value,
            visible_nodes=visible_nodes,
            session=session,  # Pass session for multi-file support
            generation=self._render_generation,
            base_row_height=self._row_height,
            header_height=self._header_height,  # Include header height for proper rendering
            waveform_max_time=self._model._session.waveform_max_time if self._model and self._model._session else None,  # Add waveform max time for renderer
            signal_range_cache=self._signal_range_cache,  # Pass signal range cache for analog rendering
            highlight_selected=self._highlight_selected,  # Pass highlight flag
            layout=self._layout,  # Pass the new layout
        )
    
    def _render_to_image(self, params: RenderParams, generation: int) -> Tuple[QImage, int, float]:
        """Render waveforms to an image (runs in thread pool)."""
        # Start timing
        render_start_time = time_module.time()

        # Log first render
        if not hasattr(self, '_first_render_logged'):
            self._first_render_logged = True
            tprint(f"  WaveformCanvas: First render triggered")

        # Timing for draw command generation
        draw_cmd_start = time_module.time()
        
        # Generate draw commands only for signals in the render area
        if 'layout' in params:
            layout = params['layout']
            # Calculate which signals are in the render area (with buffer)
            y_offset = params.get('header_height', RENDERING.DEFAULT_HEADER_HEIGHT)
            viewport_top = y_offset
            viewport_bottom = params['height']

            # Add buffer zones for smooth scrolling
            base_row_height = params.get('base_row_height', 20)
            buffer_rows = 3
            buffer_distance = buffer_rows * base_row_height * 2
            render_top = viewport_top - buffer_distance
            render_bottom = viewport_bottom + buffer_distance

            # Collect signals and group data to render
            signals_to_render = []
            group_draw_data: Dict[SignalNodeID, GroupDrawingPayload] = {}

            if layout:
                for i, row in enumerate(layout.rows):
                    if i >= len(layout.row_offsets):
                        break
                    y = layout.row_offsets[i] + y_offset - params['scroll_value']
                    row_bottom = y + row.height_px

                    # Check if this row is in the render area
                    if not (row_bottom < render_top or y > render_bottom):
                        if row.kind == 'signal':
                            node = row.source
                            if isinstance(node, SignalNode) and node.handle is not None:
                                signals_to_render.append(node)
                        elif row.kind == 'group_content' and row.descriptor:
                            # Add all child signals from the group
                            signals_to_render.extend(row.descriptor.children)

            # Get waveform max time from session
            waveform_max_time = self._model._session.waveform_max_time if self._model and self._model._session else None

            # Generate draw commands only for signals in render area
            draw_commands = self._generate_all_draw_commands(
                signals_to_render,
                params['start_time'],
                params['end_time'],
                params['width'],
                waveform_max_time
            )

            # Build group drawing payloads
            signal_range_cache = params.get('signal_range_cache', {})

            if layout:
                for i, row in enumerate(layout.rows):
                    if row.kind == 'group_content' and row.descriptor:
                        group_id = row.descriptor.cache_key

                        # Compute group range if not cached
                        if group_id not in signal_range_cache or signal_range_cache[group_id].min == float('inf'):
                            min_val = float('inf')
                            max_val = float('-inf')

                            for child in row.descriptor.children:
                                if child.handle is None:
                                    continue
                                # Get the actual Signal object if loaded
                                signal_obj = None
                                if child.signal.is_loaded():
                                    try:
                                        signal_obj = child.signal.get_signal_blocking(timeout=0.001)
                                    except (RuntimeError, TimeoutError):
                                        pass

                                if signal_obj is not None:
                                    from .signal_renderer import compute_global_signal_range
                                    cmin, cmax = compute_global_signal_range(child.format.data_format, signal_obj, child.var)
                                else:
                                    # Fallback to viewport samples
                                    dd = draw_commands.draw_commands.get(child.handle)
                                    if dd and dd.samples:
                                        vals = [s.value_float for _, s in dd.samples if s.value_float is not None]
                                        if vals:
                                            cmin = min(vals)
                                            cmax = max(vals)
                                        else:
                                            cmin, cmax = 0.0, 1.0
                                    else:
                                        cmin, cmax = 0.0, 1.0
                                if cmin < min_val:
                                    min_val = cmin
                                if cmax > max_val:
                                    max_val = cmax

                            if min_val == float('inf') or max_val == float('-inf') or min_val == max_val:
                                if min_val == float('inf') or max_val == float('-inf'):
                                    min_val, max_val = 0.0, 1.0
                                else:
                                    margin = abs(min_val) * 0.1 if min_val != 0 else 1.0
                                    min_val -= margin
                                    max_val += margin

                            from .data_model import DataFormat
                            signal_range_cache[group_id] = SignalRangeCache(min=min_val, max=max_val, viewport_ranges={}, data_format=DataFormat.UNSIGNED)

                        # Build child drawings dict
                        child_drawings = {}
                        for child in row.descriptor.children:
                            if child.handle is not None and child.handle in draw_commands.draw_commands:
                                child_drawings[child.handle] = draw_commands.draw_commands[child.handle]

                        group_draw_data[group_id] = GroupDrawingPayload(
                            descriptor=row.descriptor,
                            child_drawings=child_drawings,
                            range=signal_range_cache[group_id]
                        )

            params['draw_commands'] = draw_commands.draw_commands
            params['group_draw_data'] = group_draw_data
        else:
            params['draw_commands'] = {}
            params['group_draw_data'] = {}
        
        draw_cmd_time = (time_module.time() - draw_cmd_start) * 1000
        
        
        # Timing for image creation and painting
        paint_start = time_module.time()
        
        # Create image at device-pixel resolution
        dpr = float(params.get('dpr', 1.0))
        w_px = max(1, int(math.ceil(params['width'] * dpr)))
        h_px = max(1, int(math.ceil(params['height'] * dpr)))
        image = QImage(w_px, h_px, QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(dpr)
        # Use darker background color by default (for invalid ranges)
        image.fill(QColor(config.COLORS.BACKGROUND_INVALID))
        
        # Create painter; disable geometry antialiasing for crisp lines, keep text AA
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        
        try:
            # First paint the valid time range background
            waveform_max_time = self._model._session.waveform_max_time if self._model and self._model._session else None
            waveform_min_time = self._model._session.waveform_min_time if self._model and self._model._session else 0

            if waveform_max_time is not None and params['width'] > 0:
                # Calculate pixel positions for time boundaries
                x_min = int((waveform_min_time - params['start_time']) * params['width'] /
                           (params['end_time'] - params['start_time']))
                x_max = int((waveform_max_time + 1 - params['start_time']) * params['width'] /
                           (params['end_time'] - params['start_time']))

                # Clip to image bounds
                x_min = max(0, x_min)
                x_max = min(params['width'], x_max)

                # Paint the valid time range with lighter background
                if x_max > x_min:
                    painter.fillRect(x_min, 0, x_max - x_min, params['height'], QColor(config.COLORS.BACKGROUND))

            # Render normal waveforms
            self._render_waveforms(painter, params)
        finally:
            painter.end()
        
        paint_time = (time_module.time() - paint_start) * 1000
        
        # Calculate render time
        render_time_ms = (time_module.time() - render_start_time) * 1000

        # Log first render timing
        if hasattr(self, '_first_render_logged') and self._first_render_logged:
            self._first_render_logged = False  # Reset flag
            tprint(f"    First render completed in {render_time_ms:.1f}ms")
            tprint(f"      Draw commands generation: {(draw_cmd_time):.1f}ms")
            tprint(f"      Actual painting: {paint_time:.1f}ms")

        return image, generation, render_time_ms
    
    
    def _render_waveforms(self, painter: QPainter, params: RenderParams) -> None:
        """Render waveforms using new layout system."""

        # Check if we have draw commands
        draw_commands = params.get('draw_commands', {})
        group_draw_data = params.get('group_draw_data', {})
        layout = params.get('layout')

        if not layout:
            # No layout means no rows to render
            painter.setPen(QColor(config.COLORS.TEXT_MUTED))
            painter.setFont(QFont("Arial", RENDERING.FONT_SIZE_LARGE))
            painter.drawText(params['width'] // 2 - 50, params['height'] // 2, "No signals to display")
            return

        # Waveforms need to be offset by header height
        y_offset = params.get('header_height', RENDERING.DEFAULT_HEADER_HEIGHT)

        painter.save()
        # Set clipping to prevent drawing outside the waveform area
        painter.setClipRect(0, y_offset, params['width'], params['height'] - y_offset)

        # Calculate visible viewport bounds for culling with buffer zones
        viewport_top = y_offset
        viewport_bottom = params['height']

        # Add buffer zones: render 3 extra rows above and below visible area
        base_row_height = params.get('base_row_height', 20)
        buffer_rows = 3
        buffer_distance = buffer_rows * base_row_height * 2

        # Expand the render bounds by the buffer distance
        render_top = viewport_top - buffer_distance
        render_bottom = viewport_bottom + buffer_distance

        # Draw each visible row using layout
        for i, row in enumerate(layout.rows):
            if i >= len(layout.row_offsets):
                break

            # Calculate y position: row offset minus scroll offset
            y = layout.row_offsets[i] + y_offset - params['scroll_value']
            row_height = row.height_px

            # Viewport culling: skip rows outside the render area
            row_bottom = y + row_height
            if row_bottom < render_top or y > render_bottom:
                continue

            # Draw the row based on its type
            self._draw_layout_row(painter, row, i, y, row_height, draw_commands, group_draw_data, params)

        painter.restore()
        
    
    
    def _draw_time_ruler_simple(self, painter: QPainter, params: RenderParams) -> None:
        """Simple version of time ruler drawing."""
        # Use default ruler config since we can't access model from thread
        ruler_config = TimeRulerConfig()
        
        # Draw ruler background
        painter.fillRect(0, 0, params['width'], RENDERING.DEFAULT_HEADER_HEIGHT, QColor(config.COLORS.HEADER_BACKGROUND))
        pen = QPen(QColor(config.COLORS.RULER_LINE))
        pen.setWidth(0)
        painter.setPen(pen)
        painter.drawLine(0, RENDERING.DEFAULT_HEADER_HEIGHT - 1, params['width'], RENDERING.DEFAULT_HEADER_HEIGHT - 1)
        
        # Simple time labels
        painter.setPen(QColor(config.COLORS.TEXT))
        painter.setFont(QFont(RENDERING.FONT_FAMILY, RENDERING.FONT_SIZE_NORMAL))
        
        # Draw some time markers
        num_ticks = 10
        for i in range(num_ticks + 1):
            x = i * params['width'] // num_ticks
            time = params['start_time'] + (params['end_time'] - params['start_time']) * i // num_ticks
            
            # Draw tick
            painter.drawLine(x, 30, x, 34)
            
            # Draw label
            label = f"{time}"
            painter.drawText(x - 20, 5, 40, 20, Qt.AlignmentFlag.AlignCenter, label)
    
    def _draw_layout_row(self, painter: QPainter, row: VisibleRow, row_index: int, y: int, row_height: int,
                         draw_commands: Dict[SignalHandle, SignalDrawingData],
                         group_draw_data: Dict[SignalNodeID, GroupDrawingPayload],
                         params: RenderParams) -> None:
        """Draw a row based on its layout descriptor."""
        # Determine background color
        is_selected = False
        if self._model and self._model._controller:
            is_selected = row.source.instance_id in self._model._controller._selected_ids

        if params.get('highlight_selected', False) and is_selected:
            # Use solid dark purple selection background for highlighted selected signals
            bg_color = QColor(config.COLORS.SELECTION_BACKGROUND)
        elif row_index % 2 == 0:
            # Use alternating row color
            bg_color = QColor(config.COLORS.ALTERNATE_ROW)
        else:
            # Use default background (transparent, no fill needed)
            bg_color = None

        # Draw background if needed
        if bg_color:
            painter.fillRect(0, y, params['width'], row_height, bg_color)

        # Draw border
        border_pen = QPen(QColor(config.COLORS.BORDER))
        border_pen.setWidth(0)  # cosmetic 1 device-pixel
        painter.setPen(border_pen)
        painter.drawLine(0, y + row_height - 1, params['width'], y + row_height - 1)

        # Handle different row types
        if row.kind == 'group_header':
            # Just draw the background and border for group headers
            pass
        elif row.kind == 'signal':
            # Draw a regular signal
            node = row.source
            if isinstance(node, SignalNode) and node.handle is not None:
                # Check if signal is loading
                if not node.signal.is_loaded():
                    # Draw loading placeholder
                    painter.setPen(QPen(QColor(128, 128, 128)))  # Gray color for loading text
                    painter.setFont(QFont("Arial", 9))
                    loading_text = "Loading..."
                    text_rect = QRectF(10, y + row_height // 2 - 10, params['width'] - 20, 20)
                    painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, loading_text)
                # Check if we have draw commands for this signal
                elif node.handle in draw_commands:
                    drawing_data = draw_commands[node.handle]
                    # Create node_info for renderer compatibility
                    node_info: NodeInfo = {
                        'name': node.name,
                        'handle': node.handle,
                        'is_group': False,
                        'format': node.format,
                        'render_type': node.format.render_type,
                        'height_scaling': node.height_scaling,
                        'instance_id': node.instance_id,
                        'is_selected': is_selected,
                        'signal': node.signal.get_signal_blocking(timeout=0.001) if node.signal.is_loaded() else None,
                        'var': node.var if hasattr(node, 'var') else None,
                        'file_id': node.file_id,
                    }
                    render_type = node.format.render_type
                    if render_type == RenderType.BOOL:
                        draw_digital_signal(painter, node_info, drawing_data, y, row_height, params)
                    elif render_type == RenderType.BUS:
                        draw_bus_signal(painter, node_info, drawing_data, y, row_height, params)
                    elif render_type == RenderType.ANALOG:
                        draw_analog_signal(painter, node_info, drawing_data, y, row_height, params)
                    elif render_type == RenderType.EVENT:
                        draw_event_signal(painter, node_info, drawing_data, y, row_height, params)
                # else: Signal not loaded and no draw commands - show nothing (shouldn't happen)
        elif row.kind == 'group_content' and row.descriptor:
            # Draw group content using the registry
            group_id = row.descriptor.cache_key
            if group_id in group_draw_data:
                payload = group_draw_data[group_id]
                mode = row.descriptor.mode
                if mode in GROUP_RENDERERS:
                    renderer = GROUP_RENDERERS[mode]
                    renderer(painter, payload, y, row_height, params)

    
    def _draw_cursor(self, painter: QPainter, params: RenderParams) -> None:
        """Thread-safe version of cursor drawing."""
        if params['cursor_time'] >= params['start_time'] and params['cursor_time'] <= params['end_time']:
            x = int((params['cursor_time'] - params['start_time']) * params['width'] / 
                   (params['end_time'] - params['start_time']))
            
            painter.setPen(QPen(QColor(config.COLORS.CURSOR), RENDERING.CURSOR_WIDTH))
            painter.drawLine(x, 0, x, params['height'])


    def _calculate_and_store_ruler_info(self) -> None:
        """Calculate and store ruler information for grid drawing."""
        # Get configuration from session if available
        if self._model and self._model._session:
            ruler_config = self._model._session.time_ruler_config
            # Update renderer with current config and timescale
            self._time_grid_renderer.update_config(ruler_config)
            if self._model._session.timescale:
                self._time_grid_renderer.update_timescale(self._model._session.timescale)
                display_unit = self._model._session.timescale.unit
            else:
                display_unit = ruler_config.time_unit
        else:
            # Use default configuration
            ruler_config = TimeRulerConfig()
            self._time_grid_renderer.update_config(ruler_config)
            display_unit = ruler_config.time_unit
        
        # Check if clock mode is active
        clock_mode = False
        if self._model and self._model._session and self._model._session.clock_signal:
            clock_period, phase_offset, _ = self._model._session.clock_signal
            self._time_grid_renderer.set_clock_signal(clock_period, phase_offset)
            clock_mode = True
        else:
            self._time_grid_renderer.set_clock_signal(None)
        
        # Calculate tick positions and step size
        tick_infos, step_size = self._time_grid_renderer.calculate_ticks(
            self._start_time, self._end_time, self.width(), display_unit, clock_mode
        )
        
        # Store tick positions for grid drawing
        self._last_tick_positions = tick_infos
        self._last_ruler_config = ruler_config
        
    def _draw_time_ruler(self, painter: QPainter) -> None:
        """Draw the time ruler according to spec 4.11."""
        # If model not loaded, don't draw ruler
        if not self._model:
            return

        # Use stored configuration if available
        if self._last_ruler_config is not None and self._last_tick_positions:
            tick_positions = self._last_tick_positions
        else:
            # Fallback: calculate now
            self._calculate_and_store_ruler_info()
            tick_positions = self._last_tick_positions
        
        # Check if clock mode is active
        clock_mode = False
        if self._model and self._model._session and self._model._session.clock_signal:
            clock_mode = True
        
        # Renderer is always available, use it to draw ruler
        self._time_grid_renderer.render_ruler(
            painter, tick_positions, self.width(), self._header_height, clock_mode
        )
    


    
    def _generate_all_draw_commands(self, signal_nodes: List[SignalNode], start_time: Time, end_time: Time, canvas_width: int, waveform_max_time: Optional[Time]) -> CachedWaveDrawData:
        """Generate drawing commands for all signals (runs in thread pool)."""
        result = CachedWaveDrawData()
        result.viewport_hash = f"{start_time}_{end_time}_{canvas_width}"

        # Debug timing
        total_start = time_module.time()
        signal_times: List[Tuple[str, float]] = []

        # Process each signal
        for node in signal_nodes:
            if node.handle is not None:
                drawing_data = generate_signal_draw_commands(
                    node, start_time, end_time, canvas_width,
                    waveform_max_time
                )
                if drawing_data:
                    result.draw_commands[node.handle] = drawing_data

        return result
    
    def _time_to_x(self, time: Time) -> int:
        """Convert time to x coordinate."""
        return int((time - self._start_time) * self._time_scale)
        
    def _x_to_time(self, x: int) -> Time:
        """Convert x coordinate to time."""
        return int(x / self._time_scale + self._start_time)
        
    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Handle mouse presses: left sets cursor, right starts ROI selection."""
        if event.button() == Qt.MouseButton.LeftButton:
            time = self._x_to_time(int(event.position().x()))
            self._cursor_time = max(self._start_time, min(time, self._end_time))
            self.cursorMoved.emit(self._cursor_time)
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            x = int(event.position().x())
            self._start_roi_selection(x)
    
    def _paint_background_with_boundaries(self, painter: QPainter) -> None:
        """Paint background with different colors for valid/invalid time ranges."""
        # Default background color for entire canvas
        painter.fillRect(self.rect(), QColor(config.COLORS.BACKGROUND_DARK))  # Darker for invalid ranges

        # Get waveform bounds from session
        waveform_max_time = self._model._session.waveform_max_time if self._model and self._model._session else None
        waveform_min_time = self._model._session.waveform_min_time if self._model and self._model._session else 0

        # If we have valid waveform bounds, paint the valid range differently
        if waveform_max_time is not None and self.width() > 0:
            # Calculate pixel positions for time boundaries
            x_min = self._time_to_x(waveform_min_time)
            x_max = self._time_to_x(waveform_max_time + 1)  # +1 to include the last timestamp

            # Clip to widget bounds
            x_min = max(0, x_min)
            x_max = min(self.width(), x_max)

            # Paint the valid time range with a lighter background
            if x_max > x_min:
                painter.fillRect(x_min, 0, x_max - x_min, self.height(), QColor(config.COLORS.BACKGROUND))
    
    def _draw_boundary_lines(self, painter: QPainter) -> None:
        """Draw vertical lines at waveform time boundaries."""
        # Get waveform bounds from session
        waveform_max_time = self._model._session.waveform_max_time if self._model and self._model._session else None
        waveform_min_time = self._model._session.waveform_min_time if self._model and self._model._session else 0

        if waveform_max_time is None:
            return

        # Set up pen for boundary lines (cosmetic for HiDPI)
        pen = QPen(QColor(config.COLORS.BOUNDARY_LINE))
        pen.setWidth(0)  # 1 device pixel
        painter.setPen(pen)

        # Draw line at time 0 if visible
        if waveform_min_time >= self._start_time and waveform_min_time <= self._end_time:
            x_min = self._time_to_x(waveform_min_time)
            painter.drawLine(x_min, 0, x_min, self.height())

        # Draw line at max_time + 1 if visible
        boundary_time = waveform_max_time + 1
        if boundary_time >= self._start_time and boundary_time <= self._end_time:
            x_max = self._time_to_x(boundary_time)
            painter.drawLine(x_max, 0, x_max, self.height())
    
    def _draw_debug_counters(self, painter: QPainter) -> None:
        """Draw debug counters in bottom right corner."""
        # Save painter state
        painter.save()
        
        # Set up font and colors
        font = QFont(RENDERING.DEBUG_FONT_FAMILY, RENDERING.DEBUG_FONT_SIZE)
        font.setBold(True)
        painter.setFont(font)
        
        # Format times to 1 decimal place
        paint_time_ms = self._last_paint_time_ms
        render_time_ms = self._last_render_time_ms
        
        # Create text in requested format
        debug_text = f"PaintEvent # {self._paint_frame_counter} ({paint_time_ms:.1f} ms), RenderedFrame # {self._render_complete_counter} ({render_time_ms:.1f} ms)"
        # Calculate text position
        metrics = QFontMetrics(font)
        text_rect = metrics.boundingRect(debug_text)
        x = self.width() - text_rect.width() - RENDERING.DEBUG_TEXT_MARGIN
        y = self.height() - RENDERING.DEBUG_TEXT_MARGIN
        
        # Draw background
        padding = RENDERING.DEBUG_TEXT_PADDING // 2
        bg_rect = QRectF(x - padding, y - text_rect.height() - padding, 
                        text_rect.width() + 2 * padding, text_rect.height() + 2 * padding)
        painter.fillRect(bg_rect, QColor(*config.COLORS.DEBUG_BACKGROUND))
        
        # Draw text
        painter.setPen(QColor(config.COLORS.DEBUG_TEXT))
        painter.drawText(x, y, debug_text)
        
        # Restore painter state
        painter.restore()
    
    # ---- ROI selection helpers ----
    def _start_roi_selection(self, x: int) -> None:
        self._roi_selection_active = True
        self._roi_start_x = max(0, min(x, self.width()))
        self._roi_current_x = self._roi_start_x
        # Force overlay-only update
        self.update()
    
    def _update_roi_selection(self, x: int) -> None:
        if not self._roi_selection_active:
            return
        self._roi_current_x = max(0, min(int(x), self.width()))
        # Trigger overlay repaint for smooth feedback
        self.update()
    
    def _finish_roi_selection(self) -> None:
        if not self._roi_selection_active or self._roi_start_x is None or self._roi_current_x is None:
            self._clear_roi_selection()
            return
        x0 = self._roi_start_x
        x1 = self._roi_current_x
        if x0 == x1:
            # No selection; clear and return
            self._clear_roi_selection()
            return
        left_x = min(x0, x1)
        right_x = max(x0, x1)
        start_time = self._x_to_time(left_x)
        end_time = self._x_to_time(right_x)
        # Emit signal; controller will enforce min width and clamp
        self.roiSelected.emit(start_time, end_time)
        self._clear_roi_selection()
    
    def _clear_roi_selection(self) -> None:
        self._roi_selection_active = False
        self._roi_start_x = None
        self._roi_current_x = None
        self.update()
    
    def _paint_roi_overlay(self, painter: QPainter) -> None:
        if not self._roi_selection_active or self._roi_start_x is None or self._roi_current_x is None:
            return
        x0 = self._roi_start_x
        x1 = self._roi_current_x
        left_x = min(x0, x1)
        right_x = max(x0, x1)
        # Draw semi-transparent fill
        color = QColor(config.COLORS.ROI_SELECTION_COLOR)
        # Apply opacity
        alpha = int(max(0.0, min(1.0, config.COLORS.ROI_SELECTION_OPACITY)) * 255)
        fill_color = QColor(color.red(), color.green(), color.blue(), alpha)
        painter.fillRect(left_x, 0, right_x - left_x, self.height(), fill_color)
        # Draw guide lines
        pen = QPen(QColor(config.COLORS.ROI_GUIDE_LINE_COLOR))
        pen.setWidth(RENDERING.ROI_GUIDE_LINE_WIDTH)
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(left_x, 0, left_x, self.height())
        painter.drawLine(right_x, 0, right_x, self.height())
    
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._roi_selection_active:
            self._update_roi_selection(int(event.position().x()))
        else:
            super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton and self._roi_selection_active:
            self._finish_roi_selection()
            event.accept()
        else:
            super().mouseReleaseEvent(event)
    
    def keyPressEvent(self, event: QKeyEvent) -> None:
        # V key temporarily force-enables value tooltips
        if event.key() == Qt.Key.Key_V:
            self._value_tooltips_force_enabled = True
            self.update()
            # Don't accept the event - let it propagate
        # Escape cancels ROI selection if active
        elif event.key() == Qt.Key.Key_Escape and self._roi_selection_active:
            self._clear_roi_selection()
            event.accept()
            return
        super().keyPressEvent(event)
    
    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        # V key release disables force-enable
        if event.key() == Qt.Key.Key_V:
            self._value_tooltips_force_enabled = False
            self.update()
            # Don't accept the event - let it propagate
        super().keyReleaseEvent(event)
    
    def closeEvent(self, event: QCloseEvent) -> None:
        """Clean up resources when closing."""
        super().closeEvent(event)
