//! Table header component rendering
//!
//! Handles the rendering of resizable column headers for the tree view.

use eframe::egui;
use egui::Color32;

/// Renders the resizable column headers for the tree view table
///
/// # Arguments
/// * `ui` - The egui UI context for drawing
/// * `expand_width` - Width reserved for expand/collapse controls
/// * `column_widths` - Mutable array of widths for each column (will be updated on resize)
pub fn render_table_header(ui: &mut egui::Ui, expand_width: f32, column_widths: &mut [f32; 5]) {
    let column_names = ["Name", "Description", "Start Clock", "End Clock", "ID"];

    let mut x_offset = 0.0;
    let header_height = 24.0;
    let start_pos = ui.cursor().min;

    // Reserve space for the entire header row
    let (_header_rect, _) = ui.allocate_exact_size(
        egui::vec2(ui.available_width(), header_height),
        egui::Sense::hover()
    );

    // Space for expand/collapse buttons (dynamic based on max visible depth)
    x_offset += expand_width;

    for (i, name) in column_names.iter().enumerate() {
        let width = column_widths[i];

        // Draw column header label
        let label_rect = egui::Rect::from_min_size(
            egui::pos2(start_pos.x + x_offset, start_pos.y),
            egui::vec2(width, header_height),
        );

        ui.painter().text(
            label_rect.left_center() + egui::vec2(4.0, 0.0),
            egui::Align2::LEFT_CENTER,
            name,
            egui::FontId::proportional(14.0),
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
                column_widths[i] = (column_widths[i] + delta).max(50.0);
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
