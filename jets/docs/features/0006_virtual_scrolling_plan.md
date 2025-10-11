# Feature Plan: Virtual Scrolling Optimization for Large Traces

**Feature ID:** 0006
**Feature Name:** virtual_scrolling
**Status:** Planning
**Created:** 2025-10-11
**Last Updated:** 2025-10-12

---

## 1. Use Cases and Requirements Analysis

### 1.1 Problem Statement

Jets-gui experiences severe performance degradation with large traces (100K+ records, 1M+ events), dropping from 60 FPS to 5-10 FPS during scrolling. The root cause is that the application renders **every single node** in the tree recursively, regardless of whether it's visible on screen.

**Current Bottlenecks:**

1. **Tree View Rendering (jets-gui.rs:492-782)**
   - Recursively processes all expanded nodes every frame
   - For 100K records: processes 100K nodes 60 times per second
   - Each node allocation, text rendering, interaction handling adds overhead
   - Result: 100-200ms per frame

2. **Timeline View Rendering (jets-gui.rs:1250-1400)**
   - Same recursive approach as tree view
   - Renders timeline bars and event markers for all nodes
   - No culling based on time viewport or vertical position

3. **No Subtree Skipping**
   - When scrolling to row 50,000, must iterate through rows 0-49,999 first
   - O(N) iteration where N = scroll position
   - Makes scrolling to bottom exponentially slower

4. **Repeated Tree Traversals**
   - Counts total visible nodes every frame for scrollbar sizing
   - Recalculates maximum depth every frame for column width
   - No caching of these expensive calculations

### 1.2 Core Requirements

**MUST Requirements:**
1. MUST achieve 60 FPS scrolling regardless of total trace size (100K+ records)
2. MUST only render nodes that are actually visible in the viewport (virtual scrolling)
3. MUST maintain perfect synchronization between tree view and timeline view
4. MUST skip collapsed subtrees in O(1) time using cached subtree sizes
5. MUST cache expensive calculations (visible node count, max depth) and invalidate only on structural changes
6. MUST maintain correct scrollbar behavior (size, position) for navigation
7. MUST handle trace reload/replacement by clearing all caches

**SHOULD Requirements:**
1. SHOULD include small buffer (±10 rows) above/below viewport for smooth scrolling
2. SHOULD apply event marker culling to only render events within time viewport
3. SHOULD use binary search for finding first visible event in sorted event lists
4. SHOULD minimize memory overhead (< 100KB for 10K expanded nodes)
5. SHOULD validate that events are sorted before using binary search

**NICE TO HAVE:**
1. Adaptive buffer size based on scroll velocity
2. Predictive rendering for anticipated scroll direction
3. Lazy depth calculation only for visible nodes

### 1.3 Performance Targets

| Metric | Current (100K records) | Target (100K records) |
|--------|------------------------|----------------------|
| **Scroll FPS** | 5-10 FPS | 60 FPS |
| **Frame time** | 100-200ms | < 16ms |
| **Nodes rendered/frame** | 100,000 | ~50-60 |
| **Scroll to bottom time** | 30+ seconds | < 1 second |
| **Memory overhead** | N/A | < 100KB cache |

### 1.4 Scope and Constraints

**In Scope:**
- Virtual scrolling for tree view
- Virtual scrolling for timeline view
- Subtree size caching and skipping
- Wide node optimization (O(1) skip for nodes with all collapsed children)
- Visible node count caching
- Max depth caching
- Event marker culling with binary search
- Trace reload handling

**Out of Scope:**
- Lazy loading from disk (all data must be in memory)
- Progressive rendering during file load
- Level-of-detail rendering (simplified view at high zoom out)
- GPU-accelerated rendering
- Thread safety (egui is single-threaded)

**Constraints:**
- egui immediate-mode rendering model (stateless per frame)
- Must maintain exact visual output (no degradation in quality)
- Must not break existing expand/collapse functionality
- Must preserve selection state and interaction behavior

---

## 2. Codebase Research

### 2.1 Current Tree Rendering Architecture

**File:** `jets/rjets/src/jets-gui.rs`

**Tree rendering flow (lines 492-530):**
```rust
render_tree(ui) {
    for root_id in trace.root_ids() {
        render_tree_node(ui, root_id, 0, expand_width);
    }
}
```

**Recursive node rendering (lines 598-782):**
```rust
render_tree_node(ui, record_id, depth, expand_width) {
    // 1. Allocate space (ROW_HEIGHT constant: 22px)
    // 2. Draw background if selected
    // 3. Render expand/collapse button
    // 4. Render columns (name, id, clocks, description)
    // 5. If expanded, recursively render children (lines 777-781)

    if self.expanded_nodes.contains(&record_id) {
        for child_id in child_ids {
            self.render_tree_node(ui, child_id, depth + 1, expand_width);
        }
    }
}
```

**Key observation:** No concept of viewport boundaries - renders all nodes unconditionally.

