//! Asynchronous file loading state management.

/// Holds the state of an async file loading operation.
///
/// Only the in_progress flag is shared; results come through a channel.
/// This struct is wrapped in an `Arc<Mutex<>>` to allow safe sharing between
/// the main thread and background loading thread.
pub struct LoadingState {
    /// True if a file loading operation is currently in progress
    pub in_progress: bool,
}

impl LoadingState {
    /// Creates a new loading state that is not in progress.
    pub fn new() -> Self {
        Self {
            in_progress: false,
        }
    }
}

impl Default for LoadingState {
    fn default() -> Self {
        Self::new()
    }
}
