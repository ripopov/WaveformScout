# JETS Feature Plan: Virtual Trace Button in jets-gui

**Feature ID:** 0002
**Feature Name:** Virtual Trace Button in jets-gui
**Author:** JETS Agentic Coding Feature Architect
**Date:** 2025-10-11
**Target Version:** JETS v0.3.0

---

## 1. Use Cases and Requirements Analysis

### 1.1 Problem Statement

Currently, jets-gui only supports loading trace files from disk via the "📁 Open Trace" button. This creates friction during development and testing workflows:

1. **Testing Friction**: Developers testing jets-gui features must first generate a trace file on disk, then navigate the file picker to load it
2. **Demo Limitations**: Demonstrating jets-gui functionality requires having pre-generated trace files available
3. **Integration Testing Gap**: Automated tests that need trace data must set up file I/O, increasing test complexity
4. **VirtualTraceReader Underutilization**: The existing `VirtualTraceReader` in `virtual_reader.rs` generates synthetic traces in-memory but has no GUI integration

### 1.2 Solution Overview

Add a **"Virtual Trace"** button next to "Open Trace" in the jets-gui header that:
1. Generates a synthetic trace in-memory using `VirtualTraceReader`
2. Loads it into the GUI immediately without file I/O
3. Displays it using the existing trace rendering pipeline

This provides instant access to synthetic trace data for testing, demos, and development.

### 1.3 Functional Requirements

#### FR-1: Virtual Trace Button UI
**Priority:** MUST HAVE

**Description:** Add a "Virtual Trace" button in the header toolbar next to "Open Trace".

**Acceptance Criteria:**
- Button appears immediately after "Open Trace" button in horizontal layout
- Button label: "🔮 Virtual Trace" (crystal ball emoji + text)
- Button matches existing button styling (dark/light theme support)
- Button is always enabled (no preconditions required)
- Clicking button generates and loads a virtual trace instantly

**UI Location:** Header toolbar in `render_header()` method, line 159 area

---

#### FR-2: In-Memory Trace Generation
**Priority:** MUST HAVE

**Description:** Generate a synthetic trace in-memory using `VirtualTraceReader` when button is clicked.

**Acceptance Criteria:**
- Use `VirtualTraceReader::new()` with default configuration
- Generate trace with 5-10 root records (deterministic seed for reproducibility)
- Generated trace includes hierarchical structure (nested records up to depth 5)
- Generated trace includes events (0-5 events per record)
- Generated trace includes annotations with random data fields
- No file I/O involved (purely in-memory generation)

**Data Generation Characteristics:**
- Clock range: 0 to ~50,000 cycles (sufficient for meaningful visualization)
- Record durations: 50-500 cycles per record (realistic for hardware traces)
- Hierarchy depth: Up to 5 levels (matching typical hardware execution pipelines)
- Children per record: 0-5 (realistic fan-out)

---

#### FR-3: Trace Loading and Display
**Priority:** MUST HAVE

**Description:** Load the generated virtual trace into jets-gui using the existing trace data pipeline.

**Acceptance Criteria:**
- Virtual trace data passes through same `TraceData` trait interface as file-based traces
- Tree view renders virtual records identically to file-based records
- Timeline view (if implemented) renders virtual traces correctly
- Details panel displays virtual record data, annotations, and events
- All existing GUI features work with virtual traces (selection, expansion, zoom/pan)
- Header displays "Virtual Trace" instead of file path when virtual trace is loaded

**State Management:**
- Set `file_path` to `None` (no file associated with virtual trace)
- Display "Virtual Trace (seed: 42)" or similar in header metadata area

---

#### FR-4: Error Handling
**Priority:** MUST HAVE

**Description:** Handle any errors during virtual trace generation gracefully.

**Acceptance Criteria:**
- If generation fails, display error message in header error area (same as file load errors)
- Button remains clickable after error (user can retry)
- Error message format: "Error generating virtual trace: {error_detail}"

**Note:** With current `VirtualTraceReader` implementation, generation errors are unlikely (no I/O, no parsing), but defensive error handling should be included.

---

### 1.4 Non-Functional Requirements

#### NFR-1: Performance
**Priority:** MUST HAVE

**Targets:**
- **Generation Time:** <100ms for default configuration (imperceptible to user)
- **Memory:** <5 MB for generated trace (negligible compared to typical file-based traces)
- **Rendering:** Same 60 FPS performance as file-based traces (reuses existing rendering pipeline)