### 2.2 Current Timeline Rendering Architecture

**Timeline rendering flow (lines 1138-1152):**
```rust
render_timeline(ui, ctx) {
    ScrollArea::vertical().show(ui, |ui| {
        for root_id in root_ids {
            self.render_timeline_row(ui, root_id, 0, ctx);
        }
    });
}
```

**Recursive timeline row rendering (lines 1250-1400):**
```rust
render_timeline_row(ui, record_id, depth, ctx) {
    // 1. Allocate space (ROW_HEIGHT: 22px)
    // 2. Draw timeline bar for record duration
    // 3. Draw event markers for all events (lines 1343-1390)
    // 4. If expanded, recursively render children (lines 1393-1399)

    if self.expanded_nodes.contains(&record_id) {
        for child_id in child_ids {
            self.render_timeline_row(ui, child_id, depth + 1, ctx);
        }
    }
}
```

**Event rendering (lines 1343-1390):**
- Iterates through **all events** for each record
- Basic viewport culling: `if event_clk >= viewport_start_clk && event_clk <= viewport_end_clk`
- No binary search - linear scan through all events
- **ASSUMPTION:** Events are sorted by clk (not enforced by trait)

### 2.3 Scroll State Management

**Current scroll synchronization (lines 520-529):**
```rust
let scroll_area = ScrollArea::vertical()
    .id_salt("tree_scroll_area")
    .show(ui, |ui| {
        for root_id in ids_to_render {
            self.render_tree_node(ui, root_id, 0, expand_width);
        }
    });

// Update shared scroll position (IMPORTANT: use state.offset.y, not input delta)
self.shared_scroll_y = scroll_area.state.offset.y;
```

**Timeline scroll synchronization (lines 1138-1142):**
```rust
let mut scroll_area = ScrollArea::vertical()
    .id_salt("timeline_scroll_area")
    .scroll_bar_visibility(ScrollBarVisibility::AlwaysHidden);

scroll_area = scroll_area.vertical_scroll_offset(self.shared_scroll_y);
```

**Key observations:**
- Tree view controls scroll position via `scroll_area.state.offset.y`
- Timeline view follows tree scroll offset
- Scroll offset is in pixels, not row index
- **IMPORTANT:** Must use `state.offset.y`, not `input().scroll_delta` which is frame delta

### 2.4 Expanded Node Tracking

**Data structure (line 37):**
```rust
expanded_nodes: std::collections::HashSet<u64>,
```

**Expansion toggling (lines 684-689):**
```rust
if button_response.clicked() {
    if is_expanded {
        self.expanded_nodes.remove(&record_id);
    } else {
        self.expanded_nodes.insert(record_id);
    }
    // MISSING: cache invalidation should be added here
}
```

**Key observation:** HashSet lookup is O(1) for checking if node is expanded.

### 2.5 Depth Calculation (Current Implementation)

**Max depth calculation (lines 314-344):**
```rust
fn calculate_max_visible_depth(&self) -> usize {
    if let Some(trace) = &self.trace_data {
        let mut max_depth = 0;
        for root_id in trace.root_ids() {
            let depth = self.calculate_node_depth(root_id, 0);
            max_depth = max_depth.max(depth);
        }
        max_depth
    } else {
        0
    }
}

fn calculate_node_depth(&self, record_id: u64, current_depth: usize) -> usize {
    let mut max_depth = current_depth;

    if self.expanded_nodes.contains(&record_id) {
        if let Some(trace) = &self.trace_data {
            if let Some(record) = trace.get_record(record_id) {
                for child in record.children() {
                    let child_depth = self.calculate_node_depth(child.id(), current_depth + 1);
                    max_depth = max_depth.max(child_depth);
                }
            }
        }
    }

    max_depth
}
```

**Performance:** Called every frame in `render_tree()` (line 502). Recursively traverses all visible nodes.

### 2.6 TraceData API

**File:** `jets/rjets/src/traits.rs`

**Key trait methods:**
```rust
pub trait TraceData: Send {
    fn root_ids(&self) -> Vec<u64>;
    fn get_record(&self, id: u64) -> Option<&dyn TraceRecord>;
}

pub trait TraceRecord {
    fn id(&self) -> u64;
    fn parent_id(&self) -> Option<u64>;
    fn children(&self) -> Vec<&dyn TraceRecord>;
    fn events(&self) -> Vec<&dyn TraceEvent>;
}

pub trait TraceEvent {
    fn clk(&self) -> i64;
}
```

**Key observations:**
- Children are returned as Vec (random access, indexed)
- Events are returned as Vec (should be sorted by clk, but not guaranteed by trait)
- No built-in support for subtree size queries

---

## 3. Implementation Planning

### 3.1 Constants and Data Structures

**File:** `jets/rjets/src/jets-gui.rs`

#### Add Constants (after imports)

