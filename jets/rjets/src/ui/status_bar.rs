//! Status bar UI rendering
//!
//! Handles the bottom status bar displaying trace metadata.

use eframe::egui;
use egui::RichText;
use crate::app::AppState;
use crate::utils::format_clock;

/// Renders the status panel at the bottom of the window with trace metadata
///
/// # Arguments
/// * `ui` - The egui UI context for drawing
/// * `state` - Reference to application state
pub fn render_status_bar(ui: &mut egui::Ui, state: &AppState) {
    ui.horizontal(|ui| {
        if let Some(trace) = &state.trace_data {
            let metadata = trace.metadata();
            let (min_clk, max_clk) = metadata.trace_extent();
            let time_range = format!("{}..{}", format_clock(min_clk), format_clock(max_clk));
            let total_records = metadata.total_records().map(|n| n.to_string()).unwrap_or_else(|| "?".to_string());
            let total_events = metadata.total_events().map(|n| n.to_string()).unwrap_or_else(|| "?".to_string());

            if state.file_path.is_none() {
                // Virtual trace metadata
                let num_roots = trace.root_ids().len();
                ui.label(RichText::new(format!(
                    "Virtual Trace | Seed: 42 | Roots: {} | Time: {} | Records: {} | Events: {}",
                    num_roots, time_range, total_records, total_events
                )).strong());
            } else {
                // File-based trace metadata
                let header_data = metadata.header_data();
                let gpu_model = header_data
                    .get("gpu_model")
                    .and_then(|v| v.as_str())
                    .unwrap_or("Unknown");
                let clock_freq = header_data
                    .get("clock_frequency_mhz")
                    .or_else(|| header_data.get("clock_frequency_ghz"))
                    .and_then(|v| v.as_f64())
                    .map(|f| format!("{:.2}", f))
                    .unwrap_or_else(|| "Unknown".to_string());

                ui.label(RichText::new(format!(
                    "GPU: {} | Clock: {} MHz | Time: {} | Records: {} | Events: {}",
                    gpu_model, clock_freq, time_range, total_records, total_events
                )).strong());
            }
        } else {
            ui.label("No trace loaded");
        }
    });
}
