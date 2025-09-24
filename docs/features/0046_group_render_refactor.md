# Group Rendering Implementation Plan: Removing Virtual Nodes

## Executive Summary

WaveformCanvas currently manufactures “virtual” SignalNodeSignal instances to coerce the renderer into drawing group render modes such as OVERLAPPED. This indirection leaks across layout, caching, tooltips, and tests. We will replace the virtual-node hack with a first-class group rendering pipeline built on explicit row descriptors, dedicated draw data, and a registry of group renderers. The refactor keeps compatibility with existing controller/events while unlocking additional group modes (STACKED_AREA, PIPELINE) without further hacks.

## Current Implementation Analysis

### Virtual Node Pipeline
1. `WaveformCanvas.updateVisibleNodes()` flattens the tree into `_visible_nodes`.
2. For expanded groups using a non-default `GroupRenderMode`, the canvas injects an artificial `SignalNodeSignal` with `handle=None`, plus `_group_render_parent` / `_group_render_children` attributes.
3. Layout state (`_row_to_node`, `_row_heights`) and render params refer to these synthetic nodes as if they were signals.
4. `_render_to_image()` special-cases virtual nodes when deciding which signals to sample.
5. `_draw_row()` detects virtual nodes via `hasattr` and dispatches to `draw_overlapped_group()`.

### Additional Pain Points Observed in Code
- Row metadata is conflated: `_visible_nodes`, `_row_to_node`, `visible_nodes_info`, and `row_heights` all derive from the same flat list but represent different concerns.
- Selection, highlight, and value tooltip paths walk `_visible_nodes` directly and will misbehave once rows no longer have a 1:1 mapping with SignalNode instances.
- The draw command cache (`CachedWaveDrawData.draw_commands`) uses `SignalHandle` keys, so virtual nodes pollute caches only indirectly; however the route for group min/max range caching relies on mutating `SignalRangeCache` inside `draw_overlapped_group()` which runs every paint.
- Tests such as `tests/test_overlapped_mode.py` assert on the presence of virtual nodes, coupling QA to the hack.
- Future group render modes listed in `GroupRenderMode` cannot reuse the current approach without proliferating more attribute hacks.

## Design Objectives
- Represent the rows we render with explicit, typed data structures.
- Separate layout (visible rows, heights, scrolling) from drawing data (sampled commands, cached ranges).
- Provide a pluggable registry that maps each `GroupRenderMode` to a renderer and pre-draw preparation hook.
- Preserve controller semantics (`StructureChangedEvent`, selection, highlighting, tooltips) without virtual nodes.
- Keep sampling and caching efficient by only touching the signals that appear on screen.
- Make space for STACKED_AREA / PIPELINE modes by construction, not by future refactors.

## Proposed Architecture

### Layout Data Model
Introduce a dedicated layout module (`wavescout/canvas_layout.py`) to model the rows we draw.

```python
VisibleRowKind = Literal['group_header', 'signal', 'group_content']

@dataclass(frozen=True)
class GroupContentDescriptor:
    group: SignalNodeGroup
    mode: GroupRenderMode
    children: list[SignalNodeSignal]
    height_scaling: int  # sum of child scalings, pre-clamped to >= 1
    cache_key: SignalNodeID  # use group.instance_id for range caching

@dataclass(frozen=True)
class VisibleRow:
    kind: VisibleRowKind
    source: SignalNode  # group header or concrete signal
    descriptor: Optional[GroupContentDescriptor] = None  # populated for group_content rows
    height_px: int

@dataclass
class CanvasLayout:
    rows: list[VisibleRow]
    row_offsets: list[int]  # top y-pixel before scroll, parallel to rows
    signal_rows: list[int]  # indices of rows whose kind == 'signal'
    group_content_rows: dict[SignalNodeID, int]  # group instance_id -> row index
```

`CanvasLayout` replaces `_visible_nodes`, `_row_to_node`, and `_row_heights` while remaining easy to reason about in tests.

### Layout Construction
`WaveformCanvas.updateVisibleNodes()` becomes `WaveformCanvas.rebuild_layout()` and:
- Recursively walks the `WaveformItemModel` tree.
- Emits a `VisibleRow(kind='group_header', ...)` for every group regardless of render mode.
- For groups with `GroupRenderMode.SEPARATE_ROWS` (or unset), recurses into children, emitting signal/group headers normally.
- For groups with alternate modes and `is_expanded`:
  - Gathers visible child signals (skip nested groups).
  - Computes `height_scaling = max(1, sum(child.height_scaling))`.
  - Emits a `VisibleRow(kind='group_content', source=group, descriptor=...)`.
  - Does **not** emit individual child rows.
