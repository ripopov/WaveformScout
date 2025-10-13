//! Color mapping for timeline bars based on record types.
//!
//! This module provides functions for:
//! - Assigning colors to records based on their name patterns
//! - Getting the current theme's color palette
//!
//! Color assignment is deterministic based on record names.

use egui::Color32;
use rjets::{ThemeManager, ThemeColors};

/// Returns a reference to the current theme's color palette.
///
/// # Arguments
/// * `theme_manager` - The theme manager instance
/// * `current_theme_name` - The name of the currently active theme
///
/// # Returns
/// A reference to the theme's colors, or the dark theme colors as fallback
pub fn theme_colors<'a>(
    theme_manager: &'a ThemeManager,
    current_theme_name: &str,
) -> &'a ThemeColors {
    theme_manager
        .get_theme(current_theme_name)
        .map(|t| &t.colors)
        .unwrap_or_else(|| {
            // Fallback to dark theme colors
            &theme_manager.get_theme("Dark").unwrap().colors
        })
}

/// Returns a color for timeline bars based on the record's name pattern.
///
/// # Arguments
/// * `name` - The name of the record
/// * `colors` - The current theme's color palette
///
/// # Returns
/// A color based on the record name pattern
pub fn get_record_color(name: &str, colors: &ThemeColors) -> Color32 {
    match name {
        n if n.contains("HostProgram") => colors.blue,
        n if n.contains("GpuContext") => colors.purple,
        n if n.contains("Dispatch") => colors.green,
        n if n.contains("ThreadBlock") => colors.orange,
        n if n.contains("Warp") => colors.red,
        n if n.contains("Instruction") => colors.gray,
        _ => colors.text_dim,
    }
}
