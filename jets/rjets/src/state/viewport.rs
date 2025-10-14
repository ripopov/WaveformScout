//! Viewport and zoom state management.
//!
//! This module encapsulates all state related to the visible viewport,
//! including zoom level, visible time range, and scroll position.

/// State related to the visible viewport and zoom.
///
/// Responsibilities:
/// - Managing zoom level and visible time range
/// - Coordinating horizontal (time) panning
/// - Tracking vertical scroll position
/// - Enforcing viewport boundaries
#[derive(Debug, Clone)]
pub struct ViewportState {
    /// Current zoom level (1.0 = fit entire trace, higher = zoomed in)
    zoom_level: f32,
    /// Start of visible viewport in clock units
    viewport_start_clk: i64,
    /// End of visible viewport in clock units
    viewport_end_clk: i64,
    /// Shared vertical scroll position between tree and timeline
    shared_scroll_y: f32,
    /// Whether viewport filter is enabled (filters tree to show only records within viewport time range)
    viewport_filter_enabled: bool,
}

impl Default for ViewportState {
    fn default() -> Self {
        Self::new()
    }
}

impl ViewportState {
    /// Creates a new viewport state with default values.
    pub fn new() -> Self {
        Self {
            zoom_level: 1.0,
            viewport_start_clk: 0,
            viewport_end_clk: 0,
            shared_scroll_y: 0.0,
            viewport_filter_enabled: false,
        }
    }

    /// Initializes the viewport to show the entire trace extent.
    ///
    /// # Arguments
    /// * `min_clk` - Minimum clock value in trace
    /// * `max_clk` - Maximum clock value in trace
    pub fn fit_to_trace(&mut self, min_clk: i64, max_clk: i64) {
        self.set_range(min_clk, max_clk, min_clk, max_clk);
        self.shared_scroll_y = 0.0;
    }

    /// Resets viewport to initial state.
    pub fn reset(&mut self) {
        self.viewport_start_clk = 0;
        self.viewport_end_clk = 0;
        self.zoom_level = 1.0;
        self.shared_scroll_y = 0.0;
    }

    // ===== Viewport Queries =====

    /// Returns the current zoom level.
    pub fn zoom_level(&self) -> f32 {
        self.zoom_level
    }

    /// Returns the start of the visible viewport in clock units.
    pub fn viewport_start_clk(&self) -> i64 {
        self.viewport_start_clk
    }

    /// Returns the end of the visible viewport in clock units.
    pub fn viewport_end_clk(&self) -> i64 {
        self.viewport_end_clk
    }

    /// Returns the visible duration in clock units.
    pub fn visible_duration(&self) -> i64 {
        self.viewport_end_clk - self.viewport_start_clk
    }

    /// Returns the shared vertical scroll position.
    pub fn scroll_y(&self) -> f32 {
        self.shared_scroll_y
    }

    /// Returns whether viewport filter is enabled.
    pub fn viewport_filter_enabled(&self) -> bool {
        self.viewport_filter_enabled
    }

    // ===== Viewport Mutations =====

    /// Sets the visible viewport range and automatically calculates zoom level.
    ///
    /// # Arguments
    /// * `start_clk` - Start of viewport in clock units
    /// * `end_clk` - End of viewport in clock units
    /// * `trace_min_clk` - Minimum clock value in trace (for zoom calculation)
    /// * `trace_max_clk` - Maximum clock value in trace (for zoom calculation)
    pub fn set_range(&mut self, start_clk: i64, end_clk: i64, trace_min_clk: i64, trace_max_clk: i64) {
        self.viewport_start_clk = start_clk;
        self.viewport_end_clk = end_clk;

        // Calculate zoom level based on trace extent vs viewport extent
        let trace_extent = (trace_max_clk - trace_min_clk) as f32;
        let viewport_extent = (end_clk - start_clk) as f32;
        self.zoom_level = if viewport_extent > 0.0 {
            trace_extent / viewport_extent
        } else {
            1.0
        };
    }

    /// Zooms in/out around a specific clock point.
    ///
    /// # Arguments
    /// * `zoom_factor` - Multiplicative zoom factor (>1 = zoom in, <1 = zoom out)
    /// * `focus_clk` - Clock value to zoom around (stays at same screen position)
    /// * `min_clk` - Minimum allowed clock (trace boundary)
    /// * `max_clk` - Maximum allowed clock (trace boundary)
    pub fn zoom_around(&mut self, zoom_factor: f32, focus_clk: i64, min_clk: i64, max_clk: i64) {
        let old_duration = self.visible_duration() as f32;
        let new_duration = (old_duration / zoom_factor).max(1.0) as i64;

        // Calculate how much of the old range was before/after the focus point
        let focus_ratio = (focus_clk - self.viewport_start_clk) as f32 / old_duration;

        let mut new_start = focus_clk - (new_duration as f32 * focus_ratio) as i64;
        let mut new_end = new_start + new_duration;

        // Clamp to trace boundaries
        if new_start < min_clk {
            new_start = min_clk;
            new_end = new_start + new_duration;
        }
        if new_end > max_clk {
            new_end = max_clk;
            new_start = new_end - new_duration;
            if new_start < min_clk {
                new_start = min_clk;
            }
        }

        self.viewport_start_clk = new_start;
        self.viewport_end_clk = new_end;
        self.zoom_level = (max_clk - min_clk) as f32 / new_duration as f32;
    }

    /// Sets the vertical scroll position.
    ///
    /// # Arguments
    /// * `y` - New vertical scroll position in pixels
    pub fn set_scroll_y(&mut self, y: f32) {
        self.shared_scroll_y = y.max(0.0);
    }

    /// Sets whether viewport filter is enabled.
    ///
    /// # Arguments
    /// * `enabled` - Whether to enable viewport filtering
    pub fn set_viewport_filter_enabled(&mut self, enabled: bool) {
        self.viewport_filter_enabled = enabled;
    }

    /// Toggles viewport filter on/off.
    pub fn toggle_viewport_filter(&mut self) {
        self.viewport_filter_enabled = !self.viewport_filter_enabled;
    }

    // ===== Low-Level Accessors (for input handlers) =====
    // These methods provide direct mutable access to internal state
    // for performance-critical input handling code that needs fine-grained control.

    /// Returns multiple mutable references for input handling (splits borrows).
    ///
    /// # Returns
    /// Tuple of (viewport_start_clk, viewport_end_clk, zoom_level)
    pub(crate) fn for_input_handler(&mut self) -> (&mut i64, &mut i64, &mut f32) {
        (&mut self.viewport_start_clk, &mut self.viewport_end_clk, &mut self.zoom_level)
    }
}
