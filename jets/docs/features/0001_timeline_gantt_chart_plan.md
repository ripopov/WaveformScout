# JETS Feature Plan: Timeline/Gantt Chart Visualization

**Feature ID:** 0001
**Feature Name:** Timeline/Gantt Chart Visualization
**Author:** JETS Agentic Coding Feature Architect
**Date:** 2025-10-10
**Target Version:** JETS v0.2.0

---

## 1. Use Cases and Requirements Analysis

### 1.1 Problem Statement

The current JETS GUI (`jets-gui.rs`) displays trace records in a hierarchical tree with tabular columns (Name, ID, Start Clock, End Clock, Description). While effective for browsing execution hierarchy, this representation has critical limitations:

1. **No Temporal Visualization**: Users cannot visually assess execution duration, overlap, or temporal gaps between operations
2. **Difficult Critical Path Analysis**: Identifying performance bottlenecks requires manual mental reconstruction of timing relationships from numeric clock values
3. **Poor Multi-Record Correlation**: Understanding simultaneous execution across pipeline stages (e.g., multiple warps, instruction pipelines) requires cross-referencing numeric values
4. **Event Context Loss**: Events appear as JSON text in the details panel without visual temporal placement relative to their parent record's execution timeline

### 1.2 Solution Overview

Transform the GUI from a single-pane tree view into a **dual-pane interface**:

1. **Left Pane (30% width)**: Hierarchical tree view (existing, retained with enhancements)
2. **Right Pane (70% width)**: Timeline/Gantt chart canvas showing:
   - Records as horizontal bars positioned by `clk` (start) and `end_clk` (duration)
   - Events as vertical markers at `event.clk` on parent record's row
   - Time axis with zoom/pan controls
   - Synchronized vertical scrolling with tree view

This dual-pane architecture follows proven patterns from professional profiling tools (Chrome DevTools Performance, Intel VTune, AMD μProf) while maintaining simplicity appropriate for hardware trace analysis.

### 1.3 Functional Requirements

#### FR-1: Timeline Canvas Display
**Priority:** MUST HAVE

**Description:** Display a horizontal timeline canvas to the right of the tree view, showing records as horizontal bars positioned by start clock and duration.

**Acceptance Criteria:**
- Records appear as horizontal bars at Y-position corresponding to their tree row
- Bar X-position determined by `record.clk` (start time)
- Bar width determined by `record_end.clk - record.clk` (duration)
- Records without `record_end` shown with visual indicator (infinite bar with fade-out or arrow)
- Bar color determined by record type or configurable color scheme
- Bars have visual hierarchy (child records indented/nested within parent timeline)

**Data Dependencies:**
- `TraceRecord::clk()` for start position
- `TraceRecord::end_clk()` for end position (optional)
- `TraceRecord::duration()` for bar width calculation
- Tree expansion state (`expanded_nodes`) to determine visible rows

---

#### FR-2: Event Marker Visualization
**Priority:** MUST HAVE

**Description:** Display events as vertical markers on the timeline at their clock position, attached to their parent record's timeline row.

**Acceptance Criteria:**
- Events appear as circular icons/markers at `event.clk`
- Event positioned on same Y-coordinate as parent record's timeline bar
- Hovering event shows tooltip with: `name`, `description`, `data` (formatted as JSON)
- Events that occur outside parent record's time range are visually flagged (e.g., different color)
- Multiple events at similar clock values use vertical stacking or clustering to avoid overlap

**Data Dependencies:**
- `TraceEvent::clk()` for X-position
- `TraceEvent::name()` for tooltip
- `TraceEvent::description()` for tooltip
- `TraceEvent::data()` for tooltip
- `TraceEvent::record_id()` to determine parent record row

---

#### FR-3: Time Axis & Grid
**Priority:** MUST HAVE

**Description:** Provide a horizontal time axis at top of timeline canvas showing clock values with appropriate tick intervals.

**Acceptance Criteria:**
- Time axis displayed at top of timeline canvas
- Major ticks at power-of-10 intervals (auto-calculated from zoom level and visible range)
- Minor ticks at 1/5 of major interval
- Clock values formatted with thousands separators (e.g., "1,000" or "10,000")
- Optional grid lines extending vertically from major ticks (toggle in settings)
- Axis updates dynamically when zooming/panning

**Algorithm:**
1. Calculate visible time range: `visible_range = [viewport_start_clk, viewport_end_clk]`
2. Calculate tick interval: `tick_interval = next_power_of_10(visible_range / 10)`
3. Generate major ticks: `ticks = [tick_interval * i for i in range(start/tick_interval, end/tick_interval)]`
4. Generate minor ticks: `minor_ticks = [major_tick + tick_interval/5 * j for j in 1..5]`
5. Draw labels at major ticks only

---

#### FR-4: Horizontal Zoom
**Priority:** MUST HAVE

**Description:** Allow users to zoom in/out on the time axis to view different temporal resolutions.

**Acceptance Criteria:**
- Ctrl+Mouse wheel over timeline zooms in/out (centered on cursor position)
- Zoom range: 100% (fit all data) to 10,000% (single clock cycle detail)
- Zoom controls in toolbar: buttons (+/-), keyboard shortcuts (Ctrl+Plus/Minus)
- "Zoom to Fit" button resets to show entire trace duration (min `clk` to max `end_clk`)
- Zoom transformation preserves cursor position (point under cursor stays fixed)