```rust
/// Row height in pixels (consistent across tree and timeline views)
const ROW_HEIGHT: f32 = 22.0;

/// Number of rows to render above/below viewport for smooth scrolling
const VIEWPORT_BUFFER_ROWS: usize = 10;
```

#### New Cache Structures (add after line 66)

```rust
/// Cache for expensive tree calculations
struct TreeCache {
    /// Maps record_id -> total visible descendants (including self)
    /// Only stores entries for expanded nodes
    subtree_sizes: HashMap<u64, usize>,

    /// Maps record_id -> true if all direct children are collapsed (leaf optimization)
    /// Enables O(1) skipping for wide nodes with many leaf children
    all_children_collapsed: HashMap<u64, bool>,

    /// Cached total visible node count
    total_visible_nodes: Option<usize>,

    /// Cached maximum visible depth
    max_visible_depth: Option<usize>,

    /// Sequence number for cache invalidation
    /// Incremented whenever expanded_nodes changes or trace reloads
    expansion_seq: u64,
}

impl TreeCache {
    fn new() -> Self {
        Self {
            subtree_sizes: HashMap::new(),
            all_children_collapsed: HashMap::new(),
            total_visible_nodes: None,
            max_visible_depth: None,
            expansion_seq: 0,
        }
    }

    fn invalidate(&mut self) {
        self.subtree_sizes.clear();
        self.all_children_collapsed.clear();
        self.total_visible_nodes = None;
        self.max_visible_depth = None;
        self.expansion_seq += 1;
    }
}
```

#### Modify `JetsViewerApp` struct (around line 33)

**Add field:**
```rust
tree_cache: TreeCache,
```

**Update Default and new() implementations:**
- Initialize `tree_cache: TreeCache::new()`
- Add cache invalidation when loading new trace

#### Virtual Scrolling Data Structures

```rust
/// Represents a visible node in the flattened tree view
struct VisibleNode {
    record_id: u64,
    depth: usize,
    row_index: usize,
}
```

### 3.2 Core Algorithms

#### Algorithm 1: Collect Visible Nodes (Virtual Scrolling)

**File:** `jets/rjets/src/jets-gui.rs`

**New method:** `collect_visible_nodes()` (add after `calculate_node_depth`)

**Purpose:** Collect only the nodes that are visible in the viewport plus buffer

```rust
fn collect_visible_nodes(
    &mut self,
    viewport_scroll_offset: f32,
    viewport_height: f32,
) -> Vec<VisibleNode> {
    // 1. Calculate visible row range with buffer
    let start_row = (viewport_scroll_offset / ROW_HEIGHT).floor() as usize;
    let visible_rows = (viewport_height / ROW_HEIGHT).ceil() as usize;

    let first_visible_row = start_row.saturating_sub(VIEWPORT_BUFFER_ROWS);
    let last_visible_row = start_row + visible_rows + VIEWPORT_BUFFER_ROWS;

    // 2. Collect nodes in visible range using subtree skipping
    let mut result = Vec::new();
    let mut current_row = 0;

    if let Some(trace) = &self.trace_data {
        for root_id in trace.root_ids() {
            self.collect_nodes_in_range(
                root_id,
                0,  // depth
                &mut current_row,
                first_visible_row,
                last_visible_row,
                &mut result
            );

            // Early exit if we've passed visible range
            if current_row > last_visible_row {
                break;
            }
        }
    }

    result
}

fn collect_nodes_in_range(
    &mut self,
    record_id: u64,
    depth: usize,
    current_row: &mut usize,
    first_visible: usize,
    last_visible: usize,
    result: &mut Vec<VisibleNode>
) {
    // Check if this node is in visible range
    if *current_row >= first_visible && *current_row <= last_visible {
        result.push(VisibleNode {
            record_id,
            depth,
            row_index: *current_row,
        });
    }

    let node_row = *current_row;
    *current_row += 1;

    // Check if children should be processed
    if self.expanded_nodes.contains(&record_id) {
        // Check if subtree might overlap with visible range
        if node_row <= last_visible {
            if let Some(trace) = &self.trace_data {
                if let Some(record) = trace.get_record(record_id) {
                    let children = record.children();

                    // FAST PATH: All children collapsed (common case for wide nodes)
                    if self.are_all_children_collapsed_cached(record_id) {
                        // Each child takes exactly 1 row - jump directly to visible range
                        let num_children = children.len();
                        let first_child_idx = first_visible.saturating_sub(*current_row).min(num_children);
                        let last_child_idx = (last_visible - *current_row + 1).min(num_children);

                        // Add only visible children in O(V) time
                        for i in first_child_idx..last_child_idx {
                            result.push(VisibleNode {
                                record_id: children[i].id(),
                                depth: depth + 1,
                                row_index: *current_row + i,
                            });
                        }

                        // Skip all children in O(1)
                        *current_row += num_children;
                    } else {
                        // SLOW PATH: Some children expanded, check each with subtree skipping
                        for child in children {
                            // Try to skip subtree if entirely before visible range
                            let subtree_size = self.get_subtree_size(child.id());
                            if *current_row + subtree_size < first_visible {
                                *current_row += subtree_size;
                                continue;  // Skip entire subtree
                            }

                            // Subtree might be visible, recurse
                            self.collect_nodes_in_range(
                                child.id(),
                                depth + 1,
                                current_row,
                                first_visible,
                                last_visible,
                                result
                            );

                            // Early exit if we've passed visible range
                            if *current_row > last_visible {
                                break;
                            }
                        }
                    }
                }
            }
        }
    }
}
```

