# GroupRenderMode.OVERLAPPED Implementation Plan

## 1. Use Cases and Requirements Analysis

### Core Functionality
Implement a new group rendering mode called OVERLAPPED where all signal waveforms within a group are rendered together in the same row, overlaid on top of each other with different colors.

### Specific Requirements

1. **Context Menu Integration**
   - Add "Render Mode" submenu to group context menu in SignalNamesView
   - Options: "Separate Rows" (default, current behavior) and "Overlapped" 
   - Render Mode menu disabled for groups containing subgroups (only flat groups supported)

2. **Display Behavior**
   - Group node remains as an empty row with height_scaling = 1 (standard group row)
   - All child signal rows are replaced by a single combined overlapped waveform row
   - The combined row's height_scaling = sum of all children's height_scaling values
   - Individual child nodes no longer render their own rows (rendering skipped)
   - All child signals rendered as analog waveforms regardless of their original render type
   - The overlapped waveform appears immediately after the group node row

3. **Scaling Mode**
   - AnalogScalingMode.SCALE_TO_ALL_DATA automatically selected for the group
   - Global min/max computed across ALL child signals
   - Stored in _signal_range_cache with a composite key for the group

4. **Automatic Color Assignment**
   - When switching to OVERLAPPED, automatically assign rainbow colors to child nodes
   - Each child gets a distinct color from a generated palette
   - Colors are set in each child's DisplayFormat.color field
   - User can later manually change individual colors

5. **Rendering Implementation**
   - New overlapped group renderer in signal_renderer.py
   - Takes arrays of nodes and their sampled SignalDrawingData
   - Renders all waveforms in the same vertical space with transparency/layering

### Constraints
- No support for nested groups in OVERLAPPED mode (flat groups only)
- All signals forced to analog rendering regardless of type
- Global scaling across all signals in the group

## 2. Codebase Research

### Key Files Analyzed

**`wavescout/data_model.py`**
- Contains `GroupRenderMode` enum (lines 69-73) with OVERLAPPED already defined
- `SignalNode` dataclass has `group_render_mode` field (line 102)
- `height_scaling` field controls row height (line 104)
- `DisplayFormat` contains `color` field (line 89) and `analog_scaling_mode` (line 90)
- `SignalRangeCache` class (lines 316-320) stores min/max ranges for analog signals

**`wavescout/signal_names_view.py`**
- `_show_context_menu()` method (line 144) builds context menus
- Groups get special menu handling (lines 168-182)
- Existing submenus for render type (lines 218-262) and data format (lines 186-209)

**`wavescout/signal_renderer.py`**
- `draw_analog_signal()` function (line 659) provides reference implementation
- Uses `SignalDrawingData` with sampled values
- Handles signal bounds calculation and polyline rendering
- Color handling via `get_signal_color()` (line 66)

**`wavescout/waveform_canvas.py`**
- Groups currently skip rendering (line 603-604)
- Row height calculation uses `height_scaling` field
- Signal range cache maintained at line 107

**`wavescout/waveform_controller.py`**
- Central controller for state changes
- Would need new methods for changing group render mode
- Handles format changes via `set_node_format()` methods

**`wavescout/config.py`**
- No existing rainbow/palette colors defined
- Would need color generation utilities

### Current Group Handling
- Groups are currently display-only containers
- They occupy a row but don't render any waveform
- Children are rendered in separate rows below
- No existing overlapped rendering logic

## 3. Implementation Planning

### File-by-File Changes

#### 1. `wavescout/color_utils.py` (NEW FILE)
**Purpose**: Color palette generation utilities

**Functions to Add**:
- `generate_rainbow_colors(count: int) -> List[str]`: Generate distinct rainbow colors
- `generate_contrasting_colors(count: int) -> List[str]`: Alternative palette generator

**Implementation Notes**:
- Use HSV color space for even distribution
- Convert to hex strings for DisplayFormat.color
- Ensure sufficient contrast between colors

#### 2. `wavescout/data_model.py`
**Classes to Modify**: None (already has required fields)

**Validation to Add**:
- Method to check if group supports OVERLAPPED mode (no nested groups)

#### 3. `wavescout/waveform_controller.py`
**Class**: `WaveformController`

**Methods to Add**:
- `set_group_render_mode(node: SignalNode, mode: GroupRenderMode) -> None`
  - Validate group has no subgroups
  - Update group's render mode
  - Adjust height_scaling (sum of children)
  - Force children to analog rendering
  - Assign rainbow colors to children
  - Clear relevant caches
  - Emit structure/format change events

- `_assign_rainbow_colors(group: SignalNode) -> None`
  - Generate palette based on child count
  - Set each child's DisplayFormat.color

#### 4. `wavescout/signal_names_view.py`
**Class**: `SignalNamesView`

**Method**: `_show_context_menu()`