**State Management:**
- Add `zoom_level: f32` to `JetsViewerApp` struct (1.0 = fit all, 10.0 = 10x zoom)
- Add `viewport_start_clk: i64` and `viewport_end_clk: i64` for visible time range

---

#### FR-5: Horizontal Panning
**Priority:** MUST HAVE

**Description:** Allow users to pan horizontally across the timeline to view different time ranges.

**Acceptance Criteria:**
- Mouse wheel over timeline canvas pans horizontally (when not using Ctrl modifier)
- Middle-mouse drag pans horizontally
- Scrollbar at bottom of timeline provides alternative pan mechanism
- Pan constrained to valid data range (`min_clk` to `max_clk`)
- Panning is smooth and responsive (<16ms latency)

**State Management:**
- Update `viewport_start_clk` and `viewport_end_clk` based on pan delta
- Clamp values to `[trace_min_clk, trace_max_clk]`

---

#### FR-6: Vertical Synchronization
**Priority:** MUST HAVE

**Description:** Synchronize vertical scrolling between tree view and timeline canvas so corresponding rows always align.

**Acceptance Criteria:**
- Scrolling tree view scrolls timeline canvas vertically
- Scrolling timeline canvas scrolls tree view vertically
- Row heights identical between tree and timeline (22px default)
- Expanded/collapsed tree nodes adjust timeline Y-positions accordingly
- Selection state synchronized (clicking tree row highlights timeline bar, vice versa)

**Implementation Pattern:**
- Use shared scroll offset state: `shared_scroll_y: f32`
- Tree view and timeline canvas both consume this state for Y-offset calculation
- Row Y-position calculation must be identical in both rendering paths

---

#### FR-7: Selection Synchronization
**Priority:** MUST HAVE

**Description:** Clicking a record in the tree selects it in the timeline and vice versa; clicking a timeline bar selects the corresponding tree row.

**Acceptance Criteria:**
- Clicking tree row highlights corresponding timeline bar
- Clicking timeline bar highlights corresponding tree row
- Selection state shared: only one record selected at a time
- Selected record bar has distinct visual treatment (thicker border, color change, glow)
- Details panel updates to show selected record (existing behavior)

**State Management:**
- Use existing `selected_record_id: Option<u64>` state
- Timeline hit testing to determine which bar was clicked

---

### 1.4 Non-Functional Requirements

#### NFR-1: Performance
**Priority:** MUST HAVE

**Targets:**
- **Rendering:** Maintain 60 FPS (16ms frame budget) for traces with ≤100,000 records
- **Load Time:** Traces up to 500 MB load in <5 seconds (existing constraint)
- **Zoom/Pan:** <16ms response time for smooth interaction
- **Memory:** <2 GB RAM for typical trace (50,000 records, 200,000 events)

**Optimization Strategies:**
- Viewport culling: Only render records/events visible in current viewport
- LOD (Level of Detail): Skip rendering records smaller than 1 pixel when zoomed out
- Event clustering: Merge nearby events into visual clusters when zoomed out
- Lazy geometry calculation: Compute bar geometry only for visible rows

---

#### NFR-2: Visual Consistency
**Priority:** SHOULD HAVE

**Requirements:**
- Colors consistent with existing dark/light theme toggle
- Record colors derive from `record_type` with consistent color scheme
- Event markers use distinct visual style from record bars
- Selection highlight uses theme accent color
- Grid lines subtle (low opacity) to avoid visual clutter

---

## 2. Codebase Research

### 2.1 Current GUI Architecture Analysis

**File:** `jets/rjets/src/jets-gui.rs`

**Key Structures:**
- `JetsViewerApp` (lines 21-31): Main application state
  - `reader: Box<dyn TraceReader>`: Trace file reader
  - `trace_data: Option<Box<dyn TraceData>>`: Loaded trace data
  - `selected_record_id: Option<u64>`: Currently selected record
  - `expanded_nodes: HashSet<u64>`: Set of expanded tree nodes
  - `split_ratio: f32`: Vertical split between tree and details panel (currently 0.7)
  - `dark_mode: bool`: Theme state
  - `column_widths: [f32; 5]`: Tree column widths

**Current Layout (lines 456-528):**
```
TopBottomPanel::top("header") → render_header()
CentralPanel → vertical split:
  - Tree view (75% height) → render_tree()
  - Draggable separator (8px)
  - Details panel (25% height) → render_details()
```

**Rendering Methods:**
- `render_header()` (lines 69-117): Top toolbar with file picker, GPU info, theme toggle
- `render_tree()` (lines 119-148): Tree view with `ScrollArea::vertical()`
- `render_table_header()` (lines 150-213): Column headers with resize handles
- `render_tree_node()` (lines 215-378): Recursive tree rendering with expand/collapse
- `render_details()` (lines 380-453): Bottom panel with record/event details

**Row Rendering Details (lines 215-378):**
- Row height: 22px (line 238)
- Indent per level: 20px (line 236)
- Expand/collapse button: 40px width (line 263)
- Selection highlight: Color32::from_rgb(50, 80, 120) (line 258)
- Custom low-level rendering using `ui.painter()` for precise layout control