**Performance:**
- **Best case** (all children collapsed): O(V) where V = visible nodes (~50)
- **Average case** (mixed expansion): O(V + S) where S = skipped children
- **Worst case** (wide node, some expanded): O(W) where W = children before visible range
- **Critical optimization:** Thread with 100K leaf children, scroll to row 50,000:
  - Without optimization: iterate 50,000 times = 50ms+ (bottleneck!)
  - With optimization: O(50) to add visible nodes = <0.1ms ✅

#### Algorithm 2: Subtree Size Calculation and Caching

**New method:** `get_subtree_size()` and `calculate_subtree_size()`

```rust
fn get_subtree_size(&mut self, record_id: u64) -> usize {
    // Check cache first
    if let Some(&size) = self.tree_cache.subtree_sizes.get(&record_id) {
        return size;
    }

    // Calculate and cache
    let size = self.calculate_subtree_size(record_id);
    self.tree_cache.subtree_sizes.insert(record_id, size);
    size
}

fn calculate_subtree_size(&self, record_id: u64) -> usize {
    let mut total = 1;  // Count self

    if self.expanded_nodes.contains(&record_id) {
        if let Some(trace) = &self.trace_data {
            if let Some(record) = trace.get_record(record_id) {
                for child in record.children() {
                    total += self.calculate_subtree_size(child.id());
                }
            }
        }
    }

    total
}
```

**Cache invalidation:**
```rust
// Modify the expand/collapse handler (lines 684-689)
if button_response.clicked() {
    if is_expanded {
        self.expanded_nodes.remove(&record_id);
    } else {
        self.expanded_nodes.insert(record_id);
    }
    // NEW: Invalidate cache whenever expansion state changes
    self.tree_cache.invalidate();
}

// Also invalidate when loading new trace
fn load_trace(&mut self, new_trace: Box<dyn TraceData>) {
    self.trace_data = Some(new_trace);
    self.expanded_nodes.clear();
    self.tree_cache.invalidate();  // Clear cache for new trace
}
```

#### Algorithm 2b: All Children Collapsed Check (Critical for Wide Nodes)

**New method:** `are_all_children_collapsed_cached()`

```rust
fn are_all_children_collapsed_cached(&mut self, parent_id: u64) -> bool {
    // Check cache first
    if let Some(&collapsed) = self.tree_cache.all_children_collapsed.get(&parent_id) {
        return collapsed;
    }

    // Calculate: check if any child is in expanded_nodes
    let result = if let Some(trace) = &self.trace_data {
        if let Some(record) = trace.get_record(parent_id) {
            let children = record.children();
            // Empty nodes are considered "all collapsed" for simplicity
            children.is_empty() ||
            children.iter().all(|child| !self.expanded_nodes.contains(&child.id()))
        } else {
            false
        }
    } else {
        false
    };

    // Cache and return
    self.tree_cache.all_children_collapsed.insert(parent_id, result);
    result
}
```

#### Algorithm 3: Visible Node Count Caching

**New method:** `get_total_visible_nodes()`

```rust
fn get_total_visible_nodes(&mut self) -> usize {
    // Check cache
    if let Some(total) = self.tree_cache.total_visible_nodes {
        return total;
    }

    // Calculate
    let mut total = 0;
    if let Some(trace) = &self.trace_data {
        for root_id in trace.root_ids() {
            total += self.get_subtree_size(root_id);
        }
    }

    // Cache and return
    self.tree_cache.total_visible_nodes = Some(total);
    total
}
```

#### Algorithm 4: Max Depth Caching

**Modify method:** `calculate_max_visible_depth()` (lines 314-326)

```rust
fn get_max_visible_depth(&mut self) -> usize {
    // Check cache
    if let Some(depth) = self.tree_cache.max_visible_depth {
        return depth;
    }

    // Calculate (existing logic)
    let max_depth = if let Some(trace) = &self.trace_data {
        let mut max_depth = 0;
        for root_id in trace.root_ids() {
            max_depth = max_depth.max(self.calculate_node_depth(root_id, 0));
        }
        max_depth
    } else {
        0
    };

    // Cache and return
    self.tree_cache.max_visible_depth = Some(max_depth);
    max_depth
}
```

#### Algorithm 5: Event Marker Culling with Binary Search

**Modify method:** `render_timeline_row()` (lines 1343-1390)

