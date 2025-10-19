//! Asynchronous trace file loading.
//!
//! This module handles loading JETS trace files in background threads,
//! keeping the GUI responsive during file I/O operations.

use eframe::egui;
use rjets::{DynTraceData, JetsTraceReader, VirtualTraceReader, PipetraceReader, TraceReader};
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::sync::mpsc::{channel, Receiver};
use std::thread;
use crate::io::LoadingState;

/// Result of a completed trace loading operation.
pub enum LoadResult {
    /// Loading completed successfully
    Success {
        /// The loaded trace data
        data: DynTraceData,
        /// Path to the file that was loaded (None for virtual traces)
        path: Option<PathBuf>,
    },
    /// Loading failed with an error
    Error(String),
    /// No loading operation in progress
    None,
}

/// Manages asynchronous loading of trace files.
///
/// This struct coordinates background thread file loading with the main GUI thread,
/// ensuring responsive UI during potentially long-running I/O operations.
pub struct AsyncLoader {
    /// Shared loading state flag
    loading_state: Arc<Mutex<LoadingState>>,

    /// Channel receiver for loading results
    loading_receiver: Option<Receiver<Result<DynTraceData, String>>>,

    /// Path of the file currently being loaded
    pending_load_path: Option<PathBuf>,
}

impl AsyncLoader {
    /// Creates a new async loader with no active loading operation.
    pub fn new() -> Self {
        Self {
            loading_state: Arc::new(Mutex::new(LoadingState::new())),
            loading_receiver: None,
            pending_load_path: None,
        }
    }


    /// Checks if a loading operation is currently in progress.
    pub fn is_loading(&self) -> bool {
        let state = self.loading_state.lock().unwrap();
        state.in_progress
    }

    /// Starts loading a trace file asynchronously from the specified path.
    ///
    /// The GUI remains responsive during loading, and a loading indicator can be displayed.
    /// Call `check_completion()` regularly (e.g., once per frame) to check for results.
    ///
    /// # Arguments
    /// * `path` - Path to the trace file to load
    /// * `ctx` - egui context for requesting repaints when loading completes
    pub fn start_file_load(&mut self, path: PathBuf, ctx: &egui::Context) {
        // Create a channel for receiving the result
        let (sender, receiver) = channel();
        self.loading_receiver = Some(receiver);

        // Set loading state
        {
            let mut state = self.loading_state.lock().unwrap();
            state.in_progress = true;
        }

        self.pending_load_path = Some(path.clone());

        // Clone Arc and Context for background thread
        let loading_state = Arc::clone(&self.loading_state);
        let ctx_handle = ctx.clone();
        let path_string = path.to_str().unwrap().to_owned();

        // Spawn background thread for file loading
        thread::spawn(move || {
            // Determine which reader to use based on file extension
            let reader: Box<dyn TraceReader> = if path_string.ends_with(".pt") || path_string.ends_with(".pt.gz") {
                Box::new(PipetraceReader::new())
            } else {
                Box::new(JetsTraceReader::new())
            };

            // Parse the trace file (blocking operation)
            let parse_result = reader.read(&path_string);

            // Convert Result<Box<dyn TraceData>, anyhow::Error> to Result<Box<dyn TraceData>, String>
            let result = parse_result.map_err(|e| e.to_string());

            // Send result through channel
            let _ = sender.send(result);

            // Update loading state
            {
                let mut state = loading_state.lock().unwrap();
                state.in_progress = false;
            }

            // Notify GUI thread to repaint
            ctx_handle.request_repaint();
        });
    }

    /// Generates and loads a virtual trace in-memory.
    ///
    /// This is useful for testing and demonstration purposes.
    /// The virtual trace is generated synchronously (no background thread).
    ///
    /// # Returns
    /// * `Ok(data)` - Successfully generated virtual trace
    /// * `Err(msg)` - Error generating the trace
    pub fn load_virtual_trace(&mut self) -> Result<DynTraceData, String> {
        let virtual_reader = VirtualTraceReader::new();
        virtual_reader.read("").map_err(|e| e.to_string())
    }

    /// Checks if background loading has completed and returns the result if available.
    ///
    /// This should be called once per frame in the update loop to check for completion.
    ///
    /// # Returns
    /// * `LoadResult::Success` - Loading completed successfully
    /// * `LoadResult::Error` - Loading failed with an error
    /// * `LoadResult::None` - No result available (still loading or no operation active)
    pub fn check_completion(&mut self) -> LoadResult {
        // Try to receive result from channel
        if let Some(receiver) = &self.loading_receiver {
            if let Ok(result) = receiver.try_recv() {
                // Process the result
                let load_result = match result {
                    Ok(data) => {
                        // Success: Return data and path
                        let path = self.pending_load_path.take();
                        LoadResult::Success { data, path }
                    }
                    Err(error_msg) => {
                        // Error: Return error message
                        self.pending_load_path = None;
                        LoadResult::Error(error_msg)
                    }
                };

                // Clear the receiver after processing
                self.loading_receiver = None;

                return load_result;
            }
        }

        LoadResult::None
    }

}

impl Default for AsyncLoader {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_async_loader_creation() {
        let loader = AsyncLoader::new();
        assert!(!loader.is_loading());
    }

    #[test]
    fn test_virtual_trace_loading() {
        let mut loader = AsyncLoader::new();
        let result = loader.load_virtual_trace();
        assert!(result.is_ok(), "Virtual trace loading should succeed");
    }

    #[test]
    fn test_check_completion_when_idle() {
        let mut loader = AsyncLoader::new();
        let result = loader.check_completion();
        matches!(result, LoadResult::None);
    }

}
