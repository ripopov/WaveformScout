//! Caching logic for tree traversal optimizations.

use std::collections::HashMap;

/// Cache for expensive tree calculations.
///
/// This cache stores computed values for tree traversal operations to avoid
/// redundant recursive calculations. The cache is invalidated whenever the
/// expansion state changes or when a new trace is loaded.
pub struct TreeCache {
    /// Maps record_id -> total visible descendants (including self).
    /// Only stores entries for expanded nodes.
    pub subtree_sizes: HashMap<u64, usize>,

    /// Maps record_id -> true if all direct children are collapsed (leaf optimization).
    /// Enables O(1) skipping for wide nodes with many leaf children.
    pub all_children_collapsed: HashMap<u64, bool>,

    /// Cached total visible node count.
    pub total_visible_nodes: Option<usize>,

    /// Cached maximum visible depth.
    pub max_visible_depth: Option<usize>,

    /// Sequence number for cache invalidation.
    /// Incremented whenever expanded_nodes changes or trace reloads.
    pub expansion_seq: u64,

    /// Cached viewport range for filtered tree (start_clk, end_clk).
    /// Used to determine if filtered cache is still valid.
    pub filtered_viewport_range: Option<(i64, i64)>,

    /// Cached total filtered node count for current viewport.
    pub filtered_node_count: Option<usize>,
}

impl TreeCache {
    /// Creates a new empty cache.
    pub fn new() -> Self {
        Self {
            subtree_sizes: HashMap::new(),
            all_children_collapsed: HashMap::new(),
            total_visible_nodes: None,
            max_visible_depth: None,
            expansion_seq: 0,
            filtered_viewport_range: None,
            filtered_node_count: None,
        }
    }

    /// Invalidates all cached data.
    ///
    /// This should be called whenever:
    /// - A node is expanded or collapsed
    /// - A new trace is loaded
    /// - The tree structure changes
    pub fn invalidate(&mut self) {
        self.subtree_sizes.clear();
        self.all_children_collapsed.clear();
        self.total_visible_nodes = None;
        self.max_visible_depth = None;
        self.expansion_seq += 1;
        // Also invalidate filtered cache
        self.invalidate_filtered_cache();
    }

    /// Checks if filtered cache is valid for given viewport range.
    ///
    /// # Arguments
    /// * `start_clk` - Start of viewport range
    /// * `end_clk` - End of viewport range
    ///
    /// # Returns
    /// `true` if cached filtered tree matches the given range, `false` otherwise
    pub fn is_filtered_cache_valid(&self, start_clk: i64, end_clk: i64) -> bool {
        match self.filtered_viewport_range {
            Some((cached_start, cached_end)) => {
                cached_start == start_clk && cached_end == end_clk
            }
            None => false,
        }
    }

    /// Invalidates only the filtered tree cache (preserves unfiltered cache).
    ///
    /// This should be called when:
    /// - Viewport range changes (start_clk or end_clk)
    /// - Filter is toggled on/off
    pub fn invalidate_filtered_cache(&mut self) {
        self.filtered_viewport_range = None;
        self.filtered_node_count = None;
    }
}

impl Default for TreeCache {
    fn default() -> Self {
        Self::new()
    }
}
