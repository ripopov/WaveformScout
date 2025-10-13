//! Timeline row rendering logic
//!
//! Handles the visual rendering of timeline bars and event markers for trace records.
//! Includes optimizations for event visibility culling and selection highlighting.

use eframe::egui;
use egui::Color32;
use rjets::{ThemeColors, TraceData};

use crate::domain::virtual_scrolling::ROW_HEIGHT;
use crate::domain::viewport_operations;
use crate::utils::format_clock;

/// Renders a single timeline row with bars and event markers
///
/// # Arguments
/// * `ui` - The egui UI context for drawing
/// * `trace` - The trace data containing the record
/// * `record_id` - ID of the record to render
/// * `viewport_start_clk` - Start of the visible time range
/// * `viewport_end_clk` - End of the visible time range
/// * `selected_record_id` - Currently selected record ID (if any)
/// * `selected_event` - Currently selected event (record_id, clk) tuple (if any)
/// * `is_dragging` - Whether the timeline is currently being dragged
/// * `theme_colors` - Color palette for the current theme
/// * `get_record_color_fn` - Function to compute color for a record by name
///
/// # Returns
/// * `Option<TimelineRowInteraction>` - User interaction result (bar click, event click)
pub fn render_timeline_row<F>(
    ui: &mut egui::Ui,
    trace: &dyn TraceData,
    record_id: u64,
    viewport_start_clk: i64,
    viewport_end_clk: i64,
    selected_record_id: Option<u64>,
    selected_event: Option<(u64, i64)>,
    is_dragging: bool,
    theme_colors: &ThemeColors,
    get_record_color_fn: F,
) -> Option<TimelineRowInteraction>
where
    F: Fn(&str) -> Color32,
{
    let record = match trace.get_record(record_id) {
        Some(r) => r,
        None => return None,
    };

    let start_y = ui.cursor().min.y;

    // Allocate space for this row (matching tree's allocation)
    // Use hover sense instead of click to avoid interfering with canvas drag
    let (_row_rect, _row_response) = ui.allocate_exact_size(
        egui::vec2(ui.available_width(), ROW_HEIGHT),
        egui::Sense::hover()
    );

    // Get canvas rect for horizontal positioning
    let canvas_rect = ui.available_rect_before_wrap();

    // Draw the timeline bar for this record
    let start_clk = record.clk();
    let end_clk = record.end_clk().unwrap_or(viewport_end_clk);

    let x_start = viewport_operations::clk_to_x(start_clk, viewport_start_clk, viewport_end_clk, egui::Rect::from_min_max(
        egui::pos2(canvas_rect.min.x, start_y),
        egui::pos2(canvas_rect.max.x, start_y + ROW_HEIGHT)
    ));
    let x_end = viewport_operations::clk_to_x(end_clk, viewport_start_clk, viewport_end_clk, egui::Rect::from_min_max(
        egui::pos2(canvas_rect.min.x, start_y),
        egui::pos2(canvas_rect.max.x, start_y + ROW_HEIGHT)
    ));
    let width = (x_end - x_start).max(2.0);

    let mut interaction = None;

    if width >= 0.5 {
        let bar_rect = egui::Rect::from_min_size(
            egui::pos2(x_start, start_y),
            egui::vec2(width, ROW_HEIGHT),
        );

        let is_selected = selected_record_id == Some(record_id);
        let bar_color = if is_selected {
            theme_colors.blue
        } else {
            get_record_color_fn(record.name())
        };

        ui.painter().rect_filled(bar_rect, 2.0, bar_color);

        if is_selected {
            ui.painter().rect_stroke(bar_rect, 2.0, egui::Stroke::new(2.0, rjets::adjust_brightness(theme_colors.blue, 1.2)), egui::StrokeKind::Outside);
        }

        // Handle click on bar for selection (only when not dragging)
        let bar_id = ui.id().with(format!("bar_select_{}", record_id));
        let bar_response = ui.interact(bar_rect, bar_id, egui::Sense::click());

        if bar_response.clicked() && !is_dragging {
            let was_already_selected = selected_record_id == Some(record_id);
            let events = record.events();
            let first_event_clk = if !events.is_empty() {
                Some(events[0].clk())
            } else {
                None
            };

            interaction = Some(TimelineRowInteraction::BarClicked {
                record_id,
                was_already_selected,
                first_event_clk,
            });
        }

        // Handle hover tooltip (only when not dragging)
        if bar_response.hovered() && !is_dragging {
            bar_response.on_hover_ui(|ui| {
                ui.label(format!("{}", record.name()));
                ui.label(format!("Start: {}", format_clock(start_clk)));
                if let Some(end) = record.end_clk() {
                    ui.label(format!("End: {}", format_clock(end)));
                    ui.label(format!("Duration: {}", format_clock(end - start_clk)));
                }
            });
        }

        // Draw event markers with binary search optimization
        let events = record.events();

        // Use binary search to find first visible event
        let first_visible_idx = events.binary_search_by(|event| {
            if event.clk() < viewport_start_clk {
                std::cmp::Ordering::Less
            } else {
                std::cmp::Ordering::Greater
            }
        }).unwrap_or_else(|idx| idx);

        // Render only visible events
        for event in events.iter().skip(first_visible_idx) {
            let event_clk = event.clk();

            // Early exit if beyond viewport
            if event_clk > viewport_end_clk {
                break;
            }

            let x = viewport_operations::clk_to_x(event_clk, viewport_start_clk, viewport_end_clk, egui::Rect::from_min_max(
                egui::pos2(canvas_rect.min.x, start_y),
                egui::pos2(canvas_rect.max.x, start_y + ROW_HEIGHT)
            ));
            let marker_pos = egui::pos2(x, start_y + 11.0);

            // Check if this event is selected
            let is_event_selected = selected_event == Some((record_id, event_clk));
            let marker_radius = if is_event_selected { 6.76 } else { 5.2 };

            // Create interaction rect for the event marker
            let marker_rect = egui::Rect::from_center_size(
                marker_pos,
                egui::vec2(marker_radius * 2.0, marker_radius * 2.0)
            );

            let marker_id = ui.id().with(format!("event_marker_{}_{}", record_id, event_clk));
            let marker_response = ui.interact(marker_rect, marker_id, egui::Sense::click());

            // Handle click to select event (only when not dragging)
            if marker_response.clicked() && !is_dragging {
                interaction = Some(TimelineRowInteraction::EventClicked {
                    record_id,
                    event_clk,
                });
            }

            // Draw the event circle
            let event_color = if is_event_selected {
                theme_colors.red // Red fill when selected
            } else {
                theme_colors.yellow
            };
            ui.painter().circle_filled(marker_pos, marker_radius, event_color);

            // Draw selection ring for selected events
            if is_event_selected {
                ui.painter().circle_stroke(
                    marker_pos,
                    marker_radius + 1.0,
                    egui::Stroke::new(1.5, theme_colors.blue)
                );
            }
        }
    }

    interaction
}

/// Result of user interaction with a timeline row
pub enum TimelineRowInteraction {
    /// Timeline bar was clicked to select the record
    BarClicked {
        record_id: u64,
        was_already_selected: bool,
        first_event_clk: Option<i64>,
    },
    /// Event marker was clicked to select the event
    EventClicked {
        record_id: u64,
        event_clk: i64,
    },
}
