# Feature Plan: Analog Signal Value Labels at Time Ticks

## 1. Use Cases and Requirements Analysis

### Core Functionality
Display actual signal values along the bottom of analog waveform rows at regular intervals synchronized with the time ruler grid.

### Specific Requirements (from user prompt)
1. **Positioning**: Render values at every second time ruler tick position (half the rate of ruler ticks)
2. **Vertical Placement**: Values positioned at same vertical level as min value label (approximately `y_bottom - 2`)
3. **Value Format**: Use the signal's configured `DisplayFormat` (hex/dec/bin/signed/float)
   - Reuse existing value formatting code from `parse_signal_value()`
   - Respect user's format choice for each signal
4. **Overlap Handling**: Skip rendering values that would overlap with previous labels
5. **Scope**: Only applicable to analog render mode (`RenderType.ANALOG`)
   - Digital signals already display values, so this feature is analog-specific

### Visual Design
- **Font**: "Monospace", size 8 (same as min/max labels)
- **Color**: `config.COLORS.TEXT_MUTED` (same as min/max labels for visual consistency)
- **Alignment**: Centered on tick position
- **Sampling**: Value at exact tick time position

### Performance Considerations
- Minimal performance impact expected:
  - Value sampling happens at ~5-20 positions per viewport (half of tick count)
  - Signal value lookup via existing pyrox API
  - Format conversion already optimized in `parse_signal_value()`
- Overlap detection is O(n) where n is number of ticks (typically < 20)

## 2. Codebase Research

### Core Data Structures

**Time Ruler Tick Information** (`wavescout/rendering/time_grid_renderer.py:19-24`):
```python
class TickInfo(TypedDict):
    time_value: float  # Time in Timescale units
    pixel_x: int      # X coordinate in pixels
    label: str        # Formatted time label
    clock_label: Optional[str]
```

**Render Parameters** (`wavescout/rendering/signal_renderer.py:57-76`):
- `RenderParams` TypedDict passed to all signal renderers
- Contains viewport info, draw commands, session, signal range cache
- Currently does NOT include tick positions (will need to be added)

**Display Format** (`wavescout/core/data_model.py:96-102`):
- `DisplayFormat.data_format` specifies value representation (UNSIGNED/SIGNED/HEX/BIN/FLOAT)
- Signal node contains format via `node.format` field

### Existing Rendering Pipeline

**Tick Calculation Flow**:
1. `WaveformCanvas._calculate_and_store_ruler_info()` (line 1095)
   - Calls `TimeGridRenderer.calculate_ticks()`
   - Returns `List[TickInfo]` with time values and pixel positions
   - Stores in `self._last_tick_positions` for grid rendering

2. `WaveformCanvas._collect_render_params()` (line 681)
   - Assembles `RenderParams` dictionary
   - Currently does NOT include tick positions
   - Passed to `_render_to_image()` → `_render_waveforms()` → `_draw_layout_row()`

3. Signal rendering in `_draw_layout_row()` (line 1001)
   - Line 1070: Calls `draw_analog_signal(painter, node_info, drawing_data, y, row_height, params)`
   - `params` contains viewport, draw commands, but not tick info

**Current Analog Rendering** (`wavescout/rendering/signal_renderer.py:644-808`):
- Lines 701-717: Renders min/max labels if `height_scaling > 1`
  - Font: QFont("Monospace", 8)
  - Color: `config.COLORS.TEXT_MUTED`
  - Max at `y_top + 10`, Min at `y_bottom - 2`
  - Format: `f"{max_val:.2f}"` (always float, does NOT respect DataFormat)
- Lines 724-807: Draws waveform polyline as step diagram
- No value labels currently rendered along the waveform

### Value Formatting Infrastructure

**`parse_signal_value()` function** (`wavescout/rendering/signal_sampling.py:58-139`):
- Converts raw values to formatted strings based on `DataFormat`
- Signature: `parse_signal_value(value, data_format: DataFormat, bit_width: int) -> Tuple[str, float, bool]`
- Returns: `(value_str, value_float, value_bool)`
- Handles all format types:
  - UNSIGNED: decimal string (e.g., "255")
  - SIGNED: signed decimal with 2's complement (e.g., "-128")
  - HEX: uppercase hex without prefix (e.g., "FF", "DEADBEEF")
  - BIN: binary with "0b" prefix (e.g., "0b10101010")
  - FLOAT: IEEE 754 float32 for 32-bit signals
- Used in Values panel and tooltips, can be reused for this feature

**Signal Value Access**:
- `node.signal` is `AsyncLoadedSignal` wrapper
- `node.signal.get_signal_blocking(timeout)` returns pyrox `Signal` object
- `Signal.get_value_at(time)` returns value at specific time
- `node.var.bitwidth()` provides bit width for format conversion

## 3. Implementation Planning

### Data Model Changes

**File: `wavescout/rendering/signal_renderer.py`**

1. **Update `RenderParams` TypedDict** (line 57):
   - Add new optional field: `tick_positions: Optional[List[TickInfo]]`
   - Allows renderers to access tick information for synchronized labels

### Rendering Pipeline Changes

**File: `wavescout/widgets/waveform_canvas.py`**

1. **Modify `_collect_render_params()`** (line 681):
   - Add `tick_positions=self._last_tick_positions` to the returned `RenderParams` dict
   - Ensures tick info is passed to all renderers
   - Ticks already calculated by `_calculate_and_store_ruler_info()` before rendering

**File: `wavescout/rendering/signal_renderer.py`**

