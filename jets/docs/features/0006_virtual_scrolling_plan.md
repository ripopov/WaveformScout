# Feature Plan: Virtual Scrolling Optimization for Large Traces

**Feature ID:** 0006
**Feature Name:** virtual_scrolling
**Status:** Planning
**Created:** 2025-10-11

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

**SHOULD Requirements:**
1. SHOULD include small buffer (±10 rows) above/below viewport for smooth scrolling
2. SHOULD apply event marker culling to only render events within time viewport
3. SHOULD use binary search for finding first visible event in sorted event lists
4. SHOULD minimize memory overhead (< 100KB for 10K expanded nodes)

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

**Out of Scope:**
- Lazy loading from disk (all data must be in memory)
- Progressive rendering during file load
- Level-of-detail rendering (simplified view at high zoom out)
- GPU-accelerated rendering

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
```
render_tree(ui) {
    for root_id in trace.root_ids() {
        render_tree_node(ui, root_id, 0, expand_width);
    }
}
```

**Recursive node rendering (lines 598-782):**
```
render_tree_node(ui, record_id, depth, expand_width) {
    // 1. Allocate space (22px row)
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
```
render_timeline(ui, ctx) {
    ScrollArea::vertical().show(ui, |ui| {
        for root_id in root_ids {
            self.render_timeline_row(ui, root_id, 0, ctx);
        }
    });
}
```

**Recursive timeline row rendering (lines 1250-1400):**
```
render_timeline_row(ui, record_id, depth, ctx) {
    // 1. Allocate space (22px row)
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

// Update shared scroll position
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
- Tree view controls scroll position (`scroll_area.state.offset.y`)
- Timeline view follows tree scroll offset
- Scroll offset is in pixels, not row index

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
- Events are returned as Vec (should be sorted by clk, but not guaranteed)
- No built-in support for subtree size queries

---

## 3. Implementation Planning

### 3.1 Data Structures

**File:** `jets/rjets/src/jets-gui.rs`

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
    /// Incremented whenever expanded_nodes changes
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

**Algorithm:**
```
FUNCTION collect_visible_nodes(
    viewport_scroll_offset: f32,
    viewport_height: f32,
    row_height: f32
) -> Vec<VisibleNode>:

    # 1. Calculate visible row range with buffer
    LET start_row = (viewport_scroll_offset / row_height).floor() as usize
    LET visible_rows = (viewport_height / row_height).ceil() as usize
    LET buffer_rows = 10  # Buffer above/below

    LET first_visible_row = start_row.saturating_sub(buffer_rows)
    LET last_visible_row = start_row + visible_rows + buffer_rows

    # 2. Collect nodes in visible range using subtree skipping
    LET mut result = Vec::new()
    LET mut current_row = 0

    FOR root_id IN self.trace_data.root_ids():
        collect_nodes_in_range(
            root_id,
            0,  # depth
            &mut current_row,
            first_visible_row,
            last_visible_row,
            &mut result
        )

    RETURN result

FUNCTION collect_nodes_in_range(
    record_id: u64,
    depth: usize,
    current_row: &mut usize,
    first_visible: usize,
    last_visible: usize,
    result: &mut Vec<VisibleNode>
):
    # Check if this node is in visible range
    IF *current_row >= first_visible AND *current_row <= last_visible:
        result.push(VisibleNode {
            record_id,
            depth,
            row_index: *current_row,
        })

    LET node_row = *current_row
    *current_row += 1

    # Check if children should be processed
    IF self.expanded_nodes.contains(&record_id):
        # Check if subtree might overlap with visible range
        IF node_row <= last_visible:
            LET children = self.trace_data.get_record(record_id).children()

            # FAST PATH: All children collapsed (common case for wide nodes)
            IF self.are_all_children_collapsed_cached(record_id):
                # Each child takes exactly 1 row - jump directly to visible range
                LET num_children = children.len()
                LET first_child_idx = first_visible.saturating_sub(*current_row).min(num_children)
                LET last_child_idx = (last_visible - *current_row + 1).min(num_children)

                # Add only visible children in O(V) time
                FOR i IN first_child_idx..last_child_idx:
                    result.push(VisibleNode {
                        record_id: children[i].id(),
                        depth: depth + 1,
                        row_index: *current_row + i,
                    })

                # Skip all children in O(1)
                *current_row += num_children
            ELSE:
                # SLOW PATH: Some children expanded, check each with subtree skipping
                FOR child IN children:
                    # Try to skip subtree if entirely before visible range
                    IF *current_row + self.get_subtree_size(child.id()) < first_visible:
                        *current_row += self.get_subtree_size(child.id())
                        CONTINUE  # Skip entire subtree

                    # Subtree might be visible, recurse
                    collect_nodes_in_range(
                        child.id(),
                        depth + 1,
                        current_row,
                        first_visible,
                        last_visible,
                        result
                    )

                    # Early exit if we've passed visible range
                    IF *current_row > last_visible:
                        BREAK
```

**Performance:**
- **Best case** (all children collapsed): O(V) where V = visible nodes (~50)
- **Average case** (mixed expansion): O(V + S) where S = skipped children
- **Worst case** (wide node, some expanded): O(W) where W = children before visible range
- **Critical optimization:** Thread with 100K leaf children, scroll to row 50,000:
  - Without optimization: iterate 50,000 times = 50ms+ (bottleneck!)
  - With optimization: O(50) to add visible nodes = <0.1ms ✅

#### Algorithm 2: Subtree Size Calculation and Caching

**New method:** `calculate_subtree_size()` (add after `collect_nodes_in_range`)

**Purpose:** Calculate and cache the total visible descendants for a node

**Algorithm:**
```
FUNCTION get_subtree_size(record_id: u64) -> usize:
    # Check cache first
    IF self.tree_cache.subtree_sizes.contains_key(&record_id):
        RETURN self.tree_cache.subtree_sizes[&record_id]

    # Calculate and cache
    LET size = self.calculate_subtree_size(record_id)
    self.tree_cache.subtree_sizes.insert(record_id, size)
    RETURN size

FUNCTION calculate_subtree_size(record_id: u64) -> usize:
    LET mut total = 1  # Count self

    IF self.expanded_nodes.contains(&record_id):
        IF LET Some(record) = self.trace_data.get_record(record_id):
            FOR child IN record.children():
                total += self.calculate_subtree_size(child.id())

    RETURN total
```

**Cache invalidation:**
```
FUNCTION toggle_expansion(record_id: u64):
    IF self.expanded_nodes.contains(&record_id):
        self.expanded_nodes.remove(&record_id)
    ELSE:
        self.expanded_nodes.insert(record_id)

    # Invalidate cache whenever expansion state changes
    self.tree_cache.invalidate()
```

**Performance:**
- First calculation: O(N) for entire tree
- Subsequent lookups: O(1)
- Memory: 8 bytes per expanded node (~80KB for 10K nodes)

#### Algorithm 2b: All Children Collapsed Check (Critical for Wide Nodes)

**New method:** `are_all_children_collapsed_cached()` (add after `calculate_subtree_size`)

**Purpose:** Determine if all direct children of a node are collapsed (enabling O(1) skip for wide nodes)

**Algorithm:**
```
FUNCTION are_all_children_collapsed_cached(parent_id: u64) -> bool:
    # Check cache first
    IF self.tree_cache.all_children_collapsed.contains_key(&parent_id):
        RETURN self.tree_cache.all_children_collapsed[&parent_id]

    # Calculate: check if any child is in expanded_nodes
    LET result = IF LET Some(record) = self.trace_data.get_record(parent_id):
        record.children().iter().all(|child| !self.expanded_nodes.contains(&child.id()))
    ELSE:
        false  # No children = not applicable

    # Cache and return
    self.tree_cache.all_children_collapsed.insert(parent_id, result)
    RETURN result
```

**Cache invalidation:**
- Same trigger as other caches: any expand/collapse action calls `tree_cache.invalidate()`
- Conservative invalidation ensures correctness

**Performance:**
- First check: O(C) where C = number of children
- Subsequent checks: O(1) from cache
- Memory: 9 bytes per cached entry (u64 + bool + HashMap overhead)
- **Impact:** Enables O(V) collection for wide nodes instead of O(W) iteration

**Example: Thread with 100K instruction children**
- Without cache: check 100K children every frame during scroll = 1ms+
- With cache: single O(100K) calculation, then O(1) lookups = <0.001ms per frame

#### Algorithm 3: Visible Node Count Caching

**Modify method:** `calculate_total_visible_nodes()` (new method)

**Purpose:** Cache the total count of visible nodes

**Algorithm:**
```
FUNCTION get_total_visible_nodes() -> usize:
    # Check cache
    IF self.tree_cache.total_visible_nodes.is_some():
        RETURN self.tree_cache.total_visible_nodes.unwrap()

    # Calculate
    LET mut total = 0
    FOR root_id IN self.trace_data.root_ids():
        total += self.get_subtree_size(root_id)

    # Cache and return
    self.tree_cache.total_visible_nodes = Some(total)
    RETURN total
```

**Usage:**
- Replace current tree traversal for scrollbar sizing
- Called once per frame, returns cached value immediately after first frame

#### Algorithm 4: Max Depth Caching

**Modify method:** `calculate_max_visible_depth()` (lines 314-326)

**Purpose:** Cache the maximum visible depth calculation

**Algorithm:**
```
FUNCTION get_max_visible_depth() -> usize:
    # Check cache
    IF self.tree_cache.max_visible_depth.is_some():
        RETURN self.tree_cache.max_visible_depth.unwrap()

    # Calculate (existing logic)
    LET max_depth = 0
    FOR root_id IN self.trace_data.root_ids():
        max_depth = max(max_depth, self.calculate_node_depth(root_id, 0))

    # Cache and return
    self.tree_cache.max_visible_depth = Some(max_depth)
    RETURN max_depth
```

**Performance:**
- First call: O(V) where V = visible nodes
- Subsequent calls: O(1)

#### Algorithm 5: Event Marker Culling with Binary Search

**Modify method:** `render_timeline_row()` (lines 1343-1390)

**Purpose:** Use binary search to find first visible event, then iterate until past viewport

**Current logic:**
```rust
// Current: Linear scan with viewport check
for event in record.events() {
    let event_clk = event.clk();
    if event_clk >= self.viewport_start_clk && event_clk <= self.viewport_end_clk {
        // Render event marker
    }
}
```

**New logic:**
```rust
// New: Binary search + early exit
let events = record.events();

// Find first event in viewport using binary search
let first_visible_idx = events.binary_search_by(|e| {
    if e.clk() < self.viewport_start_clk {
        std::cmp::Ordering::Less
    } else {
        std::cmp::Ordering::Greater
    }
}).unwrap_or_else(|idx| idx);

// Iterate from first visible until past viewport
for event in &events[first_visible_idx..] {
    let event_clk = event.clk();

    if event_clk > self.viewport_end_clk {
        break;  // Early exit
    }

    // Render event marker (existing code)
}
```

**Performance:**
- Current: O(E) where E = total events per record
- New: O(log E + V) where V = visible events
- For 10,000 events with 10 visible: 10,000 → 24 iterations

### 3.3 Rendering Integration

#### Modify `render_tree()` method (lines 492-530)

**Current:** Renders all nodes unconditionally
**New:** Collect visible nodes first, then render with spacing

**Changes:**
```rust
fn render_tree(&mut self, ui: &mut egui::Ui) {
    // ... (header rendering unchanged) ...

    let row_height = 22.0;

    let scroll_area = ScrollArea::vertical()
        .id_salt("tree_scroll_area")
        .show(ui, |ui| {
            // NEW: Get viewport dimensions
            let viewport_scroll_offset = ui.ctx().input(|i| {
                i.scroll_delta.y  // or use scroll_area.state.offset.y
            });
            let viewport_height = ui.available_height();

            // NEW: Collect only visible nodes
            let visible_nodes = self.collect_visible_nodes(
                self.shared_scroll_y,
                viewport_height,
                row_height
            );

            if visible_nodes.is_empty() {
                return;
            }

            // NEW: Add spacing above for scrollbar correctness
            let first_row = visible_nodes[0].row_index;
            if first_row > 0 {
                let spacing_above = first_row as f32 * row_height;
                ui.add_space(spacing_above);
            }

            // NEW: Render only visible nodes
            for visible_node in &visible_nodes {
                self.render_tree_node_direct(
                    ui,
                    visible_node.record_id,
                    visible_node.depth,
                    expand_width
                );
            }

            // NEW: Add spacing below for scrollbar correctness
            let last_row = visible_nodes.last().unwrap().row_index;
            let total_rows = self.get_total_visible_nodes();
            if last_row + 1 < total_rows {
                let spacing_below = (total_rows - last_row - 1) as f32 * row_height;
                ui.add_space(spacing_below);
            }
        });

    self.shared_scroll_y = scroll_area.state.offset.y;
}
```

**New method:** `render_tree_node_direct()` (replaces recursive `render_tree_node`)

**Purpose:** Render a single node without recursion (children handled by caller)

**Changes:**
- Remove recursive child rendering logic (lines 777-781)
- Keep all visual rendering logic (expand button, columns, selection)
- Depth passed as parameter instead of calculated recursively

#### Modify `render_timeline()` method (lines 1138-1152)

**Changes:** Apply same virtual scrolling pattern as tree view

**Integration:**
```rust
fn render_timeline(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
    // ... (header and viewport input handling unchanged) ...

    let row_height = 22.0;

    let scroll_area = ScrollArea::vertical()
        .id_salt("timeline_scroll_area")
        .scroll_bar_visibility(ScrollBarVisibility::AlwaysHidden)
        .vertical_scroll_offset(self.shared_scroll_y)
        .show(ui, |ui| {
            let viewport_height = ui.available_height();

            // NEW: Reuse visible nodes from tree view (single source of truth)
            let visible_nodes = self.collect_visible_nodes(
                self.shared_scroll_y,
                viewport_height,
                row_height
            );

            // NEW: Add spacing above
            if let Some(first_node) = visible_nodes.first() {
                if first_node.row_index > 0 {
                    let spacing_above = first_node.row_index as f32 * row_height;
                    ui.add_space(spacing_above);
                }
            }

            // NEW: Render only visible timeline rows
            for visible_node in &visible_nodes {
                self.render_timeline_row_direct(
                    ui,
                    visible_node.record_id,
                    ctx
                );
            }

            // NEW: Add spacing below
            if let Some(last_node) = visible_nodes.last() {
                let total_rows = self.get_total_visible_nodes();
                if last_node.row_index + 1 < total_rows {
                    let spacing_below = (total_rows - last_node.row_index - 1) as f32 * row_height;
                    ui.add_space(spacing_below);
                }
            }
        });
}
```

**New method:** `render_timeline_row_direct()` (replaces recursive `render_timeline_row`)

**Changes:**
- Remove recursive child rendering logic (lines 1393-1399)
- Apply event marker culling with binary search (lines 1343-1390)
- Keep all visual rendering logic (bars, event circles)

### 3.4 File-by-File Change Summary

#### `jets/rjets/src/jets-gui.rs`

**Structs to add:**
- `TreeCache` struct (~25 lines)
- `VisibleNode` struct (~5 lines)

**Modifications to `JetsViewerApp`:**
- Add field: `tree_cache: TreeCache` (~1 line)
- Update `Default` impl initialization (~1 line)
- Update `new()` method initialization (~1 line)

**Methods to add:**
- `collect_visible_nodes()` (~50 lines)
- `collect_nodes_in_range()` with fast/slow path (~55 lines)
- `get_subtree_size()` (~10 lines)
- `calculate_subtree_size()` (~15 lines)
- `are_all_children_collapsed_cached()` (~15 lines)
- `get_total_visible_nodes()` (~12 lines)
- `render_tree_node_direct()` (~80 lines, non-recursive version)
- `render_timeline_row_direct()` (~70 lines, non-recursive version)

**Methods to modify:**
- `render_tree()`: Replace with virtual scrolling logic (~40 lines changed)
- `render_timeline()`: Replace with virtual scrolling logic (~40 lines changed)
- `calculate_max_visible_depth()`: Add caching (~5 lines added)
- Expand/collapse button handler: Add cache invalidation (~1 line added)

**Methods to keep unchanged:**
- `render_table_header()` - no changes
- `render_details()` - no changes
- `render_timeline_header()` - no changes
- `render_time_axis()` - no changes

**Total:** ~370 lines modified/added across 1 file

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
- Subtree size cache: 16 bytes per entry (u64 key + usize value + HashMap overhead)
- All children collapsed cache: 9 bytes per entry (u64 key + bool value + HashMap overhead)
- For 10,000 expanded nodes: ~250 KB (both caches combined)
- For 100,000 expanded nodes: ~2.5 MB (both caches combined)
- Total visible nodes cache: 8 bytes (usize)
- Max depth cache: 8 bytes (usize)

**Total overhead:** < 3 MB for 100K node trace (negligible, < 0.1% of typical trace data)

**VisibleNode temporary allocation:**
- 24 bytes per visible node (u64 + 2x usize)
- For 50 visible nodes: ~1.2 KB per frame
- Allocated and dropped every frame (short-lived)

### 4.3 Cache Invalidation Cost

**Invalidation triggers:**
- Expand/collapse button click (user interaction)
- Frequency: ~1-10 times per second during active navigation

**Invalidation cost:**
- Clear HashMap: O(1) (drops all entries)
- Clear cached values: O(1) (set to None)
- Next frame rebuilds cache: O(V) for visible nodes (~50ms for 100K nodes)

**Mitigation:** Invalidation only happens on user interaction, not every frame

### 4.4 Frame Budget

**Target:** 60 FPS = 16.67ms per frame

**Frame time breakdown (after optimization):**
| Operation | Time (100K nodes) |
|-----------|------------------|
| Collect visible nodes | ~0.1ms |
| Render 50 tree nodes | ~2ms |
| Render 50 timeline rows | ~2ms |
| Event culling (50 records × 24 checks) | ~0.5ms |
| egui layout and input | ~2ms |
| **Total** | **~6.6ms** |

**Headroom:** 10ms available for other UI elements (header, details panel)

### 4.5 Scalability

**Tested scales:**
| Trace Size | Expected FPS | Memory Overhead |
|------------|-------------|-----------------|
| 10K records | 60 FPS | ~16 KB |
| 100K records | 60 FPS | ~160 KB |
| 1M records | 60 FPS | ~1.6 MB |
| 10M records | 45-60 FPS | ~16 MB |

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
- Verify: Only ~50 visible children are added to result
- Verify: Cache correctly identifies all children as collapsed
- **Expected:** O(50) collection time instead of O(50,000) iteration

**Test Case 7: Event marker rendering**
- Setup: Record with 10,000 events
- Verify: Only events in viewport are rendered
- Verify: Scrolling through events is smooth
- Verify: Binary search finds correct first event

### 5.2 Performance Benchmarking

**Metrics to measure:**
1. **Frame time:** Measure min/avg/max frame time during scrolling
2. **Scroll to bottom time:** Time to scroll from row 0 to last row
3. **Cache rebuild time:** Time to rebuild cache after expansion
4. **Memory usage:** Heap allocation for cache structures

**Tools:**
- egui built-in performance overlay
- `std::time::Instant` for timing measurements
- Memory profiler (valgrind/heaptrack on Linux)

**Benchmarking script:**
```rust
// Add to jets-gui.rs for benchmarking
#[cfg(feature = "benchmark")]
fn benchmark_scrolling(&self) {
    let start = std::time::Instant::now();

    // Simulate scrolling through entire tree
    let total_nodes = self.get_total_visible_nodes();
    for row in 0..total_nodes {
        let scroll_offset = row as f32 * 22.0;
        let _ = self.collect_visible_nodes(scroll_offset, 800.0, 22.0);
    }

    let duration = start.elapsed();
    println!("Scroll through {} nodes: {:?}", total_nodes, duration);
}
```

### 5.3 Visual Regression Testing

**Verify no visual changes:**
1. Load same trace before and after optimization
2. Take screenshots at various scroll positions
3. Compare pixel-by-pixel (should be identical)
4. Check expand/collapse animations
5. Check selection highlighting
6. Check event marker positions

**Test scenarios:**
- Scroll to top
- Scroll to middle
- Scroll to bottom
- Expand/collapse nodes at various depths
- Select records at various scroll positions

### 5.4 Edge Cases

**Test Case: Empty trace**
- Verify: No crashes, graceful handling

**Test Case: Single root node with no children**
- Verify: Renders correctly, no virtual scrolling overhead

**Test Case: Very deep tree (depth > 100)**
- Verify: Max depth calculation handles deep hierarchies
- Verify: Horizontal scrolling works (column width)

**Test Case: All nodes collapsed**
- Verify: Only root nodes rendered
- Verify: Subtree skipping is effective

**Test Case: All nodes expanded**
- Verify: Virtual scrolling still provides benefit
- Verify: Cache handles large expansion state

---

## 6. Implementation Phases

### Phase 1: Core Virtual Scrolling with Wide Node Optimization (Critical Path)
**Estimated time:** 5-7 hours

**Tasks:**
1. Add `TreeCache` and `VisibleNode` structures (including `all_children_collapsed` cache)
2. Implement `collect_visible_nodes()` and `collect_nodes_in_range()` with fast/slow path
3. Implement `get_subtree_size()` and `calculate_subtree_size()`
4. Implement `are_all_children_collapsed_cached()` for wide node optimization
5. Modify `render_tree()` to use virtual scrolling
6. Add cache invalidation to expand/collapse handler
7. Test with medium trace (10K records) including wide nodes (threads with many children)

**Success criteria:**
- Tree view maintains 60 FPS with 10K records
- Wide nodes (100K+ children) scroll smoothly with fast path optimization
- Expand/collapse still works and triggers cache invalidation
- No visual regressions

### Phase 2: Timeline Virtual Scrolling
**Estimated time:** 2-3 hours

**Tasks:**
1. Create `render_tree_node_direct()` (non-recursive)
2. Create `render_timeline_row_direct()` (non-recursive)
3. Modify `render_timeline()` to use virtual scrolling
4. Ensure tree-timeline synchronization
5. Test with medium trace (10K records)

**Success criteria:**
- Timeline view maintains 60 FPS with 10K records
- Tree and timeline stay synchronized
- Event markers render correctly

### Phase 3: Caching and Event Culling
**Estimated time:** 2-3 hours

**Tasks:**
1. Implement `get_total_visible_nodes()` with caching
2. Modify `calculate_max_visible_depth()` to use cache
3. Implement event marker culling with binary search
4. Test cache invalidation logic
5. Test with large trace (100K records)

**Success criteria:**
- Visible node count cached (no per-frame traversal)
- Max depth cached (no per-frame traversal)
- Event markers use binary search (log complexity)

### Phase 4: Large-Scale Testing and Optimization
**Estimated time:** 2-3 hours

**Tasks:**
1. Test with 100K record trace
2. Test with 1M record trace (stress test)
3. Profile performance and identify bottlenecks
4. Fine-tune buffer size and cache strategies
5. Document performance characteristics

**Success criteria:**
- 60 FPS with 100K records
- 45-60 FPS with 1M records
- Memory overhead < 2 MB for 100K records

---

## 7. Risk Assessment

### 7.1 Technical Risks

**Risk: Scroll position desynchronization**
- **Likelihood:** Medium
- **Impact:** High (broken UI experience)
- **Mitigation:** Use `shared_scroll_y` as single source of truth; test extensively

**Risk: Cache invalidation bugs (stale state)**
- **Likelihood:** Medium
- **Impact:** Medium (incorrect rendering until next invalidation)
- **Mitigation:** Conservative invalidation (invalidate on any expansion change); thorough testing

**Risk: egui ScrollArea API limitations**
- **Likelihood:** Low
- **Impact:** High (may need workaround)
- **Mitigation:** Research egui scroll API before implementation; fallback to manual scroll rendering

**Risk: Performance regression for small traces**
- **Likelihood:** Low
- **Impact:** Low (small overhead for < 1K nodes)
- **Mitigation:** Benchmark small traces; optimize for common case

### 7.2 Implementation Risks

**Risk: Complexity of recursive → iterative conversion**
- **Likelihood:** Medium
- **Impact:** Medium (longer implementation time)
- **Mitigation:** Keep recursive logic for reference; test incrementally

**Risk: Off-by-one errors in row indexing**
- **Likelihood:** High
- **Impact:** Low (visual glitches)
- **Mitigation:** Extensive testing with various scroll positions; assertions

**Risk: Memory leak in cache structures**
- **Likelihood:** Low
- **Impact:** Medium (growing memory usage over time)
- **Mitigation:** Profile memory usage; ensure cache is cleared on trace reload

---

## 8. Success Criteria

**Performance:**
- ✅ Scrolling maintains 60 FPS with 100K+ records
- ✅ Scroll to bottom completes in < 1 second (vs. 30+ seconds)
- ✅ Frame time < 16ms for 100K records (vs. 100-200ms)
- ✅ Memory overhead < 2 MB for 100K records

**Functional:**
- ✅ Virtual scrolling renders only visible nodes (~50 per frame)
- ✅ Subtree skipping reduces iterations by 1000x
- ✅ Cache eliminates per-frame tree traversals
- ✅ Event culling uses binary search (400x speedup)
- ✅ Tree and timeline stay perfectly synchronized

**Quality:**
- ✅ No visual regressions (pixel-perfect output)
- ✅ Expand/collapse functionality preserved
- ✅ Selection and interaction behavior unchanged
- ✅ No crashes or panics with mega traces (1M+ records)

---

## 9. Future Enhancements (Out of Scope)

### 9.1 Adaptive Buffer Size
**Enhancement:** Adjust buffer size based on scroll velocity
- Fast scrolling: larger buffer (±20 rows) for smoother rendering
- Slow scrolling: smaller buffer (±5 rows) for better cache locality

### 9.2 Predictive Rendering
**Enhancement:** Pre-render nodes in anticipated scroll direction
- Track scroll direction and velocity
- Pre-collect nodes ahead of current position
- Reduce first-frame latency when scrolling fast

### 9.3 Level-of-Detail Rendering
**Enhancement:** Simplify rendering for nodes far from viewport center
- Nodes near edges: simplified rendering (no events, no tooltips)
- Nodes in center: full detail rendering
- Reduces GPU draw calls by 50%

### 9.4 Incremental Cache Rebuilding
**Enhancement:** Only invalidate affected subtrees, not entire cache
- When expanding node X: only invalidate ancestors of X
- Preserves cache for unrelated subtrees
- Reduces cache rebuild time from 50ms to < 5ms

### 9.5 GPU-Accelerated Rendering
**Enhancement:** Use GPU for timeline bar rendering
- Offload rectangle drawing to GPU shaders
- Batch all timeline bars into single draw call
- Potential 10x speedup for timeline rendering

---

## 10. Appendix

### 10.1 Related Features

**Dependencies:**
- Feature #0005: Async file loading (benefits from virtual scrolling for large traces)
- Feature #0001: Timeline Gantt chart (timeline rendering optimization)

**Enables future work:**
- Multi-million record trace support
- Real-time trace streaming visualization
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
render_tree(): O(V + log N) where V = viewport nodes (~50)
render_timeline(): O(V * (log E + Ve)) where Ve = visible events
scroll_to_row(R): O(V + log R)
count_visible_nodes(): O(1) cached
```

### 10.3 egui ScrollArea API Notes

**Key APIs:**
- `ScrollArea::vertical().show(ui, content_fn)` - Creates scrollable area
- `scroll_area.state.offset.y` - Current scroll offset in pixels
- `vertical_scroll_offset(y)` - Set scroll position programmatically
- `ui.available_height()` - Viewport height
- `ui.add_space(height)` - Add spacing (used for virtual scrolling padding)

**Limitations:**
- Scroll position is in pixels, not rows (requires conversion)
- No built-in "window into list" API (must implement manually)
- Scrollbar sizing requires correct total height (spacing above + content + spacing below)

### 10.4 Benchmarking Results (Expected)

**Test Environment:** Ryzen 5800X, 32GB RAM, Linux

| Trace Size | Current FPS | Optimized FPS | Speedup |
|------------|-------------|---------------|---------|
| 1K nodes | 60 FPS | 60 FPS | 1x |
| 10K nodes | 30 FPS | 60 FPS | 2x |
| 100K nodes | 5 FPS | 60 FPS | 12x |
| 1M nodes | 0.5 FPS | 50 FPS | 100x |

---

**Plan Status:** Ready for Implementation
**Estimated Implementation Time:** 11-16 hours
**Lines of Code Changed:** ~370 lines in 1 file
**Expected Performance Gain:** 12-100x speedup for large traces
**Key Optimization:** O(V) collection for wide nodes with collapsed children (critical for thread traces)
