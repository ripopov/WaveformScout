//! UI layout state management.
//!
//! This module encapsulates all state related to UI layout,
//! including panel split ratios and column widths.

/// State related to UI layout and sizing.
///
/// Responsibilities:
/// - Managing panel split ratios
/// - Tracking column widths
/// - Providing layout configuration queries
#[derive(Debug, Clone)]
pub struct LayoutState {
    /// Split ratio between details panel and main view (0.0 to 1.0)
    split_ratio: f32,
    /// Split ratio between tree and timeline panels (0.0 to 1.0)
    timeline_split_ratio: f32,
    /// Column widths for tree view [Name, Description, Start Clock, End Clock, ID]
    column_widths: [f32; 5],
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
            // Default widths ordered as [Name, Description, Start Clock, End Clock, ID]
            column_widths: [250.0, 300.0, 120.0, 120.0, 80.0],
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

    // ===== Low-Level Accessors (for UI handlers) =====
    // These methods provide direct mutable access to internal state
    // for UI rendering code that needs fine-grained control.

    /// Returns a mutable reference to the column widths array (for UI handlers).
    pub(crate) fn column_widths_mut(&mut self) -> &mut [f32; 5] {
        &mut self.column_widths
    }
}