**Rationale:** Virtual trace generation is purely in-memory with no I/O, so performance should be excellent.

---

#### NFR-2: Determinism
**Priority:** SHOULD HAVE

**Requirements:**
- Same button click generates identical trace (deterministic seed)
- Reproducible for debugging and testing
- Optional: Add configuration dialog in future to customize seed, depth, children count

**Rationale:** Determinism aids debugging and allows users to reliably reproduce scenarios.

---

## 2. Codebase Research

### 2.1 VirtualTraceReader Analysis

**File:** `jets/rjets/src/virtual_reader.rs`

**Current Implementation:**
- **Lines 9-31:** `VirtualTraceReader` struct with configurable `max_depth`, `max_children`, `seed`
- **Lines 16-22:** `new()` constructor with defaults: `max_depth=5`, `max_children=10`, `seed=42`
- **Lines 24-30:** `with_config()` constructor for custom configuration
- **Lines 33-48:** `TraceReader::read()` implementation generates trace in-memory

**Key Observation:** `read()` method takes `_file_path: &str` parameter but ignores it (line 34). This is a trait interface requirement from `TraceReader`, but for virtual traces the path is unused.

**Data Generation Logic:**
- **Lines 37-45:** Generates 1-5 root records using `StdRng::seed_from_u64(seed)` for determinism
- **Lines 173-240:** `VirtualTraceRecord::generate()` recursively creates hierarchical structure:
  - Clock offsets: `parent_clk + rng.gen_range(10..100)` for start
  - Durations: `rng.gen_range(50..500)` cycles
  - Data fields: 3-7 random fields per record
  - Events: 0-5 events per record, positioned within record's clock range
  - Children: 0-5 children if `depth < max_depth`, recursively generated

**Trace Characteristics:**
- **Lines 85-106:** `calculate_virtual_trace_extent()` computes `(min_clk, max_clk)` from all records
- Default extent: Falls back to `(0, 1000)` if no records (lines 86-87)
- Realistic clock ranges: Starts from parent's end clock, ensuring parent-before-child ordering

**VirtualTraceData Implementation:**
- **Lines 51-82:** Implements `TraceData` trait identically to `JetsTraceData`
- **Lines 109-121:** Provides `metadata()`, `root_ids()`, `get_record()` methods
- **Lines 123-157:** `TraceMetadata` implementation with static header data (generator info)

**Gap Analysis:**
- ✅ **Complete TraceReader Implementation:** Virtual reader fully implements `TraceReader` trait
- ✅ **TraceData Trait Compliance:** Virtual trace data is drop-in compatible with GUI expectations
- ✅ **Hierarchical Structure:** Correctly builds parent-child relationships
- ✅ **Events and Annotations:** Generates both timed events and data fields
- ⚠️ **Missing Export in lib.rs:** Virtual reader types are already exported (lines 18-22)

**Conclusion:** `VirtualTraceReader` is fully functional and complete. No gaps to fill.

---

### 2.2 GUI Integration Points

**File:** `jets/rjets/src/jets-gui.rs`

**Current State:**
- **Lines 22-51:** `JetsViewerApp` struct holds trace state:
  - `reader: Box<dyn TraceReader>` - Currently initialized with `JetsTraceReader::new()` (line 63)
  - `trace_data: Option<Box<dyn TraceData>>` - Holds loaded trace
  - `file_path: Option<PathBuf>` - Stores file path (None for virtual traces)

**Open File Button (lines 159-170):**
```rust
if ui.button("📁 Open Trace").clicked() {
    let mut dialog = rfd::FileDialog::new()
        .add_filter("JETS Traces", &["jets", "jsonl"]);

    if let Ok(cwd) = std::env::current_dir() {
        dialog = dialog.set_directory(cwd);
    }

    if let Some(path) = dialog.pick_file() {
        self.open_file(path);
    }
}
```

**open_file() Method (lines 90-113):**
```rust
fn open_file(&mut self, path: PathBuf) {
    match self.reader.read(path.to_str().unwrap()) {
        Ok(data) => {
            let (min_clk, max_clk) = data.metadata().trace_extent();

            self.trace_data = Some(data);
            self.file_path = Some(path);
            self.error_message = None;
            // ... initialize viewport, zoom, scroll state
        }
        Err(e) => {
            self.error_message = Some(format!("Error loading trace: {}", e));
        }
    }
}
```

