//! Trace data and file state management.
//!
//! This module encapsulates all state related to the loaded trace file,
//! including the trace data itself, file path, and trace time extent.

use rjets::TraceData;
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
    trace_data: Option<Box<dyn TraceData>>,
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
    pub fn load_trace(&mut self, data: Box<dyn TraceData>, path: Option<PathBuf>) {
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
    pub fn trace_data(&self) -> Option<&dyn TraceData> {
        self.trace_data.as_ref().map(|data| data.as_ref())
    }

    /// Returns a mutable reference to the loaded trace data, if any.
    pub fn trace_data_mut(&mut self) -> Option<&mut (dyn TraceData + '_)> {
        match &mut self.trace_data {
            Some(data) => Some(data.as_mut()),
            None => None,
        }
    }

    /// Returns the file path of the loaded trace, if any.
    pub fn file_path(&self) -> Option<&PathBuf> {
        self.file_path.as_ref()
    }

    /// Returns true if a trace is currently loaded.
    pub fn has_trace(&self) -> bool {
        self.trace_data.is_some()
    }

    /// Returns the time extent of the loaded trace.
    ///
    /// Returns (0, 0) if no trace is loaded.
    pub fn trace_extent(&self) -> (i64, i64) {
        (self.min_clk, self.max_clk)
    }

    /// Returns the minimum clock value in the trace.
    pub fn min_clk(&self) -> i64 {
        self.min_clk
    }

    /// Returns the maximum clock value in the trace.
    pub fn max_clk(&self) -> i64 {
        self.max_clk
    }

    /// Returns the total duration of the trace in clock units.
    pub fn duration(&self) -> i64 {
        self.max_clk - self.min_clk
    }
}
