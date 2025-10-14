# Feature Plan: Viewport-Based Tree Filtering for Temporal Focus

**Feature ID:** 0008
**Feature Name:** viewport_filter
**Status:** Planning
**Created:** 2025-10-13
**Last Updated:** 2025-10-13

---

## 1. Use Cases and Requirements Analysis

### 1.1 Problem Statement

When analyzing large JETS traces with hundreds of thousands or millions of records spanning long time periods, users need to focus on events occurring within a specific time window (the current viewport). The current tree view shows all records regardless of their temporal relationship to the viewport, making it difficult to identify and focus on temporally relevant data.

**Current Limitations:**

1. **No Temporal Filtering**
   - Tree view displays all records in the trace regardless of start clock
   - Users must manually scan through potentially millions of records to find ones starting within the viewport
   - No visual or interactive way to filter records by temporal relevance

2. **Navigation Inefficiency**
   - For traces with millions of records spanning hours of simulation time, identifying records within a narrow time window requires extensive manual navigation
   - Scrolling through hundreds of thousands of irrelevant records to find the few dozen that started during the viewport time window

3. **Cognitive Overload**
   - Viewing all records simultaneously when only a small fraction are temporally relevant to the current analysis
   - Difficult to maintain mental context when relevant records are scattered among thousands of irrelevant ones

**Example Scenario:**
```
User loads a 10-hour hardware simulation trace with 500K instruction records.
Current viewport shows clocks 1,000,000 to 1,001,000 (a 1ms window at the 1-second mark).
Only ~500 instructions actually START in this window, but tree shows all 500K.
User wants to see ONLY the 500 instructions that start during this viewport window.
```

### 1.2 Core Requirements

**MUST Requirements:**

1. **Viewport Filter Toggle**
   - MUST add a "Viewport Filter" checkbox to the header panel
   - MUST apply filter only when checkbox is enabled (default: disabled)
   - MUST preserve all existing tree view functionality when filter is inactive

2. **Leaf-Only Filtering**
   - MUST filter ONLY leaf records (records without children)
   - MUST use strict viewport inclusion: `start_clk >= viewport_start_clk AND start_clk <= viewport_end_clk`
   - MUST exclude records that overlap viewport but start outside (e.g., parent starts before viewport but children start inside)

3. **Performance Requirements**
   - MUST use binary search on sorted children for O(log N) lookup
   - MUST skip entire subtrees early when parent `start_clk > viewport_end_clk`
   - MUST rebuild filtered tree only when viewport range changes (cache filtered tree for vertical scrolling)
   - MUST handle typical JETS structure efficiently: shallow depth (2-5 levels) but wide nodes (100K+ leaf children)

4. **Cache Management**
   - MUST cache filtered tree structure keyed by viewport range
   - MUST invalidate filtered cache only on:
     - Viewport range change (start_clk or end_clk)
     - Tree expansion/collapse change
     - Trace reload
   - MUST NOT invalidate cache on vertical scroll

5. **UI Feedback**
   - MUST show filtered node count in status bar (e.g., "Showing 500 / 500,000 records")
   - MUST update count in real-time as viewport changes
   - MUST clearly indicate when filter is active

6. **Functional Preservation**
   - MUST preserve all existing tree view functionality when filter is active:
     - Expand/collapse operations
     - Node selection
     - Virtual scrolling
     - Tree-timeline synchronization

**SHOULD Requirements:**

1. **Optimization for Wide Nodes**
   - SHOULD use binary search to find first child with `start_clk >= viewport_start_clk`
   - SHOULD use binary search to find last child with `start_clk <= viewport_end_clk`
   - SHOULD reduce O(100K) iteration to O(log 100K) ≈ 17 operations for wide nodes

2. **Edge Case Handling**
   - SHOULD handle empty viewport gracefully (no records match)
   - SHOULD handle viewport that includes all records (filter effectively disabled)
   - SHOULD handle single-record traces correctly

**NICE TO HAVE:**

1. Keyboard shortcut to toggle filter (e.g., Ctrl+F)
2. Visual indicator on filtered-out parent nodes (e.g., grayed icon showing "children hidden")
3. Statistics in tooltip: "X records filtered out, Y records shown"

### 1.3 Detailed Functional Requirements

#### Filtering Logic

**Inclusion Criteria:**
- Record MUST be a leaf (no children)
- Record start_clk MUST be >= viewport_start_clk
- Record start_clk MUST be <= viewport_end_clk

**Example:**
```
Viewport:    [----]  (start_clk=1000, end_clk=1100)

Rec0  [---]           clk=800   -> FILTERED OUT (starts before viewport)
Rec1    [-------]     clk=900   -> FILTERED OUT (starts before viewport, even though it overlaps)
Rec2          [--]    clk=1000  -> INCLUDED (starts within viewport)
Rec3          [--------] clk=1050 -> INCLUDED (starts within viewport)
Rec4                   [------] clk=1200 -> FILTERED OUT (starts after viewport)
```

#### Parent Node Behavior

**When filter is active:**
- Parent nodes are ALWAYS shown (never filtered out)
- Parent nodes with NO matching leaf children are still shown
- Expand/collapse still works on parent nodes
- Parent nodes act as structural anchors for navigation

**Rationale:**
- Preserves tree structure and hierarchy
- Allows users to understand context of filtered leaves
- Maintains expand/collapse functionality
- Prevents confusing UI state where entire branches disappear

#### Cache Invalidation Rules

**Invalidate filtered cache when:**
- Viewport start_clk changes
- Viewport end_clk changes
- Any node is expanded or collapsed
- Trace is reloaded

**DO NOT invalidate when:**
- Vertical scroll position changes
- Horizontal pan (timeline zoom) without viewport boundary change
- Node selection changes
- Theme changes

### 1.4 JETS Trace Structural Guarantees

The JETS format provides critical guarantees that enable efficient filtering:

**From JETS Format Specification:**

1. **Children Sorted by Clock**
   - Parser guarantees children of a record are sorted in ascending `start_clk` order
   - Location: `jets/rjets/src/parser.rs` lines 344-351
   - Enables binary search for first/last matching child

2. **Children Start >= Parent Start**
   - All children of a record have `start_clk >= parent.start_clk`
   - Guaranteed by JETS format constraint
   - Enables early subtree skipping: if `parent.start_clk > viewport_end_clk`, all children are after viewport

3. **Shallow but Wide Trees**
   - Typical JETS traces have depth 2-5 levels
   - Each depth-1 record may have 100K+ leaf children
   - Optimization critical for wide nodes: binary search reduces O(100K) to O(log 100K) ≈ 17 operations

4. **No Forward References**
   - Parent records appear before their children in trace file
   - Parser builds relationships during single-pass parse
   - Does not affect runtime filtering, but guarantees structural integrity

