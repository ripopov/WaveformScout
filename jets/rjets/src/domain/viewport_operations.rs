//! Viewport operations for coordinate transformation and zoom calculations.
//!
//! This module provides pure functions for:
//! - Converting between clock values and screen coordinates
//! - Calculating appropriate tick intervals for time axis display
//!
//! These functions are stateless and can be tested independently.

/// Converts a clock value to an X coordinate within the canvas rect.
///
/// # Arguments
/// * `clk` - The clock value to convert
/// * `viewport_start` - The start of the visible clock range
/// * `viewport_end` - The end of the visible clock range
/// * `canvas_rect` - The canvas rectangle for positioning
pub fn clk_to_x(
    clk: i64,
    viewport_start: i64,
    viewport_end: i64,
    canvas_rect: egui::Rect,
) -> f32 {
    if viewport_end == viewport_start {
        return canvas_rect.left();
    }
    let normalized = (clk - viewport_start) as f32 / (viewport_end - viewport_start) as f32;
    canvas_rect.left() + normalized * canvas_rect.width()
}

/// Converts an X coordinate to a clock value within the viewport range.
///
/// # Arguments
/// * `x` - The X coordinate to convert
/// * `viewport_start` - The start of the visible clock range
/// * `viewport_end` - The end of the visible clock range
/// * `canvas_rect` - The canvas rectangle for positioning
pub fn x_to_clk(
    x: f32,
    viewport_start: i64,
    viewport_end: i64,
    canvas_rect: egui::Rect,
) -> i64 {
    let normalized = (x - canvas_rect.left()) / canvas_rect.width();
    viewport_start + (normalized * (viewport_end - viewport_start) as f32) as i64
}

/// Finds the next power of 10 that is greater than or equal to the given value.
/// Used for determining appropriate tick intervals on the time axis.
///
/// # Arguments
/// * `value` - The value to find the next power of 10 for
///
/// # Returns
/// The next power of 10 >= value
pub fn next_power_of_10(value: f32) -> i64 {
    if value <= 0.0 {
        return 1;
    }
    let log_value = value.log10().ceil();
    10_i64.pow(log_value as u32)
}
