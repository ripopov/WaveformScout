//! Utility modules for the JETS trace viewer.

pub mod formatting;
pub mod geometry;

// Re-export commonly used functions
pub use formatting::{format_clock, get_current_memory_mb, format_memory_mb};
