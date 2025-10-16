//! Tree traversal and computation operations.
//!
//! This module contains pure functions for tree operations like:
//! - Calculating subtree sizes
//! - Computing node depths
//! - Determining visible node counts
//!
//! These functions are extracted from the main application to enable
//! independent testing and clearer separation of domain logic.

use crate::cache::TreeCache;
use crate::domain::visibility::{self, VisibilityStrategy};
use rjets::TraceData;
use std::collections::HashSet;

/// Gets the total number of visible nodes (uses cache if available).
///
/// # Arguments
/// * `trace` - The trace data containing the tree structure
/// * `expanded_nodes` - Set of IDs for expanded nodes
/// * `cache` - Tree cache for memoizing results
pub fn get_total_visible_nodes(
    trace: &dyn TraceData,
    expanded_nodes: &HashSet<u64>,
    cache: &mut TreeCache,
) -> usize {
    if let Some(total) = cache.total_visible_nodes {
        return total;
    }

    let mut total = 0;
    for root_id in trace.root_ids() {
        total += get_subtree_size(root_id, trace, expanded_nodes, cache);
    }

    cache.total_visible_nodes = Some(total);
    total
}

/// Gets the maximum visible depth (uses cache if available).
///
/// # Arguments
/// * `trace` - The trace data containing the tree structure
/// * `expanded_nodes` - Set of IDs for expanded nodes
/// * `cache` - Tree cache for memoizing results
pub fn get_max_visible_depth(
    trace: &dyn TraceData,
    expanded_nodes: &HashSet<u64>,
    cache: &mut TreeCache,
) -> usize {
    if let Some(depth) = cache.max_visible_depth {
        return depth;
    }

    let depth = calculate_max_visible_depth(trace, expanded_nodes);
    cache.max_visible_depth = Some(depth);
    depth
}

/// Calculates the maximum visible depth in the tree, accounting for expanded nodes.
///
/// # Arguments
/// * `trace` - The trace data containing the tree structure
/// * `expanded_nodes` - Set of IDs for expanded nodes
pub fn calculate_max_visible_depth(
    trace: &dyn TraceData,
    expanded_nodes: &HashSet<u64>,
) -> usize {
    let mut max_depth = 0;
    for root_id in trace.root_ids() {
        let depth = calculate_node_depth(root_id, 0, trace, expanded_nodes);
        max_depth = max_depth.max(depth);
    }
    max_depth
}

/// Recursively calculates the depth of a node and its visible children.
///
/// # Arguments
/// * `record_id` - The ID of the record to calculate depth for
/// * `current_depth` - The current depth in the recursion
/// * `trace` - The trace data containing the tree structure
/// * `expanded_nodes` - Set of IDs for expanded nodes
pub fn calculate_node_depth(
    record_id: u64,
    current_depth: usize,
    trace: &dyn TraceData,
    expanded_nodes: &HashSet<u64>,
) -> usize {
    let mut max_depth = current_depth;

    if expanded_nodes.contains(&record_id) {
        if let Some(record) = trace.get_record(record_id) {
            for child in record.children() {
                let child_depth = calculate_node_depth(
                    child.id(),
                    current_depth + 1,
                    trace,
                    expanded_nodes,
                );
                max_depth = max_depth.max(child_depth);
            }
        }
    }

    max_depth
}

/// Gets the subtree size from cache or calculates it.
///
/// # Arguments
/// * `record_id` - The ID of the record to get subtree size for
/// * `trace` - The trace data containing the tree structure
/// * `expanded_nodes` - Set of IDs for expanded nodes
/// * `cache` - Tree cache for memoizing results
pub fn get_subtree_size(
    record_id: u64,
    trace: &dyn TraceData,
    expanded_nodes: &HashSet<u64>,
    cache: &mut TreeCache,
) -> usize {
    if let Some(&size) = cache.subtree_sizes.get(&record_id) {
        return size;
    }

    let size = calculate_subtree_size(record_id, trace, expanded_nodes, &cache.subtree_sizes);
    cache.subtree_sizes.insert(record_id, size);
    size
}