**Observation:** `open_file()` method assumes a file path exists. For virtual traces, we need a separate method that doesn't require a path.

**Header Rendering (lines 157-236):**
- Lines 174-188: Displays trace metadata (GPU model, clock frequency) from `header_data()`
- Lines 219: Displays "No trace loaded" when `trace_data.is_none()`

**Integration Strategy:**
1. Add new method `open_virtual_trace()` that generates trace using `VirtualTraceReader`
2. Add button in `render_header()` after "Open Trace" button
3. Modify header display to show "Virtual Trace (seed: X)" when `file_path.is_none()` but `trace_data.is_some()`

---

### 2.3 Reader Type Management

**Current Design (line 63):**
```rust
reader: Box::new(JetsTraceReader::new()),
```

**Implication:** The `reader` field is initialized once with `JetsTraceReader`. To support virtual traces, we have two options:

**Option A: Replace reader when switching to virtual trace**
- Swap `reader` to `VirtualTraceReader` when virtual button clicked
- Swap back to `JetsTraceReader` when file opened
- **Downside:** Unnecessary state mutation

**Option B: Use virtual reader directly in button handler (RECOMMENDED)**
- Keep `reader` field for file-based traces only
- Create temporary `VirtualTraceReader` instance in `open_virtual_trace()` method
- Only use it to generate trace data, then discard
- **Advantage:** Simpler, clearer separation of concerns

**Recommendation:** Option B. The `reader` field is only used in `open_file()` for file-based traces. For virtual traces, we create a temporary reader inline.

---

## 3. Implementation Planning

### 3.1 File-by-File Changes

#### **File:** `jets/rjets/src/jets-gui.rs`

**Modifications:**

**1. Import VirtualTraceReader (add to line 3 area):**
```rust
use rjets::{TraceReader, TraceData, JetsTraceReader, VirtualTraceReader};
```

**Nature of Change:** Add `VirtualTraceReader` to existing imports from `rjets` crate.

**Rationale:** Virtual trace reader is already exported by `lib.rs`, just needs to be imported in GUI module.

---

**2. Add open_virtual_trace() Method (after open_file(), ~line 114):**

**Function Signature:**
```rust
fn open_virtual_trace(&mut self)
```

**Purpose:** Generate and load a virtual trace in-memory using `VirtualTraceReader`.

**Implementation Steps:**
1. Create temporary `VirtualTraceReader::new()` instance (uses default seed 42)
2. Call `reader.read("")` with empty path (path unused for virtual traces)
3. On success:
   - Extract trace extent via `data.metadata().trace_extent()`
   - Set `self.trace_data = Some(data)`
   - Set `self.file_path = None` (no file path for virtual traces)
   - Clear `self.error_message`
   - Initialize viewport: `viewport_start_clk = min_clk`, `viewport_end_clk = max_clk`
   - Reset zoom: `zoom_level = 1.0`
   - Reset scroll: `shared_scroll_y = 0.0`
   - Clear selection: `selected_record_id = None`
   - Clear expansion: `expanded_nodes.clear()`
   - Store trace extent: `trace_min_clk = min_clk`, `trace_max_clk = max_clk`
4. On error:
   - Set `self.error_message = Some(format!("Error generating virtual trace: {}", e))`

**Integration Point:** Shares state initialization logic with `open_file()`. Consider extracting common initialization into helper method.

---

**3. Add Virtual Trace Button in render_header() (after "Open Trace" button, ~line 171):**

**Button UI Code:**
```rust
if ui.button("🔮 Virtual Trace").clicked() {
    self.open_virtual_trace();
}
```

**Placement:** Immediately after the "Open Trace" button (after line 170), before the separator (line 172).

**Layout Pattern:** Uses same horizontal layout as existing buttons, no special sizing needed.

---

**4. Update Header Metadata Display (lines 174-188):**

**Current Behavior:** Displays GPU model and clock frequency from `header_data()`.

**Required Change:** When `file_path.is_none()` and `trace_data.is_some()`, recognize this as a virtual trace and display:
```
"Virtual Trace | Seed: 42 | Records: X"
```