### 2.2 Data Model Analysis

**File:** `jets/rjets/src/traits.rs`

**Core Traits:**
- `TraceData`: Provides `root_ids()`, `get_record(id)`, `metadata()`
- `TraceRecord`: Provides `clk()`, `end_clk()`, `duration()`, `name()`, `id()`, `parent_id()`, `children()`, `events()`
- `TraceEvent`: Provides `clk()`, `name()`, `record_id()`, `description()`, `data()`

**Implementation:** `jets/rjets/src/parser.rs`

**Key Data Structures:**
- `JetsTraceData` (lines 75-80):
  - `roots: Vec<JetsTraceRecord>`: Root records
  - `records_by_id: HashMap<u64, usize>`: ID → index in `all_records`
  - `all_records: Vec<JetsTraceRecord>`: Flattened list for O(1) lookup
- `JetsTraceRecord` (lines 44-66):
  - `clk: i64`, `end_clk: Option<i64>`, `duration: Option<i64>`
  - `id: u64`, `parent_id: Option<u64>`
  - `children: Vec<JetsTraceRecord>`: Hierarchical structure
  - `events: Vec<JetsTraceEvent>`: Events attached to this record
  - `annotations: Vec<JetsTraceAnnotation>`: Merged into `data()` method

**Observation:** Current data model is already optimized for tree traversal and flat lookups. Timeline rendering can leverage `all_records` for efficient iteration.

### 2.3 egui Rendering Patterns

**Framework:** `eframe` 0.29 + `egui` 0.29 (Cargo.toml lines 9-10)

**Current egui Usage Patterns:**
1. **Immediate Mode:** All UI rebuilt every frame in `update()` method
2. **Custom Rendering:** Heavy use of `ui.painter()` for precise layout control (lines 175-210, 254-370)
3. **Manual Layout:** Row-by-row geometry calculation with `allocate_exact_size()`
4. **ScrollArea:** Built-in scrolling with `ScrollArea::vertical()` (lines 141-147)
5. **Interaction:** `Sense::click()`, `Sense::drag()`, `Sense::click_and_drag()` for user input

**Relevant egui Patterns for Timeline:**
- `ui.painter().rect_filled()`: Draw record bars
- `ui.painter().circle_filled()`: Draw event markers
- `ui.painter().line_segment()`: Draw grid lines
- `ui.painter().text()`: Draw time axis labels
- `ui.interact(rect, id, sense)`: Hit testing for click events
- `ui.input(|i| i.pointer.hover_pos())`: Mouse hover for tooltips

### 2.4 Trace Data Characteristics (from `gpu_sim.jets`)

**Observed Patterns:**
- Clock values range from ~1000 to ~200,000+ (lines 2-50 sample)
- Deeply nested hierarchies: HostProgram → GpuContext → Dispatch → GTE → ThreadBlock → Warp → Instruction (7 levels)
- Events are dense: Instructions have 5-6 events each (DecodeStage, ScoreboardCheck, OperandCollect, Execute, Writeback)
- Event clock ranges: Events can span wide ranges (e.g., TMA_Issue at 2201, TMA_Complete at 2301 = 100 cycles)
- Record durations: Instructions ~5-10 cycles, Warps/ThreadBlocks 100s-1000s of cycles

**Implications for Timeline:**
- Need wide zoom range (100x-10000x) to show both entire trace and single instructions
- Event clustering critical when zoomed out (avoid rendering 1000s of overlapping markers)
- Vertical space constrained: Deep hierarchies may require 100+ rows

---

## 3. Implementation Planning

### 3.1 File-by-File Changes

#### **File:** `jets/rjets/src/jets-gui.rs`

**Modifications:**

**1. App State Extension (`JetsViewerApp` struct, lines 21-31):**

Add new fields:
- `timeline_split_ratio: f32` — Horizontal split between tree (left) and timeline (right), default 0.3
- `zoom_level: f32` — Current zoom level (1.0 = fit all data, 10.0 = 10x zoom), default 1.0
- `viewport_start_clk: i64` — Visible time range start, initialized on trace load
- `viewport_end_clk: i64` — Visible time range end, initialized on trace load
- `shared_scroll_y: f32` — Shared vertical scroll offset between tree and timeline
- `show_grid: bool` — Toggle for grid lines, default true
- `trace_min_clk: i64` — Minimum clock value in entire trace (computed on load)
- `trace_max_clk: i64` — Maximum clock value in entire trace (computed on load)

**2. Initialization Method (`new()`, lines 40-52):**

Add initialization for new fields:
- Set `timeline_split_ratio = 0.3`
- Set `zoom_level = 1.0`
- Set `viewport_start_clk = 0`, `viewport_end_clk = 0` (updated on trace load)
- Set `shared_scroll_y = 0.0`
- Set `show_grid = true`
- Set `trace_min_clk = 0`, `trace_max_clk = 0`

**3. File Loading (`open_file()`, lines 54-67):**