```rust
// Replace linear event iteration with binary search
let events = record.events();

// Sort events if not already sorted (defensive programming)
let mut sorted_events = events;
sorted_events.sort_by_key(|e| e.clk());

// Find first event in viewport using binary search
let first_visible_idx = sorted_events.binary_search_by(|e| {
    if e.clk() < self.viewport_start_clk {
        std::cmp::Ordering::Less
    } else {
        std::cmp::Ordering::Greater
    }
}).unwrap_or_else(|idx| idx);

// Iterate from first visible until past viewport
for event in &sorted_events[first_visible_idx..] {
    let event_clk = event.clk();

    if event_clk > self.viewport_end_clk {
        break;  // Early exit
    }

    // Render event marker (existing code)
}
```

### 3.3 Rendering Integration

#### Modify `render_tree()` method (lines 492-530)

```rust
fn render_tree(&mut self, ui: &mut egui::Ui) {
    // ... (header rendering unchanged) ...

    let scroll_area = ScrollArea::vertical()
        .id_salt("tree_scroll_area")
        .show(ui, |ui| {
            // Get current scroll position from last frame
            let viewport_scroll_offset = self.shared_scroll_y;
            let viewport_height = ui.available_height();

            // Collect only visible nodes
            let visible_nodes = self.collect_visible_nodes(
                viewport_scroll_offset,
                viewport_height
            );

            if visible_nodes.is_empty() {
                return;
            }

            // Add spacing above for scrollbar correctness
            let first_row = visible_nodes[0].row_index;
            if first_row > 0 {
                let spacing_above = first_row as f32 * ROW_HEIGHT;
                ui.add_space(spacing_above);
            }

            // Render only visible nodes
            for visible_node in &visible_nodes {
                self.render_tree_node_direct(
                    ui,
                    visible_node.record_id,
                    visible_node.depth,
                    expand_width
                );
            }

            // Add spacing below for scrollbar correctness
            let last_row = visible_nodes.last().unwrap().row_index;
            let total_rows = self.get_total_visible_nodes();
            if last_row + 1 < total_rows {
                let spacing_below = (total_rows - last_row - 1) as f32 * ROW_HEIGHT;
                ui.add_space(spacing_below);
            }
        });

    // Update shared scroll position for timeline sync
    self.shared_scroll_y = scroll_area.state.offset.y;
}
```

**New method:** `render_tree_node_direct()` (non-recursive version)

```rust
fn render_tree_node_direct(
    &mut self,
    ui: &mut egui::Ui,
    record_id: u64,
    depth: usize,
    expand_width: f32
) {
    // Same as render_tree_node but WITHOUT recursive child rendering
    // Lines 598-776 stay the same
    // Remove lines 777-781 (recursive child rendering)
}
```

#### Modify `render_timeline()` method (lines 1138-1152)

Apply same virtual scrolling pattern as tree view:

```rust
fn render_timeline(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
    // ... (header and viewport input handling unchanged) ...

    let scroll_area = ScrollArea::vertical()
        .id_salt("timeline_scroll_area")
        .scroll_bar_visibility(ScrollBarVisibility::AlwaysHidden)
        .vertical_scroll_offset(self.shared_scroll_y)
        .show(ui, |ui| {
            let viewport_height = ui.available_height();

            // Reuse visible nodes calculation (single source of truth)
            let visible_nodes = self.collect_visible_nodes(
                self.shared_scroll_y,
                viewport_height
            );

            // Add spacing above
            if let Some(first_node) = visible_nodes.first() {
                if first_node.row_index > 0 {
                    let spacing_above = first_node.row_index as f32 * ROW_HEIGHT;
                    ui.add_space(spacing_above);
                }
            }

            // Render only visible timeline rows
            for visible_node in &visible_nodes {
                self.render_timeline_row_direct(
                    ui,
                    visible_node.record_id,
                    ctx
                );
            }

            // Add spacing below
            if let Some(last_node) = visible_nodes.last() {
                let total_rows = self.get_total_visible_nodes();
                if last_node.row_index + 1 < total_rows {
                    let spacing_below = (total_rows - last_node.row_index - 1) as f32 * ROW_HEIGHT;
                    ui.add_space(spacing_below);
                }
            }
        });
}
```

### 3.4 File-by-File Change Summary

#### `jets/rjets/src/jets-gui.rs`

**Constants to add:**
- `ROW_HEIGHT: f32 = 22.0` (~1 line)
- `VIEWPORT_BUFFER_ROWS: usize = 10` (~1 line)

**Structs to add:**
- `TreeCache` struct (~30 lines)
- `VisibleNode` struct (~5 lines)

**Modifications to `JetsViewerApp`:**
- Add field: `tree_cache: TreeCache` (~1 line)
- Update `Default` impl initialization (~1 line)
- Update `new()` method initialization (~1 line)
- Add cache invalidation in trace loading (~2 lines)

