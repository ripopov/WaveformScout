//! Text formatting utilities for the JETS trace viewer.
//!
//! This module provides helper functions for formatting values in a human-readable way.

use sysinfo::{System, RefreshKind, ProcessRefreshKind, Pid};

/// Formats a clock value as a string with thousands separators for readability.
///
/// # Examples
/// ```
/// assert_eq!(format_clock(1000), "1,000");
/// assert_eq!(format_clock(1234567), "1,234,567");
/// ```
pub fn format_clock(clk: i64) -> String {
    let s = clk.to_string();
    let mut result = String::new();
    let chars: Vec<char> = s.chars().collect();
    for (i, ch) in chars.iter().enumerate() {
        if i > 0 && (chars.len() - i) % 3 == 0 {
            result.push(',');
        }
        result.push(*ch);
    }
    result
}

/// Gets the current process memory usage in megabytes.
///
/// Returns 0.0 if the process information cannot be retrieved.
///
/// # Examples
/// ```
/// let memory = get_current_memory_mb();
/// assert!(memory >= 0.0);
/// ```
pub fn get_current_memory_mb() -> f64 {
    let mut sys = System::new_with_specifics(
        RefreshKind::new().with_processes(ProcessRefreshKind::new().with_memory())
    );
    sys.refresh_processes_specifics(ProcessRefreshKind::new().with_memory());

    if let Some(process) = sys.process(Pid::from_u32(std::process::id())) {
        process.memory() as f64 / (1024.0 * 1024.0)
    } else {
        0.0
    }
}

/// Formats memory usage in MB as a human-readable string.
///
/// # Arguments
/// * `memory_mb` - Memory usage in megabytes
///
/// # Examples
/// ```
/// assert_eq!(format_memory_mb(512.5), "Memory: 512.5 MB");
/// assert_eq!(format_memory_mb(2048.0), "Memory: 2.00 GB");
/// ```
pub fn format_memory_mb(memory_mb: f64) -> String {
    if memory_mb > 1024.0 {
        format!("Memory: {:.2} GB", memory_mb / 1024.0)
    } else {
        format!("Memory: {:.1} MB", memory_mb)
    }
}