**Changes**:
- After line 173 (group menu section), add Render Mode submenu
- Create QActionGroup for exclusive selection
- Add "Separate Rows" action (checked if current mode is SEPARATE_ROWS)
- Add "Overlapped" action (checked if current mode is OVERLAPPED)
- Disable menu if group has subgroups
- Connect actions to controller's `set_group_render_mode()`

#### 5. `wavescout/signal_renderer.py`
**New Function**: `draw_overlapped_group()`

**Parameters**:
- `painter: QPainter`
- `group_node: SignalNode`
- `child_nodes: List[SignalNode]`
- `child_drawing_data: List[SignalDrawingData]`
- `y: int`
- `row_height: int`
- `params: RenderParams`

**Implementation**:
- Calculate global min/max from signal_range_cache
- For each child signal:
  - Get its color from DisplayFormat.color
  - Set painter pen with slight transparency for overlay effect
  - Map values to Y coordinates using global range
  - Draw polyline similar to draw_analog_signal
- Handle undefined/high-impedance regions
- Add legend or labels if space permits

#### 6. `wavescout/waveform_canvas.py`
**Class**: `WaveformCanvas`

**Method**: `paintEvent()`

**Changes at line 603** (where groups skip rendering):
- Group nodes still render as empty rows (existing behavior preserved)
- For OVERLAPPED groups, after rendering the empty group row:
  - Render a single combined overlapped waveform row immediately after
  - Collect all child nodes and their drawing data
  - Call `draw_overlapped_group()` with combined height_scaling
  - Skip rendering individual child signal rows (mark them as handled)
- Row height calculation: group row = 1, overlapped row = sum of children's height_scaling

**Method**: `_calculate_signal_range()`

**Changes**:
- For OVERLAPPED groups, compute range across all children
- Store with group's instance_id as key

#### 7. `wavescout/signal_sampling.py`
**Changes**: None required (existing sampling works for overlapped mode)

### Algorithm Descriptions

#### Rainbow Color Generation Algorithm
1. Calculate hue step: `360 / count` degrees
2. For each index i:
   - Hue = `i * step`
   - Saturation = 0.7 (good visibility)
   - Value = 0.9 (bright but not glaring)
3. Convert HSV to RGB then to hex string
4. Return list of color strings

#### Overlapped Rendering Algorithm
1. Determine global Y range from cached min/max across all children
2. Add 10% headroom to avoid clipping
3. For each child signal:
   - Set pen color with 80% opacity for layering
   - Iterate through sample points
   - Map value to Y using global range
   - Build polyline segments
   - Handle discontinuities (undefined/high-Z)
   - Draw polyline
4. Optionally draw legend with signal names and colors

#### Height Scaling Calculation
1. When switching to OVERLAPPED:
   - Group node keeps height_scaling = 1 (empty row)
   - Create virtual overlapped row with height = sum of all child height_scaling values
   - Mark individual child rows as "skip rendering" (height effectively 0)
   - Total display height = 1 (group) + sum (overlapped row)
2. When switching back to SEPARATE_ROWS:
   - Group node remains height_scaling = 1 (empty row)
   - Children restore their individual height_scaling values
   - Remove virtual overlapped row

### UI Integration

#### Context Menu Structure
```
Group Context Menu
├── Create Group
├── Rename
├── Save as Snippet
├── Render Mode ►
│   ├── ✓ Separate Rows
│   └──   Overlapped
└── ...
```

#### Visual Updates
- Group node appears as empty row (height = 1) with expand/collapse controls
- Overlapped waveform row appears immediately below group node
- All child waveforms superimposed in the overlapped row with distinct colors
- Individual child signal rows are hidden/skipped
- Overlapped row height = sum of all children's original height_scaling values
- Each signal uses distinct color from automatically assigned rainbow palette

### Performance Considerations

#### Cache Management
- Signal range cache must handle group-level entries
- Key by group instance_id when in OVERLAPPED mode
- Invalidate cache when children added/removed from group
- Recompute global min/max only when needed

#### Rendering Optimization
- Pre-allocate polyline points array
- Use single QPainter path per signal if possible
- Consider level-of-detail: skip signals if too many in group
- Batch color assignments to avoid multiple redraws

#### Memory Usage
- Store one set of drawing data per child signal
- Group-level cache entry for combined range
- Color palette generated on-demand, not stored

### Integration Points

#### Event Flow
1. User selects "Overlapped" from context menu
2. SignalNamesView calls controller.set_group_render_mode()
3. Controller:
   - Updates data model
   - Assigns colors
   - Emits StructureChangedEvent
4. Canvas receives event and redraws
5. Item model updates to show new layout

#### Validation Points
- Check for nested groups before enabling menu item
- Verify all children have valid handles
- Ensure analog scaling mode is appropriate
- Validate color generation for large child counts

### Testing Considerations
- Groups with 1, 2, 5, 10+ children
- Mixed signal types (bool, bus, analog) in same group
- Switching between render modes repeatedly
- Color persistence across mode switches
- Performance with large signal counts
- Nested group validation