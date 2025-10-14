//! Timeline input handling for panning, zooming, and region selection.
//!
//! This module handles all mouse and keyboard input for the timeline view,
//! including:
//! - Drag panning (left mouse + drag)
//! - Zoom to region (Ctrl+drag or right mouse + drag)
//! - Scroll wheel zoom (Ctrl + wheel)
//! - Scroll wheel pan (wheel without Ctrl)
//! - Cursor tracking for hover position

use eframe::egui;
use crate::domain::viewport_operations;

/// Result of timeline input handling
pub enum TimelineInputResult {
    /// No interaction occurred
    None,
    /// Viewport was updated (pan or zoom)
    ViewportUpdated,
    /// Cursor hover position changed
    CursorMoved,
}

/// Handles all timeline input events and updates viewport/interaction state.
///
/// # Arguments
/// * `ctx` - The egui context for input access
/// * `canvas_rect` - The canvas rectangle for coordinate calculations
/// * `canvas_response` - The canvas interaction response
/// * `viewport_start_clk` - Current viewport start clock (mutable)
/// * `viewport_end_clk` - Current viewport end clock (mutable)
/// * `trace_min_clk` - Minimum trace clock for clamping
/// * `trace_max_clk` - Maximum trace clock for clamping
/// * `zoom_level` - Current zoom level (mutable)
/// * `is_dragging` - Drag state flag (mutable)
/// * `drag_start_clk` - Clock where drag started (mutable)
/// * `is_selecting_region` - Region selection state flag (mutable)
/// * `region_start_pos` - Region selection start position (mutable)
/// * `cursor_hover_pos` - Cursor hover position (mutable)
/// * `cursor_hover_clk` - Cursor hover clock value (mutable)
///
/// # Returns
/// The result of input handling
#[allow(clippy::too_many_arguments)]
pub fn handle_timeline_input(
    ctx: &egui::Context,
    canvas_rect: egui::Rect,
    canvas_response: &egui::Response,
    viewport_start_clk: &mut i64,
    viewport_end_clk: &mut i64,
    trace_min_clk: i64,
    trace_max_clk: i64,
    zoom_level: &mut f32,
    is_dragging: &mut bool,
    drag_start_clk: &mut i64,
    is_selecting_region: &mut bool,
    region_start_pos: &mut Option<egui::Pos2>,
    cursor_hover_pos: &mut Option<egui::Pos2>,
    cursor_hover_clk: &mut Option<i64>,
) -> TimelineInputResult {
    let mut result = TimelineInputResult::None;

    // Check if Ctrl is held or right mouse button is being used
    let ctrl_held = ctx.input(|i| i.modifiers.ctrl);
    let right_mouse_held = ctx.input(|i| i.pointer.button_down(egui::PointerButton::Secondary));

    // Handle drag interactions
    if canvas_response.dragged() {
        if ctrl_held || right_mouse_held {
            // Ctrl+Drag or Right Mouse Drag: Zoom to region selection
            if !*is_selecting_region {
                // Start region selection
                *is_selecting_region = true;
                if let Some(pos) = ctx.input(|i| i.pointer.press_origin()) {
                    *region_start_pos = Some(pos);
                }
            } else {
                // region selection in progress (debug print removed)
            }
        } else {
            // Normal drag: Panning
            let drag_delta = canvas_response.drag_delta();

                if !*is_dragging {
                // Starting drag
                *is_dragging = true;
                if let Some(pos) = ctx.input(|i| i.pointer.press_origin()) {
                    *drag_start_clk = viewport_operations::x_to_clk(pos.x, *viewport_start_clk, *viewport_end_clk, canvas_rect);
                }
                    // drag started (debug print removed)
            }

            // Calculate how much clock time the drag represents
            let viewport_range = (*viewport_end_clk - *viewport_start_clk) as f32;
            let pixels_to_clk_ratio = viewport_range / canvas_rect.width();
            let clk_delta = (-drag_delta.x * pixels_to_clk_ratio) as i64;

            // dragging (debug print removed)

            // Apply the pan
            *viewport_start_clk += clk_delta;
            *viewport_end_clk += clk_delta;

            // Clamp to trace bounds
            if *viewport_start_clk < trace_min_clk {
                let diff = trace_min_clk - *viewport_start_clk;
                *viewport_start_clk = trace_min_clk;
                *viewport_end_clk += diff;
            }
            if *viewport_end_clk > trace_max_clk {
                let diff = *viewport_end_clk - trace_max_clk;
                *viewport_end_clk = trace_max_clk;
                *viewport_start_clk -= diff;
            }

            // viewport after drag (debug print removed)
            result = TimelineInputResult::ViewportUpdated;
        }
    } else {
        // Mouse released
        if *is_selecting_region {
            // Complete zoom to region only if selection is large enough (filter out misclicks)
            const MIN_SELECTION_PIXELS: f32 = 5.0;

            if let (Some(start_pos), Some(current_pos)) = (*region_start_pos, ctx.input(|i| i.pointer.hover_pos())) {
                let pixel_distance = (current_pos.x - start_pos.x).abs();

                if pixel_distance >= MIN_SELECTION_PIXELS {
                    // Selection is large enough, proceed with zoom
                    let start_clk = viewport_operations::x_to_clk(start_pos.x, *viewport_start_clk, *viewport_end_clk, canvas_rect);
                    let end_clk = viewport_operations::x_to_clk(current_pos.x, *viewport_start_clk, *viewport_end_clk, canvas_rect);

                    let (new_start_clk, new_end_clk) = if start_clk < end_clk {
                        (start_clk, end_clk)
                    } else {
                        (end_clk, start_clk)
                    };

                    // Apply zoom to the selected region
                    *viewport_start_clk = new_start_clk.max(trace_min_clk);
                    *viewport_end_clk = new_end_clk.min(trace_max_clk);

                    // Update zoom level
                    let new_range = (*viewport_end_clk - *viewport_start_clk) as f32;
                    let full_range = (trace_max_clk - trace_min_clk) as f32;
                    *zoom_level = full_range / new_range;

                    // zoomed to region (debug print removed)
                    result = TimelineInputResult::ViewportUpdated;
                } else {
                    // region selection too small (debug print removed)
                }
            }

            *is_selecting_region = false;
            *region_start_pos = None;
            // region selection ended (debug print removed)
        } else if *is_dragging {
            // Drag ended
            *is_dragging = false;
            // drag ended (debug print removed)
        }
    }

    // Track cursor hover position for vertical cursor line
    // Don't rely on canvas_response.hovered() as it's blocked by child widgets
    // Instead, directly check if pointer is in the canvas rect
    if let Some(hover_pos) = ctx.input(|i| i.pointer.hover_pos()) {
        if canvas_rect.contains(hover_pos) {
            *cursor_hover_pos = Some(hover_pos);
            *cursor_hover_clk = Some(viewport_operations::x_to_clk(hover_pos.x, *viewport_start_clk, *viewport_end_clk, canvas_rect));
            result = TimelineInputResult::CursorMoved;
        } else {
            *cursor_hover_pos = None;
            *cursor_hover_clk = None;
        }
    } else {
        *cursor_hover_pos = None;
        *cursor_hover_clk = None;
    }

    // Handle scroll wheel input when hovering over canvas
    if canvas_rect.contains(ctx.input(|i| i.pointer.hover_pos()).unwrap_or(egui::Pos2::ZERO)) {
        ctx.input(|i| {
            // DEBUG: Print all scroll-related inputs
            if i.raw_scroll_delta != egui::Vec2::ZERO || i.smooth_scroll_delta != egui::Vec2::ZERO {
                // scroll delta changed (debug print removed)
            }

            // Handle zoom (Ctrl + Mouse Wheel)
            // Try both raw_scroll_delta and smooth_scroll_delta for compatibility
            let scroll_y = if i.raw_scroll_delta.y != 0.0 {
                i.raw_scroll_delta.y
            } else {
                i.smooth_scroll_delta.y
            };

            if i.modifiers.ctrl && scroll_y != 0.0 {
                // zoom triggered (debug print removed)

                let zoom_factor = 1.0 + scroll_y * 0.002;
                let mouse_pos = i.pointer.hover_pos().unwrap_or(canvas_rect.center());
                let mouse_clk = viewport_operations::x_to_clk(mouse_pos.x, *viewport_start_clk, *viewport_end_clk, canvas_rect);

                // zoom factor computed (debug print removed)

                *zoom_level = (*zoom_level * zoom_factor).clamp(1.0, 10000.0);

                let new_range = (trace_max_clk - trace_min_clk) as f32 / *zoom_level;
                let old_range = (*viewport_end_clk - *viewport_start_clk) as f32;
                let left_ratio = if old_range > 0.0 {
                    (mouse_clk - *viewport_start_clk) as f32 / old_range
                } else {
                    0.5
                };

                *viewport_start_clk = mouse_clk - (left_ratio * new_range) as i64;
                *viewport_end_clk = *viewport_start_clk + new_range as i64;
                *viewport_start_clk = (*viewport_start_clk).max(trace_min_clk);
                *viewport_end_clk = (*viewport_end_clk).min(trace_max_clk);

                // new zoom level applied (debug print removed)
                result = TimelineInputResult::ViewportUpdated;
            }

            // Handle pan (mouse wheel without Ctrl or middle-mouse drag)
            // Mouse wheel Y-axis pans horizontally in the timeline
            let scroll_y_for_pan = if i.raw_scroll_delta.y != 0.0 {
                i.raw_scroll_delta.y
            } else {
                i.smooth_scroll_delta.y
            };

            if !i.modifiers.ctrl && scroll_y_for_pan != 0.0 {
                // pan triggered (debug print removed)

                // Negative scroll_y means scroll down/right, positive means scroll up/left
                // Invert the sign so scrolling down moves the timeline left (showing later times)
                let viewport_range = (*viewport_end_clk - *viewport_start_clk) as f32;

                // Calculate pan amount with minimum threshold to ensure movement at high zoom
                let pan_amount = (-scroll_y_for_pan / 100.0) * viewport_range * 0.1;

                // At high zoom levels (small viewport_range), ensure we always move at least 1 clock
                // Use a minimum of 1 clock or 2% of viewport range, whichever is larger
                let min_pan = (viewport_range * 0.02).max(1.0);
                let pan_clk = if pan_amount.abs() < min_pan {
                    if pan_amount >= 0.0 {
                        min_pan
                    } else {
                        -min_pan
                    }
                } else {
                    pan_amount
                };

                // pan calculation (debug print removed)

                *viewport_start_clk += pan_clk as i64;
                *viewport_end_clk += pan_clk as i64;

                // Clamp to trace bounds
                if *viewport_start_clk < trace_min_clk {
                    let diff = trace_min_clk - *viewport_start_clk;
                    *viewport_start_clk = trace_min_clk;
                    *viewport_end_clk += diff;
                }
                if *viewport_end_clk > trace_max_clk {
                    let diff = *viewport_end_clk - trace_max_clk;
                    *viewport_end_clk = trace_max_clk;
                    *viewport_start_clk -= diff;
                }

                // new viewport after pan (debug print removed)
                result = TimelineInputResult::ViewportUpdated;
            }
        });
    }

    result
}