/// Calculates the total number of visible descendants including self.
///
/// # Arguments
/// * `record_id` - The ID of the record to calculate size for
/// * `trace` - The trace data containing the tree structure
/// * `expanded_nodes` - Set of IDs for expanded nodes
/// * `cache_map` - Existing cache map for looking up already-computed sizes
pub fn calculate_subtree_size(
    record_id: u64,
    trace: &dyn TraceData,
    expanded_nodes: &HashSet<u64>,
    cache_map: &std::collections::HashMap<u64, usize>,
) -> usize {
    let mut total = 1; // Count self

    if expanded_nodes.contains(&record_id) {
        if let Some(record) = trace.get_record(record_id) {
            for child in record.children() {
                // Use cached size if available, otherwise calculate recursively
                total += if let Some(&cached_size) = cache_map.get(&child.id()) {
                    cached_size
                } else {
                    calculate_subtree_size(child.id(), trace, expanded_nodes, cache_map)
                };
            }
        }
    }

    total
}

/// Checks if all children of a node are collapsed (uses cache if available).
///
/// # Arguments
/// * `parent_id` - The ID of the parent record
/// * `trace` - The trace data containing the tree structure
/// * `expanded_nodes` - Set of IDs for expanded nodes
/// * `cache` - Tree cache for memoizing results
pub fn are_all_children_collapsed_cached(
    parent_id: u64,
    trace: &dyn TraceData,
    expanded_nodes: &HashSet<u64>,
    cache: &mut TreeCache,
) -> bool {
    if let Some(&collapsed) = cache.all_children_collapsed.get(&parent_id) {
        return collapsed;
    }

    let result = if let Some(record) = trace.get_record(parent_id) {
        let children = record.children();
        if children.is_empty() {
            true // No children = treat as collapsed
        } else {
            children.iter().all(|child| !expanded_nodes.contains(&child.id()))
        }
    } else {
        true
    };

    cache.all_children_collapsed.insert(parent_id, result);
    result
}

/// A visible node with its row index and depth.
///
/// Used by the visibility strategy system to return flattened tree nodes
/// with their positions and depths for rendering.
#[derive(Clone)]
pub struct FilteredVisibleNode {
    pub record_id: u64,
    pub row_index: usize,
    pub depth: usize,
    /// Tree branch context: For each depth level (0 to depth-1), indicates
    /// whether there are more siblings below this node at that level.
    pub branch_context: Vec<bool>,
    /// Whether this is the last child of its parent
    pub is_last_child: bool,
}

// ===== Visibility Strategy Adapter Functions =====

/// Expansion-aware visibility strategy wrapper.
///
/// This adapter wraps a base visibility strategy and adds expansion state checking.
/// It only descends into nodes that are expanded, combining expansion state with
/// the base strategy's visibility rules.
struct ExpansionAwareStrategy<'a, S: VisibilityStrategy> {
    base_strategy: &'a S,
    expanded_nodes: &'a HashSet<u64>,
}

impl<'a, S: VisibilityStrategy> VisibilityStrategy for ExpansionAwareStrategy<'a, S> {
    fn include_parent(&self, parent: &dyn rjets::TraceRecord, depth: usize) -> bool {
        self.base_strategy.include_parent(parent, depth)
    }

    fn include_leaf(&self, leaf: &dyn rjets::TraceRecord, depth: usize) -> bool {
        self.base_strategy.include_leaf(leaf, depth)
    }

    fn descend_into(&self, parent: &dyn rjets::TraceRecord, depth: usize) -> bool {
        // Only descend if BOTH the node is expanded AND the base strategy allows it
        self.expanded_nodes.contains(&parent.id()) && self.base_strategy.descend_into(parent, depth)
    }

    fn child_window_hint(
        &self,
        parent: &dyn rjets::TraceRecord,
        depth: usize,
    ) -> Option<(usize, usize)> {
        self.base_strategy.child_window_hint(parent, depth)
    }
}