**Implementation Approach:**
```rust
if let Some(trace) = &self.trace_data {
    if self.file_path.is_none() {
        // Virtual trace
        let num_records = trace.root_ids().len();
        ui.label(RichText::new(format!("Virtual Trace | Seed: 42 | Roots: {}", num_records)).strong());
    } else {
        // Existing file-based trace metadata display
        let header_data = trace.metadata().header_data();
        // ... existing code ...
    }
}
```

**Rationale:** Virtual traces don't have GPU model or clock frequency metadata (see `virtual_reader.rs` lines 129-135). Instead, display generation parameters for context.

---

**5. Optional: Refactor Common Initialization (lines 90-113):**

**Purpose:** Both `open_file()` and `open_virtual_trace()` share identical initialization logic for viewport, zoom, scroll, selection, and expansion state.

**Suggested Refactoring (optional, improves maintainability):**
```rust
fn initialize_trace_state(&mut self, data: Box<dyn TraceData>) {
    let (min_clk, max_clk) = data.metadata().trace_extent();

    self.trace_data = Some(data);
    self.error_message = None;
    self.expanded_nodes.clear();
    self.selected_record_id = None;

    self.trace_min_clk = min_clk;
    self.trace_max_clk = max_clk;
    self.viewport_start_clk = min_clk;
    self.viewport_end_clk = max_clk;
    self.zoom_level = 1.0;
    self.shared_scroll_y = 0.0;
}
```

**Then update both methods:**
```rust
fn open_file(&mut self, path: PathBuf) {
    match self.reader.read(path.to_str().unwrap()) {
        Ok(data) => {
            self.initialize_trace_state(data);
            self.file_path = Some(path);
        }
        Err(e) => {
            self.error_message = Some(format!("Error loading trace: {}", e));
        }
    }
}

fn open_virtual_trace(&mut self) {
    let virtual_reader = VirtualTraceReader::new();
    match virtual_reader.read("") {
        Ok(data) => {
            self.initialize_trace_state(data);
            self.file_path = None;
        }
        Err(e) => {
            self.error_message = Some(format!("Error generating virtual trace: {}", e));
        }
    }
}
```

**Note:** This refactoring is optional but recommended to follow DRY principle.

---

#### **File:** `jets/rjets/src/virtual_reader.rs`

**No changes required.**

**Analysis:**
- ✅ `VirtualTraceReader` fully implements `TraceReader` trait (lines 33-48)
- ✅ Generates deterministic traces with seed 42 (line 20)
- ✅ Creates hierarchical records with events and annotations (lines 173-240)
- ✅ Computes trace extent correctly (lines 85-106)
- ✅ All `TraceData`, `TraceRecord`, `TraceEvent` trait methods implemented (lines 109-341)

**Conclusion:** Implementation is complete and ready for GUI integration.

---

#### **File:** `jets/rjets/src/lib.rs`

**No changes required.**

**Verification:**
- Lines 18-22: `VirtualTraceReader` and related types already exported:
  ```rust
  pub use virtual_reader::{
      VirtualTraceReader, VirtualTraceData,
      VirtualTraceRecord, VirtualTraceEvent
  };
  ```

**Conclusion:** Public API already exposes virtual trace types for GUI usage.

---

### 3.2 Algorithm Descriptions

No complex algorithms required for this feature. The implementation primarily involves UI integration and state management using existing infrastructure.

**Trace Generation Flow:**
1. User clicks "🔮 Virtual Trace" button
2. `open_virtual_trace()` method called
3. Create `VirtualTraceReader::new()` (seed=42, max_depth=5, max_children=10)
4. Call `reader.read("")` to generate trace in-memory:
   - Generate 1-5 root records with random ID generation
   - Recursively generate children up to depth 5
   - Generate 0-5 events per record within parent's clock range
   - Generate 3-7 data fields per record
   - Build `VirtualTraceData` with `records_by_id` lookup map
5. Extract trace extent `(min_clk, max_clk)` from metadata
6. Initialize GUI state (viewport, zoom, scroll, selection)
7. Trace renders using existing tree/timeline rendering pipeline

**Determinism:** Same seed (42) produces identical trace every time for reproducibility.

---

### 3.3 UI Integration Details

#### Button Placement

**Before:**
```
┌─────────────────────────────────────────────────────────────┐
│ [📁 Open Trace] │ GPU: ... | Clock: ... MHz │ [🔍+][🔍-]... │
└─────────────────────────────────────────────────────────────┘
```

