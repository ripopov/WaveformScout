//! Virtual scrolling coordination for tree and timeline panels.
//!
//! Provides shared logic for collecting visible nodes in the viewport,
//! calculating padding, and managing scroll synchronization.

use crate::cache::TreeCache;
use crate::ui::virtual_scrolling::{self, VisibleNode};
use rjets::DynTraceData;
use std::collections::HashSet;

/// Manages virtual scrolling state and operations for synchronized panels.
pub struct VirtualScrollManager;

impl VirtualScrollManager {
    /// Gets the total number of visible nodes in the tree (cached).
    pub fn get_total_visible_nodes(
        trace: &DynTraceData,
        expanded_nodes: &HashSet<u64>,
        cache: &mut TreeCache,
    ) -> usize {
        crate::domain::tree_operations::get_total_visible_nodes(trace, expanded_nodes, cache)
    }

    /// Gets the maximum visible depth in the tree (cached).
    pub fn get_max_visible_depth(
        trace: &DynTraceData,
        expanded_nodes: &HashSet<u64>,
        cache: &mut TreeCache,
    ) -> usize {
        crate::domain::tree_operations::get_max_visible_depth(trace, expanded_nodes, cache)
    }

    /// Collects nodes visible in the current viewport plus buffer.
    pub fn collect_visible_nodes(
        trace: &DynTraceData,
        expanded_nodes: &HashSet<u64>,
        _cache: &mut TreeCache,
        viewport_scroll_offset: f32,
        viewport_height: f32,
    ) -> Vec<VisibleNode> {
        // Use the new strategy-based traversal system
        let all_nodes = crate::domain::tree_operations::collect_unfiltered_visible_nodes_strategy(
            trace,
            expanded_nodes,
        );

        // Apply vertical scroll culling with buffer
        let row_height = virtual_scrolling::ROW_HEIGHT;
        let first_visible_row = (viewport_scroll_offset / row_height).floor() as usize;
        let last_visible_row = first_visible_row + (viewport_height / row_height).ceil() as usize;

        // Add buffer
        let first_visible_row = first_visible_row.saturating_sub(virtual_scrolling::VIEWPORT_BUFFER_ROWS);
        let last_visible_row = last_visible_row + virtual_scrolling::VIEWPORT_BUFFER_ROWS;

        all_nodes
            .into_iter()
            .filter(|node| {
                node.row_index >= first_visible_row && node.row_index <= last_visible_row
            })
            .map(|node| VisibleNode {
                record_id: node.record_id,
                row_index: node.row_index,
                depth: node.depth,
                branch_context: node.branch_context,
                is_last_child: node.is_last_child,
            })
            .collect()
    }

    /// Calculates the expand column width based on tree depth.
    ///
    /// Reserves space for at least 5 levels by default to avoid resizing.
    /// Formula: 20px base for expand icon + 20px per indent level
    pub fn calculate_expand_width(max_depth: usize) -> f32 {
        20.0 + (max_depth.max(5) as f32 * 20.0)
    }

    /// Calculates top padding for virtual scrolling (rows before viewport).
    pub fn calculate_top_padding(visible_nodes: &[VisibleNode]) -> f32 {
        let first_row = visible_nodes.first().map(|n| n.row_index).unwrap_or(0);
        if first_row > 0 {
            first_row as f32 * virtual_scrolling::ROW_HEIGHT
        } else {
            0.0
        }
    }

    /// Calculates bottom padding for virtual scrolling (rows after viewport).
    pub fn calculate_bottom_padding(
        visible_nodes: &[VisibleNode],
        total_visible_nodes: usize,
    ) -> f32 {
        let last_row = visible_nodes.last().map(|n| n.row_index).unwrap_or(0);
        let rows_after = total_visible_nodes.saturating_sub(last_row + 1);
        if rows_after > 0 {
            rows_after as f32 * virtual_scrolling::ROW_HEIGHT
        } else {
            0.0
        }
    }

    /// Collects nodes visible in the current viewport with viewport filter applied.
    ///
    /// This method applies temporal filtering based on the viewport clock range,
    /// showing only leaf records that start within [viewport_start_clk, viewport_end_clk].
    pub fn collect_filtered_visible_nodes(
        trace: &DynTraceData,
        expanded_nodes: &HashSet<u64>,
        cache: &mut TreeCache,
        viewport_scroll_offset: f32,
        viewport_height: f32,
        viewport_start_clk: i64,
        viewport_end_clk: i64,
    ) -> Vec<VisibleNode> {
        // Use the new strategy-based traversal system with viewport filter
        let filtered_nodes = crate::domain::tree_operations::collect_viewport_filtered_nodes_strategy(
            trace,
            expanded_nodes,
            viewport_start_clk,
            viewport_end_clk,
        );

        // Update cache with filtered node count
        cache.filtered_node_count = Some(filtered_nodes.len());

        // Apply vertical scroll culling
        let row_height = virtual_scrolling::ROW_HEIGHT;
        let first_visible_row = (viewport_scroll_offset / row_height).floor() as usize;
        let last_visible_row = first_visible_row + (viewport_height / row_height).ceil() as usize + 1;

        filtered_nodes
            .into_iter()
            .filter(|node| {
                node.row_index >= first_visible_row && node.row_index <= last_visible_row
            })
            .map(|node| VisibleNode {
                record_id: node.record_id,
                row_index: node.row_index,
                depth: node.depth,
                branch_context: node.branch_context,
                is_last_child: node.is_last_child,
            })
            .collect()
    }
}
