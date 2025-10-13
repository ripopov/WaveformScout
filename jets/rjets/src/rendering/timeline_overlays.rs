//! Timeline overlay rendering for cursor line and region selection.
//!
//! This module handles the rendering of interactive overlays on the timeline:
//! - Vertical cursor line with timestamp label
//! - Region selection rectangle for zoom-to-region

use eframe::egui;
use egui::Color32;
use rjets::ThemeColors;
use crate::utils::format_clock;

/// Renders the vertical cursor line and timestamp label at the hover position.
///
/// # Arguments
/// * `ctx` - The egui context for accessing the debug painter
/// * `scroll_rect` - The scrollable area rectangle for clipping
/// * `hover_pos` - The cursor hover position
/// * `hover_clk` - The clock value at the hover position
/// * `theme_colors` - The color palette for the current theme
pub fn render_cursor_overlay(
    ctx: &egui::Context,
    scroll_rect: egui::Rect,
    hover_pos: egui::Pos2,
    hover_clk: i64,
    theme_colors: &ThemeColors,
) {
    let line_x = hover_pos.x;
    let content_top = scroll_rect.top();
    let content_bottom = scroll_rect.bottom();

    // Use debug_painter which draws on top of everything
    let painter = ctx.debug_painter();

    // Draw the vertical cursor line
    painter.line_segment(
        [
            egui::pos2(line_x, content_top),
            egui::pos2(line_x, content_bottom),
        ],
        egui::Stroke::new(1.5, theme_colors.yellow),
    );

    // Draw timestamp label at the bottom of the line
    let label_text = format_clock(hover_clk);
    let font_id = egui::FontId::proportional(12.0);
    let label_color = theme_colors.yellow;
    let bg_color = Color32::from_rgba_premultiplied(0, 0, 0, 200);

    // Measure text size to create background box
    let galley = painter.layout_no_wrap(
        label_text.clone(),
        font_id.clone(),
        label_color,
    );

    let text_size = galley.size();
    let padding = egui::vec2(4.0, 2.0);
    let label_pos = egui::pos2(line_x, content_bottom - text_size.y - padding.y * 2.0 - 4.0);

    // Draw background box
    let bg_rect = egui::Rect::from_min_size(
        egui::pos2(label_pos.x - padding.x, label_pos.y - padding.y),
        egui::vec2(text_size.x + padding.x * 2.0, text_size.y + padding.y * 2.0),
    );
    painter.rect_filled(bg_rect, 2.0, bg_color);
    painter.rect_stroke(bg_rect, 2.0, egui::Stroke::new(1.0, label_color), egui::StrokeKind::Outside);

    // Draw text
    painter.text(
        egui::pos2(label_pos.x + padding.x, label_pos.y + padding.y),
        egui::Align2::LEFT_TOP,
        label_text,
        font_id,
        label_color,
    );
}

/// Renders the region selection overlay for zoom-to-region functionality.
///
/// # Arguments
/// * `ctx` - The egui context for accessing the debug painter
/// * `scroll_rect` - The scrollable area rectangle for clipping
/// * `start_pos` - The start position of the selection
/// * `current_pos` - The current cursor position
/// * `theme_colors` - The color palette for the current theme
pub fn render_region_selection_overlay(
    ctx: &egui::Context,
    scroll_rect: egui::Rect,
    start_pos: egui::Pos2,
    current_pos: egui::Pos2,
    theme_colors: &ThemeColors,
) {
    let content_top = scroll_rect.top();
    let content_bottom = scroll_rect.bottom();

    // Calculate the selection rectangle
    let left_x = start_pos.x.min(current_pos.x);
    let right_x = start_pos.x.max(current_pos.x);

    let selection_rect = egui::Rect::from_min_max(
        egui::pos2(left_x, content_top),
        egui::pos2(right_x, content_bottom),
    );

    // Use debug_painter to draw on top
    let painter = ctx.debug_painter();

    // Draw semi-transparent overlay
    painter.rect_filled(
        selection_rect,
        0.0,
        rjets::with_alpha(theme_colors.blue, 80),
    );

    // Draw border
    painter.rect_stroke(
        selection_rect,
        0.0,
        egui::Stroke::new(2.0, theme_colors.blue),
        egui::StrokeKind::Outside,
    );
}
