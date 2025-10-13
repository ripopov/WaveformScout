//! Theme and styling state management.
//!
//! This module encapsulates all state related to visual theming,
//! including theme manager and currently selected theme.

use rjets::ThemeManager;

/// State related to visual theme and styling.
///
/// Responsibilities:
/// - Managing theme instances
/// - Tracking current theme selection
/// - Providing theme-related queries
pub struct ThemeState {
    /// Theme manager instance
    theme_manager: ThemeManager,
    /// Name of currently selected theme
    current_theme_name: String,
}

impl std::fmt::Debug for ThemeState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ThemeState")
            .field("current_theme_name", &self.current_theme_name)
            .finish_non_exhaustive()
    }
}

impl Default for ThemeState {
    fn default() -> Self {
        Self::new()
    }
}

impl ThemeState {
    /// Creates a new theme state with the default theme.
    pub fn new() -> Self {
        Self {
            theme_manager: ThemeManager::new(),
            current_theme_name: "Dark".to_string(),
        }
    }

    /// Creates a new theme state with a specific theme.
    ///
    /// # Arguments
    /// * `theme_name` - The name of the theme to use
    pub fn with_theme(theme_name: String) -> Self {
        Self {
            theme_manager: ThemeManager::new(),
            current_theme_name: theme_name,
        }
    }

    // ===== Theme Queries =====

    /// Returns a reference to the theme manager.
    pub fn theme_manager(&self) -> &ThemeManager {
        &self.theme_manager
    }

    /// Returns the name of the current theme.
    pub fn current_theme_name(&self) -> &str {
        &self.current_theme_name
    }

    // ===== Theme Mutations =====

    /// Sets the current theme by name.
    ///
    /// # Arguments
    /// * `theme_name` - The name of the theme to activate
    pub fn set_theme(&mut self, theme_name: String) {
        self.current_theme_name = theme_name;
    }
}
