//! Application-level coordination and workflow management.
//!
//! Handles high-level application operations like file loading, error handling,
//! and coordinating between different subsystems.

use crate::app::AppState;
use crate::io::{AsyncLoader, LoadResult};
use std::path::PathBuf;
use rjets::TraceMetadata;

/// Coordinates application-level operations and workflows.
///
/// This struct is responsible for:
/// - Managing file loading workflows
/// - Handling loading completion
/// - Coordinating virtual trace generation
/// - Managing error states
pub struct ApplicationCoordinator;

impl ApplicationCoordinator {
    /// Initiates asynchronous file loading.
    ///
    /// Immediately clears previous trace data to show loading indicator.
    pub fn open_file(
        state: &mut AppState,
        loader: &mut AsyncLoader,
        path: PathBuf,
        ctx: &egui::Context,
    ) {
        // Immediately clear previous trace data to show loading indicator
        state.reset_trace_state();

        // Start async loading
        loader.start_file_load(path, ctx);
    }

    /// Checks for loading completion and applies results to application state.
    ///
    /// Called once per frame in the update loop.
    /// Returns true if a load operation completed (success or error).
    pub fn check_loading_completion(state: &mut AppState, loader: &mut AsyncLoader) -> bool {
        match loader.check_completion() {
            LoadResult::Success { data, path } => {
                // Success: Initialize trace data and viewport
                let (min_clk, max_clk) = data.metadata().trace_extent();

                state.trace.load_trace(data, path);
                state.error_message = None;
                state.tree.clear();
                state.selection.clear();
                state.tree_cache.invalidate();

                state.initialize_viewport(min_clk, max_clk);
                true
            }
            LoadResult::Error(error_msg) => {
                // Error: Display error message
                state.error_message = Some(format!("Error loading trace: {}", error_msg));
                state.trace.clear();
                true
            }
            LoadResult::None => {
                // No result available yet (still loading or no operation active)
                false
            }
        }
    }

    /// Generates and loads a virtual trace in-memory.
    ///
    /// This is useful for testing and demonstration purposes.
    pub fn open_virtual_trace(state: &mut AppState, loader: &mut AsyncLoader) {
        match loader.load_virtual_trace() {
            Ok(data) => {
                // Get trace extent from metadata
                let (min_clk, max_clk) = data.metadata().trace_extent();

                state.trace.load_trace(data, None);
                state.error_message = None;
                state.tree.clear();
                state.selection.clear();
                state.tree_cache.invalidate();

                state.initialize_viewport(min_clk, max_clk);
            }
            Err(e) => {
                state.error_message = Some(format!("Error generating virtual trace: {}", e));
            }
        }
    }

    /// Handles tree node selection interaction.
    ///
    /// Updates selection state and auto-selects first event for new selections.
    pub fn handle_node_selection(
        state: &mut AppState,
        record_id: u64,
        was_already_selected: bool,
        first_event_clk: Option<i64>,
    ) {
        Self::update_record_selection(state, record_id, was_already_selected, first_event_clk);
    }

    /// Updates record selection with consistent auto-selection logic.
    ///
    /// If the record was not already selected, auto-selects the first event if available.
    /// If already selected, updates the record selection without changing the event.
    fn update_record_selection(
        state: &mut AppState,
        record_id: u64,
        was_already_selected: bool,
        first_event_clk: Option<i64>,
    ) {
        let event_to_select = if !was_already_selected {
            first_event_clk
        } else {
            // Already selected: just update record selection without changing event
            None
        };

        state.selection.select_record(record_id, event_to_select);
    }

    /// Handles tree node expand/collapse interaction.
    ///
    /// Updates expansion state and invalidates cache.
    pub fn handle_node_expand_toggle(state: &mut AppState, record_id: u64, was_expanded: bool) {
        if was_expanded {
            state.tree.collapse(record_id);
        } else {
            state.tree.expand(record_id);
        }
        // Invalidate cache when expand/collapse changes
        state.tree_cache.invalidate();
    }

    /// Handles timeline bar click interaction.
    ///
    /// Updates selection state and auto-selects first event for new selections.
    pub fn handle_timeline_bar_click(
        state: &mut AppState,
        record_id: u64,
        was_already_selected: bool,
        first_event_clk: Option<i64>,
    ) {
        // Use the intent-revealing selection API
        if !was_already_selected {
            // New selection: auto-select first event if available
            state.selection.select_record(record_id, first_event_clk);
        } else {
            // Already selected: just update record selection without changing event
            state.selection.select_record(record_id, None);
        }
    }
    /// Handles timeline event click interaction.
    ///
    /// Updates event selection and record selection.
    pub fn handle_timeline_event_click(state: &mut AppState, record_id: u64, event_clk: i64) {
        state.selection.select_event(record_id, event_clk);
    }
}
