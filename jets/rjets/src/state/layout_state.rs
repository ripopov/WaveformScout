//! UI layout state management.
//!
//! This module encapsulates all state related to UI layout,
//! including panel split ratios and column widths.

use serde::{Deserialize, Serialize};

/// State related to UI layout and sizing.
///
/// Responsibilities:
/// - Managing panel split ratios
/// - Tracking column widths
/// - Providing layout configuration queries
/// - Managing viewport boundary text input state
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LayoutState {
    /// Split ratio between details panel and main view (0.0 to 1.0)
    split_ratio: f32,
    /// Split ratio between tree and timeline panels (0.0 to 1.0)
    timeline_split_ratio: f32,
    /// Width of the expand/collapse column (tree branch visualization area)
    expand_width: f32,
    /// Column widths for tree view [Name, Description, Start Clock, End Clock, ID]
    column_widths: [f32; 5],
    /// Text buffer for viewport start boundary input
    viewport_start_text: String,
    /// Text buffer for viewport end boundary input
    viewport_end_text: String,
}

impl Default for LayoutState {
    fn default() -> Self {
        Self::new()
    }
}

impl LayoutState {
    /// Creates a new layout state with default values.
    pub fn new() -> Self {
        Self {
            split_ratio: 0.7,
            timeline_split_ratio: 0.3,
            expand_width: 100.0, // Default width for expand/collapse column
            // Default widths ordered as [Name, Description, Start Clock, End Clock, ID]
            column_widths: [250.0, 300.0, 120.0, 120.0, 80.0],
            viewport_start_text: String::new(),
            viewport_end_text: String::new(),
        }
    }

    /// Creates a new layout state with custom column widths.
    pub fn with_column_widths(column_widths: [f32; 5]) -> Self {
        Self {
            split_ratio: 0.7,
            timeline_split_ratio: 0.3,
            expand_width: 100.0,
            column_widths,
            viewport_start_text: String::new(),
            viewport_end_text: String::new(),
        }
    }

    // ===== Layout Queries =====

    /// Returns the main split ratio (details panel vs main view).
    pub fn split_ratio(&self) -> f32 {
        self.split_ratio
    }

    /// Returns the timeline split ratio (tree vs timeline).
    pub fn timeline_split_ratio(&self) -> f32 {
        self.timeline_split_ratio
    }

    /// Returns the column widths array.
    pub fn column_widths(&self) -> &[f32; 5] {
        &self.column_widths
    }

    /// Returns the expand column width.
    pub fn expand_width(&self) -> f32 {
        self.expand_width
    }

    // ===== Low-Level Accessors (for UI handlers) =====
    // These methods provide direct mutable access to internal state
    // for UI rendering code that needs fine-grained control.

    /// Returns a mutable reference to the column widths array (for UI handlers).
    pub(crate) fn column_widths_mut(&mut self) -> &mut [f32; 5] {
        &mut self.column_widths
    }

    /// Returns a mutable reference to the expand column width (for UI handlers).
    pub(crate) fn expand_width_mut(&mut self) -> &mut f32 {
        &mut self.expand_width
    }

    // ===== Viewport Text Input Accessors =====

    /// Returns a mutable reference to the viewport start text buffer.
    pub fn viewport_start_text_mut(&mut self) -> &mut String {
        &mut self.viewport_start_text
    }

    /// Returns a mutable reference to the viewport end text buffer.
    pub fn viewport_end_text_mut(&mut self) -> &mut String {
        &mut self.viewport_end_text
    }

    /// Updates the viewport text buffers from current viewport values.
    pub fn sync_viewport_text(&mut self, start_clk: i64, end_clk: i64) {
        self.viewport_start_text = start_clk.to_string();
        self.viewport_end_text = end_clk.to_string();
    }
}
