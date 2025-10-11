//! Theme support module for JETS GUI
//!
//! This module provides a comprehensive theming system with color schemes for the JETS trace viewer.
//! It includes built-in themes (Light, Dark, Dracula, One Dark Pro) and a centralized theme manager.
//!
//! # Examples
//!
//! ```
//! use rjets::theme::{ThemeManager, Theme};
//!
//! let manager = ThemeManager::new();
//! let dracula = manager.get_theme("Dracula").unwrap();
//! println!("Dracula background: {:?}", dracula.colors.background);
//! ```

use egui::Color32;
use std::collections::HashMap;

/// Complete color palette for a theme, covering all UI elements
#[derive(Debug, Clone)]
pub struct ThemeColors {
    // Background colors
    pub background: Color32,
    pub panel_background: Color32,
    pub extreme_background: Color32,

    // Foreground colors
    pub text: Color32,
    pub text_dim: Color32,
    pub text_strong: Color32,

    // Interactive colors
    pub selection: Color32,
    pub hover: Color32,
    pub border: Color32,

    // Syntax/semantic colors (for timeline bars and events)
    pub red: Color32,
    pub orange: Color32,
    pub yellow: Color32,
    pub green: Color32,
    pub cyan: Color32,
    pub blue: Color32,
    pub purple: Color32,
    pub magenta: Color32,
    pub gray: Color32,
}

/// A complete theme definition with metadata and color palette
#[derive(Debug, Clone)]
pub struct Theme {
    pub name: String,
    pub description: String,
    pub colors: ThemeColors,
}

/// Centralized theme manager providing access to all available themes
pub struct ThemeManager {
    themes: HashMap<String, Theme>,
    current_theme_name: String,
}

impl ThemeManager {
    /// Creates a new ThemeManager initialized with all built-in themes
    pub fn new() -> Self {
        let mut themes = HashMap::new();

        themes.insert("Light".to_string(), light_theme());
        themes.insert("Dark".to_string(), dark_theme());
        themes.insert("Dracula".to_string(), dracula_theme());
        themes.insert("One Dark Pro".to_string(), one_dark_pro_theme());

        Self {
            themes,
            current_theme_name: "Dark".to_string(),
        }
    }

    /// Retrieves a theme by name
    pub fn get_theme(&self, name: &str) -> Option<&Theme> {
        self.themes.get(name)
    }

    /// Returns a list of all available theme names
    pub fn list_themes(&self) -> Vec<&str> {
        let mut names: Vec<&str> = self.themes.keys().map(|s| s.as_str()).collect();
        names.sort();
        names
    }

    /// Gets the currently selected theme
    pub fn current_theme(&self) -> &Theme {
        self.themes.get(&self.current_theme_name).unwrap()
    }

    /// Sets the current theme by name
    pub fn set_current_theme(&mut self, name: &str) -> Result<(), String> {
        if self.themes.contains_key(name) {
            self.current_theme_name = name.to_string();
            Ok(())
        } else {
            Err(format!("Theme '{}' not found", name))
        }
    }

    /// Applies a theme's colors to egui visuals
    pub fn apply_theme(&self, theme: &Theme, visuals: &mut egui::Visuals) {
        let colors = &theme.colors;

        // Override background colors
        visuals.panel_fill = colors.panel_background;
        visuals.extreme_bg_color = colors.extreme_background;
        visuals.faint_bg_color = colors.hover;

        // Override text colors
        visuals.override_text_color = Some(colors.text);

        // Override selection
        visuals.selection.bg_fill = colors.selection;
        visuals.selection.stroke.color = colors.blue;

        // Override widget colors
        visuals.widgets.noninteractive.bg_fill = colors.panel_background;
        visuals.widgets.inactive.bg_fill = colors.hover;
        visuals.widgets.hovered.bg_fill = colors.hover;
        visuals.widgets.active.bg_fill = colors.selection;

        // Override hyperlink
        visuals.hyperlink_color = colors.cyan;

        // Override error/warning colors
        visuals.error_fg_color = colors.red;
        visuals.warn_fg_color = colors.orange;
    }
}

