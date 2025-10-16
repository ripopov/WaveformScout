//! Virtual scrolling data structures and constants.
//!
//! This module provides types and constants used by the virtual scrolling system
//! for efficient rendering of large hierarchical trees.
//!
//! The actual traversal logic has been moved to the visibility strategy system
//! in the domain module.

/// Row height in pixels (consistent across tree and timeline views)
pub const ROW_HEIGHT: f32 = 22.0;

/// Number of rows to render above/below viewport for smooth scrolling
pub const VIEWPORT_BUFFER_ROWS: usize = 10;

/// Represents a visible node in the flattened tree view.
///
/// Used by the virtual scrolling system to track which nodes are currently
/// visible in the viewport, allowing efficient rendering of large trees.
pub struct VisibleNode {
    /// The unique identifier of the record
    pub record_id: u64,

    /// The depth of this node in the tree hierarchy (0 for root)
    pub depth: usize,

    /// The row index in the flattened view
    pub row_index: usize,

    /// Tree branch context: For each depth level (0 to depth-1), indicates
    /// whether there are more siblings below this node at that level.
    /// Used to draw tree branch lines (│ for continuing branches, space for none).
    pub branch_context: Vec<bool>,

    /// Whether this is the last child of its parent
    pub is_last_child: bool,
}