2. **Enhance `draw_analog_signal()`** (line 644):
   - After drawing the waveform polyline (after line 807)
   - Add new section to render value labels at tick positions
   - Only execute if `height_scaling > 1` (consistent with min/max labels)

### Value Label Rendering Algorithm

**Location**: New code block in `draw_analog_signal()` after line 807

**Algorithm**:
```
1. Extract tick positions from params:
   tick_infos = params.get('tick_positions', [])

2. Filter to every second tick:
   value_ticks = tick_infos[::2]  # Every 2nd element (0, 2, 4, ...)

3. For overlap detection, track:
   last_label_end_x = -infinity

4. Setup rendering:
   font = QFont("Monospace", 8)
   painter.setFont(font)
   fm = painter.fontMetrics()
   text_color = QColor(config.COLORS.TEXT_MUTED)
   painter.setPen(QPen(text_color, 0))

5. For each tick in value_ticks:
   a. Extract tick time and pixel position:
      tick_time = tick['time_value']
      tick_x = tick['pixel_x']

   b. Get signal value at tick time:
      - Use node_info['signal'] (cached Signal object)
      - Call signal.get_value_at(tick_time)
      - Handle None/error cases gracefully

   c. Format value using existing function:
      - Get data_format from node_info['format'].data_format
      - Get bit_width from node_info['var'].bitwidth() (default 32)
      - Call parse_signal_value(raw_value, data_format, bit_width)
      - Extract value_str from returned tuple

   d. Check for overlap:
      - Measure text width: text_width = fm.horizontalAdvance(value_str)
      - Calculate label bounds: label_start_x = tick_x - text_width/2
      - If label_start_x < last_label_end_x + padding: skip this label
      - Otherwise: update last_label_end_x = tick_x + text_width/2

   e. Render the label:
      - Position: x = tick_x - text_width/2, y = y_bottom - 2
      - painter.drawText(x, y, value_str)
```

**Key Implementation Details**:

1. **Signal Value Retrieval**:
   - Access via `node_info['signal']` (already cached in NodeInfo)
   - Use `signal.get_value_at(tick_time)` for point-in-time sampling
   - Handle edge cases: signal not loaded, value undefined, high-Z

2. **Format Conversion**:
   - Import and reuse: `from ..rendering.signal_sampling import parse_signal_value`
   - Data format: `node_info['format'].data_format`
   - Bit width: `node_info['var'].bitwidth()` if var exists, else default to 32

3. **Overlap Detection**:
   - Maintain `last_label_end_x` variable
   - Compare `label_start_x` with `last_label_end_x + padding`
   - Padding constant: 10 pixels minimum gap between labels
   - Skip label if overlap detected

4. **Rendering Details**:
   - Font: `QFont("Monospace", 8)` (matches min/max labels)
   - Color: `config.COLORS.TEXT_MUTED` (consistent with min/max)
   - Y position: `y_bottom - 2` (same as min value label)
   - X position: Centered on tick position

### Error Handling

1. **Missing tick positions**: If `tick_positions` not in params, skip feature gracefully
2. **Signal value errors**: Catch exceptions from `get_value_at()`, skip that label
3. **Format errors**: If `parse_signal_value()` fails, use fallback string representation
4. **Missing var/bitwidth**: Default to 32-bit when bitwidth unavailable

### Integration Points

**Upstream Changes**:
- `WaveformCanvas._collect_render_params()`: Add tick positions to params dict

**Downstream Usage**:
- `draw_analog_signal()`: Consume tick positions from params
- Other renderers: Ignore new param (no changes needed)

**Testing Hooks**:
- Verify tick positions passed correctly via params
- Test value formatting for all DataFormat types
- Validate overlap detection with various tick densities
- Check rendering only occurs for analog signals with height_scaling > 1

### Visual Consistency

**Font and Color Alignment**:
- Use identical styling as min/max labels for cohesive appearance
- Monospace font ensures predictable width calculations
- TEXT_MUTED color indicates auxiliary information (not primary signal)

**Spacing and Layout**:
- Every-second-tick sampling prevents overcrowding
- Overlap detection ensures readability at high zoom levels
- Bottom placement keeps values near the waveform baseline

## 4. Testing Strategy

### Unit Tests
1. **Value formatting**: Test `parse_signal_value()` with all DataFormat types
2. **Overlap detection**: Verify skip logic with mock tick positions and widths
3. **Tick filtering**: Confirm every-second-tick extraction works correctly

### Integration Tests
1. **Analog rendering with labels**: Verify labels appear at correct positions
2. **Format switching**: Change DataFormat and confirm label updates
3. **Zoom levels**: Test label rendering at various zoom levels (sparse/dense ticks)
4. **Height scaling**: Verify labels only appear when height_scaling > 1
5. **Mixed signals**: Confirm digital signals unaffected

### Visual Regression
1. Capture screenshots with analog signals showing value labels
2. Verify alignment with time ruler ticks
3. Confirm no overlap at various zoom levels

## 5. Summary

This feature enhances analog signal visualization by displaying formatted values at regular intervals synchronized with the time ruler. The implementation:

- **Leverages existing infrastructure**: Reuses tick calculation, value formatting, and rendering pipeline
- **Maintains visual consistency**: Uses same font/color as min/max labels
- **Respects user preferences**: Honors configured DisplayFormat for each signal
- **Handles edge cases**: Overlap detection, error handling, graceful degradation
- **Minimal performance impact**: Efficient sampling and rendering

The changes are localized to two files with clear integration points, making the feature straightforward to implement and test.