Add trace extent calculation after successful load:
- Iterate through `all_records` to find global `min_clk` and `max_clk`
- Set `trace_min_clk` and `trace_max_clk`
- Initialize `viewport_start_clk = trace_min_clk`
- Initialize `viewport_end_clk = trace_max_clk`
- Reset `zoom_level = 1.0` (fit all)
- Reset `shared_scroll_y = 0.0`

**4. Layout Restructuring (`update()` method, lines 456-528):**

**Current:**
```
TopBottomPanel::top("header")
CentralPanel (vertical split):
  - Tree view (70%)
  - Separator
  - Details panel (30%)
```

**New:**
```
TopBottomPanel::top("header")
CentralPanel (horizontal split):
  - Left panel (30%):
    - Tree view (70% of left panel)
    - Separator
    - Details panel (30% of left panel)
  - Vertical separator (draggable)
  - Right panel (70%):
    - Timeline canvas (100% of right panel)
```

**Implementation:**
- Use nested `egui::SidePanel::left()` for tree+details
- Use `egui::CentralPanel` for timeline canvas
- Add horizontal draggable separator between panels

**5. New Rendering Methods:**

**`render_timeline(&mut self, ui: &mut egui::Ui)`**
- **Purpose:** Main timeline canvas rendering coordinator
- **Steps:**
  1. Handle zoom/pan input (mouse wheel, Ctrl+wheel, middle-drag)
  2. Update `viewport_start_clk`, `viewport_end_clk`, `zoom_level` based on input
  3. Calculate visible records (viewport culling)
  4. Render time axis (call `render_time_axis()`)
  5. Render grid (if `show_grid == true`)
  6. Render record bars (call `render_record_bars()`)
  7. Render event markers (call `render_event_markers()`)
  8. Handle selection (hit testing on record bars)
  9. Handle hover tooltips

**`render_time_axis(&self, ui: &mut egui::Ui, canvas_rect: egui::Rect)`**
- **Purpose:** Draw time axis at top of timeline
- **Steps:**
  1. Calculate major tick interval (next_power_of_10((viewport_end - viewport_start) / 10))
  2. Generate major tick positions: `clk_to_x(tick_clk)`
  3. Generate minor tick positions (5 ticks between each major tick)
  4. Draw major ticks (vertical lines, full height)
  5. Draw minor ticks (vertical lines, half height)
  6. Draw labels at major ticks (formatted with thousands separators)

**`render_record_bars(&self, ui: &mut egui::Ui, canvas_rect: egui::Rect)`**
- **Purpose:** Draw horizontal bars for each visible record
- **Steps:**
  1. Get visible rows from tree state (compute Y-offsets matching tree view)
  2. For each visible record:
     - Calculate bar geometry: `x = clk_to_x(record.clk())`, `width = clk_to_x(record.end_clk()) - x`
     - Handle records without `end_clk`: extend to viewport edge with visual indicator
     - Apply LOD filtering: skip bars with `width < 1.0` pixels
     - Choose color based on `record_type` (or selection state if selected)
     - Draw bar using `ui.painter().rect_filled()`
     - Draw selection highlight (border) if `selected_record_id == record.id()`

**`render_event_markers(&self, ui: &mut egui::Ui, canvas_rect: egui::Rect)`**
- **Purpose:** Draw event markers on timeline
- **Steps:**
  1. For each visible record (same Y-offsets as bars):
     - Get `record.events()`
     - For each event in viewport time range:
       - Calculate marker position: `x = clk_to_x(event.clk())`, `y = record_row_y`
       - Draw circle using `ui.painter().circle_filled()`
       - Handle hover: if mouse over marker, show tooltip with event details

**`render_grid(&self, ui: &mut egui::Ui, canvas_rect: egui::Rect)`**
- **Purpose:** Draw vertical grid lines at major tick positions
- **Steps:**
  1. Calculate major tick positions (same as time axis)
  2. For each tick: draw vertical line from top to bottom of canvas
  3. Use low opacity color (e.g., `Color32::from_rgba(200, 200, 200, 30)`)

**6. Helper Methods:**

**`clk_to_x(&self, clk: i64, canvas_rect: egui::Rect) -> f32`**
- **Purpose:** Convert clock value to X-coordinate in timeline canvas
- **Formula:**
  ```
  normalized = (clk - viewport_start_clk) / (viewport_end_clk - viewport_start_clk)
  x = canvas_rect.left() + normalized * canvas_rect.width()
  ```

**`x_to_clk(&self, x: f32, canvas_rect: egui::Rect) -> i64`**
- **Purpose:** Convert X-coordinate to clock value (for hit testing)
- **Formula:**
  ```
  normalized = (x - canvas_rect.left()) / canvas_rect.width()
  clk = viewport_start_clk + normalized * (viewport_end_clk - viewport_start_clk)
  ```

**`compute_visible_rows(&self) -> Vec<(u64, f32)>`**
- **Purpose:** Calculate Y-offsets for visible records matching tree view
- **Steps:**
  1. Iterate through `roots` in same order as tree rendering
  2. For each root, recursively process children if expanded
  3. Accumulate Y-offset: `current_y += 22.0` (row height)
  4. Apply `shared_scroll_y` offset
  5. Return `Vec<(record_id, y_offset)>` for records in viewport

