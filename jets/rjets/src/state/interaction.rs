//! Mouse and keyboard interaction state.
//!
//! This module encapsulates all state related to ongoing user interactions,
//! including dragging, panning, and region selection.

/// State related to ongoing mouse/keyboard interactions.
///
/// Responsibilities:
/// - Tracking drag/pan operations
/// - Managing region selection for zoom-to-region
/// - Maintaining interaction state for gesture continuity
#[derive(Debug, Clone, Default)]
pub struct InteractionState {
    /// Whether user is currently dragging to pan
    is_dragging: bool,
    /// Clock value where drag started (for delta calculation)
    drag_start_clk: i64,
    /// Whether user is selecting a region to zoom
    is_selecting_region: bool,
    /// Start position of region selection in screen coordinates
    region_start_pos: Option<egui::Pos2>,
}

impl InteractionState {
    /// Creates a new interaction state with no active interactions.
    pub fn new() -> Self {
        Self {
            is_dragging: false,
            drag_start_clk: 0,
            is_selecting_region: false,
            region_start_pos: None,
        }
    }

    /// Resets all interaction state.
    pub fn reset(&mut self) {
        self.is_dragging = false;
        self.drag_start_clk = 0;
        self.is_selecting_region = false;
        self.region_start_pos = None;
    }

    // ===== Drag/Pan State Queries =====

    /// Returns true if a drag operation is in progress.
    pub fn is_dragging(&self) -> bool {
        self.is_dragging
    }

    /// Returns the clock value where the drag started.
    pub fn drag_start_clk(&self) -> i64 {
        self.drag_start_clk
    }

    // ===== Region Selection State Queries =====

    /// Returns true if a region selection is in progress.
    pub fn is_selecting_region(&self) -> bool {
        self.is_selecting_region
    }

    /// Returns the start position of the region selection, if any.
    pub fn region_start_pos(&self) -> Option<egui::Pos2> {
        self.region_start_pos
    }

    /// Returns true if any interaction is in progress.
    pub fn has_active_interaction(&self) -> bool {
        self.is_dragging || self.is_selecting_region
    }

    // ===== Drag/Pan Mutations =====

    /// Starts a drag/pan operation at the given clock value.
    ///
    /// # Arguments
    /// * `start_clk` - The clock value at the drag start position
    pub fn start_drag(&mut self, start_clk: i64) {
        self.is_dragging = true;
        self.drag_start_clk = start_clk;
    }

    /// Ends the current drag/pan operation.
    pub fn end_drag(&mut self) {
        self.is_dragging = false;
        self.drag_start_clk = 0;
    }

    // ===== Region Selection Mutations =====

    /// Starts a region selection at the given screen position.
    ///
    /// # Arguments
    /// * `start_pos` - The screen position where region selection starts
    pub fn start_region_selection(&mut self, start_pos: egui::Pos2) {
        self.is_selecting_region = true;
        self.region_start_pos = Some(start_pos);
    }

    /// Ends the current region selection and returns the start position if it existed.
    ///
    /// # Returns
    /// The start position of the completed region selection, if any.
    pub fn end_region_selection(&mut self) -> Option<egui::Pos2> {
        let start_pos = self.region_start_pos;
        self.is_selecting_region = false;
        self.region_start_pos = None;
        start_pos
    }

    /// Cancels the current region selection without completing it.
    pub fn cancel_region_selection(&mut self) {
        self.is_selecting_region = false;
        self.region_start_pos = None;
    }

    // ===== Low-Level Accessors (for input handlers) =====
    // These methods provide direct mutable access to internal state
    // for performance-critical input handling code that needs fine-grained control.

    /// Returns multiple mutable references for input handling (splits borrows).
    ///
    /// # Returns
    /// Tuple of (is_dragging, drag_start_clk, is_selecting_region, region_start_pos)
    pub(crate) fn for_input_handler(&mut self) -> (&mut bool, &mut i64, &mut bool, &mut Option<egui::Pos2>) {
        (&mut self.is_dragging, &mut self.drag_start_clk, &mut self.is_selecting_region, &mut self.region_start_pos)
    }
}
