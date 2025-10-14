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
                .add_filter("All Trace Files", &["jets", "jsonl", "br", "pt", "gz"])
                .add_filter("JETS Traces", &["jets", "jsonl", "br"])
                .add_filter("PipeTrace Files", &["pt", "gz"]);

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

        if state.trace.trace_data().is_some() {
            // Zoom controls
            if ui.button("🔍+").clicked() {
                let center = (state.viewport.viewport_start_clk() + state.viewport.viewport_end_clk()) / 2;
                state.viewport.zoom_around(1.5, center, state.trace.min_clk(), state.trace.max_clk());
            }

            if ui.button("🔍-").clicked() {
                let center = (state.viewport.viewport_start_clk() + state.viewport.viewport_end_clk()) / 2;
                state.viewport.zoom_around(1.0 / 1.5, center, state.trace.min_clk(), state.trace.max_clk());
            }

            if ui.button("⛶ Fit").clicked() {
                state.viewport.set_zoom(1.0);
                state.viewport.set_range(state.trace.min_clk(), state.trace.max_clk());
            }

            ui.label(format!("Zoom: {:.1}x", state.viewport.zoom_level()));
        }

        // Push theme selector to the right
        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
            let old_theme = state.theme.current_theme_name().to_string();
            let mut current_theme = old_theme.clone();
            egui::ComboBox::from_id_salt("theme_selector")
                .selected_text(&current_theme)
                .show_ui(ui, |ui| {
                    for theme_name in state.theme.theme_manager().list_themes() {
                        ui.selectable_value(
                            &mut current_theme,
                            theme_name.to_string(),
                            theme_name
                        );
                    }
                });

            // Save theme preference if it changed
            if old_theme != current_theme {
                state.theme.set_theme(current_theme);
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