impl Default for ThemeManager {
    fn default() -> Self {
        Self::new()
    }
}

/// Creates the Light theme using egui defaults
fn light_theme() -> Theme {
    Theme {
        name: "Light".to_string(),
        description: "Light theme with egui default colors".to_string(),
        colors: ThemeColors {
            // Background colors (light theme)
            background: Color32::from_rgb(248, 248, 248),
            panel_background: Color32::from_rgb(248, 248, 248),
            extreme_background: Color32::from_rgb(255, 255, 255),

            // Foreground colors
            text: Color32::from_rgb(0, 0, 0),
            text_dim: Color32::from_rgb(120, 120, 120),
            text_strong: Color32::from_rgb(0, 0, 0),

            // Interactive colors
            selection: Color32::from_rgb(180, 200, 255),
            hover: Color32::from_rgb(220, 220, 220),
            border: Color32::from_rgb(160, 160, 160),

            // Syntax colors (suitable for light background)
            red: Color32::from_rgb(200, 40, 40),
            orange: Color32::from_rgb(230, 120, 20),
            yellow: Color32::from_rgb(180, 140, 0),
            green: Color32::from_rgb(40, 160, 40),
            cyan: Color32::from_rgb(0, 160, 180),
            blue: Color32::from_rgb(40, 100, 200),
            purple: Color32::from_rgb(140, 60, 180),
            magenta: Color32::from_rgb(200, 40, 160),
            gray: Color32::from_rgb(120, 120, 120),
        },
    }
}

/// Creates the Dark theme using egui defaults
fn dark_theme() -> Theme {
    Theme {
        name: "Dark".to_string(),
        description: "Dark theme with egui default colors".to_string(),
        colors: ThemeColors {
            // Background colors (dark theme)
            background: Color32::from_rgb(39, 39, 39),
            panel_background: Color32::from_rgb(39, 39, 39),
            extreme_background: Color32::from_rgb(16, 16, 16),

            // Foreground colors
            text: Color32::from_rgb(255, 255, 255),
            text_dim: Color32::from_rgb(160, 160, 160),
            text_strong: Color32::from_rgb(255, 255, 255),

            // Interactive colors
            selection: Color32::from_rgb(50, 80, 120),
            hover: Color32::from_rgb(70, 70, 70),
            border: Color32::from_rgb(100, 100, 100),

            // Syntax colors (current hardcoded colors from jets-gui)
            red: Color32::from_rgb(231, 76, 60),
            orange: Color32::from_rgb(243, 156, 18),
            yellow: Color32::from_rgb(241, 196, 15),
            green: Color32::from_rgb(46, 204, 113),
            cyan: Color32::from_rgb(26, 188, 156),
            blue: Color32::from_rgb(52, 152, 219),
            purple: Color32::from_rgb(155, 89, 182),
            magenta: Color32::from_rgb(255, 121, 198),
            gray: Color32::from_rgb(149, 165, 166),
        },
    }
}