**Filtering Optimization Opportunities:**

- **Binary search on sorted children**: Find first child with `start_clk >= viewport_start_clk` in O(log N)
- **Binary search for last matching**: Find last child with `start_clk <= viewport_end_clk` in O(log N)
- **Early subtree skip**: If `parent.start_clk > viewport_end_clk`, skip entire subtree (all children must start after viewport)
- **Cannot skip when parent starts before**: If `parent.start_clk < viewport_start_clk`, some children may start inside viewport, must check

**Example Performance Gain:**
```
Wide node with 100,000 leaf instruction children, viewport at row 50,000:
- Without binary search: iterate 50,000 times = O(50K)
- With binary search: O(log 100K) ≈ 17 comparisons to find first, then iterate visible ≈ 50 records
- Speedup: 1000x faster for wide nodes
```

### 1.5 Performance Targets

| Metric | Current (unfiltered) | Target (filtered) |
|--------|---------------------|-------------------|
| **Tree rebuild on viewport change** | N/A | < 10ms for 500K records |
| **Vertical scroll FPS** | 60 FPS | 60 FPS (cached) |
| **Binary search overhead** | N/A | ~17 comparisons per 100K children |
| **Cache memory overhead** | 0 MB | < 2 MB for typical traces |
| **Filter toggle response** | N/A | < 50ms |

### 1.6 Scope and Constraints

**In Scope:**
- Viewport filter checkbox in header
- Leaf-only filtering based on start_clk
- Binary search optimization for sorted children
- Filtered tree cache with smart invalidation
- Filtered count display in status bar
- Integration with existing virtual scrolling

**Out of Scope:**
- Filtering by record type, name, or other attributes (future feature)
- Filtering by end_clk or duration (only start_clk)
- Filtering events or annotations (only records)
- Multiple simultaneous filter criteria (only viewport)
- Saved filter presets
- Filter history or undo

**Constraints:**
- MUST maintain 60 FPS scrolling with filter active
- MUST NOT break existing tree view interactions
- MUST NOT increase memory usage by more than 2 MB for typical traces
- MUST use existing JETS format guarantees (no format changes)
- MUST work with all three trace types (JETS, PipeTrace, Virtual)

---

## 2. Codebase Research

### 2.1 Current Tree View Architecture

**File:** `jets/rjets/src/ui/tree_panel.rs`

**Current rendering flow (lines 27-126):**
```
render_tree_panel(ui, state, theme_colors):
1. Check if trace data exists; return early if None
2. Calculate dynamic expand column width based on max visible depth
3. Render table header with column widths
4. Create ScrollArea and render content:
   a. Get viewport metrics (height, scroll offset)
   b. Call VirtualScrollManager::collect_visible_nodes() to get only visible nodes
   c. Add top padding for skipped rows
   d. Render each visible node via render_tree_node()
   e. Add bottom padding for remaining rows
5. Update shared scroll position from scroll_area.state.offset.y
```