**`calculate_trace_extent(&self) -> (i64, i64)`**
- **Purpose:** Find min/max clock values in trace
- **Steps:**
  1. Iterate `all_records`, track `min_clk = min(record.clk())`
  2. Track `max_clk = max(record.end_clk().unwrap_or(record.clk()))`
  3. Return `(min_clk, max_clk)`

**`next_power_of_10(value: f32) -> i64`**
- **Purpose:** Round value up to next power of 10 for tick intervals
- **Formula:**
  ```
  exponent = ceil(log10(value))
  return 10^exponent
  ```

**`format_clock(clk: i64) -> String`**
- **Purpose:** Format clock value with thousands separators
- **Example:** `12345 → "12,345"`, `1000000 → "1,000,000"`

**7. Input Handling (in `render_timeline()`):**

**Zoom (Ctrl + Mouse Wheel):**
```
if ctx.input(|i| i.modifiers.ctrl) {
    let scroll_delta = ctx.input(|i| i.raw_scroll_delta.y);
    let zoom_factor = 1.0 + scroll_delta * 0.001;
    let mouse_x = ctx.input(|i| i.pointer.hover_pos()).x;
    let mouse_clk = x_to_clk(mouse_x);

    // Apply zoom
    zoom_level *= zoom_factor;
    zoom_level = zoom_level.clamp(1.0, 10000.0);

    // Adjust viewport to keep mouse_clk fixed
    let new_range = (trace_max_clk - trace_min_clk) / zoom_level;
    let left_ratio = (mouse_clk - viewport_start_clk) / (viewport_end_clk - viewport_start_clk);
    viewport_start_clk = mouse_clk - left_ratio * new_range;
    viewport_end_clk = viewport_start_clk + new_range;
}
```

**Pan (Mouse Wheel or Middle-Drag):**
```
let scroll_delta = ctx.input(|i| i.raw_scroll_delta.x);
let pan_clk = (scroll_delta / canvas_width) * (viewport_end_clk - viewport_start_clk);
viewport_start_clk -= pan_clk;
viewport_end_clk -= pan_clk;

// Clamp to trace bounds
viewport_start_clk = viewport_start_clk.max(trace_min_clk);
viewport_end_clk = viewport_end_clk.min(trace_max_clk);
```

**Selection (Click on Bar):**
```
if ui.input(|i| i.pointer.primary_clicked()) {
    let click_pos = ui.input(|i| i.pointer.interact_pos()).unwrap();
    let click_clk = x_to_clk(click_pos.x);

    // Hit test: find record bar under cursor
    for (record_id, y_offset) in visible_rows {
        let record = trace_data.get_record(record_id);
        if click_pos.y >= y_offset && click_pos.y <= y_offset + 22.0 {
            if click_clk >= record.clk() && click_clk <= record.end_clk().unwrap_or(i64::MAX) {
                selected_record_id = Some(record_id);
                break;
            }
        }
    }
}
```

**8. Vertical Scroll Synchronization:**

**Tree View Scroll (in `render_tree()`):**
- Wrap `ScrollArea::vertical()` with callback to capture scroll offset:
  ```
  let scroll_response = ScrollArea::vertical().show(ui, |ui| { ... });
  shared_scroll_y = scroll_response.state.offset.y;
  ```

**Timeline Scroll (in `render_timeline()`):**
- Use same `shared_scroll_y` when calculating row Y-offsets in `compute_visible_rows()`

---

#### **File:** `jets/rjets/src/lib.rs` (No changes required)

**Rationale:** All required trait methods (`clk()`, `end_clk()`, `events()`) already exist. No new data model changes needed.

---

#### **File:** `jets/rjets/src/parser.rs` (No changes required)

**Rationale:** Existing parsing logic already computes `end_clk` and `duration` (lines 190-195). No format changes needed.

---

#### **File:** `jets/JETS.md` (Optional documentation update)

**Section to Add (if visualization metadata becomes standardized):**

Add to Section 2.3 (Record Line, around line 134):

```markdown
#### Visualization Metadata (Optional in `data` field)

For optimal Gantt chart rendering, records may include these optional fields in the `data` object:

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `color` | string | Hex color override for this record | `"#ff5722"` |
| `display_label` | string | Short label to show on Gantt bar | `"LD R4"` |
| `criticality` | float | Critical path weight (0.0-1.0) | `0.85` |
```

Add to Section 2.5 (Event Line, around line 246):

```markdown
#### Visualization Metadata (Optional in `data` field)

For Gantt chart event markers, events may include these optional fields:

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `color` | string | Hex color for event marker | `"#e74c3c"` |
| `severity` | string | Visual severity level | `"info"`, `"warning"`, `"error"` |
| `marker_style` | string | Visual style hint | `"circle"`, `"diamond"`, `"square"` |
```

**Note:** This is informative, not mandatory. Existing traces without these fields will still render correctly using default color schemes.

---

### 3.2 Algorithm Descriptions

#### Algorithm: Viewport Culling (Record Filtering)

**Purpose:** Only render records visible in current time viewport to maintain 60 FPS.