- Collapsed groups only emit their header row.
- Computes `height_px = base_row_height * node.height_scaling` for signal rows and header rows; group content rows use the derived scaling.
- Pre-computes `row_offsets` for efficient hit-testing, tooltips, and partial rendering.

### Draw Command Preparation
`_render_to_image()` (or a helper) now works off `CanvasLayout`:
- Determine the set of signal handles in view by scanning `layout.signal_rows` and aggregating children from visible `group_content` rows.
- Sample those handles with `generate_signal_draw_commands()` as today, producing `signal_draw_commands: dict[SignalHandle, SignalDrawingData]`.
- Build `group_draw_data: dict[SignalNodeID, GroupDrawingPayload]` from layout + sampled data.

```python
@dataclass
class GroupDrawingPayload:
    descriptor: GroupContentDescriptor
    child_drawings: dict[SignalHandle, SignalDrawingData]
    range: SignalRangeCache  # global min/max for the group
```

Cache group ranges outside the renderer: reuse `WaveformCanvas._signal_range_cache` keyed by `descriptor.cache_key`, populate missing entries via a helper that queries the DB or samples.

### Rendering Pipeline
- Extend `RenderParams` in `wavescout/signal_renderer.py` to carry `layout`, `signal_draw_commands`, and `group_draw_data`.
- Replace `NodeInfo` with a richer `RowRenderInfo` TypedDict or dataclass that includes `row_kind`, `signal_handle`, `group_id`, `is_selected`, etc.
- `_render_waveforms()` iterates `layout.rows` instead of `_visible_nodes`.
- `_draw_row()` becomes a dispatcher:
  - `group_header`: draw background/highlight only.
  - `signal`: retrieve `signal_draw_commands[handle]` and call the existing signal renderer.
  - `group_content`: fetch `GroupDrawingPayload` and route to the registered group renderer.

Create a small registry in `signal_renderer.py`:

```python
GroupRenderer = Protocol:
    def __call__(self, painter: QPainter, payload: GroupDrawingPayload,
                 y: int, row_height: int, params: RenderParams) -> None: ...

GROUP_RENDERERS: dict[GroupRenderMode, GroupRenderer] = {
    GroupRenderMode.OVERLAPPED: draw_overlapped_group,
    # Future modes go here
}
```

`draw_overlapped_group()` is updated to consume `GroupDrawingPayload` (no attribute lookups, no cache mutation).

### State, Selection, and Tooltips
- Maintain `self._layout: CanvasLayout` on the canvas; drop `_visible_nodes`/`_row_to_node`.
- Selection/highlight logic uses `RowRenderInfo.is_selected` for both group headers and group-content rows (the content row mirrors the parent group selection state).
- Value tooltips iterate `layout.signal_rows` and fetch geometry via `row_offsets`; group-content rows can either show aggregated info (future enhancement) or be skipped for now. 
- Cursor ROI and marker alignment reuse `row_offsets` + `height_px`.

### Event & Controller Integration
- `WaveformController.set_group_render_mode()` still publishes `StructureChangedEvent(change_kind='group')`, which triggers the model to reset and the canvas to rebuild its layout.
- No changes to the event contract are required, but the canvas must rebuild `self._layout` on `layoutChanged`/`modelReset` as well.

### Extensibility Hooks
- `GroupContentDescriptor` is mode-agnostic; future renderers can enrich it (e.g., stacked area may need ordering metadata). This plan keeps the descriptor in a separate module so new modes can extend it without touching the canvas core.
- By isolating group range caching and renderer registry, additional modes gain consistent plumbing.

## Testing & Validation Strategy
- Extend existing pytest-qt cases to validate `CanvasLayout` invariants (row count, kinds, heights) after toggling render modes.
- Add unit tests for `canvas_layout.build_layout()` covering nested groups, collapsed states, and edge cases (no eligible children).
- Update rendering tests to ensure `draw_overlapped_group()` receives precomputed range data (e.g., mock payload with sentinel values).
- Run regression suite: `QT_QPA_PLATFORM=offscreen make test`, `make typecheck`, and targeted renders of VCD/FST fixtures in `test_inputs/`.


## Risks & Mitigations

This architecture removes the virtual node hack, keeps the canvas code type-safe, and provides a clear path for richer group visualizations without future rewrites.