**After:**
```
┌──────────────────────────────────────────────────────────────────┐
│ [📁 Open Trace][🔮 Virtual Trace] │ GPU: ... | Clock: ... │ ... │
└──────────────────────────────────────────────────────────────────┘
```

**Layout Code (in render_header(), line 158-172):**
```rust
ui.horizontal(|ui| {
    if ui.button("📁 Open Trace").clicked() {
        // ... existing file picker code ...
    }

    // NEW: Virtual Trace button
    if ui.button("🔮 Virtual Trace").clicked() {
        self.open_virtual_trace();
    }

    ui.separator();

    // ... existing metadata display ...
});
```

---

#### Metadata Display

**File-Based Trace (existing):**
```
GPU: RTX 4090 | Clock: 2520 MHz
```

**Virtual Trace (new):**
```
Virtual Trace | Seed: 42 | Roots: 3
```

**Implementation (lines 174-188):**
```rust
if let Some(trace) = &self.trace_data {
    if self.file_path.is_none() {
        // Virtual trace metadata
        let num_roots = trace.root_ids().len();
        ui.label(RichText::new(
            format!("Virtual Trace | Seed: 42 | Roots: {}", num_roots)
        ).strong());
    } else {
        // Existing file-based trace metadata
        let header_data = trace.metadata().header_data();
        let gpu_model = header_data
            .get("gpu_model")
            .and_then(|v| v.as_str())
            .unwrap_or("Unknown");
        // ... rest of existing code ...
    }
}
```

---

#### Error Handling

**Error Display (existing pattern, line 233-235):**
```rust
if let Some(err) = &self.error_message {
    ui.colored_label(Color32::RED, err);
}
```

**Error Messages:**
- File loading: `"Error loading trace: {error}"`
- Virtual trace: `"Error generating virtual trace: {error}"` (new)

**Note:** Virtual trace generation errors are unlikely (no I/O, no parsing), but error handling follows existing pattern for consistency.

---

### 3.4 Testing Considerations

#### Manual Testing Checklist

**Basic Functionality:**
- [ ] Virtual Trace button appears next to Open Trace button
- [ ] Clicking button generates and loads trace without errors
- [ ] Tree view displays generated records with hierarchical structure
- [ ] Details panel shows record data, annotations, and events
- [ ] Timeline view (if implemented) renders virtual trace correctly
- [ ] Header displays "Virtual Trace | Seed: 42 | Roots: X"

**Interaction Testing:**
- [ ] Can expand/collapse virtual trace records
- [ ] Can select records in tree and timeline
- [ ] Zoom/pan controls work with virtual trace
- [ ] Can switch between file trace and virtual trace multiple times
- [ ] Details panel updates correctly when selecting virtual records
- [ ] Event markers render correctly in timeline

**Error Scenarios (edge cases):**
- [ ] Button remains functional after loading file trace
- [ ] Loading virtual trace clears previous file trace state
- [ ] Loading file trace clears previous virtual trace state
- [ ] Error message clears when successfully loading trace

**Performance Testing:**
- [ ] Virtual trace loads instantly (<100ms)
- [ ] No memory leaks when repeatedly loading virtual traces
- [ ] Rendering maintains 60 FPS with virtual trace

---

#### Automated Testing (Future Work)

**Suggested Unit Tests (to be added in future):**
```rust
#[test]
fn test_virtual_trace_generation() {
    let reader = VirtualTraceReader::new();
    let result = reader.read("");
    assert!(result.is_ok());
    let data = result.unwrap();
    assert!(data.root_ids().len() >= 1);
}

#[test]
fn test_virtual_trace_determinism() {
    let reader1 = VirtualTraceReader::new();
    let reader2 = VirtualTraceReader::new();
    let data1 = reader1.read("").unwrap();
    let data2 = reader2.read("").unwrap();
    assert_eq!(data1.root_ids(), data2.root_ids());
}
```

---

## 4. Future Enhancements (Out of Scope)

### 4.1 Virtual Trace Configuration Dialog

**Description:** Add dialog to customize virtual trace generation parameters before loading.

**Configuration Options:**
- Seed (for reproducibility)
- Maximum depth (hierarchy levels)
- Maximum children per record
- Number of root records
- Clock range scaling

**UI Pattern:** "🔮 Virtual Trace ▼" dropdown with "Configure..." option that opens modal dialog.

---

### 4.2 Virtual Trace Presets

