//! State management modules for the JETS trace viewer.
//!
//! This module contains state-only logic (no UI concerns):
//! - Trace state (trace data, file path, trace extent)
//! - Viewport state (clock ranges, zoom levels)
//! - Selection state (selected records, events)
//! - Tree state (expansion, visibility)
//! - Interaction state (drag, hover, selection regions)
//! - Theme state (theme manager, current theme)
//! - Layout state (split ratios, column widths)

mod trace_state;
mod viewport;
mod selection;
mod tree_state;
mod interaction;
mod theme_state;
mod layout_state;

pub use trace_state::TraceState;
pub use viewport::ViewportState;
pub use selection::SelectionState;
pub use tree_state::TreeState;
pub use interaction::InteractionState;
pub use theme_state::ThemeState;
pub use layout_state::LayoutState;
