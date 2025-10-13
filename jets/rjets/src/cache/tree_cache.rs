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
    }
}

impl Default for TreeCache {
    fn default() -> Self {
        Self::new()
    }
}
