//! Trace data and file state management.
//!
//! This module encapsulates all state related to the loaded trace file,
//! including the trace data itself, file path, and trace time extent.

use rjets::{DynTraceData, TraceMetadata};
use std::path::PathBuf;

/// State related to the loaded trace file and its time extent.
///
/// Responsibilities:
/// - Managing trace data lifetime
/// - Tracking source file path
/// - Maintaining trace time boundaries (min/max clock)
#[derive(Default)]
pub struct TraceState {
    /// The currently loaded trace data (if any)
    trace_data: Option<DynTraceData>,
    /// Path to the currently loaded file (None for virtual traces)
    file_path: Option<PathBuf>,
    /// Minimum clock value in the trace
    min_clk: i64,
    /// Maximum clock value in the trace
    max_clk: i64,
}

impl TraceState {
    /// Creates a new trace state with no loaded trace.
    pub fn new() -> Self {
        Self {
            trace_data: None,
            file_path: None,
            min_clk: 0,
            max_clk: 0,
        }
    }

    /// Loads new trace data and initializes time extent.
    ///
    /// # Arguments
    /// * `data` - The trace data to load
    /// * `path` - Optional file path (None for virtual traces)
    pub fn load_trace(&mut self, data: DynTraceData, path: Option<PathBuf>) {
        let (min, max) = data.metadata().trace_extent();
        self.trace_data = Some(data);
        self.file_path = path;
        self.min_clk = min;
        self.max_clk = max;
    }

    /// Clears all trace state, resetting to empty state.
    pub fn clear(&mut self) {
        self.trace_data = None;
        self.file_path = None;
        self.min_clk = 0;
        self.max_clk = 0;
    }

    /// Returns a reference to the loaded trace data, if any.
    pub fn trace_data(&self) -> Option<&DynTraceData> {
        self.trace_data.as_ref()
    }

    /// Returns the file path of the loaded trace, if any.
    pub fn file_path(&self) -> Option<&PathBuf> {
        self.file_path.as_ref()
    }

    /// Returns the minimum clock value in the trace.
    pub fn min_clk(&self) -> i64 {
        self.min_clk
    }

    /// Returns the maximum clock value in the trace.
    pub fn max_clk(&self) -> i64 {
        self.max_clk
    }
}