**Steps:**
1. **Input:** `viewport_start_clk`, `viewport_end_clk`, `all_records`, `visible_row_ids`
2. **Filter by time:**
   ```
   visible_records = []
   for record in all_records:
       if record.id not in visible_row_ids:
           continue  # Skip collapsed rows

       record_start = record.clk()
       record_end = record.end_clk().unwrap_or(i64::MAX)

       # Check overlap with viewport
       if record_end >= viewport_start_clk && record_start <= viewport_end_clk:
           visible_records.append(record)
   ```
3. **Output:** List of records to render

**Complexity:** O(N) where N = total records, but typically filters to <1% of records when zoomed in.

---

#### Algorithm: LOD Filtering (Sub-Pixel Record Skipping)

**Purpose:** Skip rendering records that would be smaller than 1 pixel to avoid wasted draw calls.

**Steps:**
1. **Input:** `record`, `viewport_start_clk`, `viewport_end_clk`, `canvas_width`
2. **Calculate pixel width:**
   ```
   clk_to_pixel_ratio = canvas_width / (viewport_end_clk - viewport_start_clk)
   record_duration = record.end_clk().unwrap_or(viewport_end_clk) - record.clk()
   pixel_width = record_duration * clk_to_pixel_ratio
   ```
3. **Filter:**
   ```
   if pixel_width < 1.0:
       skip_rendering = true
   ```
4. **Output:** Boolean flag to skip rendering

**Optimization:** Can be extended to skip events as well when zoomed out significantly.

---

#### Algorithm: Event Clustering (for Future Enhancement)

**Purpose:** Merge nearby events into visual clusters when zoomed out to avoid rendering thousands of overlapping markers.

**Steps (deferred to future iteration):**
1. Group events within N pixels of each other
2. Render cluster as single marker with count badge
3. On zoom-in, expand cluster to individual markers

**Note:** Not implemented in initial version (FR-1 through FR-7). Can be added later as optimization.

---

#### Algorithm: Zoom-to-Cursor

**Purpose:** Zoom in/out while keeping the point under the cursor fixed (intuitive zoom behavior).

**Steps:**
1. **Inputs:** `mouse_x`, `viewport_start_clk`, `viewport_end_clk`, `zoom_delta`
2. **Calculate mouse clock position:**
   ```
   mouse_clk = x_to_clk(mouse_x, canvas_rect)
   ```
3. **Calculate new viewport range:**
   ```
   new_total_range = (trace_max_clk - trace_min_clk) / new_zoom_level
   ```
4. **Calculate left/right ratios:**
   ```
   old_range = viewport_end_clk - viewport_start_clk
   left_ratio = (mouse_clk - viewport_start_clk) / old_range
   right_ratio = (viewport_end_clk - mouse_clk) / old_range
   ```
5. **Apply new viewport:**
   ```
   viewport_start_clk = mouse_clk - left_ratio * new_total_range
   viewport_end_clk = mouse_clk + right_ratio * new_total_range
   ```
6. **Clamp to bounds:**
   ```
   viewport_start_clk = max(viewport_start_clk, trace_min_clk)
   viewport_end_clk = min(viewport_end_clk, trace_max_clk)
   ```

**Result:** Point under cursor remains visually fixed while zoom changes.

---

### 3.3 UI Integration Details

#### Layout Transformation

**Before (Current):**
```
┌─────────────────────────────────────────┐
│ Header                                  │
├─────────────────────────────────────────┤
│ Tree View (70% height)                  │
│ ├─ Columns: Name | ID | Start | End    │
│ └─ ScrollArea (vertical)                │
├─────────────────────────────────────────┤
│ Draggable Separator (8px)               │
├─────────────────────────────────────────┤
│ Details Panel (30% height)              │
│ └─ Record/Event JSON display            │
└─────────────────────────────────────────┘
```

**After (New):**
```
┌────────────────────────────────────────────────────────────┐
│ Header (+ Zoom controls)                                   │
├──────────────────┬─────────────────────────────────────────┤
│ Tree View (30%)  │ Timeline Canvas (70%)                   │
│ ┌──────────────┐ │ ┌─────────────────────────────────────┐ │
│ │ Name    | ID │ │ │ Time Axis (0──1000──2000──3000───)  │ │
│ ├──────────────┤ │ ├─────────────────────────────────────┤ │
│ │ ▶ Record  1  │─┼─┤ ████████████████                    │ │
│ │   ▼ Child 2  │─┼─┤   ██████████░                       │ │
│ │     Node  3  │─┼─┤     ████░ ▲                         │ │
│ │              │ │ │           └─Event marker             │ │
│ │              │ │ │                                      │ │
│ │ (ScrollArea) │ │ │ (Synchronized vertical scroll)       │ │
│ └──────────────┘ │ └─────────────────────────────────────┘ │
│                  │                                          │
├──────────────────┤ (Shared vertical scroll offset)         │
│ Details Panel    │                                          │
│ (30% of left)    │                                          │
│ └─Record data    │                                          │
└──────────────────┴─────────────────────────────────────────┘
```

**egui Layout Code Pattern:**
```rust
egui::SidePanel::left("left_panel")
    .default_width(available_width * timeline_split_ratio)
    .resizable(true)
    .show(ctx, |ui| {
        // Vertical split: tree view + details panel
        let tree_height = ui.available_height() * split_ratio;

        // Tree view (top)
        ui.allocate_ui(egui::vec2(ui.available_width(), tree_height), |ui| {
            self.render_tree(ui);
        });

        // Separator (middle)
        self.render_vertical_separator(ui);

        // Details panel (bottom)
        self.render_details(ui);
    });

egui::CentralPanel::default().show(ctx, |ui| {
    self.render_timeline(ui);
});
```

