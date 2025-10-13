//! Tree expansion state management.
//!
//! This module encapsulates all state related to the tree view,
//! specifically which nodes are expanded or collapsed.

use std::collections::HashSet;

/// State related to tree node expansion.
///
/// Responsibilities:
/// - Tracking which tree nodes are expanded
/// - Providing intent-revealing expansion queries
/// - Managing bulk expansion operations
#[derive(Debug, Clone, Default)]
pub struct TreeState {
    /// Set of expanded node IDs
    expanded_nodes: HashSet<u64>,
}

impl TreeState {
    /// Creates a new tree state with no expanded nodes.
    pub fn new() -> Self {
        Self {
            expanded_nodes: HashSet::new(),
        }
    }

    /// Clears all expansion state (collapses all nodes).
    pub fn clear(&mut self) {
        self.expanded_nodes.clear();
    }

    // ===== Expansion Queries =====

    /// Returns true if the given node is expanded.
    pub fn is_expanded(&self, node_id: u64) -> bool {
        self.expanded_nodes.contains(&node_id)
    }

    /// Returns the number of expanded nodes.
    pub fn expanded_count(&self) -> usize {
        self.expanded_nodes.len()
    }

    /// Returns true if any nodes are expanded.
    pub fn has_expanded_nodes(&self) -> bool {
        !self.expanded_nodes.is_empty()
    }

    /// Returns an iterator over expanded node IDs.
    pub fn expanded_nodes(&self) -> impl Iterator<Item = &u64> {
        self.expanded_nodes.iter()
    }

    /// Returns a reference to the set of expanded node IDs.
    ///
    /// This is useful for virtual scrolling and other performance-critical
    /// operations that need direct access to the HashSet.
    pub fn expanded_nodes_set(&self) -> &HashSet<u64> {
        &self.expanded_nodes
    }

    // ===== Expansion Mutations =====

    /// Expands the given node.
    ///
    /// # Arguments
    /// * `node_id` - The node to expand
    ///
    /// # Returns
    /// `true` if the node was newly expanded, `false` if already expanded.
    pub fn expand(&mut self, node_id: u64) -> bool {
        self.expanded_nodes.insert(node_id)
    }

    /// Collapses the given node.
    ///
    /// # Arguments
    /// * `node_id` - The node to collapse
    ///
    /// # Returns
    /// `true` if the node was expanded and is now collapsed, `false` if already collapsed.
    pub fn collapse(&mut self, node_id: u64) -> bool {
        self.expanded_nodes.remove(&node_id)
    }

    /// Toggles the expansion state of the given node.
    ///
    /// # Arguments
    /// * `node_id` - The node to toggle
    ///
    /// # Returns
    /// `true` if the node is now expanded, `false` if now collapsed.
    pub fn toggle(&mut self, node_id: u64) -> bool {
        if self.expanded_nodes.contains(&node_id) {
            self.expanded_nodes.remove(&node_id);
            false
        } else {
            self.expanded_nodes.insert(node_id);
            true
        }
    }

    /// Expands multiple nodes at once.
    ///
    /// # Arguments
    /// * `node_ids` - Iterator of node IDs to expand
    pub fn expand_many(&mut self, node_ids: impl IntoIterator<Item = u64>) {
        self.expanded_nodes.extend(node_ids);
    }

    /// Collapses multiple nodes at once.
    ///
    /// # Arguments
    /// * `node_ids` - Iterator of node IDs to collapse
    pub fn collapse_many(&mut self, node_ids: impl IntoIterator<Item = u64>) {
        for node_id in node_ids {
            self.expanded_nodes.remove(&node_id);
        }
    }

    /// Expands all nodes in the given set (replaces current expansion state).
    ///
    /// # Arguments
    /// * `node_ids` - The complete set of nodes to expand
    pub fn set_expanded(&mut self, node_ids: HashSet<u64>) {
        self.expanded_nodes = node_ids;
    }
}