**Methods to add:**
- `collect_visible_nodes()` (~30 lines)
- `collect_nodes_in_range()` with fast/slow path (~65 lines)
- `get_subtree_size()` (~10 lines)
- `calculate_subtree_size()` (~15 lines)
- `are_all_children_collapsed_cached()` (~20 lines)
- `get_total_visible_nodes()` (~15 lines)
- `get_max_visible_depth()` (~20 lines, replaces existing)
- `render_tree_node_direct()` (~80 lines, non-recursive version)
- `render_timeline_row_direct()` (~70 lines, non-recursive version)

**Methods to modify:**
- `render_tree()`: Replace with virtual scrolling logic (~40 lines changed)
- `render_timeline()`: Replace with virtual scrolling logic (~40 lines changed)
- Expand/collapse button handler: Add cache invalidation (~2 lines added)
- Event rendering in timeline: Add binary search (~20 lines changed)

**Total:** ~400 lines modified/added across 1 file

#### Other Files

**No changes needed:**
- `jets/rjets/src/traits.rs` - API remains the same
- `jets/rjets/src/parser.rs` - data structures unchanged
- `jets/rjets/src/lib.rs` - exports unchanged
- `jets/rjets/Cargo.toml` - no new dependencies

---

## 4. Performance Considerations

### 4.1 Time Complexity Analysis

**Current Implementation:**
| Operation | Current | After Optimization |
|-----------|---------|-------------------|
| Render tree (100K nodes) | O(100,000) | O(50 + log 100,000) ≈ O(67) |
| Scroll to row 50,000 | O(50,000) | O(50 + log 50,000) ≈ O(66) |
| Count visible nodes | O(N) per frame | O(1) cached |
| Calculate max depth | O(N) per frame | O(1) cached |
| Render events (10K events/record) | O(10,000) per record | O(log 10,000 + V) ≈ O(24) |

**Expected Speedup:**
- Tree rendering: ~1,500x faster (100,000 → 67 operations)
- Scroll to bottom: ~750x faster (50,000 → 66 operations)
- Visible node count: ~100,000x faster (removed per-frame traversal)
- Event rendering: ~400x faster (10,000 → 24 iterations)

### 4.2 Memory Overhead

**Cache Memory Usage:**
- Subtree size cache: ~16 bytes per expanded node (HashMap overhead included)
- All children collapsed cache: ~16 bytes per checked node
- For 10,000 expanded nodes: ~320 KB total
- For 100,000 expanded nodes: ~3.2 MB total
- Total visible nodes cache: 8 bytes
- Max depth cache: 8 bytes

**Total overhead:** < 4 MB for 100K node trace (negligible, < 0.1% of typical trace data)

**VisibleNode temporary allocation:**
- 24 bytes per visible node (u64 + 2x usize)
- For 70 visible nodes (50 + 2×10 buffer): ~1.7 KB per frame
- Allocated and dropped every frame (short-lived)

### 4.3 Cache Invalidation Cost

**Invalidation triggers:**
- Expand/collapse button click (user interaction)
- Trace file reload/replacement
- Frequency: ~1-10 times per second during active navigation

**Invalidation cost:**
- Clear HashMaps: O(1) amortized
- Next frame rebuilds cache: O(V) for visible nodes
- Acceptable because it only happens on user interaction

### 4.4 Frame Budget

**Target:** 60 FPS = 16.67ms per frame

**Frame time breakdown (after optimization):**
| Operation | Time (100K nodes) |
|-----------|------------------|
| Collect visible nodes | ~0.1ms |
| Render 50-70 tree nodes | ~2-3ms |
| Render 50-70 timeline rows | ~2-3ms |
| Event culling (70 records × 24 checks) | ~1ms |
| egui layout and input | ~2ms |
| **Total** | **~8-10ms** |

**Headroom:** 6-8ms available for other UI elements

### 4.5 Scalability

**Tested scales:**
| Trace Size | Expected FPS | Memory Overhead |
|------------|-------------|-----------------|
| 10K records | 60 FPS | ~32 KB |
| 100K records | 60 FPS | ~320 KB |
| 1M records | 60 FPS | ~3.2 MB |
| 10M records | 45-60 FPS | ~32 MB |

**Bottleneck for 10M+ records:** Cache rebuilding after expansion (1-2 seconds)

---

## 5. Testing Strategy

### 5.1 Functional Testing

**Test Case 1: Small trace (< 1K records)**
- Verify: Same visual output as before optimization
- Verify: All nodes render correctly
- Verify: Expand/collapse works
- Verify: Selection works

**Test Case 2: Medium trace (10K records)**
- Verify: Scrolling is smooth (60 FPS)
- Verify: Scroll to bottom is fast (< 1 second)
- Verify: Tree and timeline stay synchronized

**Test Case 3: Large trace (100K records)**
- Verify: Scrolling maintains 60 FPS
- Verify: Scroll to row 50,000 is fast (< 1 second)
- Verify: No visual artifacts or missing nodes

