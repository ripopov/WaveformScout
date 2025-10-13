//! Time axis rendering logic
//!
//! Handles the visual rendering of the time axis with major and minor tick marks,
//! clock value labels, and grid lines.

use eframe::egui;
use crate::domain::viewport_operations;
use crate::utils::format_clock;

/// Renders the time axis with major and minor tick marks and clock value labels
///
/// # Arguments
/// * `ui` - The egui UI context for drawing
/// * `canvas_rect` - The rectangular area to draw the time axis in
/// * `viewport_start_clk` - Start of the visible time range
/// * `viewport_end_clk` - End of the visible time range
pub fn render_time_axis(
    ui: &mut egui::Ui,
    canvas_rect: egui::Rect,
    viewport_start_clk: i64,
    viewport_end_clk: i64,
) {
    // Use the exact rect provided (24px from header allocation)
    let axis_rect = canvas_rect;

    ui.painter().rect_filled(
        axis_rect,
        0.0,
        ui.visuals().extreme_bg_color,
    );

    let visible_range = (viewport_end_clk - viewport_start_clk) as f32;
    if visible_range <= 0.0 {
        return;
    }

    let tick_interval = viewport_operations::next_power_of_10(visible_range / 10.0);
    let first_tick = (viewport_start_clk / tick_interval) * tick_interval;

    let mut tick_clk = first_tick;
    while tick_clk <= viewport_end_clk {
        let x = viewport_operations::clk_to_x(tick_clk, viewport_start_clk, viewport_end_clk, canvas_rect);

        // Draw major tick line (scaled to fit 24px height)
        ui.painter().line_segment(
            [
                egui::pos2(x, axis_rect.top()),
                egui::pos2(x, axis_rect.top() + 8.0),
            ],
            egui::Stroke::new(2.0, ui.visuals().text_color()),
        );

        // Draw label (centered vertically in available space)
        ui.painter().text(
            egui::pos2(x, axis_rect.top() + 12.0),
            egui::Align2::CENTER_TOP,
            format_clock(tick_clk),
            egui::FontId::proportional(10.0),
            ui.visuals().text_color(),
        );

        // Draw minor ticks (scaled to fit)
        for i in 1..5 {
            let minor_clk = tick_clk + (tick_interval * i) / 5;
            if minor_clk > viewport_end_clk {
                break;
            }
            let minor_x = viewport_operations::clk_to_x(minor_clk, viewport_start_clk, viewport_end_clk, canvas_rect);
            ui.painter().line_segment(
                [
                    egui::pos2(minor_x, axis_rect.top()),
                    egui::pos2(minor_x, axis_rect.top() + 4.0),
                ],
                egui::Stroke::new(1.0, ui.visuals().text_color().gamma_multiply(0.5)),
            );
        }

        tick_clk += tick_interval;
    }
}
