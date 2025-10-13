//! Selection and hover state management.
//!
//! This module encapsulates all state related to user selection,
//! including selected records, events, and hover information.

/// State related to user selection and hover.
///
/// Responsibilities:
/// - Tracking selected record ID
/// - Tracking selected event (record + clock)
/// - Managing hover position and clock value
/// - Providing intent-revealing selection queries
#[derive(Debug, Clone, Default)]
pub struct SelectionState {
    /// Currently selected record ID
    selected_record_id: Option<u64>,
    /// Currently selected event (record_id, event_clk)
    selected_event: Option<(u64, i64)>,
    /// Cursor hover position for visual feedback
    cursor_hover_pos: Option<egui::Pos2>,
    /// Clock value at cursor hover position
    cursor_hover_clk: Option<i64>,
}

impl SelectionState {
    /// Creates a new selection state with nothing selected.
    pub fn new() -> Self {
        Self {
            selected_record_id: None,
            selected_event: None,
            cursor_hover_pos: None,
            cursor_hover_clk: None,
        }
    }

    /// Clears all selection and hover state.
    pub fn clear(&mut self) {
        self.selected_record_id = None;
        self.selected_event = None;
        self.cursor_hover_pos = None;
        self.cursor_hover_clk = None;
    }

    // ===== Selection Queries =====

    /// Returns the currently selected record ID, if any.
    pub fn selected_record_id(&self) -> Option<u64> {
        self.selected_record_id
    }

    /// Returns the currently selected event (record_id, event_clk), if any.
    pub fn selected_event(&self) -> Option<(u64, i64)> {
        self.selected_event
    }

    /// Returns true if the given record is currently selected.
    pub fn is_record_selected(&self, record_id: u64) -> bool {
        self.selected_record_id == Some(record_id)
    }

    /// Returns true if the given event is currently selected.
    pub fn is_event_selected(&self, record_id: u64, event_clk: i64) -> bool {
        self.selected_event == Some((record_id, event_clk))
    }

    /// Returns true if any record is selected.
    pub fn has_selection(&self) -> bool {
        self.selected_record_id.is_some()
    }

    // ===== Hover Queries =====

    /// Returns the current cursor hover position, if any.
    pub fn hover_pos(&self) -> Option<egui::Pos2> {
        self.cursor_hover_pos
    }

    /// Returns the clock value at the cursor hover position, if any.
    pub fn hover_clk(&self) -> Option<i64> {
        self.cursor_hover_clk
    }

    /// Returns true if the cursor is currently hovering.
    pub fn is_hovering(&self) -> bool {
        self.cursor_hover_pos.is_some()
    }

    // ===== Selection Mutations =====

    /// Selects a record and optionally auto-selects its first event.
    ///
    /// # Arguments
    /// * `record_id` - The record to select
    /// * `first_event_clk` - Optional first event clock to auto-select
    pub fn select_record(&mut self, record_id: u64, first_event_clk: Option<i64>) {
        self.selected_record_id = Some(record_id);

        // Auto-select first event if provided
        if let Some(event_clk) = first_event_clk {
            self.selected_event = Some((record_id, event_clk));
        }
    }

    /// Selects a specific event and its parent record.
    ///
    /// # Arguments
    /// * `record_id` - The parent record ID
    /// * `event_clk` - The event clock value
    pub fn select_event(&mut self, record_id: u64, event_clk: i64) {
        self.selected_record_id = Some(record_id);
        self.selected_event = Some((record_id, event_clk));
    }

    /// Clears the event selection but keeps the record selection.
    pub fn clear_event_selection(&mut self) {
        self.selected_event = None;
    }

    /// Clears the record selection (also clears event selection).
    pub fn clear_record_selection(&mut self) {
        self.selected_record_id = None;
        self.selected_event = None;
    }

    // ===== Hover Mutations =====

    /// Updates the hover position and associated clock value.
    ///
    /// # Arguments
    /// * `pos` - The cursor position
    /// * `clk` - The corresponding clock value at that position
    pub fn set_hover(&mut self, pos: egui::Pos2, clk: i64) {
        self.cursor_hover_pos = Some(pos);
        self.cursor_hover_clk = Some(clk);
    }

    /// Clears the hover state.
    pub fn clear_hover(&mut self) {
        self.cursor_hover_pos = None;
        self.cursor_hover_clk = None;
    }

    // ===== Low-Level Accessors (for input handlers) =====
    // These methods provide direct mutable access to internal state
    // for performance-critical input handling code that needs fine-grained control.

    /// Returns multiple mutable references for input handling (splits borrows).
    ///
    /// # Returns
    /// Tuple of (cursor_hover_pos, cursor_hover_clk)
    pub(crate) fn for_input_handler(&mut self) -> (&mut Option<egui::Pos2>, &mut Option<i64>) {
        (&mut self.cursor_hover_pos, &mut self.cursor_hover_clk)
    }
}