**Test Case 4: Mega trace (1M records, stress test)**
- Verify: Scrolling maintains 45-60 FPS
- Verify: Memory usage is reasonable (< 50 MB overhead)
- Verify: Application remains responsive

**Test Case 5: Expand/collapse with large trace**
- Action: Expand node with 50K children
- Verify: Cache invalidates and rebuilds
- Verify: First frame may be slow (< 100ms), subsequent frames are smooth
- Verify: Collapsed subtree is skipped correctly

**Test Case 6: Wide node with collapsed children (Critical Path)**
- Setup: Thread node with 100,000 instruction children, all collapsed
- Action: Scroll to row 50,000 (middle of children)
- Verify: Scroll completes in < 100ms (fast path optimization)
- Verify: Only ~70 visible children are added to result
- Verify: Cache correctly identifies all children as collapsed

**Test Case 7: Event marker rendering**
- Setup: Record with 10,000 events
- Verify: Only events in viewport are rendered
- Verify: Scrolling through events is smooth
- Verify: Events are sorted before binary search

**Test Case 8: Trace reload**
- Action: Load new trace file
- Verify: All caches are cleared
- Verify: expanded_nodes HashSet is cleared
- Verify: No stale data from previous trace

**Test Case 9: Edge cases**
- Empty trace: No crashes, graceful handling
- Single root with no children: Renders correctly
- All nodes collapsed: Only roots rendered
- All nodes expanded: Virtual scrolling still provides benefit
- Node with 0 children marked expanded: No issues
- Node with 1 child: Correct handling
- Deeply nested single-child chains: Correct depth calculation
- Alternating expand/collapse patterns: Cache stays consistent

### 5.2 Performance Benchmarking

**Metrics to measure:**
1. **Frame time:** Use egui's built-in performance overlay
2. **Scroll performance:** Time to scroll from row 0 to last row
3. **Cache rebuild time:** Time after expand/collapse
4. **Memory usage:** Track cache structure sizes

**Benchmarking code to add:**
```rust
#[cfg(feature = "benchmark")]
impl JetsViewerApp {
    fn benchmark_scrolling(&mut self) {
        let start = std::time::Instant::now();

        let total_nodes = self.get_total_visible_nodes();
        let step = ROW_HEIGHT * 100.0; // Scroll 100 rows at a time

        for offset in (0..total_nodes * ROW_HEIGHT as usize).step_by(step as usize) {
            let _ = self.collect_visible_nodes(offset as f32, 1000.0);
        }

        let duration = start.elapsed();
        println!("Benchmark: Scrolled {} nodes in {:?}", total_nodes, duration);
        println!("Average time per frame: {:?}", duration / (total_nodes as u32 / 100));
    }
}
```

### 5.3 Visual Regression Testing

**Manual verification checklist:**
1. Load same trace before and after optimization
2. Take screenshots at:
   - Top of trace
   - Middle of trace
   - Bottom of trace
   - With various nodes expanded
3. Verify pixel-perfect rendering match
4. Check selection highlighting works
5. Check event markers align correctly

---

## 6. Implementation Phases

### Phase 1: Core Virtual Scrolling with Wide Node Optimization (Critical Path)
**Estimated time:** 5-7 hours

**Tasks:**
1. Add constants and `TreeCache`, `VisibleNode` structures
2. Implement `collect_visible_nodes()` and `collect_nodes_in_range()` with fast/slow path
3. Implement subtree size caching methods
4. Implement `are_all_children_collapsed_cached()` for wide node optimization
5. Modify `render_tree()` to use virtual scrolling
6. Add cache invalidation to expand/collapse and trace loading
7. Test with medium trace (10K records) including wide nodes

**Success criteria:**
- Tree view maintains 60 FPS with 10K records
- Wide nodes (100K+ children) scroll smoothly
- Expand/collapse triggers proper cache invalidation
- No visual regressions

### Phase 2: Timeline Virtual Scrolling
**Estimated time:** 2-3 hours

**Tasks:**
1. Create `render_tree_node_direct()` (non-recursive)
2. Create `render_timeline_row_direct()` (non-recursive)
3. Modify `render_timeline()` to use virtual scrolling
4. Ensure tree-timeline synchronization via shared_scroll_y
5. Test synchronization with various traces

**Success criteria:**
- Timeline view maintains 60 FPS
- Tree and timeline perfectly synchronized
- Event markers render correctly

### Phase 3: Caching and Event Culling
**Estimated time:** 2-3 hours

**Tasks:**
1. Implement `get_total_visible_nodes()` with caching
2. Convert `calculate_max_visible_depth()` to cached version
3. Implement event marker culling with binary search
4. Add event sorting before binary search
5. Test with large trace (100K records)

**Success criteria:**
- No per-frame tree traversals
- Events use binary search
- Handles unsorted events gracefully

### Phase 4: Large-Scale Testing and Optimization
**Estimated time:** 2-3 hours

