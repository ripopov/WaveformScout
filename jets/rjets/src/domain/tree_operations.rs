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