---

#### Color Scheme Design

**Record Bar Colors (by `record_type`):**

| Record Type | Color (Hex) | Description |
|-------------|-------------|-------------|
| `HostProgram` | `#3498db` (Blue) | Host-side operations |
| `GpuContextSubmission` | `#9b59b6` (Purple) | GPU context operations |
| `DispatchCompute` | `#2ecc71` (Green) | Compute dispatches |
| `ThreadBlock` | `#f39c12` (Orange) | Thread block execution |
| `Warp` | `#e74c3c` (Red) | Warp execution |
| `SASS_Instruction` | `#95a5a6` (Gray) | Individual instructions |
| (default) | `#34495e` (Dark Gray) | Unknown types |

**Selection Highlight:**
- Border: 2px solid `#3498db` (Blue, theme accent color)
- Background: Lighten base color by 20%

**Event Markers:**
- Default: Circle, 6px radius, `#e74c3c` (Red)
- Hover: Circle, 8px radius, `#c0392b` (Dark Red)
- Tooltip: White background, black text, 4px padding

**Grid Lines:**
- Color: `Color32::from_rgba(200, 200, 200, 30)` (low opacity)
- Width: 1px

**Dark/Light Theme Adaptation:**
- Use egui's `ui.visuals()` to query current theme
- Adjust color brightness/saturation based on `visuals.dark_mode`

---

#### Tooltip Design

**Event Tooltip Format:**
```
┌─────────────────────────────┐
│ DecodeStage                 │
│ CLK: 2,182                  │
│ Description: Instruction... │
│ Data:                       │
│   { "stage": "frontend" }   │
└─────────────────────────────┘
```

**Implementation:**
- Use `egui::Window::new().title_bar(false).show()`
- Position at mouse cursor + offset (10px right, 10px down)
- Max width: 300px
- Auto-hide when mouse moves away

---

### 3.4 Performance Optimization Strategy

#### Rendering Budget Breakdown (60 FPS = 16ms frame)

| Phase | Budget | Optimization |
|-------|--------|--------------|
| Viewport culling | 2ms | Filter records to visible time range |
| Row Y-offset calculation | 2ms | Lazy compute only for visible rows |
| Record bar rendering | 6ms | LOD filtering (skip <1px bars) |
| Event marker rendering | 4ms | Limit to ~1000 markers max |
| Grid/axis rendering | 1ms | Cached tick positions |
| Input handling | 1ms | Throttle mouse events |

**Total:** 16ms (fits 60 FPS budget)

---

#### Memory Optimization

**Existing Memory Usage (from trace loading):**
- `all_records`: ~200 bytes/record × 50,000 = 10 MB
- `events`: ~100 bytes/event × 200,000 = 20 MB
- **Total:** ~30 MB per trace

**Timeline Memory Overhead:**
- Viewport culling: Only render ~1% of records when zoomed in (500 records)
- Geometry cache: ~50 bytes/visible record × 500 = 25 KB
- Event markers: ~20 bytes/visible event × 1000 = 20 KB
- **Total overhead:** <100 KB (negligible)

**Conclusion:** No significant memory increase expected. Timeline rendering is compute-bound, not memory-bound.

---

#### Lazy Computation Strategy

**Defer until needed:**
1. **Trace extent calculation:** Only when trace loads (one-time cost)
2. **Visible row computation:** Only when tree expansion state changes
3. **Bar geometry:** Only for visible records in viewport
4. **Event clustering:** Deferred to future iteration

**Caching opportunities:**
- Cache tick positions until zoom/pan changes
- Cache visible row list until tree expansion changes
- Cache record bar colors (static, based on `record_type`)

---

## 4. Testing Strategy (Informational)

### 4.1 Unit Testing

**Test Cases (to be implemented by coding agent):**
1. `test_clk_to_x_conversion()`: Verify coordinate transformation accuracy
2. `test_viewport_culling()`: Verify only visible records are rendered
3. `test_lod_filtering()`: Verify sub-pixel records are skipped
4. `test_zoom_to_cursor()`: Verify cursor position remains fixed during zoom
5. `test_trace_extent_calculation()`: Verify min/max clock values computed correctly

### 4.2 Integration Testing

**Test Scenarios:**
1. Load `gpu_sim.jets`, verify timeline renders all records
2. Zoom to 100x, verify render performance stays >60 FPS
3. Click record bar, verify selection syncs with tree view
4. Hover event marker, verify tooltip displays correct data
5. Expand/collapse tree nodes, verify timeline row alignment

### 4.3 Performance Testing

**Benchmarks:**
- Measure frame time with 100,000 record trace (target: <16ms)
- Measure zoom latency (target: <16ms)
- Measure pan latency (target: <16ms)
- Measure memory usage (target: <2 GB for 500 MB trace)

---

## 5. Future Enhancements (Out of Scope for v0.2.0)