**Key observation:** Virtual scrolling already implemented (Feature #0006), filters ALL records before rendering. This is where we'll integrate viewport filtering.

### 2.2 Virtual Scrolling System

**File:** `jets/rjets/src/ui/virtual_scroll_manager.rs`

**Current visible node collection (lines 33-48):**
```
VirtualScrollManager::collect_visible_nodes(
    trace,
    expanded_nodes,
    cache,
    viewport_scroll_offset,
    viewport_height
) -> Vec<VisibleNode>
```

This function delegates to `virtual_scrolling::collect_visible_nodes()` which:
1. Traverses tree starting from roots
2. Respects expanded/collapsed state
3. Returns only nodes visible in vertical scroll viewport
4. Uses cache for subtree sizes to skip collapsed branches

**Integration point:** We'll add an optional viewport clock filter parameter to this function.

### 2.3 Tree Operations and Caching

**File:** `jets/rjets/src/domain/tree_operations.rs`

**Current operations (lines 1-192):**
- `get_total_visible_nodes()` - counts visible nodes (cached)
- `get_subtree_size()` - gets cached or calculates subtree size
- `calculate_subtree_size()` - recursive subtree size calculation
- `are_all_children_collapsed_cached()` - checks if all children collapsed (cached)

**Key observation:** Uses `TreeCache` to store expensive calculations. We'll add filtered tree caching here.

### 2.4 Header Panel UI

**File:** `jets/rjets/src/ui/header.rs`

**Current header rendering (lines 26-178):**
```
render_header(ui, state) -> Option<HeaderInteraction>:
1. Horizontal layout with:
   - "Open Trace" button
   - "Virtual Trace" button
   - Separator
   - Zoom controls (if trace loaded): +, -, Fit buttons
   - Viewport boundary text fields (editable)
   - Theme selector (right-aligned)
2. Error message display (if any)
3. Returns HeaderInteraction enum for button clicks
```

**Integration point:** Add "Viewport Filter" checkbox after viewport boundary fields (around line 143).

### 2.5 Viewport State Management

**File:** `jets/rjets/src/state/viewport.rs`

**Current ViewportState (lines 14-164):**
```rust
pub struct ViewportState {
    zoom_level: f32,
    viewport_start_clk: i64,
    viewport_end_clk: i64,
    shared_scroll_y: f32,
}
```

**Key methods:**
- `viewport_start_clk()` - getter for start boundary
- `viewport_end_clk()` - getter for end boundary
- `set_range()` - updates viewport range and recalculates zoom
- `zoom_around()` - zooms around focus point

**Integration point:** Add `viewport_filter_enabled: bool` field and associated methods.

### 2.6 Status Bar

**File:** `jets/rjets/src/ui/status_bar.rs`

**Current status bar (lines 15-60):**
```
render_status_bar(ui, state):
1. Show memory usage (always visible)
2. If trace loaded:
   - Virtual trace: show seed, roots, time range, total records/events
   - File trace: show GPU model, clock freq, time range, total records/events
```

**Integration point:** Add filtered count display: "Showing 500 / 500,000 records" after existing metadata.

### 2.7 TraceRecord Trait

**File:** `jets/rjets/src/traits.rs`

**Current TraceRecord trait (lines 49-80):**
```rust
pub trait TraceRecord {
    fn clk(&self) -> i64;
    fn end_clk(&self) -> Option<i64>;
    fn duration(&self) -> Option<i64>;
    fn name(&self) -> &str;
    fn id(&self) -> RecordId;
    fn parent_id(&self) -> Option<RecordId>;
    fn description(&self) -> &str;
    fn data(&self) -> HashMap<String, serde_json::Value>;
    fn children(&self) -> Vec<&dyn TraceRecord>;
    fn events(&self) -> Vec<&dyn TraceEvent>;
}
```

**Missing method needed:** `subtree_depth() -> usize` to determine if record is a leaf (depth == 0) or parent (depth > 0).

### 2.8 Parser Implementation

**File:** `jets/rjets/src/parser.rs`

**JetsTraceRecord structure (lines 71-100):**
```rust
pub struct JetsTraceRecord {
    pub clk: i64,
    pub name: Arc<str>,
    pub record_type: Arc<str>,
    pub id: RecordId,
    pub parent_id: Option<RecordId>,
    pub description: Arc<str>,
    pub data: Option<serde_json::Value>,
    pub end_clk: Option<i64>,
    pub duration: Option<i64>,
    pub child_indices: Vec<usize>,  // Indices into arena
    pub annotations: Vec<JetsTraceAnnotation>,
    pub events: Vec<JetsTraceEvent>,
    arena: OnceCell<Arc<Vec<JetsTraceRecord>>>,
}
```

**Children sorting (lines 344-351):**
```rust
// Sort children indices by clock time and name
for children in children_by_parent.values_mut() {
    children.sort_by(|&a, &b| {
        let rec_a = &all_records[a];
        let rec_b = &all_records[b];
        rec_a.clk.cmp(&rec_b.clk).then_with(|| rec_a.name.cmp(&rec_b.name))
    });
}
```

**Key observation:** Children are guaranteed sorted by clk, enabling binary search.

### 2.9 TreeCache Structure

**File:** `jets/rjets/src/cache/tree_cache.rs`

**Current TreeCache (lines 10-61):**
```rust
pub struct TreeCache {
    pub subtree_sizes: HashMap<u64, usize>,
    pub all_children_collapsed: HashMap<u64, bool>,
    pub total_visible_nodes: Option<usize>,
    pub max_visible_depth: Option<usize>,
    pub expansion_seq: u64,
}
```

**Integration point:** Add filtered tree cache fields keyed by viewport range.

---

## 3. Implementation Planning

### 3.1 Data Structure Changes

#### Add to `ViewportState` (`jets/rjets/src/state/viewport.rs`)

```rust
pub struct ViewportState {
    // Existing fields...
    zoom_level: f32,
    viewport_start_clk: i64,
    viewport_end_clk: i64,
    shared_scroll_y: f32,

    // NEW: Viewport filter state
    viewport_filter_enabled: bool,
}
```

**New methods to add:**
- `viewport_filter_enabled() -> bool` - getter
- `set_viewport_filter_enabled(enabled: bool)` - setter
- `toggle_viewport_filter()` - toggle filter on/off

#### Add to `TreeCache` (`jets/rjets/src/cache/tree_cache.rs`)

```rust
pub struct TreeCache {
    // Existing fields...
    pub subtree_sizes: HashMap<u64, usize>,
    pub all_children_collapsed: HashMap<u64, bool>,
    pub total_visible_nodes: Option<usize>,
    pub max_visible_depth: Option<usize>,
    pub expansion_seq: u64,

    // NEW: Filtered tree cache
    /// Cached viewport range for filtered tree (start_clk, end_clk)
    pub filtered_viewport_range: Option<(i64, i64)>,

    /// Cached total filtered node count for current viewport
    pub filtered_node_count: Option<usize>,
}
```

**New methods to add:**
- `invalidate_filtered_cache()` - clears filtered cache while preserving unfiltered cache
- `is_filtered_cache_valid(start_clk, end_clk) -> bool` - checks if cached viewport matches current

#### Add to `TraceRecord` trait (`jets/rjets/src/traits.rs`)

```rust
pub trait TraceRecord {
    // Existing methods...

    // NEW: Returns depth of subtree rooted at this record
    // Returns 0 for leaf records (no children)
    // Returns 1 for records with only leaf children
    // Returns max(child.subtree_depth()) + 1 for deeper trees
    fn subtree_depth(&self) -> usize;
}
```

### 3.2 Core Algorithm: Viewport Filtering with Binary Search

**New function in `jets/rjets/src/domain/tree_operations.rs`:**

```
collect_filtered_visible_nodes(
    trace: &dyn TraceData,
    expanded_nodes: &HashSet<u64>,
    cache: &mut TreeCache,
    viewport_scroll_offset: f32,
    viewport_height: f32,
    viewport_start_clk: i64,
    viewport_end_clk: i64,
) -> Vec<VisibleNode>
```

**Algorithm steps:**

1. **Check filtered cache validity:**
   - If `cache.is_filtered_cache_valid(viewport_start_clk, viewport_end_clk)` return cached result
   - Otherwise, rebuild filtered tree

2. **Initialize traversal:**
   - Create result vector for VisibleNode entries
   - Start with row_index = 0
   - Get root IDs from trace

3. **For each root record:**
   - Call `collect_filtered_nodes_recursive(root_id, depth=0, current_row, result)`

4. **Return filtered nodes:**
   - Store viewport range in cache: `cache.filtered_viewport_range = Some((start_clk, end_clk))`
   - Store filtered count: `cache.filtered_node_count = Some(result.len())`
   - Apply vertical scroll viewport filtering (delegate to existing virtual scroll logic)
   - Return final visible nodes

**Recursive collection function:**

```
collect_filtered_nodes_recursive(
    record_id: u64,
    depth: usize,
    current_row: &mut usize,
    trace: &dyn TraceData,
    expanded_nodes: &HashSet<u64>,
    viewport_start_clk: i64,
    viewport_end_clk: i64,
    result: &mut Vec<VisibleNode>,
)
```

**Algorithm steps:**

1. **Get record from trace:**
   - Retrieve record by ID
   - If record is None, return early

2. **Check if record is leaf (no children):**
   - If `record.subtree_depth() == 0`:
     - Check temporal bounds: `record.clk() >= viewport_start_clk && record.clk() <= viewport_end_clk`
     - If matches: add to result as VisibleNode with current row_index and depth
     - Increment current_row
     - Return (done with this branch)

3. **Record is parent (has children):**
   - ALWAYS add parent to result (structural anchor)
   - Increment current_row

4. **Early subtree skip (optimization):**
   - If `record.clk() > viewport_end_clk`:
     - ALL children start after viewport (JETS guarantee: children >= parent clock)
     - Return early, skip entire subtree

5. **Check if node is expanded:**
   - If NOT expanded: return (collapsed subtree not visible)
   - If expanded: continue to process children

6. **Process children with binary search optimization:**
   - Get children: `let children = record.children()`
   - If children is empty: return

   - **Binary search for first matching child:**
     ```
     first_idx = binary_search_first_gte(children, viewport_start_clk)
     ```
     - Finds first child where `child.clk() >= viewport_start_clk`
     - Returns index or children.len() if none found

   - **Binary search for last matching child:**
     ```
     last_idx = binary_search_last_lte(children, viewport_end_clk)
     ```
     - Finds last child where `child.clk() <= viewport_end_clk`
     - Returns index or 0 if none found

   - **Iterate only matching range:**
     ```
     for child in &children[first_idx..=last_idx] {
         collect_filtered_nodes_recursive(child.id(), depth+1, current_row, ...)
     }
     ```

**Binary search helper functions:**

```
binary_search_first_gte(children: &[&dyn TraceRecord], target_clk: i64) -> usize:
1. Use Rust's partition_point to find first child with clk >= target_clk
2. Return index of first match or children.len() if no match
```

```
binary_search_last_lte(children: &[&dyn TraceRecord], target_clk: i64) -> Option<usize>:
1. Use Rust's binary_search_by to find last child with clk <= target_clk
2. Return index of last match or None if no match
```

**Performance characteristics:**
- **Time complexity per node:**
  - Leaf record check: O(1)
  - Binary search for first match: O(log N) where N = children count
  - Binary search for last match: O(log N)
  - Iterate matching range: O(M) where M = matching children count
  - **Total: O(log N + M) per parent node**

- **Best case:** All children filtered out, O(log N) per parent
- **Worst case:** All children match, O(N) per parent (same as unfiltered)
- **Typical case:** Wide nodes (100K children), narrow viewport (50 matches) = O(log 100K + 50) ≈ O(67)

### 3.3 Integration with Virtual Scrolling

**Modify `jets/rjets/src/ui/virtual_scroll_manager.rs`:**

Add new method:
```
pub fn collect_filtered_visible_nodes(
    trace: &dyn TraceData,
    expanded_nodes: &HashSet<u64>,
    cache: &mut TreeCache,
    viewport_scroll_offset: f32,
    viewport_height: f32,
    viewport_start_clk: i64,
    viewport_end_clk: i64,
) -> Vec<VisibleNode>
```

This method:
1. Calls `domain::tree_operations::collect_filtered_visible_nodes()` to get filtered tree
2. Applies vertical scroll viewport culling (reuse existing logic)
3. Returns final visible nodes for rendering

**Modify `jets/rjets/src/ui/tree_panel.rs`:**

Update `render_tree_panel()` around line 68:
```rust
// Collect visible nodes (filtered or unfiltered based on state)
let visible_nodes = if state.viewport.viewport_filter_enabled() {
    VirtualScrollManager::collect_filtered_visible_nodes(
        trace,
        state.tree.expanded_nodes_set(),
        &mut state.tree_cache,
        scroll_offset,
        viewport_height,
        state.viewport.viewport_start_clk(),
        state.viewport.viewport_end_clk(),
    )
} else {
    VirtualScrollManager::collect_visible_nodes(
        trace,
        state.tree.expanded_nodes_set(),
        &mut state.tree_cache,
        scroll_offset,
        viewport_height,
    )
};
```

### 3.4 UI Implementation

#### Header Panel Checkbox

**Modify `jets/rjets/src/ui/header.rs`:**

Add checkbox after viewport boundary fields (around line 143):

```rust
ui.separator();

// Viewport Filter checkbox
let filter_enabled = state.viewport.viewport_filter_enabled();
let filter_response = ui.checkbox(&mut state.viewport.viewport_filter_enabled_mut(), "Viewport Filter");

if filter_response.changed() {
    // Filter toggled, invalidate filtered cache
    state.tree_cache.invalidate_filtered_cache();
}

if filter_response.hovered() {
    egui::show_tooltip(ui.ctx(), ui.id().with("viewport_filter_tooltip"), |ui| {
        ui.label("Show only leaf records that start within the viewport time range");
    });
}
```

**Return new HeaderInteraction variant:**
```rust
pub enum HeaderInteraction {
    OpenFileRequested(PathBuf),
    OpenVirtualTraceRequested,
    // NEW:
    ViewportFilterToggled(bool),
}
```

#### Status Bar Count Display

**Modify `jets/rjets/src/ui/status_bar.rs`:**

Add filtered count display after existing metadata (around line 54):

```rust
if state.viewport.viewport_filter_enabled() {
    // Show filtered count if filter is active
    let filtered_count = state.tree_cache.filtered_node_count.unwrap_or(0);
    let total_count = metadata.total_records().unwrap_or(0);
    ui.label(RichText::new(format!(
        " | Filtered: {} / {} records",
        filtered_count, total_count
    )).strong().color(egui::Color32::YELLOW));
}
```

### 3.5 TraceRecord Trait Implementation

#### Add `subtree_depth()` to trait

**Modify `jets/rjets/src/traits.rs`:**

Add method to trait (after line 79):
```rust
/// Returns the depth of the subtree rooted at this record.
/// - Returns 0 for leaf records (no children)
/// - Returns 1 for records with only leaf children
/// - Returns max(child.subtree_depth()) + 1 for deeper trees
fn subtree_depth(&self) -> usize;
```

#### Implement for JetsTraceRecord

**Modify `jets/rjets/src/parser.rs`:**

Add implementation in `impl TraceRecord for JetsTraceRecord` (after line 529):

```rust
fn subtree_depth(&self) -> usize {
    if self.child_indices.is_empty() {
        return 0; // Leaf node
    }

    // Get arena reference
    let arena = match self.arena.get() {
        Some(a) => a,
        None => return 1, // Conservative: assume depth 1 if arena not initialized
    };

    // Calculate max depth of children + 1
    let max_child_depth = self.child_indices.iter()
        .filter_map(|&idx| arena.get(idx))
        .map(|child| {
            // Ensure child has arena reference
            let _ = child.arena.get_or_init(|| Arc::clone(arena));
            child.subtree_depth()
        })
        .max()
        .unwrap_or(0);

    max_child_depth + 1
}
```

**Performance consideration:**
- First call: O(N) where N = total descendants (recursive traversal)
- Should cache result in TreeCache for repeated calls
- Alternative: compute during parsing and store as field (eliminates runtime cost)

**Optimization:** Add cached depth to TreeCache:
```rust
// In TreeCache:
pub subtree_depths: HashMap<u64, usize>,
```

#### Implement for VirtualTraceRecord

**Modify `jets/rjets/src/virtual_reader.rs`:**

Add similar implementation for `impl TraceRecord for VirtualTraceRecord`.

#### Implement for PipetraceRecord

**Modify `jets/rjets/src/pipetrace_reader.rs`:**

Add similar implementation for `impl TraceRecord for PipetraceRecord`.

### 3.6 Cache Management

**Modify `jets/rjets/src/cache/tree_cache.rs`:**

Add methods for filtered cache management:

```rust
impl TreeCache {
    /// Checks if filtered cache is valid for given viewport range
    pub fn is_filtered_cache_valid(&self, start_clk: i64, end_clk: i64) -> bool {
        match self.filtered_viewport_range {
            Some((cached_start, cached_end)) => {
                cached_start == start_clk && cached_end == end_clk
            }
            None => false,
        }
    }

    /// Invalidates only the filtered tree cache (preserves unfiltered cache)
    pub fn invalidate_filtered_cache(&mut self) {
        self.filtered_viewport_range = None;
        self.filtered_node_count = None;
    }

    /// Invalidates all caches (override existing method)
    pub fn invalidate(&mut self) {
        // Clear unfiltered caches
        self.subtree_sizes.clear();
        self.all_children_collapsed.clear();
        self.total_visible_nodes = None;
        self.max_visible_depth = None;
        self.expansion_seq += 1;

        // Clear filtered caches
        self.invalidate_filtered_cache();
    }
}
```

**Cache invalidation triggers:**

1. **Viewport range change:**
   - When `viewport_start_clk` or `viewport_end_clk` changes
   - Call `cache.invalidate_filtered_cache()`
   - Location: viewport change handlers in `ViewportState` or input handling

2. **Tree expansion change:**
   - When any node is expanded or collapsed
   - Call `cache.invalidate()` (invalidate both filtered and unfiltered)
   - Location: expand/collapse handlers in application coordinator

3. **Trace reload:**
   - When new trace is loaded
   - Call `cache.invalidate()`
   - Location: trace loading in `ApplicationCoordinator`

4. **Filter toggle:**
   - When checkbox is toggled on/off
   - Call `cache.invalidate_filtered_cache()` (only if toggled ON, no need if toggled OFF)

### 3.7 File-by-File Implementation Summary

#### `jets/rjets/src/state/viewport.rs`
**Changes:**
- Add field: `viewport_filter_enabled: bool` (1 line)
- Add method: `viewport_filter_enabled() -> bool` (3 lines)
- Add method: `set_viewport_filter_enabled(enabled: bool)` (3 lines)
- Add method: `toggle_viewport_filter()` (5 lines)
- Update `Default::default()` to initialize filter as false (1 line)
- Update `new()` to initialize filter as false (1 line)

**Total:** ~15 lines added

#### `jets/rjets/src/cache/tree_cache.rs`
**Changes:**
- Add fields: `filtered_viewport_range: Option<(i64, i64)>`, `filtered_node_count: Option<usize>` (2 lines)
- Add method: `is_filtered_cache_valid(&self, i64, i64) -> bool` (8 lines)
- Add method: `invalidate_filtered_cache(&mut self)` (4 lines)
- Update `invalidate(&mut self)` to also clear filtered cache (2 lines)
- Update `new()` to initialize new fields (2 lines)

**Total:** ~18 lines added/modified

#### `jets/rjets/src/traits.rs`
**Changes:**
- Add method to `TraceRecord` trait: `fn subtree_depth(&self) -> usize;` (4 lines with doc comment)

**Total:** ~4 lines added

#### `jets/rjets/src/parser.rs`
**Changes:**
- Implement `subtree_depth()` for `JetsTraceRecord` (20 lines)

**Total:** ~20 lines added

#### `jets/rjets/src/virtual_reader.rs`
**Changes:**
- Implement `subtree_depth()` for `VirtualTraceRecord` (15 lines)

**Total:** ~15 lines added

#### `jets/rjets/src/pipetrace_reader.rs`
**Changes:**
- Implement `subtree_depth()` for `PipetraceRecord` (15 lines)

**Total:** ~15 lines added

#### `jets/rjets/src/domain/tree_operations.rs`
**Changes:**
- Add helper: `binary_search_first_gte(children, target_clk) -> usize` (10 lines)
- Add helper: `binary_search_last_lte(children, target_clk) -> Option<usize>` (10 lines)
- Add function: `collect_filtered_nodes_recursive(...)` (60 lines)
- Add function: `collect_filtered_visible_nodes(...)` (30 lines)

**Total:** ~110 lines added

#### `jets/rjets/src/ui/virtual_scroll_manager.rs`
**Changes:**
- Add method: `collect_filtered_visible_nodes(...)` that delegates to domain layer (15 lines)

**Total:** ~15 lines added

#### `jets/rjets/src/ui/tree_panel.rs`
**Changes:**
- Modify `render_tree_panel()` to conditionally use filtered collection (15 lines)
- Update total node count calculation when filter active (5 lines)

**Total:** ~20 lines modified

#### `jets/rjets/src/ui/header.rs`
**Changes:**
- Add viewport filter checkbox with tooltip (12 lines)
- Add `ViewportFilterToggled` variant to `HeaderInteraction` enum (1 line)

**Total:** ~13 lines added

#### `jets/rjets/src/ui/status_bar.rs`
**Changes:**
- Add filtered count display when filter active (8 lines)

**Total:** ~8 lines added

#### Total Estimated Changes
- **Lines added/modified:** ~253 lines across 11 files
- **New functions:** 4 major functions (binary search helpers, recursive collection, visible nodes wrapper)
- **New trait method:** 1 (`subtree_depth()`)
- **New state fields:** 3 (filter enabled, filtered viewport range, filtered count)

---

## 4. Performance Considerations

### 4.1 Time Complexity Analysis

**Unfiltered tree traversal (current):**
- Time: O(V) where V = total visible nodes (expanded)
- Example: 100,000 expanded nodes = 100,000 iterations

**Filtered tree traversal with binary search:**
- Time: O(P × log C + M) where:
  - P = number of parent nodes traversed
  - C = average children per parent
  - M = number of matching leaf nodes
- Example: 10 parent nodes, 100K children each, 500 matches = 10 × log(100K) + 500 ≈ 10 × 17 + 500 = 670 operations

**Speedup for narrow viewport on wide tree:**
- Unfiltered: O(100,000) operations
- Filtered: O(670) operations
- **Speedup: ~150x faster**

### 4.2 Binary Search Optimization Impact

**For wide node with 100,000 children:**
- Linear search for first match: O(50,000) if match at midpoint
- Binary search for first match: O(log 100,000) ≈ 17 comparisons
- **Improvement: ~3,000x faster for first match**

**For multiple wide nodes:**
- If trace has 10 wide threads with 100K instructions each
- Viewport shows 50 instructions per thread (500 total)
- Linear: 10 × 50,000 = 500,000 iterations
- Binary search: 10 × (17 + 50) = 670 operations
- **Improvement: ~750x faster overall**

### 4.3 Cache Memory Overhead

**Filtered cache storage:**
- `filtered_viewport_range`: 16 bytes (two i64)
- `filtered_node_count`: 8 bytes (usize)
- Subtree depth cache: 16 bytes × N records (if cached)
  - For 500K records: ~8 MB
  - **Optimization:** Only cache depths for parent nodes (~100 records) = ~1.6 KB

**Total additional memory:** < 2 KB for filtered cache metadata, ~1.6 KB for depth cache (parents only)

**Trade-off:** Minimal memory cost (<10 KB) for massive performance gain (100-1000x speedup)

### 4.4 Cache Invalidation Cost

**Filtered cache invalidation (viewport change):**
- Clear two Option fields: O(1)
- Next frame rebuilds filtered tree: O(P × log C + M)
- Typical cost: < 10ms for 500K record trace with narrow viewport

**Full cache invalidation (expand/collapse):**
- Clears all caches including filtered: O(1) amortized
- Next frame rebuilds all caches: O(V + P × log C + M)
- Typical cost: < 20ms for large traces

**Compared to unfiltered:**
- Unfiltered traverse: O(100K) = ~50ms
- Filtered traverse: O(670) = ~1ms
- **Improvement: 50x faster even after cache rebuild**

### 4.5 Subtree Depth Calculation

**Options:**

**Option A: Calculate on-demand with caching**
- First call per record: O(D) where D = descendants
- Cached subsequent calls: O(1)
- Memory: 16 bytes × P parent records
- **Chosen approach** - good balance

**Option B: Pre-compute during parsing**
- Add `subtree_depth: usize` field to `JetsTraceRecord`
- Compute during parse: O(N) one-time cost
- Store as field: 8 bytes × N records
- Access: O(1) always
- **Trade-off:** 4 MB extra memory for 500K records, but zero runtime cost
- **Future optimization if depth cache becomes bottleneck**

**Option C: No caching, compute every time**
- Every call: O(D)
- Memory: 0 bytes
- **Too slow** - rejected

**Recommendation:** Start with Option A (on-demand with caching), migrate to Option B if profiling shows depth calculation is bottleneck.

---

## 5. Algorithm Complexity Summary

### 5.1 Operation Complexity Table

| Operation | Unfiltered | Filtered (binary search) | Improvement |
|-----------|-----------|--------------------------|-------------|
| Traverse wide node (100K children, 50 matches) | O(100,000) | O(log 100K + 50) ≈ O(67) | ~1,500x |
| Full tree traversal (10 wide nodes) | O(1,000,000) | O(670) | ~1,500x |
| Check if leaf | N/A | O(1) cached, O(D) uncached | - |
| Find first matching child | O(N/2) avg | O(log N) | ~N/(2 log N) |
| Viewport change (cache miss) | O(V) | O(P log C + M) | Varies |
| Vertical scroll (cache hit) | O(V) | O(1) cache lookup | ∞ |

**Legend:**
- V = total visible (expanded) nodes
- P = parent nodes traversed
- C = children per parent
- M = matching nodes
- N = children count for single node
- D = descendants for subtree depth

### 5.2 Best/Worst/Average Case Analysis

**Best Case (empty viewport, no matches):**
- Time: O(P × log C) where P = parent count, C = children per parent
- Example: 10 parents × log(100K) ≈ 170 operations
- **Result:** Extremely fast, tree is nearly empty

**Worst Case (viewport includes entire trace):**
- Time: O(V) where V = all visible nodes
- Same as unfiltered traversal
- **Result:** No performance regression when filter doesn't actually filter

**Average Case (narrow viewport on wide tree):**
- Time: O(P × log C + M) where M << C
- Example: 10 parents × log(100K) + 500 matches ≈ 670 operations
- **Result:** 100-1000x speedup over unfiltered

**Typical JETS trace characteristics:**
- Depth: 2-5 levels (shallow)
- Width: 100K-1M children per depth-1 node (very wide)
- Viewport: 0.1-1% of total time range (narrow)
- **Ideal for binary search optimization**

---

## 6. Testing Strategy

### 6.1 Functional Testing

**Test Case 1: Filter Toggle**
- Load trace with 10K records
- Toggle filter ON: verify checkbox state, verify cache invalidated
- Toggle filter OFF: verify checkbox state, verify unfiltered view
- Verify: No crashes, UI responds immediately

**Test Case 2: Empty Viewport (No Matches)**
- Load trace, set viewport to time range with no record starts
- Enable filter
- Verify: Tree shows only parent nodes, no leaf nodes
- Verify: Status bar shows "Showing 0 / 10000 records"

**Test Case 3: Full Viewport (All Matches)**
- Load trace, set viewport to include entire trace time range
- Enable filter
- Verify: All records visible (same as unfiltered)
- Verify: Status bar shows "Showing 10000 / 10000 records"

**Test Case 4: Partial Viewport (Some Matches)**
- Load trace with 100K records spanning 0-100,000 clocks
- Set viewport to 10,000-20,000 clocks (10% of range)
- Enable filter
- Verify: ~10,000 records visible (10% of total)
- Verify: Filtered records have start_clk in [10000, 20000]
- Verify: Parent nodes still visible even if no matching children

**Test Case 5: Wide Node Binary Search**
- Generate virtual trace: 1 parent with 100,000 leaf children (clocks 0-100,000)
- Set viewport to 50,000-50,100 (100 clock window)
- Enable filter
- Measure: Time to rebuild filtered tree should be < 10ms
- Verify: Exactly 100 leaf records visible (clocks 50,000-50,100)
- Verify: Binary search used (check log messages or instrument code)

**Test Case 6: Expand/Collapse with Filter Active**
- Load trace, enable filter, expand parent node
- Verify: Only matching leaf children appear
- Collapse parent node
- Verify: Children hidden, parent still visible
- Verify: Cache invalidated on expand/collapse

**Test Case 7: Viewport Change with Filter Active**
- Load trace, enable filter
- Change viewport by zooming or panning
- Verify: Filtered tree rebuilds automatically
- Verify: Status bar count updates
- Verify: Cache invalidated on viewport change

**Test Case 8: Vertical Scroll with Filter Active**
- Load trace with many filtered records (>100 visible)
- Enable filter
- Scroll vertically through tree
- Verify: Smooth 60 FPS scrolling
- Verify: Cache NOT invalidated on vertical scroll

**Test Case 9: Subtree Depth Calculation**
- Create trace with known structure:
  - Root (depth 3)
    - Parent1 (depth 2)
      - Parent2 (depth 1)
        - Leaf1, Leaf2, Leaf3 (depth 0)
- Verify: `subtree_depth()` returns correct values
- Verify: Depth calculation cached for performance

**Test Case 10: Edge Cases**
- Single record trace: filter works
- Trace with no leaf records (all have children): filter shows only parents
- Trace with no parent records (all leaves): filter shows matching leaves
- Viewport exactly matches single record clock: that record shown
- Viewport between two records: no leaves shown, parents visible

### 6.2 Performance Benchmarking

**Benchmark 1: Wide Node Filtering**
- Setup: Virtual trace with 10 parents, each with 100K leaf children
- Viewport: 1% of time range (narrow)
- Measure: Time to build filtered tree
- Target: < 10ms
- Compare: Unfiltered would take ~100ms

**Benchmark 2: Cache Hit Performance**
- Setup: Load large trace, enable filter
- Action: Vertical scroll 1000 pixels
- Measure: Frame times during scroll
- Target: All frames < 16ms (60 FPS)
- Verify: No cache invalidation during scroll

**Benchmark 3: Cache Rebuild Performance**
- Setup: Large trace (500K records), filter enabled
- Action: Change viewport range (trigger cache invalidation)
- Measure: Time from viewport change to first frame rendered
- Target: < 50ms (perceived as instant)

**Benchmark 4: Binary Search vs Linear Search**
- Setup: Single parent with 100K children, viewport with 50 matches at position 50,000
- Measure: Time to find first matching child
  - With binary search: should be ~17 comparisons
  - With linear search: would be ~50,000 iterations
- Expected: 1000x speedup

### 6.3 Integration Testing

**Integration Test 1: Filter + Virtual Scrolling**
- Verify filtered tree works correctly with virtual scrolling
- Verify vertical scroll viewport applied AFTER temporal filtering
- Verify row indices calculated correctly for filtered tree

**Integration Test 2: Filter + Tree Expansion**
- Verify expand/collapse invalidates cache
- Verify filtered tree rebuilds with new expansion state
- Verify node counts update correctly

**Integration Test 3: Filter + Viewport Controls**
- Verify filter respects viewport text field changes
- Verify filter respects zoom in/out
- Verify filter respects fit-to-trace button
- Verify status bar updates in real-time

**Integration Test 4: Filter + Trace Reload**
- Enable filter, load trace A
- Load trace B (replace trace A)
- Verify: Cache fully invalidated
- Verify: Filter still enabled, applied to trace B

**Integration Test 5: Filter + Theme Change**
- Enable filter
- Change theme
- Verify: Filtered tree not rebuilt (cache not invalidated)
- Verify: Visual appearance updates correctly

### 6.4 Memory Testing

**Memory Test 1: Cache Size**
- Load trace with 500K records
- Enable filter, trigger cache build
- Measure: Memory usage of TreeCache
- Target: < 2 MB additional memory
- Check: `filtered_viewport_range`, `filtered_node_count`, depth cache

**Memory Test 2: Memory Leak Check**
- Enable filter, change viewport 1000 times
- Measure: Memory usage over time
- Verify: No memory leak (memory stabilizes)
- Verify: Old cache entries properly cleared

---

## 7. Implementation Phases

### Phase 1: Core Infrastructure (2-3 hours)
**Tasks:**
1. Add `viewport_filter_enabled` field to `ViewportState` with getters/setters
2. Add `filtered_viewport_range` and `filtered_node_count` to `TreeCache`
3. Implement cache management methods: `is_filtered_cache_valid()`, `invalidate_filtered_cache()`
4. Add `subtree_depth()` to `TraceRecord` trait
5. Implement `subtree_depth()` for `JetsTraceRecord`, `VirtualTraceRecord`, `PipetraceRecord`

**Success Criteria:**
- Code compiles without errors
- All trait implementations present
- Basic depth calculation works correctly

### Phase 2: Binary Search Helpers (1-2 hours)
**Tasks:**
1. Implement `binary_search_first_gte()` helper function
2. Implement `binary_search_last_lte()` helper function
3. Add unit tests for binary search functions
4. Test edge cases: empty array, single element, no matches, all matches

**Success Criteria:**
- Binary search functions pass all unit tests
- Performance verified with benchmarks (log N complexity)

### Phase 3: Filtering Algorithm (3-4 hours)
**Tasks:**
1. Implement `collect_filtered_nodes_recursive()` function
2. Implement early subtree skip optimization
3. Integrate binary search for child range finding
4. Implement `collect_filtered_visible_nodes()` wrapper
5. Add method to `VirtualScrollManager` for filtered collection

**Success Criteria:**
- Filtering algorithm correctly identifies matching leaves
- Early skip works when parent.clk > viewport_end_clk
- Binary search used for wide nodes
- Manual testing with small traces shows correct filtering

### Phase 4: UI Integration (2-3 hours)
**Tasks:**
1. Add viewport filter checkbox to header panel
2. Add tooltip explaining filter behavior
3. Handle checkbox toggle and cache invalidation
4. Update `render_tree_panel()` to conditionally use filtered collection
5. Add filtered count display to status bar

**Success Criteria:**
- Checkbox appears in header, toggles correctly
- Filtered tree shows only matching records when enabled
- Status bar displays correct filtered count
- No visual regressions in tree view

### Phase 5: Cache Management (1-2 hours)
**Tasks:**
1. Implement cache invalidation triggers:
   - Viewport range change
   - Tree expansion/collapse
   - Trace reload
   - Filter toggle
2. Verify cache hits during vertical scroll (no invalidation)
3. Add logging/debugging for cache hits/misses

**Success Criteria:**
- Cache invalidated at correct times
- Cache preserved during vertical scroll
- Performance improves due to caching (measured)

### Phase 6: Testing and Polish (2-3 hours)
**Tasks:**
1. Run all functional tests (Test Cases 1-10)
2. Run performance benchmarks
3. Test with real trace files (not just virtual)
4. Fix any bugs discovered
5. Optimize hot paths if needed
6. Add comments and documentation

**Success Criteria:**
- All test cases pass
- Performance targets met
- No crashes or visual glitches
- Code is well-documented

### Phase 7: Edge Cases and Refinement (1-2 hours)
**Tasks:**
1. Test edge cases: empty trace, single record, no leaves, no parents
2. Test with all three trace types (JETS, PipeTrace, Virtual)
3. Test with extreme viewport ranges (empty, full)
4. Verify behavior with deeply nested traces
5. Final polish and code review

**Success Criteria:**
- All edge cases handled gracefully
- Works correctly with all trace types
- No crashes or unexpected behavior
- Code ready for merge

**Total Estimated Time:** 12-19 hours

---

## 8. Risk Assessment

### 8.1 Technical Risks

**Risk 1: Binary search on unsorted children**
- **Likelihood:** Low (JETS parser guarantees sorting)
- **Impact:** High (incorrect filtering results)
- **Mitigation:**
  - Verify sorting in parser code (lines 344-351 in parser.rs)
  - Add assertion in binary search to detect unsorted data
  - Test with all three trace types to ensure sorting guarantee holds

**Risk 2: Subtree depth calculation performance**
- **Likelihood:** Medium
- **Impact:** Medium (slow first load with filter enabled)
- **Mitigation:**
  - Cache depth calculations in TreeCache
  - Only calculate depth for parent nodes (not leaves)
  - If still slow, pre-compute during parsing (Option B)

**Risk 3: Cache invalidation bugs**
- **Likelihood:** Medium
- **Impact:** Medium (stale filtered tree, incorrect counts)
- **Mitigation:**
  - Conservative invalidation strategy (invalidate on any structural change)
  - Extensive testing of invalidation triggers
  - Add cache validation in debug builds

**Risk 4: Integration with virtual scrolling**
- **Likelihood:** Low
- **Impact:** High (broken rendering, crashes)
- **Mitigation:**
  - Filtered collection returns same `VisibleNode` structure as unfiltered
  - Reuse existing virtual scroll viewport culling
  - Test with various scroll positions and viewport sizes

### 8.2 Usability Risks

**Risk 1: Confusing UI when filter active**
- **Likelihood:** Medium
- **Impact:** Medium (user doesn't understand why records are missing)
- **Mitigation:**
  - Clear checkbox label: "Viewport Filter"
  - Tooltip explaining behavior
  - Status bar shows filtered count prominently
  - Consider visual indicator on filtered-out parents (future enhancement)

**Risk 2: Filter toggle causes jarring UI change**
- **Likelihood:** Low
- **Impact:** Low (momentary confusion)
- **Mitigation:**
  - Smooth transition (< 50ms rebuild)
  - Preserve scroll position and selection when possible
  - Consider animation or fade effect (future enhancement)

### 8.3 Performance Risks

**Risk 1: Cache rebuild too slow on viewport change**
- **Likelihood:** Low (binary search should be fast enough)
- **Impact:** Medium (UI feels sluggish during pan/zoom)
- **Mitigation:**
  - Target < 10ms rebuild time
  - Profile with large traces (500K records)
  - If too slow, add incremental cache updates (future optimization)

**Risk 2: Memory usage too high**
- **Likelihood:** Low (filtered cache is small)
- **Impact:** Low (slight memory increase)
- **Mitigation:**
  - Monitor memory in tests
  - Clear old cache entries aggressively
  - Limit depth cache to parent nodes only

---

## 9. Success Criteria

### 9.1 Functional Success
- ✅ Filter checkbox appears in header, toggles correctly
- ✅ Filtered tree shows only leaf records with start_clk in viewport range
- ✅ Parent nodes always visible regardless of filter
- ✅ Status bar displays filtered count: "Showing X / Y records"
- ✅ All existing tree functionality works with filter active (expand, collapse, select)
- ✅ Cache invalidated correctly on viewport change, expand/collapse, trace reload
- ✅ Cache preserved during vertical scroll (no unnecessary rebuilds)

### 9.2 Performance Success
- ✅ Filtered tree rebuild: < 10ms for 500K records with narrow viewport
- ✅ Vertical scroll: 60 FPS with filter active (cache hit)
- ✅ Binary search: ~17 comparisons for 100K children (O(log N))
- ✅ Memory overhead: < 2 MB additional for typical traces
- ✅ No performance regression when filter inactive

### 9.3 Quality Success
- ✅ No crashes or visual glitches with filter active
- ✅ Works correctly with JETS, PipeTrace, and Virtual trace types
- ✅ Handles edge cases gracefully (empty viewport, single record, etc.)
- ✅ Code is well-documented and maintainable
- ✅ All test cases pass (functional, performance, integration)

---

## 10. Future Enhancements (Out of Scope)

### 10.1 Multi-Criteria Filtering
Add additional filter criteria beyond viewport temporal range:
- Filter by record type
- Filter by record name (regex)
- Filter by duration range
- Combine multiple filters with AND/OR logic

### 10.2 Visual Indicators for Filtered Content
- Gray out parent nodes with no matching children
- Show icon or badge indicating "filtered children hidden"
- Tooltip on parent showing "X children hidden by filter"

### 10.3 Filter Presets and Persistence
- Save/load filter configurations
- Named filter presets (e.g., "Frontend instructions", "Cache misses")
- Persist filter state across sessions

### 10.4 Filter Statistics Panel
- Dedicated panel showing filter statistics
- Histogram of record distribution across time
- Identify time ranges with high/low activity

### 10.5 Performance Optimizations
- Pre-compute subtree depth during parsing (eliminate runtime cost)
- Incremental cache updates for viewport changes (avoid full rebuild)
- Parallel filtering for multi-threaded traces (when thread safety added)

---

## Appendix

### A.1 JETS Format Guarantees (Reference)

From `jets/JETS.md` and `jets/rjets/src/parser.rs`:

1. **Children Sorted by Clock:**
   - Line 344-351 in parser.rs: `children.sort_by(|&a, &b| rec_a.clk.cmp(&rec_b.clk))`
   - Guarantee: Children of any record are sorted by ascending start_clk

2. **Children Start >= Parent Start:**
   - JETS format spec: "All children of a record have start_clk >= parent.start_clk"
   - Enables early subtree skip optimization

3. **No Forward References:**
   - JETS format spec: "Parent records must appear before their children"
   - Parser builds relationships in single pass
   - All references resolved during parsing

### A.2 Binary Search Complexity Proof

**Claim:** Finding first child with `clk >= target` in sorted array of size N takes O(log N) time.

**Proof:**
1. Sorted array enables binary search
2. Each comparison eliminates half of remaining search space
3. After k comparisons: N / 2^k elements remain
4. Search completes when N / 2^k = 1
5. Solving: k = log₂(N)
6. Therefore: O(log N) complexity ∎

**Example:**
- N = 100,000 children
- k = log₂(100,000) ≈ 16.6 ≈ 17 comparisons
- Linear search would require ~50,000 comparisons on average
- Speedup: 50,000 / 17 ≈ 2,941x

### A.3 Related Features

**Dependencies:**
- Feature #0006: Virtual Scrolling (provides infrastructure for viewport-based node collection)

**Enables:**
- Future Feature: Multi-criteria filtering (builds on viewport filter architecture)
- Future Feature: Interactive time range selection (drag on timeline to set filter)
- Future Feature: Statistical analysis of filtered records

**Synergies:**
- Works seamlessly with virtual scrolling for maximum performance
- Leverages existing TreeCache infrastructure
- Compatible with all three trace types (JETS, PipeTrace, Virtual)

---

**Plan Status:** Ready for Implementation
**Estimated Implementation Time:** 12-19 hours
**Lines of Code:** ~250 lines across 11 files
**Key Innovation:** Binary search on sorted children for 1000x speedup on wide nodes
