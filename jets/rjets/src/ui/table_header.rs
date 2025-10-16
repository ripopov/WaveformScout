//! Table header component rendering
//!
//! Handles the rendering of resizable column headers for the tree view.

use eframe::egui;
use egui::Color32;
use crate::rendering::text_utils::truncate_text_to_fit;
use crate::state::LayoutState;

/// Renders the resizable column headers for the tree view table
///
/// # Arguments
/// * `ui` - The egui UI context for drawing
/// * `layout` - Mutable reference to layout state containing expand_width and column_widths
pub fn render_table_header(ui: &mut egui::Ui, layout: &mut LayoutState) {
    let column_names = ["Name", "Description", "Start Clock", "End Clock", "ID"];

    let mut x_offset = 0.0;
    let header_height = 24.0;
    let start_pos = ui.cursor().min;

    // Reserve space for the entire header row
    let (_header_rect, _) = ui.allocate_exact_size(
        egui::vec2(ui.available_width(), header_height),
        egui::Sense::hover()
    );

    let font_id = egui::FontId::proportional(14.0);
    let painter = ui.painter();

    // Get current expand_width value
    let mut expand_width = layout.expand_width();

    // Render expand/collapse column header (tree visualization area)
    let expand_label_rect = egui::Rect::from_min_size(
        egui::pos2(start_pos.x + x_offset, start_pos.y),
        egui::vec2(expand_width, header_height),
    );

    // Draw "Tree" label for the expand column
    painter.text(
        expand_label_rect.left_center() + egui::vec2(4.0, 0.0),
        egui::Align2::LEFT_CENTER,
        "Tree",
        font_id.clone(),
        ui.visuals().strong_text_color(),
    );

    x_offset += expand_width;

    // Resize handle for expand column
    let handle_width = 8.0;
    let expand_handle_rect = egui::Rect::from_center_size(
        egui::pos2(start_pos.x + x_offset, start_pos.y + header_height / 2.0),
        egui::vec2(handle_width, header_height),
    );

    let expand_handle_id = ui.id().with("header_resize_expand");
    let expand_handle_response = ui.interact(expand_handle_rect, expand_handle_id, egui::Sense::drag());

    // Handle dragging for expand column
    if expand_handle_response.dragged() {
        let delta = expand_handle_response.drag_delta().x;
        expand_width = (expand_width + delta).max(50.0);
        *layout.expand_width_mut() = expand_width;
    }

    // Visual feedback for expand column resize handle
    let expand_handle_color = if expand_handle_response.hovered() || expand_handle_response.dragged() {
        ui.ctx().set_cursor_icon(egui::CursorIcon::ResizeHorizontal);
        Color32::from_rgb(100, 150, 255)
    } else {
        ui.visuals().widgets.noninteractive.bg_stroke.color.gamma_multiply(0.5)
    };

    painter.rect_filled(expand_handle_rect.shrink(2.0), 0.0, expand_handle_color);

    // Render remaining column headers
    for (i, name) in column_names.iter().enumerate() {
        let width = layout.column_widths()[i];

        // Draw column header label
        let label_rect = egui::Rect::from_min_size(
            egui::pos2(start_pos.x + x_offset, start_pos.y),
            egui::vec2(width, header_height),
        );

        let truncated_name = truncate_text_to_fit(name, width, &font_id, painter);
        painter.text(
            label_rect.left_center() + egui::vec2(4.0, 0.0),
            egui::Align2::LEFT_CENTER,
            &truncated_name,
            font_id.clone(),
            ui.visuals().strong_text_color(),
        );

        x_offset += width;

        // Column resize handle
        if i < column_names.len() - 1 {
            let handle_width = 8.0;
            let handle_rect = egui::Rect::from_center_size(
                egui::pos2(start_pos.x + x_offset, start_pos.y + header_height / 2.0),
                egui::vec2(handle_width, header_height),
            );

            let handle_id = ui.id().with(format!("header_resize_{}", i));
            let handle_response = ui.interact(handle_rect, handle_id, egui::Sense::drag());

            // Handle dragging
            if handle_response.dragged() {
                let delta = handle_response.drag_delta().x;
                let new_width = (layout.column_widths()[i] + delta).max(50.0);
                layout.column_widths_mut()[i] = new_width;
            }

            // Visual feedback
            let color = if handle_response.hovered() || handle_response.dragged() {
                ui.ctx().set_cursor_icon(egui::CursorIcon::ResizeHorizontal);
                Color32::from_rgb(100, 150, 255)
            } else {
                ui.visuals().widgets.noninteractive.bg_stroke.color.gamma_multiply(0.5)
            };

            ui.painter().rect_filled(handle_rect.shrink(2.0), 0.0, color);
        }
    }
}
