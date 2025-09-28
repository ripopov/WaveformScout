"""Canvas layout management for WaveformCanvas.

This module provides data structures and utilities for managing the layout
of rows in the waveform canvas, replacing the virtual node hack with explicit
row descriptors.
"""

from dataclasses import dataclass, field
from typing import Literal, Optional

from wavescout.data_model import SignalNodeID
from wavescout.data_model import GroupRenderMode, TreeNode, GroupNode, SignalNode
from wavescout.waveform_item_model import WaveformItemModel

__all__ = [
    'VisibleRowKind',
    'GroupContentDescriptor',
    'VisibleRow',
    'CanvasLayout',
    'build_layout',
]

VisibleRowKind = Literal['group_header', 'signal', 'group_content']


@dataclass(frozen=True)
class GroupContentDescriptor:
    """Descriptor for group content rows that are rendered together."""
    group: GroupNode
    mode: GroupRenderMode
    children: list[SignalNode]
    height_scaling: int  # sum of child scalings, pre-clamped to >= 1
    cache_key: SignalNodeID  # use group.instance_id for range caching


@dataclass(frozen=True)
class VisibleRow:
    """Represents a single row in the canvas layout."""
    kind: VisibleRowKind
    source: TreeNode  # group header or concrete signal
    descriptor: Optional[GroupContentDescriptor] = None  # populated for group_content rows
    height_px: int = 20  # will be computed based on scaling


@dataclass
class CanvasLayout:
    """Complete layout information for the canvas."""
    rows: list[VisibleRow] = field(default_factory=list)
    row_offsets: list[int] = field(default_factory=list)  # top y-pixel before scroll
    signal_rows: list[int] = field(default_factory=list)  # indices of rows with kind == 'signal'
    group_content_rows: dict[SignalNodeID, int] = field(default_factory=dict)  # group instance_id -> row index

    @property
    def total_height(self) -> int:
        """Total height of all rows."""
        if not self.rows:
            return 0
        if len(self.row_offsets) != len(self.rows):
            return 0
        return self.row_offsets[-1] + self.rows[-1].height_px

    def row_at_y(self, y: int) -> Optional[int]:
        """Find the row index at the given y coordinate."""
        if not self.rows or y < 0:
            return None

        # Binary search for the row
        left, right = 0, len(self.rows) - 1
        while left <= right:
            mid = (left + right) // 2
            row_top = self.row_offsets[mid]
            row_bottom = row_top + self.rows[mid].height_px

            if y < row_top:
                right = mid - 1
            elif y >= row_bottom:
                left = mid + 1
            else:
                return mid

        return None


def _collect_visible_signals(group: GroupNode) -> list[SignalNode]:
    """Collect all visible signal children of a group (not nested groups)."""
    signals: list[SignalNode] = []
    for child in group.children:
        if isinstance(child, SignalNode):
            signals.append(child)
        # Skip nested groups for group render modes
    return signals


def _walk_tree(
    node: TreeNode,
    model: WaveformItemModel,
    base_row_height: int,
) -> list[VisibleRow]:
    """Recursively walk the tree and generate visible rows."""
    rows: list[VisibleRow] = []

    if isinstance(node, GroupNode):
        # Always emit group header
        header_row = VisibleRow(
            kind='group_header',
            source=node,
            height_px=base_row_height * node.height_scaling
        )
        rows.append(header_row)

        # Check if group is expanded (stored in node itself)
        is_expanded = node.is_expanded

        if is_expanded:
            # Check render mode
            render_mode = node.group_render_mode

            if render_mode is None or render_mode == GroupRenderMode.SEPARATE_ROWS:
                # Recurse into children normally
                for child in node.children:
                    rows.extend(_walk_tree(child, model, base_row_height))
            else:
                # Create group content row
                signals = _collect_visible_signals(node)
                if signals:  # Only create content row if there are signals
                    height_scaling = max(1, sum(s.height_scaling for s in signals))
                    descriptor = GroupContentDescriptor(
                        group=node,
                        mode=render_mode,
                        children=signals,
                        height_scaling=height_scaling,
                        cache_key=node.instance_id
                    )
                    content_row = VisibleRow(
                        kind='group_content',
                        source=node,
                        descriptor=descriptor,
                        height_px=base_row_height * height_scaling
                    )
                    rows.append(content_row)

    elif isinstance(node, SignalNode):
        # Regular signal row
        signal_row = VisibleRow(
            kind='signal',
            source=node,
            height_px=base_row_height * node.height_scaling
        )
        rows.append(signal_row)

    return rows


def build_layout(
    model: WaveformItemModel,
    base_row_height: int = 20,
) -> CanvasLayout:
    """Build a complete canvas layout from the waveform item model.

    Args:
        model: The waveform item model containing the signal tree
        base_row_height: Base height for a single row in pixels

    Returns:
        Complete layout information for rendering
    """
    layout = CanvasLayout()

    # Walk the tree to collect visible rows
    if model._session and model._session.root_nodes:
        for root_node in model._session.root_nodes:
            layout.rows.extend(_walk_tree(root_node, model, base_row_height))

    # Compute row offsets and indices
    current_y = 0
    for i, row in enumerate(layout.rows):
        layout.row_offsets.append(current_y)
        current_y += row.height_px

        # Track signal rows
        if row.kind == 'signal':
            layout.signal_rows.append(i)

        # Track group content rows
        elif row.kind == 'group_content' and row.descriptor:
            layout.group_content_rows[row.descriptor.cache_key] = i

    return layout