**Description:** Pre-defined virtual trace configurations for common testing scenarios.

**Presets:**
- "Small Trace" (3 roots, depth 3, ~50 records)
- "Medium Trace" (5 roots, depth 5, ~500 records) - current default
- "Large Trace" (10 roots, depth 7, ~5000 records)
- "Deep Hierarchy" (2 roots, depth 10, focus on depth)
- "Wide Hierarchy" (20 roots, depth 2, focus on breadth)

**UI Pattern:** Dropdown menu with preset options.

---

### 4.3 Export Virtual Trace to File

**Description:** Allow saving currently loaded virtual trace to `.jets` file for sharing or archival.

**Implementation:** Add "Export..." button in header when virtual trace is loaded, uses `TraceWriter` to serialize.

---

## 5. Risk Assessment

### 5.1 Technical Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Virtual trace data incompatibility with GUI expectations | Low | `VirtualTraceData` implements identical traits as `JetsTraceData` |
| Performance degradation with large virtual traces | Low | Default configuration generates <1000 records, well within performance budget |
| Determinism broken by RNG changes | Low | Fixed seed (42) ensures reproducibility; document in code |

---

### 5.2 UX Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Users confuse virtual trace with real trace | Low | Clear header label "Virtual Trace" when loaded |
| Users expect file path for virtual trace | Low | Set `file_path = None`, handle gracefully in header display |
| Button placement causes accidental clicks | Very Low | Standard button spacing, no hover preview |

---

## 6. Success Metrics

### 6.1 Functional Completeness
- [ ] Virtual Trace button appears and responds to clicks
- [ ] Virtual trace generates and loads without errors
- [ ] All existing GUI features work with virtual traces
- [ ] Header correctly identifies virtual traces

### 6.2 Performance Metrics
- [ ] Virtual trace generation <100ms
- [ ] Rendering performance identical to file-based traces (60 FPS)
- [ ] Memory usage <5 MB for virtual trace

### 6.3 Usability Validation
- [ ] Users can generate virtual trace in single click
- [ ] Virtual trace provides useful data for testing/demo purposes
- [ ] Clear distinction between file-based and virtual traces in UI

---

## 7. Implementation Checklist

**Phase 1: Core Integration**
- [ ] Add `VirtualTraceReader` import to `jets-gui.rs`
- [ ] Implement `open_virtual_trace()` method
- [ ] Add "🔮 Virtual Trace" button in `render_header()`
- [ ] Wire button click to `open_virtual_trace()` method

**Phase 2: State Management**
- [ ] Initialize trace state (viewport, zoom, scroll) when virtual trace loads
- [ ] Set `file_path = None` for virtual traces
- [ ] Clear previous trace state (selection, expansion)

**Phase 3: UI Polish**
- [ ] Update header metadata display to show "Virtual Trace" info
- [ ] Test button placement and styling (dark/light themes)
- [ ] Verify error message display works

**Phase 4: Testing**
- [ ] Manual testing of all FR acceptance criteria
- [ ] Test switching between file and virtual traces
- [ ] Performance validation (generation time, rendering FPS)

**Phase 5: Documentation**
- [ ] Add code comments explaining virtual trace integration
- [ ] Update user-facing documentation (if any)

---

## 8. Dependencies

**No new crate dependencies required.**

**Existing Dependencies Used:**
- `rjets::VirtualTraceReader` (already implemented and exported)
- `rand` (already used by `virtual_reader.rs` for RNG)
- `egui` (for button UI)

**Estimated Implementation Effort:** 2-4 hours for experienced Rust + egui developer.

---

## 9. Open Questions

**Q1: Should virtual trace configuration be exposed in initial version?**
- **Recommendation:** No. Use default configuration (seed=42, depth=5, children=10) for simplicity. Add configuration dialog in future enhancement.

**Q2: Should virtual trace be saveable to file?**
- **Recommendation:** Not in initial version. Users can generate file-based traces using `jets-tracegen` if needed. Add export feature in future enhancement.

**Q3: Should we display different icons/colors for virtual records?**
- **Recommendation:** No. Virtual traces should render identically to file-based traces to validate rendering pipeline. Visual distinction only in header metadata.

**Q4: Should seed be randomized on each click or fixed?**
- **Recommendation:** Fixed seed (42) for determinism and reproducibility. Add seed randomization option in future configuration dialog.

---

**End of Plan**