### 5.1 Event Clustering
- Merge nearby events into clusters when zoomed out
- Display cluster count badge
- Expand on zoom-in

### 5.2 Critical Path Highlighting
- Use `criticality` field from record `data` to highlight critical path
- Color gradient based on criticality value (0.0-1.0)

### 5.3 Swimlane Grouping
- Group records by `unit_id` or `thread_id` into horizontal lanes
- Collapse/expand lanes independently

### 5.4 Minimap Navigator
- Small overview panel showing entire trace
- Draggable viewport rectangle for quick navigation

### 5.5 Record Comparison Mode
- Select two records, show duration diff in details panel
- Highlight overlapping time ranges

### 5.6 Export Timeline as Image
- Render timeline to PNG/SVG for reports
- Include time axis, record bars, events

---

## 6. Risk Assessment

### 6.1 Technical Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Rendering performance <60 FPS with large traces | High | Implement viewport culling + LOD filtering early |
| Vertical scroll synchronization complexity | Medium | Use shared state pattern (already validated in code) |
| egui custom rendering learning curve | Low | Existing code already uses custom rendering extensively |
| Event marker overlap causing visual clutter | Medium | Implement simple vertical stacking (deferred clustering) |

### 6.2 UX Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Users expect waveform-style zooming (horizontal only) | Low | Clearly label as "Gantt chart" not "waveform viewer" |
| Timeline too narrow on small screens | Low | Make split resizable, save preference |
| Event tooltips obscure timeline | Low | Position tooltips intelligently (above/below cursor) |

---

## 7. Success Metrics

### 7.1 Functional Completeness
- [ ] All FR-1 through FR-7 acceptance criteria pass
- [ ] Timeline renders correctly for `gpu_sim.jets` sample trace
- [ ] Zoom/pan controls work smoothly
- [ ] Selection synchronization works bidirectionally

### 7.2 Performance Metrics
- [ ] Maintains 60 FPS with 100,000 record trace
- [ ] Zoom latency <16ms
- [ ] Pan latency <16ms
- [ ] Memory usage <2 GB for 500 MB trace

### 7.3 UX Validation
- [ ] Users can identify critical path visually within 5 seconds
- [ ] Users can correlate events to record execution phase visually
- [ ] Zoom/pan controls feel natural (no jitter or lag)

---

## 8. Implementation Checklist

**Phase 1: Core Timeline Rendering (FR-1, FR-3)**
- [ ] Add timeline state fields to `JetsViewerApp`
- [ ] Implement horizontal split layout (tree + timeline panels)
- [ ] Implement `clk_to_x()` and `x_to_clk()` helpers
- [ ] Implement `calculate_trace_extent()` on trace load
- [ ] Implement `render_time_axis()` with tick generation
- [ ] Implement `render_record_bars()` with viewport culling
- [ ] Implement color scheme for record types

**Phase 2: Interactivity (FR-4, FR-5)**
- [ ] Implement zoom input handling (Ctrl+wheel)
- [ ] Implement pan input handling (wheel, middle-drag)
- [ ] Implement "Zoom to Fit" button
- [ ] Add zoom/pan controls to header toolbar

**Phase 3: Synchronization (FR-6, FR-7)**
- [ ] Implement shared vertical scroll state
- [ ] Synchronize tree view scroll to timeline
- [ ] Synchronize timeline scroll to tree view
- [ ] Implement timeline click → tree selection
- [ ] Implement tree click → timeline highlight

**Phase 4: Events & Polish (FR-2)**
- [ ] Implement `render_event_markers()`
- [ ] Implement event hover tooltips
- [ ] Implement grid rendering (optional toggle)
- [ ] Add theme-aware color adjustments

**Phase 5: Testing & Optimization**
- [ ] Profile rendering performance with large traces
- [ ] Implement LOD filtering if needed
- [ ] Add keyboard shortcuts (Ctrl+Plus/Minus for zoom)
- [ ] Test with multiple sample traces

---

## 9. Open Questions for Implementation

1. **Event Marker Size:** Should event markers scale with zoom level, or remain constant size?
   - **Recommendation:** Constant 6px radius for clarity at all zoom levels.

2. **Infinite Records (no `end_clk`):** Visual treatment options:
   - Option A: Extend to viewport edge with fade-out gradient
   - Option B: Extend to viewport edge with arrow indicator
   - **Recommendation:** Option B (arrow) for clarity.

3. **Tree Column Visibility:** Should tree columns (Start/End Clock) be hidden when timeline is visible (redundant)?
   - **Recommendation:** Keep visible initially, add toggle in future version.

4. **Default Zoom Level:** Should initial view be "fit all" or "fit first 1000 cycles"?
   - **Recommendation:** Fit all (show entire trace extent).

5. **Scrollbar Placement:** Should horizontal scrollbar be at bottom of timeline or bottom of window?
   - **Recommendation:** Bottom of timeline panel (above details panel).

---

## 10. Dependencies

**No new crate dependencies required.** All features can be implemented using existing dependencies:
- `egui` 0.29: Provides all necessary rendering primitives
- `eframe` 0.29: Application framework
- `serde_json`: Already used for data access

**Estimated Implementation Effort:** 3-5 days for experienced Rust + egui developer.

---

**End of Plan**
