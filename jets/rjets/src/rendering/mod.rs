//! Rendering subsystem for drawing trace visualizations
//!
//! This module contains all rendering logic for the JETS trace viewer:
//! - Tree node rendering (hierarchical view)
//! - Timeline row rendering (temporal view)
//! - Time axis rendering (clock labels and tick marks)
//! - Timeline overlays (cursor line, region selection)

pub mod tree_renderer;
pub mod timeline_renderer;
pub mod time_axis_renderer;
pub mod timeline_overlays;
