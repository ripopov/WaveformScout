//! Tree panel UI rendering
//!
//! Handles the left panel with hierarchical tree view of trace records.
//! Uses virtual scrolling for performance with large traces.

use crate::app::AppState;
use crate::rendering::tree_renderer;
use crate::ui::{table_header, virtual_scroll_manager::VirtualScrollManager};
use egui::ScrollArea;
use rjets::ThemeColors;

/// Result of tree panel interactions that need to be handled by the application.
pub enum TreePanelInteraction {
    /// A tree node was selected
    NodeSelected {
        record_id: u64,
        was_already_selected: bool,
        first_event_clk: Option<i64>,
    },
    /// A tree node's expansion state was toggled
    NodeExpandToggled {
        record_id: u64,
        was_expanded: bool,
    },
}

/// Renders the complete tree panel with header and virtual scrolling content.
///
/// This function encapsulates all tree panel rendering logic that was previously
/// in JetsViewerApp::render_tree().
pub fn render_tree_panel(
    ui: &mut egui::Ui,
    state: &mut AppState,
    theme_colors: &ThemeColors,
) -> Option<TreePanelInteraction> {
    // Check if we have trace data
    let trace = match state.trace.trace_data() {
        Some(t) => t,
        None => {
            ui.label("No trace data to display");
            return None;
        }
    };

    // Render table header with resizable expand column
    // (Users can now resize it, and it will be saved)
    table_header::render_table_header(ui, &mut state.layout);
    ui.separator();

    // Get expand_width after header rendering (may have been resized)
    let expand_width = state.layout.expand_width();

    // Track interactions to return
    let mut interaction: Option<TreePanelInteraction> = None;

    // Render scrollable content with virtual scrolling
    let scroll_area = ScrollArea::vertical()
        .id_salt("tree_scroll_area")
        .show(ui, |ui| {
            // Get viewport metrics
            let viewport_height = ui.available_height();
            let scroll_offset = state.viewport.scroll_y();

            // Collect visible nodes (filtered or unfiltered based on viewport filter state)
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

            if visible_nodes.is_empty() {
                return;
            }

            // Calculate padding (use filtered count if filter is enabled)
            let total_visible_nodes = if state.viewport.viewport_filter_enabled() {
                state.tree_cache.filtered_node_count.unwrap_or(0)
            } else {
                VirtualScrollManager::get_total_visible_nodes(
                    trace,
                    state.tree.expanded_nodes_set(),
                    &mut state.tree_cache,
                )
            };

            // Add top padding for skipped rows
            let top_padding = VirtualScrollManager::calculate_top_padding(&visible_nodes);
            if top_padding > 0.0 {
                ui.add_space(top_padding);
            }

            // Render visible nodes
            for node in &visible_nodes {
                if let Some(node_interaction) = render_tree_node(
                    ui,
                    trace,
                    node.record_id,
                    node.depth,
                    expand_width,
                    state.layout.column_widths(),
                    state.tree.expanded_nodes_set(),
                    state.selection.selected_record_id(),
                    theme_colors,
                    &mut state.tree_cache,
                    &node.branch_context,
                    node.is_last_child,
                ) {
                    interaction = Some(node_interaction);
                }
            }

            // Add bottom padding for remaining rows
            let bottom_padding = VirtualScrollManager::calculate_bottom_padding(
                &visible_nodes,
                total_visible_nodes,
            );
            if bottom_padding > 0.0 {
                ui.add_space(bottom_padding);
            }
        });

    // Update shared scroll position
    state.viewport.set_scroll_y(scroll_area.state.offset.y);

    interaction
}

/// Renders a single tree node row (delegates to tree_renderer).
fn render_tree_node(
    ui: &mut egui::Ui,
    trace: &rjets::DynTraceData,
    record_id: u64,
    depth: usize,
    expand_width: f32,
    column_widths: &[f32; 5],
    expanded_nodes: &std::collections::HashSet<u64>,
    selected_record_id: Option<u64>,
    theme_colors: &ThemeColors,
    tree_cache: &mut crate::cache::TreeCache,
    branch_context: &[bool],
    is_last_child: bool,
) -> Option<TreePanelInteraction> {
    tree_renderer::render_tree_node(
        ui,
        trace,
        record_id,
        depth,
        expand_width,
        column_widths,
        expanded_nodes,
        selected_record_id,
        theme_colors,
        tree_cache,
        branch_context,
        is_last_child,
    )
    .map(|tree_interaction| match tree_interaction {
        tree_renderer::TreeNodeInteraction::Selected {
            record_id,
            was_already_selected,
            first_event_clk,
        } => TreePanelInteraction::NodeSelected {
            record_id,
            was_already_selected,
            first_event_clk,
        },
        tree_renderer::TreeNodeInteraction::ExpandToggled {
            record_id,
            was_expanded,
        } => TreePanelInteraction::NodeExpandToggled {
            record_id,
            was_expanded,
        },
    })
}
