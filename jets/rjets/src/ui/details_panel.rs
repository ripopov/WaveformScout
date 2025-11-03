//! Details panel UI rendering
//!
//! Handles the details panel showing annotations, data, and events for the selected record.

use eframe::egui;
use egui::{Color32, RichText, ScrollArea};
use rjets::ThemeColors;
use crate::app::AppState;
use rjets::{TraceData, TraceRecord, TraceEvent, AttributeAccessor};

/// Renders the details panel showing annotations, data, and events for the selected record
///
/// # Arguments
/// * `ui` - The egui UI context for drawing
/// * `state` - Reference to application state
/// * `theme_colors` - Color palette for the current theme
pub fn render_details_panel(ui: &mut egui::Ui, state: &AppState, theme_colors: &ThemeColors) {
    if let (Some(trace), Some(selected_id)) = (state.trace.trace_data(), state.selection.selected_record_id()) {
        if let Some(record) = trace.get_record(selected_id) {
            ui.label(RichText::new(format!("Details for record: {}", selected_id)).strong());
            ui.separator();

            let available_height = ui.available_height();

            ScrollArea::vertical()
                .id_salt("details_scroll_area")
                .max_height(available_height)
                .auto_shrink([false, false])
                .show(ui, |ui| {
                // Show record itself
                let record_json = serde_json::json!({
                    "clk": record.clk(),
                    "name": record.name(),
                    "description": record.description(),
                    "id": record.id(),
                    "parent_id": record.parent_id()
                });
                ui.colored_label(theme_colors.blue,
                    serde_json::to_string(&record_json).unwrap());

                ui.add_space(10.0);

                // Show merged data (includes annotations) - ALL of them, sorted by key
                ui.label(RichText::new("Annotations & Data:").strong());
                let attr_count = record.attr_count();
                if attr_count > 0 {
                    let mut attrs = record.attrs();
                    attrs.sort_by(|a, b| a.0.cmp(&b.0));

                    for (key, value) in attrs {
                        let data_json = serde_json::json!({
                            key: value
                        });
                        ui.colored_label(
                            theme_colors.green,
                            serde_json::to_string(&data_json).unwrap()
                        );
                    }
                } else {
                    ui.colored_label(Color32::GRAY, "(no data)");
                }

                ui.add_space(10.0);

                // Show events - ALL of them, sorted by timestamp
                ui.label(RichText::new("Events:").strong());
                let num_events = record.num_events();
                let mut events: Vec<_> = (0..num_events)
                    .filter_map(|i| record.event_at(i))
                    .collect();
                events.sort_by_key(|e| e.clk());
                if !events.is_empty() {
                    for event in &events {
                        let event_attrs = event.attrs();
                        let data_obj: serde_json::Map<String, serde_json::Value> = event_attrs.into_iter().collect();
                        let evt_json = serde_json::json!({
                            "clk": event.clk(),
                            "name": event.name(),
                            "description": event.description(),
                            "record_id": event.record_id(),
                            "data": data_obj
                        });
                        let event_text = serde_json::to_string(&evt_json).unwrap();

                        // Check if this event is selected
                        let is_event_selected = state.selection.selected_event() == Some((event.record_id(), event.clk()));

                        if is_event_selected {
                            // Draw with highlighted background using theme selection color
                            let text_color = theme_colors.orange;
                            let bg_color = theme_colors.selection;

                            // Use a frame with background color
                            egui::Frame::NONE
                                .fill(bg_color)
                                .inner_margin(4.0)
                                .corner_radius(2.0)
                                .show(ui, |ui| {
                                    ui.colored_label(text_color, event_text);
                                });
                        } else {
                            ui.colored_label(
                                theme_colors.orange,
                                event_text
                            );
                        }
                    }
                } else {
                    ui.colored_label(Color32::GRAY, "(no events)");
                }
            });
        }
    } else {
        ui.label("Data & Events (select a record to view)");
    }
}
