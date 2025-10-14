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

// ===== Viewport Filtering Functions =====

/// Binary search to find the first child with clk >= target_clk.
///
/// # Arguments
/// * `children` - Sorted slice of child records
/// * `target_clk` - Target clock value to search for
///
/// # Returns
/// Index of first child with clk >= target_clk, or children.len() if none found
fn binary_search_first_gte(children: &[&dyn rjets::TraceRecord], target_clk: i64) -> usize {
    children.partition_point(|child| child.clk() < target_clk)
}

/// Binary search to find the last child with clk <= target_clk.
///
/// # Arguments
/// * `children` - Sorted slice of child records
/// * `target_clk` - Target clock value to search for
///
/// # Returns
/// Index of last child with clk <= target_clk, or None if none found
fn binary_search_last_lte(children: &[&dyn rjets::TraceRecord], target_clk: i64) -> Option<usize> {
    if children.is_empty() {
        return None;
    }

    let idx = children.partition_point(|child| child.clk() <= target_clk);
    if idx == 0 {
        None
    } else {
        Some(idx - 1)
    }
}

/// A visible node with its row index and depth (for filtered trees).
#[derive(Clone)]
pub struct FilteredVisibleNode {
    pub record_id: u64,
    pub row_index: usize,
    pub depth: usize,
}

/// Recursively collects filtered nodes that should be visible.
///
/// # Arguments
/// * `record_id` - ID of current record to process
/// * `depth` - Current depth in tree
/// * `current_row` - Mutable counter for row indices
/// * `trace` - Trace data
/// * `expanded_nodes` - Set of expanded node IDs
/// * `viewport_start_clk` - Start of viewport range
/// * `viewport_end_clk` - End of viewport range
/// * `result` - Output vector to append visible nodes to
/// * `cache` - Tree cache for subtree depth lookups
fn collect_filtered_nodes_recursive(
    record_id: u64,
    depth: usize,
    current_row: &mut usize,
    trace: &dyn TraceData,
    expanded_nodes: &HashSet<u64>,
    viewport_start_clk: i64,
    viewport_end_clk: i64,
    result: &mut Vec<FilteredVisibleNode>,
    cache: &mut TreeCache,
) {
    // Get record from trace
    let Some(record) = trace.get_record(record_id) else {
        return;
    };

    // Get or calculate subtree depth (cached)
    let subtree_depth = if let Some(&depth) = cache.subtree_depths.get(&record_id) {
        depth
    } else {
        let depth = record.subtree_depth();
        cache.subtree_depths.insert(record_id, depth);
        depth
    };

    // Check if record is leaf (no children)
    if subtree_depth == 0 {
        // Leaf node: check temporal bounds
        let record_clk = record.clk();
        if record_clk >= viewport_start_clk && record_clk <= viewport_end_clk {
            // This leaf matches the viewport filter
            result.push(FilteredVisibleNode {
                record_id,
                row_index: *current_row,
                depth,
            });
            *current_row += 1;
        }
        return;
    }

    // Record is parent (has children): ALWAYS add to result (structural anchor)
    result.push(FilteredVisibleNode {
        record_id,
        row_index: *current_row,
        depth,
    });
    *current_row += 1;

    // Early subtree skip: if parent starts after viewport, all children also start after
    if record.clk() > viewport_end_clk {
        return;
    }

    // Check if node is expanded
    if !expanded_nodes.contains(&record_id) {
        return; // Collapsed, don't process children
    }

    // Process children
    let children = record.children();
    if children.is_empty() {
        return;
    }

    // Check if all children are leaves by checking the first child's subtree depth
    // (all siblings at the same level have the same depth characteristic)
    let first_child = children[0];
    let first_child_subtree_depth = if let Some(&depth) = cache.subtree_depths.get(&first_child.id()) {
        depth
    } else {
        let depth = first_child.subtree_depth();
        cache.subtree_depths.insert(first_child.id(), depth);
        depth
    };

    // Only apply binary search optimization if children are leaves
    // For intermediate parent nodes, we must recurse into all children
    // because they might have leaf descendants in the viewport range
    if first_child_subtree_depth == 0 {
        // Children are leaves: use binary search optimization
        let first_idx = binary_search_first_gte(&children, viewport_start_clk);
        let last_idx = binary_search_last_lte(&children, viewport_end_clk);

        if let Some(last) = last_idx {
            if first_idx <= last {
                for child in &children[first_idx..=last] {
                    collect_filtered_nodes_recursive(
                        child.id(),
                        depth + 1,
                        current_row,
                        trace,
                        expanded_nodes,
                        viewport_start_clk,
                        viewport_end_clk,
                        result,
                        cache,
                    );
                }
            }
        }
    } else {
        // Children are intermediate parents: recurse into all of them
        // They might have leaf descendants that start in the viewport range
        for child in children {
            collect_filtered_nodes_recursive(
                child.id(),
                depth + 1,
                current_row,
                trace,
                expanded_nodes,
                viewport_start_clk,
                viewport_end_clk,
                result,
                cache,
            );
        }
    }
}

/// Collects all nodes that pass the viewport filter.
///
/// # Arguments
/// * `trace` - The trace data
/// * `expanded_nodes` - Set of expanded node IDs
/// * `cache` - Tree cache for optimization
/// * `viewport_start_clk` - Start of viewport time range
/// * `viewport_end_clk` - End of viewport time range
///
/// # Returns
/// Vector of filtered visible nodes with row indices and depths
pub fn collect_filtered_visible_nodes(
    trace: &dyn TraceData,
    expanded_nodes: &HashSet<u64>,
    cache: &mut TreeCache,
    viewport_start_clk: i64,
    viewport_end_clk: i64,
) -> Vec<FilteredVisibleNode> {
    // Check if cache is valid
    if cache.is_filtered_cache_valid(viewport_start_clk, viewport_end_clk) {
        // Note: We don't actually cache the full node list, just the count
        // This is because caching the full list would use too much memory
        // Instead we rely on the fast binary search to rebuild quickly
    }

    let mut result = Vec::new();
    let mut current_row = 0;

    for root_id in trace.root_ids() {
        collect_filtered_nodes_recursive(
            root_id,
            0,
            &mut current_row,
            trace,
            expanded_nodes,
            viewport_start_clk,
            viewport_end_clk,
            &mut result,
            cache,
        );
    }

    // Update cache with new viewport range and node count
    cache.filtered_viewport_range = Some((viewport_start_clk, viewport_end_clk));
    cache.filtered_node_count = Some(result.len());

    result
}
