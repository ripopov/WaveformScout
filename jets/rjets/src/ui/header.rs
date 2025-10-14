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
                state.viewport.set_range(
                    state.trace.min_clk(),
                    state.trace.max_clk(),
                    state.trace.min_clk(),
                    state.trace.max_clk()
                );
            }

            ui.label(format!("Zoom: {:.1}x", state.viewport.zoom_level()));

            ui.separator();

            // Viewport boundary controls
            ui.label("Viewport:");

            // Sync text buffers with current viewport values if they're empty
            if state.layout.viewport_start_text_mut().is_empty() {
                state.layout.sync_viewport_text(
                    state.viewport.viewport_start_clk(),
                    state.viewport.viewport_end_clk()
                );
            }

            // Start boundary text field
            let start_response = egui::TextEdit::singleline(state.layout.viewport_start_text_mut())
                .desired_width(80.0)
                .show(ui);

            ui.label("-");

            // End boundary text field
            let end_response = egui::TextEdit::singleline(state.layout.viewport_end_text_mut())
                .desired_width(80.0)
                .show(ui);

            // Check if user pressed Enter on either field
            let enter_pressed = ui.input(|i| i.key_pressed(egui::Key::Enter));
            if (start_response.response.lost_focus() || end_response.response.lost_focus()) && enter_pressed {
                // Try to parse both text fields
                let start_result = state.layout.viewport_start_text_mut().parse::<i64>();
                let end_result = state.layout.viewport_end_text_mut().parse::<i64>();

                match (start_result, end_result) {
                    (Ok(mut new_start), Ok(mut new_end)) => {
                        // Swap if start > end
                        if new_start > new_end {
                            std::mem::swap(&mut new_start, &mut new_end);
                        }

                        // Apply the new range (zoom is calculated automatically)
                        state.viewport.set_range(
                            new_start,
                            new_end,
                            state.trace.min_clk(),
                            state.trace.max_clk()
                        );

                        // Sync text to potentially swapped values
                        state.layout.sync_viewport_text(new_start, new_end);
                    }
                    _ => {
                        // Reset to current values if either parse fails
                        state.layout.sync_viewport_text(
                            state.viewport.viewport_start_clk(),
                            state.viewport.viewport_end_clk()
                        );
                    }
                }
            }

            // Update text fields when viewport changes (e.g., from zoom buttons)
            let current_start = state.viewport.viewport_start_clk();
            let current_end = state.viewport.viewport_end_clk();
            if state.layout.viewport_start_text_mut().parse::<i64>().unwrap_or(0) != current_start
                || state.layout.viewport_end_text_mut().parse::<i64>().unwrap_or(0) != current_end {
                // Only update if neither field has focus
                if !start_response.response.has_focus() && !end_response.response.has_focus() {
                    state.layout.sync_viewport_text(current_start, current_end);
                }
            }

            ui.separator();

            // Viewport filter checkbox
            let mut filter_enabled = state.viewport.viewport_filter_enabled();
            let filter_response = ui.checkbox(&mut filter_enabled, "⏱ Viewport Filter");

            if filter_response.changed() {
                state.viewport.set_viewport_filter_enabled(filter_enabled);
                // Invalidate filtered cache when toggling
                state.tree_cache.invalidate_filtered_cache();
            }

            if filter_response.hovered() {
                filter_response.on_hover_text(
                    "Show only leaf records that start within the viewport time range"
                );
            }
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
