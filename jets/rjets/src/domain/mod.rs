//! Domain logic modules for JETS trace viewer.
//!
//! This module contains core business logic:
//! - Tree operations (hierarchy traversal, node queries, size calculations)
//! - Viewport operations (coordinate transformations, clock-to-pixel conversions)
//! - Visibility strategies (policy-driven tree traversal filtering)

pub mod tree_operations;
pub mod viewport_operations;
pub mod visibility;
