//! Virtual scrolling data structures and logic.
//!
//! This module provides efficient rendering of large hierarchical trees by only
//! rendering the nodes visible in the viewport plus a buffer.

use std::collections::HashSet;
use rjets::TraceData;
use crate::cache::TreeCache;
use crate::domain::tree_operations;

/// Row height in pixels (consistent across tree and timeline views)
pub const ROW_HEIGHT: f32 = 22.0;

/// Number of rows to render above/below viewport for smooth scrolling
pub const VIEWPORT_BUFFER_ROWS: usize = 10;

/// Represents a visible node in the flattened tree view.
///
/// Used by the virtual scrolling system to track which nodes are currently
/// visible in the viewport, allowing efficient rendering of large trees.
pub struct VisibleNode {
    /// The unique identifier of the record
    pub record_id: u64,

    /// The depth of this node in the tree hierarchy (0 for root)
    pub depth: usize,

    /// The row index in the flattened view
    pub row_index: usize,
}

/// Collects only the nodes visible in the viewport plus buffer.
///
/// # Arguments
/// * `trace` - The trace data containing all records
/// * `expanded_nodes` - Set of expanded node IDs
/// * `tree_cache` - Cache for tree computations
/// * `viewport_scroll_offset` - The vertical scroll offset in pixels
/// * `viewport_height` - The height of the viewport in pixels
///
/// # Returns
/// A vector of visible nodes with their depths and row indices
pub fn collect_visible_nodes(
    trace: &dyn TraceData,
    expanded_nodes: &HashSet<u64>,
    tree_cache: &mut TreeCache,
    viewport_scroll_offset: f32,
    viewport_height: f32,
) -> Vec<VisibleNode> {
    let first_visible_row = (viewport_scroll_offset / ROW_HEIGHT) as usize;
    let last_visible_row = ((viewport_scroll_offset + viewport_height) / ROW_HEIGHT) as usize;

    // Add buffer
    let first_visible_row = first_visible_row.saturating_sub(VIEWPORT_BUFFER_ROWS);
    let last_visible_row = last_visible_row + VIEWPORT_BUFFER_ROWS;

    let mut result = Vec::new();
    let mut current_row = 0;

    for root_id in trace.root_ids() {
        collect_nodes_in_range(
            root_id,
            0,
            &mut current_row,
            first_visible_row,
            last_visible_row,
            &mut result,
            trace,
            expanded_nodes,
            tree_cache,
        );

        // Early exit if we've passed the visible range
        if current_row > last_visible_row {
            break;
        }
    }

    result
}

/// Recursively collects nodes in the visible range with optimized skipping.
///
/// This function implements several optimizations:
/// - Early exit when past visible range
/// - Subtree skipping for collapsed regions
/// - Fast path for wide nodes with all children collapsed
#[allow(clippy::too_many_arguments)]
fn collect_nodes_in_range(
    record_id: u64,
    depth: usize,
    current_row: &mut usize,
    first_visible: usize,
    last_visible: usize,
    result: &mut Vec<VisibleNode>,
    trace: &dyn TraceData,
    expanded_nodes: &HashSet<u64>,
    tree_cache: &mut TreeCache,
) {
    // Add current node if it's in the visible range
    if *current_row >= first_visible && *current_row <= last_visible {
        result.push(VisibleNode {
            record_id,
            depth,
            row_index: *current_row,
        });
    }

    *current_row += 1;

    // If we've passed the visible range, we can stop
    if *current_row > last_visible {
        return;
    }

    // Process children if expanded
    if expanded_nodes.contains(&record_id) {
        // First, extract child IDs without holding the borrow
        let child_ids: Vec<u64> = if let Some(record) = trace.get_record(record_id) {
            record.children().iter().map(|c| c.id()).collect()
        } else {
            Vec::new()
        };

        if child_ids.is_empty() {
            return;
        }

        // OPTIMIZATION: Fast path for wide nodes with all children collapsed
        if child_ids.len() > 100 && tree_operations::are_all_children_collapsed_cached(
            record_id,
            trace,
            expanded_nodes,
            tree_cache,
        ) {
            // All children are collapsed, so we can add them in O(V) time
            let num_children = child_ids.len();

            // Calculate which children are in the visible range
            let first_child_in_range = if *current_row <= first_visible {
                first_visible.saturating_sub(*current_row)
            } else {
                0
            };

            let last_child_in_range = if *current_row + num_children > last_visible {
                last_visible.saturating_sub(*current_row)
            } else {
                num_children.saturating_sub(1)
            };

            // Add visible children
            for i in first_child_in_range..=last_child_in_range.min(num_children.saturating_sub(1)) {
                if let Some(&child_id) = child_ids.get(i) {
                    result.push(VisibleNode {
                        record_id: child_id,
                        depth: depth + 1,
                        row_index: *current_row + i,
                    });
                }
            }

            // Skip all children
            *current_row += num_children;
        } else {
            // Normal recursive traversal with subtree skipping
            for &child_id in &child_ids {
                // Try to skip entire subtree if it's before the visible range
                if *current_row < first_visible {
                    let subtree_size = tree_operations::get_subtree_size(
                        child_id,
                        trace,
                        expanded_nodes,
                        tree_cache,
                    );
                    if *current_row + subtree_size <= first_visible {
                        // Entire subtree is before visible range, skip it
                        *current_row += subtree_size;
                        continue;
                    }
                }

                // Recursively process this child
                collect_nodes_in_range(
                    child_id,
                    depth + 1,
                    current_row,
                    first_visible,
                    last_visible,
                    result,
                    trace,
                    expanded_nodes,
                    tree_cache,
                );

                // Early exit if we've passed the visible range
                if *current_row > last_visible {
                    break;
                }
            }
        }
    }
}