/// Creates the Dracula theme
///
/// Official colors from: https://draculatheme.com/spec
fn dracula_theme() -> Theme {
    Theme {
        name: "Dracula".to_string(),
        description: "Official Dracula theme color palette".to_string(),
        colors: ThemeColors {
            // Background colors
            // Background: #282a36
            background: hex_to_color32("#282a36"),
            panel_background: hex_to_color32("#282a36"),
            // Darker background for contrast: #21222c
            extreme_background: hex_to_color32("#21222c"),

            // Foreground colors
            // Foreground: #f8f8f2
            text: hex_to_color32("#f8f8f2"),
            // Comment: #6272a4
            text_dim: hex_to_color32("#6272a4"),
            text_strong: hex_to_color32("#f8f8f2"),

            // Interactive colors
            // Current Line: #44475a
            selection: hex_to_color32("#44475a"),
            hover: hex_to_color32("#44475a"),
            border: hex_to_color32("#6272a4"),

            // Syntax colors (official Dracula palette)
            red: hex_to_color32("#ff5555"),      // Red
            orange: hex_to_color32("#ffb86c"),   // Orange
            yellow: hex_to_color32("#f1fa8c"),   // Yellow
            green: hex_to_color32("#50fa7b"),    // Green
            cyan: hex_to_color32("#8be9fd"),     // Cyan
            blue: hex_to_color32("#bd93f9"),     // Purple (used as blue)
            purple: hex_to_color32("#bd93f9"),   // Purple
            magenta: hex_to_color32("#ff79c6"),  // Pink
            gray: hex_to_color32("#6272a4"),     // Comment
        },
    }
}

/// Creates the One Dark Pro theme
///
/// Official colors from: https://github.com/Binaryify/OneDark-Pro
fn one_dark_pro_theme() -> Theme {
    Theme {
        name: "One Dark Pro".to_string(),
        description: "VSCode One Dark Pro color palette".to_string(),
        colors: ThemeColors {
            // Background colors
            // Background: #282c34
            background: hex_to_color32("#282c34"),
            panel_background: hex_to_color32("#282c34"),
            // Slightly darker: #21252b
            extreme_background: hex_to_color32("#21252b"),

            // Foreground colors
            // Foreground: #abb2bf
            text: hex_to_color32("#abb2bf"),
            // Comment Grey: #5c6370
            text_dim: hex_to_color32("#5c6370"),
            text_strong: hex_to_color32("#abb2bf"),

            // Interactive colors
            // Gutter Grey: #4b5263
            selection: hex_to_color32("#4b5263"),
            hover: hex_to_color32("#4b5263"),
            border: hex_to_color32("#5c6370"),

            // Syntax colors (official One Dark Pro palette)
            red: hex_to_color32("#e06c75"),      // Light Red
            orange: hex_to_color32("#d19a66"),   // Dark Yellow (orange)
            yellow: hex_to_color32("#e5c07b"),   // Light Yellow
            green: hex_to_color32("#98c379"),    // Green
            cyan: hex_to_color32("#56b6c2"),     // Cyan
            blue: hex_to_color32("#61afef"),     // Blue
            purple: hex_to_color32("#c678dd"),   // Magenta (purple)
            magenta: hex_to_color32("#c678dd"),  // Magenta
            gray: hex_to_color32("#5c6370"),     // Comment Grey
        },
    }
}

/// Converts a hex color string (like "#282a36") to Color32
pub fn hex_to_color32(hex: &str) -> Color32 {
    let hex = hex.trim_start_matches('#');

    if hex.len() == 6 {
        let r = u8::from_str_radix(&hex[0..2], 16).unwrap_or(0);
        let g = u8::from_str_radix(&hex[2..4], 16).unwrap_or(0);
        let b = u8::from_str_radix(&hex[4..6], 16).unwrap_or(0);
        Color32::from_rgb(r, g, b)
    } else {
        Color32::from_rgb(0, 0, 0) // Fallback to black
    }
}

/// Adjusts the brightness of a color by a factor (1.0 = no change, >1.0 = brighter, <1.0 = darker)
pub fn adjust_brightness(color: Color32, factor: f32) -> Color32 {
    let r = (color.r() as f32 * factor).min(255.0) as u8;
    let g = (color.g() as f32 * factor).min(255.0) as u8;
    let b = (color.b() as f32 * factor).min(255.0) as u8;
    Color32::from_rgb(r, g, b)
}

/// Sets the alpha channel of a color
pub fn with_alpha(color: Color32, alpha: u8) -> Color32 {
    Color32::from_rgba_premultiplied(color.r(), color.g(), color.b(), alpha)
}
