//! UI panel rendering subsystem
//!
//! This module contains all UI panel rendering logic for the JETS trace viewer:
//! - Header panel (file controls, zoom, theme selector)
//! - Tree panel (hierarchical signal view)
//! - Timeline panel (temporal view with panning and zooming)
//! - Details panel (record details, annotations, events)
//! - Status bar (trace metadata display)
//! - Table header component (resizable column headers)
//! - Virtual scroll manager (shared scrolling logic)
//! - Panel manager (panel orchestration and layout)

pub mod header;
pub mod tree_panel;
pub mod timeline_panel;
pub mod details_panel;
pub mod status_bar;
pub mod table_header;
pub mod virtual_scroll_manager;
pub mod panel_manager;
