//! Centralized application state for the JETS viewer.
//!
//! This module implements the State pattern by composing focused state components
//! that each manage a specific aspect of the application's state. This approach:
//! - Keeps invariants local within each component
//! - Allows borrow-checker friendly access to different state aspects
//! - Provides intent-revealing methods for state mutations
//! - Mirrors established Rust UI projects (dioxus, iced)

use crate::cache::TreeCache;
use crate::state::{
    TraceState, ViewportState, SelectionState, TreeState,
    InteractionState, ThemeState, LayoutState
};

/// Main application state composed of focused state components.
///
/// This struct uses the State pattern to organize application state into
/// cohesive, independently-manageable components. Each component has:
/// - Private fields to enforce invariants
/// - Intent-revealing public methods
/// - Clear separation of concerns
pub struct AppState {
    // ===== Focused State Components =====
    /// Trace data and file state
    pub trace: TraceState,

    /// Viewport and zoom state
    pub viewport: ViewportState,

    /// Selection and hover state
    pub selection: SelectionState,

    /// Tree expansion state
    pub tree: TreeState,

    /// Interaction state (drag, pan, region selection)
    pub interaction: InteractionState,

    /// Theme and styling state
    pub theme: ThemeState,

    /// UI layout state
    pub layout: LayoutState,

    // ===== Top-Level State =====
    /// Current error message to display (if any)
    pub error_message: Option<String>,

    /// Tree computation cache for performance optimization
    pub tree_cache: TreeCache,
}

impl Default for AppState {
    fn default() -> Self {
        Self::new()
    }
}

impl AppState {
    /// Creates a new application state with default values.
    pub fn new() -> Self {
        Self {
            trace: TraceState::new(),
            viewport: ViewportState::new(),
            selection: SelectionState::new(),
            tree: TreeState::new(),
            interaction: InteractionState::new(),
            theme: ThemeState::new(),
            layout: LayoutState::new(),
            error_message: None,
            tree_cache: TreeCache::new(),
        }
    }

    /// Creates a new AppState with a specific theme loaded from storage.
    pub fn with_theme(theme_name: String) -> Self {
        Self {
            trace: TraceState::new(),
            viewport: ViewportState::new(),
            selection: SelectionState::new(),
            tree: TreeState::new(),
            interaction: InteractionState::new(),
            theme: ThemeState::with_theme(theme_name),
            layout: LayoutState::new(),
            error_message: None,
            tree_cache: TreeCache::new(),
        }
    }

    /// Creates a new AppState with theme and layout settings loaded from storage.
    pub fn with_theme_and_layout(theme_name: String, column_widths: [f32; 5], expand_width: f32) -> Self {
        let mut layout = LayoutState::with_column_widths(column_widths);
        *layout.expand_width_mut() = expand_width;

        Self {
            trace: TraceState::new(),
            viewport: ViewportState::new(),
            selection: SelectionState::new(),
            tree: TreeState::new(),
            interaction: InteractionState::new(),
            theme: ThemeState::with_theme(theme_name),
            layout,
            error_message: None,
            tree_cache: TreeCache::new(),
        }
    }

    // ===== High-Level Coordination Methods =====

    /// Resets the trace-related state when loading a new trace.
    ///
    /// This clears trace data, selection, viewport, and tree expansion.
    pub fn reset_trace_state(&mut self) {
        self.trace.clear();
        self.viewport.reset();
        self.selection.clear();
        self.tree.clear();
        self.interaction.reset();
        self.error_message = None;
        self.tree_cache.invalidate();
    }

    /// Initializes viewport after trace data is loaded.
    ///
    /// # Arguments
    /// * `min_clk` - Minimum clock value in trace
    /// * `max_clk` - Maximum clock value in trace
    pub fn initialize_viewport(&mut self, min_clk: i64, max_clk: i64) {
        self.viewport.fit_to_trace(min_clk, max_clk);
    }

}