**Tasks:**
1. Test with 100K record trace
2. Test with 1M record trace (stress test)
3. Profile and identify any remaining bottlenecks
4. Fine-tune buffer size if needed
5. Add benchmark measurements
6. Document performance characteristics

**Success criteria:**
- 60 FPS with 100K records
- 45-60 FPS with 1M records
- Memory overhead within budget
- All edge cases handled

---

## 7. Risk Assessment

### 7.1 Technical Risks

**Risk: Scroll position desynchronization**
- **Likelihood:** Low (using proven state.offset.y approach)
- **Impact:** High (broken UI experience)
- **Mitigation:** Use `shared_scroll_y` as single source of truth; extensive testing

**Risk: Cache invalidation bugs (stale state)**
- **Likelihood:** Medium
- **Impact:** Medium (incorrect rendering until next invalidation)
- **Mitigation:** Conservative invalidation on any change; clear testing of all invalidation paths

**Risk: Events not sorted**
- **Likelihood:** Medium (trait doesn't guarantee sorting)
- **Impact:** Low (we sort defensively before binary search)
- **Mitigation:** Always sort events before binary search

**Risk: egui ScrollArea API changes**
- **Likelihood:** Low
- **Impact:** Medium (may need adjustments)
- **Mitigation:** Document egui version dependency; monitor egui updates

### 7.2 Implementation Risks

**Risk: Off-by-one errors in row indexing**
- **Likelihood:** High
- **Impact:** Low (visual glitches)
- **Mitigation:** Extensive testing; clear variable naming

**Risk: Performance regression for small traces**
- **Likelihood:** Low
- **Impact:** Low (minimal overhead)
- **Mitigation:** Benchmark small traces; optimize hot paths

**Risk: Memory leak in cache structures**
- **Likelihood:** Low (Rust manages memory)
- **Impact:** Medium (growing memory over time)
- **Mitigation:** Ensure cache cleared on trace reload; use memory profiler

---

## 8. Success Criteria

**Performance:**
- ✅ Scrolling maintains 60 FPS with 100K+ records
- ✅ Scroll to bottom completes in < 1 second
- ✅ Frame time < 16ms for typical viewport
- ✅ Memory overhead < 4 MB for 100K records

**Functional:**
- ✅ Virtual scrolling renders only ~70 nodes per frame
- ✅ Subtree skipping reduces iterations by 1000x+
- ✅ Cache eliminates per-frame tree traversals
- ✅ Event culling uses binary search
- ✅ Tree and timeline stay synchronized
- ✅ Trace reload clears all caches

**Quality:**
- ✅ No visual regressions
- ✅ Expand/collapse functionality preserved
- ✅ Selection behavior unchanged
- ✅ No crashes with mega traces (1M+ records)
- ✅ All edge cases handled gracefully

---

## 9. Future Enhancements (Out of Scope)

### 9.1 Adaptive Buffer Size
Adjust buffer based on scroll velocity for optimal smoothness vs. performance.

### 9.2 Predictive Rendering
Pre-render nodes in anticipated scroll direction based on velocity.

### 9.3 Level-of-Detail Rendering
Simplify rendering for nodes at viewport edges.

### 9.4 Incremental Cache Rebuilding
Only invalidate affected subtrees instead of entire cache.

### 9.5 GPU-Accelerated Rendering
Offload timeline bar rendering to GPU shaders.

---

## 10. Appendix

### 10.1 Related Features

**Dependencies:**
- Feature #0005: Async file loading (benefits from virtual scrolling)
- Feature #0001: Timeline Gantt chart (shares timeline optimization)

**Enables:**
- Multi-million record trace support
- Real-time trace streaming
- Interactive filtering with large datasets

### 10.2 Algorithm Complexity Reference

**Current Implementation:**
```
render_tree(): O(N) where N = total visible nodes
render_timeline(): O(N * E) where E = events per node
scroll_to_row(R): O(R) where R = target row
count_visible_nodes(): O(N) per frame
```

**Optimized Implementation:**
```
render_tree(): O(V + log N) where V = viewport nodes (~70)
render_timeline(): O(V * (log E + Ve)) where Ve = visible events
scroll_to_row(R): O(V + log R)
count_visible_nodes(): O(1) cached
```

### 10.3 egui ScrollArea Key Points

**Critical APIs:**
- `scroll_area.state.offset.y` - Current scroll position (use this, not delta!)
- `vertical_scroll_offset(y)` - Set scroll programmatically
- `ui.available_height()` - Get viewport height
- `ui.add_space(height)` - Add virtual spacing

**Important:** Always use `state.offset.y` for scroll position, never `input().scroll_delta`.

---

**Plan Status:** Ready for Implementation
**Estimated Implementation Time:** 12-18 hours
**Lines of Code Changed:** ~400 lines in 1 file
**Expected Performance Gain:** 12-100x speedup for large traces
**Key Innovation:** Fast path for wide nodes with collapsed children (O(V) instead of O(W))