/// Collects visible nodes using a visibility strategy, handling expansion state.
///
/// This is a unified function that replaces the separate filtered/unfiltered traversal
/// paths. It uses the visibility strategy pattern to determine which nodes to include.
///
/// # Arguments
/// * `trace` - The trace data
/// * `expanded_nodes` - Set of expanded node IDs
/// * `strategy` - The visibility strategy to apply
///
/// # Returns
/// Vector of filtered visible nodes with row indices and depths
pub fn collect_visible_nodes_with_strategy<S: VisibilityStrategy>(
    trace: &dyn TraceData,
    expanded_nodes: &HashSet<u64>,
    strategy: &S,
) -> Vec<FilteredVisibleNode> {
    // Wrap the strategy with expansion-aware logic
    let expansion_strategy = ExpansionAwareStrategy {
        base_strategy: strategy,
        expanded_nodes,
    };

    // Get roots as trait objects
    let roots: Vec<&dyn rjets::TraceRecord> = trace
        .root_ids()
        .iter()
        .filter_map(|&id| trace.get_record(id))
        .collect();

    // Traverse using the strategy and assign row indices
    visibility::traverse_visible(roots, &expansion_strategy)
        .enumerate()
        .map(|(row_index, node)| FilteredVisibleNode {
            record_id: node.record.id(),
            row_index,
            depth: node.depth,
            branch_context: node.branch_context,
            is_last_child: node.is_last_child,
        })
        .collect()
}

/// Collects unfiltered visible nodes using the unified strategy system.
///
/// This replaces the manual traversal in `collect_nodes_in_range` by using
/// the UnfilteredStrategy with the visibility system.
///
/// # Arguments
/// * `trace` - The trace data
/// * `expanded_nodes` - Set of expanded node IDs
///
/// # Returns
/// Vector of all visible nodes (expansion-filtered only)
pub fn collect_unfiltered_visible_nodes_strategy(
    trace: &dyn TraceData,
    expanded_nodes: &HashSet<u64>,
) -> Vec<FilteredVisibleNode> {
    let strategy = visibility::UnfilteredStrategy;
    collect_visible_nodes_with_strategy(trace, expanded_nodes, &strategy)
}

/// Collects viewport-filtered visible nodes using the unified strategy system.
///
/// This replaces `collect_filtered_visible_nodes` by using the ViewportFilterStrategy
/// with the visibility system.
///
/// # Arguments
/// * `trace` - The trace data
/// * `expanded_nodes` - Set of expanded node IDs
/// * `viewport_start_clk` - Start of viewport time range
/// * `viewport_end_clk` - End of viewport time range
///
/// # Returns
/// Vector of viewport-filtered visible nodes
pub fn collect_viewport_filtered_nodes_strategy(
    trace: &dyn TraceData,
    expanded_nodes: &HashSet<u64>,
    viewport_start_clk: i64,
    viewport_end_clk: i64,
) -> Vec<FilteredVisibleNode> {
    let strategy = visibility::ViewportFilterStrategy {
        start: viewport_start_clk,
        end: viewport_end_clk,
    };
    collect_visible_nodes_with_strategy(trace, expanded_nodes, &strategy)
}

#[cfg(test)]
mod strategy_tests {
    use super::*;
    use std::collections::HashMap;
    use std::sync::Arc;

    // Mock implementations for testing using Arc for shared ownership
    struct MockTrace {
        records: HashMap<u64, Arc<MockRecord>>,
        roots: Vec<u64>,
    }

    struct MockRecord {
        id: u64,
        clk: i64,
        children: Vec<Arc<MockRecord>>,
    }

    // Implement Send manually since Arc<T> is Send when T is Send+Sync
    unsafe impl Send for MockTrace {}

    impl rjets::TraceData for MockTrace {
        fn metadata(&self) -> &dyn rjets::TraceMetadata {
            unimplemented!()
        }

        fn root_ids(&self) -> Vec<u64> {
            self.roots.clone()
        }

        fn get_record(&self, id: u64) -> Option<&dyn rjets::TraceRecord> {
            self.records.get(&id).map(|r| r.as_ref() as &dyn rjets::TraceRecord)
        }
    }

