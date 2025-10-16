//! Text rendering utilities
//!
//! Shared utilities for text measurement and truncation.

use eframe::egui;

/// Truncates text to fit within a given width, adding ".." if truncated
///
/// # Arguments
/// * `text` - The text to potentially truncate
/// * `available_width` - Maximum width available for the text
/// * `font_id` - Font to use for measuring text
/// * `painter` - Painter for text measurement
///
/// # Returns
/// * Truncated string that fits within the available width
pub fn truncate_text_to_fit(
    text: &str,
    available_width: f32,
    font_id: &egui::FontId,
    painter: &egui::Painter,
) -> String {
    // Reserve some padding to avoid exact edge cases
    let padding = 8.0; // 4.0 on each side
    let max_width = available_width - padding;

    if max_width <= 0.0 {
        return String::new();
    }

    // Measure the full text
    let full_galley = painter.layout_no_wrap(
        text.to_string(),
        font_id.clone(),
        egui::Color32::WHITE,
    );
    let full_text_width = full_galley.size().x;

    if full_text_width <= max_width {
        return text.to_string();
    }

    // Text is too long, need to truncate with ".."
    let ellipsis = "..";
    let ellipsis_galley = painter.layout_no_wrap(
        ellipsis.to_string(),
        font_id.clone(),
        egui::Color32::WHITE,
    );
    let ellipsis_width = ellipsis_galley.size().x;

    if ellipsis_width >= max_width {
        return String::new();
    }

    let available_for_text = max_width - ellipsis_width;

    // Binary search for the right truncation point
    let mut low = 0;
    let mut high = text.chars().count();
    let mut best_fit = 0;

    while low <= high {
        let mid = (low + high) / 2;
        let truncated: String = text.chars().take(mid).collect();
        let truncated_galley = painter.layout_no_wrap(
            truncated.clone(),
            font_id.clone(),
            egui::Color32::WHITE,
        );
        let truncated_width = truncated_galley.size().x;

        if truncated_width <= available_for_text {
            best_fit = mid;
            low = mid + 1;
        } else {
            high = mid.saturating_sub(1);
        }
    }

    let mut result: String = text.chars().take(best_fit).collect();
    result.push_str(ellipsis);
    result
}
