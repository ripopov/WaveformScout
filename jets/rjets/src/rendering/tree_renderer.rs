//! Tree node rendering logic
//!
//! Handles the visual rendering of individual tree nodes in the hierarchical view.
//! Uses egui's painter API for custom drawing with column layout support.

use eframe::egui;
use rjets::{TraceData, ThemeColors};
use std::collections::HashSet;

use crate::ui::virtual_scrolling::ROW_HEIGHT;
use crate::cache::TreeCache;

/// Renders a single tree node row with expand/collapse controls and column data
///
/// # Arguments
/// * `ui` - The egui UI context for drawing
/// * `trace` - The trace data containing the record
/// * `record_id` - ID of the record to render
/// * `depth` - Indentation depth in the tree hierarchy
/// * `expand_width` - Width reserved for expand/collapse controls
/// * `column_widths` - Array of widths for each column
/// * `expanded_nodes` - Set of currently expanded node IDs
/// * `selected_record_id` - Currently selected record ID (if any)
/// * `theme_colors` - Color palette for the current theme
/// * `tree_cache` - Cache for tree computations
///
/// # Returns
/// * `Option<TreeNodeInteraction>` - User interaction result (expand/collapse, selection)
pub fn render_tree_node(
    ui: &mut egui::Ui,
    trace: &dyn TraceData,
    record_id: u64,
    depth: usize,
    expand_width: f32,
    column_widths: &[f32; 5],
    expanded_nodes: &HashSet<u64>,
    selected_record_id: Option<u64>,
    theme_colors: &ThemeColors,
    _tree_cache: &mut TreeCache,
) -> Option<TreeNodeInteraction> {
    // Extract all needed data from the record first to avoid borrow checker issues
    let record = match trace.get_record(record_id) {
        Some(r) => r,
        None => return None,
    };

    let has_children = !record.children().is_empty();
    let name = record.name().to_string();
    let description = record.description().to_string();
    let clk = record.clk();
    let end_clk = record.end_clk();

    let events = record.events();
    let first_event_clk = if !events.is_empty() {
        Some(events[0].clk())
    } else {
        None
    };

    let indent = depth as f32 * 20.0;
    let is_selected = selected_record_id == Some(record_id);

    let mut x_offset = 0.0;
    let start_pos = ui.cursor().min;

    // Reserve space for the entire row
    let (row_rect, row_response) = ui.allocate_exact_size(
        egui::vec2(ui.available_width(), ROW_HEIGHT),
        egui::Sense::click()
    );

    let mut interaction = None;

    if row_response.clicked() {
        // Check if this is a new selection
        let was_already_selected = selected_record_id == Some(record_id);
        interaction = Some(TreeNodeInteraction::Selected {
            record_id,
            was_already_selected,
            first_event_clk,
        });
    }

    // Draw background for selected row
    if is_selected {
        ui.painter().rect_filled(
            row_rect,
            0.0,
            theme_colors.selection,
        );
    }

    // Tree expansion control (fixed 20px width for button area, positioned after indent)
    let button_area_width = 20.0;
    let expand_rect = egui::Rect::from_min_size(
        egui::pos2(start_pos.x + indent, start_pos.y),
        egui::vec2(button_area_width, ROW_HEIGHT),
    );

    if has_children {
        let is_expanded = expanded_nodes.contains(&record_id);
        let symbol = if is_expanded { "▼" } else { "▶" };

        let button_id = ui.id().with(format!("expand_{}", record_id));
        let button_rect = egui::Rect::from_center_size(
            expand_rect.center(),
            egui::vec2(16.0, 16.0),
        );
        let button_response = ui.interact(button_rect, button_id, egui::Sense::click());

        if button_response.clicked() {
            interaction = Some(TreeNodeInteraction::ExpandToggled {
                record_id,
                was_expanded: is_expanded,
            });
        }

        ui.painter().text(
            button_rect.center(),
            egui::Align2::CENTER_CENTER,
            symbol,
            egui::FontId::proportional(12.0),
            ui.visuals().text_color(),
        );
    }

    x_offset += expand_width;

    // Column 0: Name
    let name_rect = egui::Rect::from_min_size(
        egui::pos2(start_pos.x + x_offset, start_pos.y),
        egui::vec2(column_widths[0], ROW_HEIGHT),
    );
    ui.painter().text(
        name_rect.left_center() + egui::vec2(4.0, 0.0),
        egui::Align2::LEFT_CENTER,
        &name,
        egui::FontId::proportional(13.0),
        ui.visuals().text_color(),
    );
    x_offset += column_widths[0];

    // Column 1: ID
    let id_rect = egui::Rect::from_min_size(
        egui::pos2(start_pos.x + x_offset, start_pos.y),
        egui::vec2(column_widths[1], ROW_HEIGHT),
    );
    ui.painter().text(
        id_rect.left_center() + egui::vec2(4.0, 0.0),
        egui::Align2::LEFT_CENTER,
        &record_id.to_string(),
        egui::FontId::proportional(13.0),
        ui.visuals().text_color(),
    );
    x_offset += column_widths[1];

    // Column 2: Start Clock
    let start_rect = egui::Rect::from_min_size(
        egui::pos2(start_pos.x + x_offset, start_pos.y),
        egui::vec2(column_widths[2], ROW_HEIGHT),
    );
    ui.painter().text(
        start_rect.left_center() + egui::vec2(4.0, 0.0),
        egui::Align2::LEFT_CENTER,
        &clk.to_string(),
        egui::FontId::proportional(13.0),
        ui.visuals().text_color(),
    );
    x_offset += column_widths[2];

    // Column 3: End Clock
    let end_str = end_clk
        .map(|e| e.to_string())
        .unwrap_or_else(|| "N/A".to_string());

    let end_rect = egui::Rect::from_min_size(
        egui::pos2(start_pos.x + x_offset, start_pos.y),
        egui::vec2(column_widths[3], ROW_HEIGHT),
    );
    ui.painter().text(
        end_rect.left_center() + egui::vec2(4.0, 0.0),
        egui::Align2::LEFT_CENTER,
        &end_str,
        egui::FontId::proportional(13.0),
        ui.visuals().text_color(),
    );
    x_offset += column_widths[3];

    // Column 4: Description
    let desc_rect = egui::Rect::from_min_size(
        egui::pos2(start_pos.x + x_offset, start_pos.y),
        egui::vec2(column_widths[4], ROW_HEIGHT),
    );
    ui.painter().text(
        desc_rect.left_center() + egui::vec2(4.0, 0.0),
        egui::Align2::LEFT_CENTER,
        &description,
        egui::FontId::proportional(13.0),
        ui.visuals().text_color(),
    );

    interaction
}

/// Result of user interaction with a tree node
pub enum TreeNodeInteraction {
    /// Node was clicked to select it
    Selected {
        record_id: u64,
        was_already_selected: bool,
        first_event_clk: Option<i64>,
    },
    /// Expand/collapse button was clicked
    ExpandToggled {
        record_id: u64,
        was_expanded: bool,
    },
}
