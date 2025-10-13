//! Header panel UI rendering
//!
//! Handles the top menu bar with file controls, zoom buttons, and theme selector.

use eframe::egui;
use egui::Color32;
use std::path::PathBuf;
use crate::app::AppState;

/// Result of user interaction with the header panel
pub enum HeaderInteraction {
    /// User clicked "Open Trace" button
    OpenFileRequested(PathBuf),
    /// User clicked "Virtual Trace" button
    OpenVirtualTraceRequested,
}

/// Renders the application header with file controls and zoom controls
///
/// # Arguments
/// * `ui` - The egui UI context for drawing
/// * `state` - Mutable reference to application state
///
/// # Returns
/// * `Option<HeaderInteraction>` - User interaction result
pub fn render_header(ui: &mut egui::Ui, state: &mut AppState) -> Option<HeaderInteraction> {
    let mut interaction = None;

    ui.horizontal(|ui| {
        if ui.button("📁 Open Trace").clicked() {
            let mut dialog = rfd::FileDialog::new()
                .add_filter("JETS Traces", &["jets", "jsonl", "br"]);

            if let Ok(cwd) = std::env::current_dir() {
                dialog = dialog.set_directory(cwd);
            }

            if let Some(path) = dialog.pick_file() {
                interaction = Some(HeaderInteraction::OpenFileRequested(path));
            }
        }

        if ui.button("🔮 Virtual Trace").clicked() {
            interaction = Some(HeaderInteraction::OpenVirtualTraceRequested);
        }

        ui.separator();

        if state.trace_data.is_some() {
            // Zoom controls
            if ui.button("🔍+").clicked() {
                state.zoom_level = (state.zoom_level * 1.5).min(10000.0);
                let new_range = (state.trace_max_clk - state.trace_min_clk) as f32 / state.zoom_level;
                let center = (state.viewport_start_clk + state.viewport_end_clk) / 2;
                state.viewport_start_clk = center - (new_range / 2.0) as i64;
                state.viewport_end_clk = center + (new_range / 2.0) as i64;
                state.viewport_start_clk = state.viewport_start_clk.max(state.trace_min_clk);
                state.viewport_end_clk = state.viewport_end_clk.min(state.trace_max_clk);
            }

            if ui.button("🔍-").clicked() {
                state.zoom_level = (state.zoom_level / 1.5).max(1.0);
                let new_range = (state.trace_max_clk - state.trace_min_clk) as f32 / state.zoom_level;
                let center = (state.viewport_start_clk + state.viewport_end_clk) / 2;
                state.viewport_start_clk = center - (new_range / 2.0) as i64;
                state.viewport_end_clk = center + (new_range / 2.0) as i64;
                state.viewport_start_clk = state.viewport_start_clk.max(state.trace_min_clk);
                state.viewport_end_clk = state.viewport_end_clk.min(state.trace_max_clk);
            }

            if ui.button("⛶ Fit").clicked() {
                state.zoom_level = 1.0;
                state.viewport_start_clk = state.trace_min_clk;
                state.viewport_end_clk = state.trace_max_clk;
            }

            ui.label(format!("Zoom: {:.1}x", state.zoom_level));
        }

        // Push theme selector to the right
        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
            let old_theme = state.current_theme_name.clone();
            egui::ComboBox::from_id_salt("theme_selector")
                .selected_text(&state.current_theme_name)
                .show_ui(ui, |ui| {
                    for theme_name in state.theme_manager.list_themes() {
                        ui.selectable_value(
                            &mut state.current_theme_name,
                            theme_name.to_string(),
                            theme_name
                        );
                    }
                });

            // Save theme preference if it changed
            if old_theme != state.current_theme_name {
                eprintln!("DEBUG [render_header]: Theme changed from '{}' to '{}'", old_theme, state.current_theme_name);
                // Mark that we need to save on next frame (we'll handle this in update with frame.storage_mut)
                ui.ctx().request_repaint();
            }

            ui.label("Theme:");
        });
    });

    if let Some(err) = &state.error_message {
        ui.colored_label(Color32::RED, err);
    }

    interaction
}
