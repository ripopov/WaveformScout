//! Centralized application state for the JETS viewer.

use rjets::{TraceData, ThemeManager};
use std::collections::HashSet;
use std::path::PathBuf;
use crate::cache::TreeCache;

/// Main application state containing all data and UI state.
///
/// This struct consolidates all application state that was previously scattered
/// across individual fields in JetsViewerApp. It provides a cleaner separation
/// between the eframe app implementation and the actual application logic.
pub struct AppState {
    // ===== Trace Data & File State =====
    /// The currently loaded trace data (if any)
    pub trace_data: Option<Box<dyn TraceData>>,

    /// Path to the currently loaded file (None for virtual traces)
    pub file_path: Option<PathBuf>,

    // ===== Selection & Interaction State =====
    /// Currently selected record ID
    pub selected_record_id: Option<u64>,

    /// Currently selected event (record_id, event_clk)
    pub selected_event: Option<(u64, i64)>,

    /// Cursor hover position for visual feedback
    pub cursor_hover_pos: Option<egui::Pos2>,

    /// Clock value at cursor hover position
    pub cursor_hover_clk: Option<i64>,

    // ===== Tree Expansion State =====
    /// Set of expanded node IDs in the tree view
    pub expanded_nodes: HashSet<u64>,

    // ===== Viewport & Zoom State =====
    /// Current zoom level (1.0 = fit, higher = zoomed in)
    pub zoom_level: f32,

    /// Start of visible viewport in clock units
    pub viewport_start_clk: i64,

    /// End of visible viewport in clock units
    pub viewport_end_clk: i64,

    /// Minimum clock in trace
    pub trace_min_clk: i64,

    /// Maximum clock in trace
    pub trace_max_clk: i64,

    /// Shared vertical scroll position between tree and timeline
    pub shared_scroll_y: f32,

    // ===== Drag & Pan Interaction State =====
    /// Whether user is currently dragging to pan
    pub is_dragging: bool,

    /// Clock value where drag started
    pub drag_start_clk: i64,

    /// Whether user is selecting a region to zoom
    pub is_selecting_region: bool,

    /// Start position of region selection
    pub region_start_pos: Option<egui::Pos2>,

    // ===== UI Layout State =====
    /// Split ratio between details panel and main view
    pub split_ratio: f32,

    /// Split ratio between tree and timeline panels
    pub timeline_split_ratio: f32,

    /// Column widths for tree view [Name, ID, Start Clock, End Clock, Description]
    pub column_widths: [f32; 5],

    // ===== Theme & Styling =====
    /// Theme manager instance
    pub theme_manager: ThemeManager,

    /// Name of currently selected theme
    pub current_theme_name: String,

    // ===== Error Handling =====
    /// Current error message to display (if any)
    pub error_message: Option<String>,

    // ===== Caching =====
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
            trace_data: None,
            file_path: None,
            selected_record_id: None,
            expanded_nodes: HashSet::new(),
            error_message: None,
            split_ratio: 0.7,
            theme_manager: ThemeManager::new(),
            current_theme_name: "Dark".to_string(),
            column_widths: [250.0, 80.0, 120.0, 120.0, 300.0],
            timeline_split_ratio: 0.3,
            zoom_level: 1.0,
            viewport_start_clk: 0,
            viewport_end_clk: 0,
            shared_scroll_y: 0.0,
            trace_min_clk: 0,
            trace_max_clk: 0,
            is_dragging: false,
            drag_start_clk: 0,
            is_selecting_region: false,
            region_start_pos: None,
            cursor_hover_pos: None,
            cursor_hover_clk: None,
            selected_event: None,
            tree_cache: TreeCache::new(),
        }
    }

    /// Creates a new AppState with a specific theme loaded from storage.
    pub fn with_theme(theme_name: String) -> Self {
        let mut state = Self::new();
        state.current_theme_name = theme_name;
        state
    }

    /// Resets the trace-related state when loading a new trace.
    pub fn reset_trace_state(&mut self) {
        self.trace_data = None;
        self.file_path = None;
        self.expanded_nodes.clear();
        self.selected_record_id = None;
        self.selected_event = None;
        self.error_message = None;
        self.tree_cache.invalidate();
        self.viewport_start_clk = 0;
        self.viewport_end_clk = 0;
        self.trace_min_clk = 0;
        self.trace_max_clk = 0;
        self.zoom_level = 1.0;
        self.shared_scroll_y = 0.0;
    }

    /// Initializes viewport after trace data is loaded.
    pub fn initialize_viewport(&mut self, min_clk: i64, max_clk: i64) {
        self.trace_min_clk = min_clk;
        self.trace_max_clk = max_clk;
        self.viewport_start_clk = min_clk;
        self.viewport_end_clk = max_clk;
        self.zoom_level = 1.0;
        self.shared_scroll_y = 0.0;
    }
}
