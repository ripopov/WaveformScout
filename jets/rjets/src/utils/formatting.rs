//! Text formatting utilities for the JETS trace viewer.
//!
//! This module provides helper functions for formatting values in a human-readable way.

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