    impl rjets::TraceRecord for MockRecord {
        fn clk(&self) -> i64 {
            self.clk
        }
        fn end_clk(&self) -> Option<i64> {
            None
        }
        fn duration(&self) -> Option<i64> {
            None
        }
        fn name(&self) -> &str {
            "test"
        }
        fn id(&self) -> u64 {
            self.id
        }
        fn parent_id(&self) -> Option<u64> {
            None
        }
        fn description(&self) -> &str {
            ""
        }
        fn data(&self) -> HashMap<String, serde_json::Value> {
            HashMap::new()
        }
        fn children(&self) -> Vec<&dyn rjets::TraceRecord> {
            self.children
                .iter()
                .map(|c| c.as_ref() as &dyn rjets::TraceRecord)
                .collect()
        }
        fn events(&self) -> Vec<&dyn rjets::TraceEvent> {
            vec![]
        }
        fn subtree_depth(&self) -> usize {
            if self.children.is_empty() {
                0
            } else {
                1
            }
        }
    }

    #[test]
    fn test_unfiltered_strategy_adapter() {
        // Create simple trace: root(1) -> child(2), child(3)
        let child2 = Arc::new(MockRecord {
            id: 2,
            clk: 10,
            children: vec![],
        });
        let child3 = Arc::new(MockRecord {
            id: 3,
            clk: 20,
            children: vec![],
        });
        let root = Arc::new(MockRecord {
            id: 1,
            clk: 0,
            children: vec![child2.clone(), child3.clone()],
        });

        let mut records = HashMap::new();
        records.insert(1, root);
        records.insert(2, child2);
        records.insert(3, child3);

        let trace = MockTrace {
            records,
            roots: vec![1],
        };

        // Test with node 1 expanded
        let mut expanded = HashSet::new();
        expanded.insert(1);

        let nodes = collect_unfiltered_visible_nodes_strategy(&trace, &expanded);

        // Should get all 3 nodes with row indices
        assert_eq!(nodes.len(), 3);
        assert_eq!(nodes[0].record_id, 1);
        assert_eq!(nodes[0].row_index, 0);
        assert_eq!(nodes[0].depth, 0);
        assert_eq!(nodes[1].record_id, 2);
        assert_eq!(nodes[1].row_index, 1);
        assert_eq!(nodes[2].record_id, 3);
        assert_eq!(nodes[2].row_index, 2);
    }

    #[test]
    fn test_viewport_filter_strategy_adapter() {
        // Create trace with leaves at different times
        let child2 = Arc::new(MockRecord {
            id: 2,
            clk: 50,
            children: vec![],
        });
        let child3 = Arc::new(MockRecord {
            id: 3,
            clk: 150,
            children: vec![],
        });
        let child4 = Arc::new(MockRecord {
            id: 4,
            clk: 250,
            children: vec![],
        });
        let root = Arc::new(MockRecord {
            id: 1,
            clk: 0,
            children: vec![child2.clone(), child3.clone(), child4.clone()],
        });

        let mut records = HashMap::new();
        records.insert(1, root);
        records.insert(2, child2);
        records.insert(3, child3);
        records.insert(4, child4);

        let trace = MockTrace {
            records,
            roots: vec![1],
        };

        let mut expanded = HashSet::new();
        expanded.insert(1);

        // Filter to [100, 200] - should only get parent and child at 150
        let nodes = collect_viewport_filtered_nodes_strategy(&trace, &expanded, 100, 200);

        assert_eq!(nodes.len(), 2);
        assert_eq!(nodes[0].record_id, 1); // Parent always included
        assert_eq!(nodes[1].record_id, 3); // Leaf at clk 150
    }

    #[test]
    fn test_expansion_state_respected() {
        // Create simple trace
        let child2 = Arc::new(MockRecord {
            id: 2,
            clk: 10,
            children: vec![],
        });
        let child3 = Arc::new(MockRecord {
            id: 3,
            clk: 20,
            children: vec![],
        });
        let root = Arc::new(MockRecord {
            id: 1,
            clk: 0,
            children: vec![child2.clone(), child3.clone()],
        });

        let mut records = HashMap::new();
        records.insert(1, root);
        records.insert(2, child2);
        records.insert(3, child3);

        let trace = MockTrace {
            records,
            roots: vec![1],
        };

        // Test with node 1 NOT expanded
        let expanded = HashSet::new();

        let nodes = collect_unfiltered_visible_nodes_strategy(&trace, &expanded);

        // Should only get root, not children
        assert_eq!(nodes.len(), 1);
        assert_eq!(nodes[0].record_id, 1);
    }
}
