//! Theme management and persistence coordination.
//!
//! Handles theme selection, application, and persistent storage across sessions.

use crate::app::AppState;

const THEME_KEY: &str = "theme_preference";

/// Coordinates theme management and persistence.
pub struct ThemeCoordinator;

impl ThemeCoordinator {
    /// Loads theme preference from persistent storage during application startup.
    ///
    /// Returns the theme name if found, otherwise defaults to "Dark".
    pub fn load_theme_from_storage(storage: Option<&dyn eframe::Storage>) -> String {
        if let Some(storage) = storage {
            storage.get_string(THEME_KEY).unwrap_or_else(|| "Dark".to_string())
        } else {
            "Dark".to_string()
        }
    }

    /// Saves current theme preference to persistent storage.
    ///
    /// Should be called during application shutdown or when theme changes.
    pub fn save_theme_to_storage(storage: &mut dyn eframe::Storage, theme_name: &str) {
        storage.set_string(THEME_KEY, theme_name.to_string());
        storage.flush();
    }

    /// Applies the current theme to the egui context.
    ///
    /// Called every frame to ensure theme is correctly applied.
    pub fn apply_current_theme(ctx: &egui::Context, state: &AppState) {
        let theme_name = state.theme.current_theme_name();
        if let Some(theme) = state.theme.theme_manager().get_theme(theme_name) {
            let mut visuals = if theme.name == "Light" {
                egui::Visuals::light()
            } else {
                egui::Visuals::dark()
            };

            state.theme.theme_manager().apply_theme(theme, &mut visuals);
            ctx.set_visuals(visuals);
        }
    }
}
