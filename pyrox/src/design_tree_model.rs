// Design Tree Model - High-performance hierarchical tree for waveform viewers
//
// This module provides a Rust implementation of a tree model that efficiently
// handles large design hierarchies with millions of variables and scopes.
// It is designed to work with Qt's QAbstractItemModel interface while remaining
// framework-agnostic for broader applicability.

use std::sync::Arc;

use pyo3::prelude::*;
use wellen::{Hierarchy as WellenHierarchy, ScopeRef, VarRef};

use crate::{Hierarchy, SignalHandle, Var, Scope};

/// Represents a node reference in the design tree
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NodeRef {
    /// Root node (virtual node containing top-level scopes)
    Root,
    /// Reference to a scope in the hierarchy
    Scope(ScopeRef),
    /// Reference to a variable in the hierarchy
    Var(VarRef),
}

/// Lazy wrapper around wellen hierarchy for tree model operations
pub struct DesignTreeModel {
    /// Shared reference to the hierarchy
    hierarchy: Arc<WellenHierarchy>,
}

impl DesignTreeModel {
    /// Create a new tree model from a wellen hierarchy
    pub fn new(hierarchy: Arc<WellenHierarchy>) -> Self {
        DesignTreeModel { hierarchy }
    }

    /// Get a node reference for a child at the given row under parent
    fn get_child_ref(&self, parent: NodeRef, row: usize) -> Option<NodeRef> {
        match parent {
            NodeRef::Root => {
                // Get top-level scopes
                self.hierarchy.scopes().nth(row).map(NodeRef::Scope)
            }
            NodeRef::Scope(scope_ref) => {
                let scope = &self.hierarchy[scope_ref];
                // First check variables, then child scopes
                let var_count = scope.vars(&self.hierarchy).count();
                if row < var_count {
                    scope.vars(&self.hierarchy).nth(row).map(NodeRef::Var)
                } else {
                    scope.scopes(&self.hierarchy).nth(row - var_count).map(NodeRef::Scope)
                }
            }
            NodeRef::Var(_) => None, // Variables have no children
        }
    }

    /// Get parent node reference
    fn get_parent_ref(&self, node: NodeRef) -> Option<NodeRef> {
        match node {
            NodeRef::Root => None,
            NodeRef::Scope(scope_ref) => {
                // Get the parent scope directly from the scope
                let scope = &self.hierarchy[scope_ref];
                if let Some(parent_ref) = scope.parent(&self.hierarchy) {
                    Some(NodeRef::Scope(parent_ref))
                } else {
                    // Top-level scope
                    Some(NodeRef::Root)
                }
            }
            NodeRef::Var(var_ref) => {
                // Get the parent scope directly from the variable
                let var = &self.hierarchy[var_ref];
                var.parent(&self.hierarchy).map(NodeRef::Scope)
            }
        }
    }



    /// Get row of a child node within its parent
    fn get_row_of_child_ref(&self, parent: NodeRef, child: NodeRef) -> Option<usize> {
        match parent {
            NodeRef::Root => {
                if let NodeRef::Scope(scope_ref) = child {
                    self.hierarchy.scopes().position(|s| s == scope_ref)
                } else {
                    None
                }
            }
            NodeRef::Scope(parent_scope_ref) => {
                let parent_scope = &self.hierarchy[parent_scope_ref];
                match child {
                    NodeRef::Var(var_ref) => {
                        parent_scope.vars(&self.hierarchy).position(|v| v == var_ref)
                    }
                    NodeRef::Scope(scope_ref) => {
                        let var_count = parent_scope.vars(&self.hierarchy).count();
                        parent_scope.scopes(&self.hierarchy)
                            .position(|s| s == scope_ref)
                            .map(|pos| var_count + pos)
                    }
                    _ => None,
                }
            }
            NodeRef::Var(_) => None,
        }
    }

    /// Get number of children for a node
    fn row_count_ref(&self, node: NodeRef) -> usize {
        match node {
            NodeRef::Root => self.hierarchy.scopes().count(),
            NodeRef::Scope(scope_ref) => {
                let scope = &self.hierarchy[scope_ref];
                scope.vars(&self.hierarchy).count() + scope.scopes(&self.hierarchy).count()
            }
            NodeRef::Var(_) => 0,
        }
    }

    /// Get display name for a node
    fn get_name(&self, node: NodeRef) -> String {
        match node {
            NodeRef::Root => "ROOT".to_string(),
            NodeRef::Scope(scope_ref) => {
                self.hierarchy[scope_ref].name(&self.hierarchy).to_string()
            }
            NodeRef::Var(var_ref) => {
                self.hierarchy[var_ref].name(&self.hierarchy).to_string()
            }
        }
    }

    /// Get type string for a node
    fn get_type_string(&self, node: NodeRef) -> Option<String> {
        match node {
            NodeRef::Root => Some("root".to_string()),
            NodeRef::Scope(scope_ref) => {
                Some(format!("{:?}", self.hierarchy[scope_ref].scope_type()).to_lowercase())
            }
            NodeRef::Var(var_ref) => {
                Some(format!("{:?}", self.hierarchy[var_ref].var_type()).to_lowercase())
            }
        }
    }

    /// Get bit range for a node
    fn get_bit_range(&self, node: NodeRef) -> Option<String> {
        if let NodeRef::Var(var_ref) = node {
            let var = &self.hierarchy[var_ref];
            var.length().and_then(|width| {
                if width > 1 {
                    if let Some(index) = var.index() {
                        Some(format!("[{}:{}]", index.msb(), index.lsb()))
                    } else {
                        Some(format!("[{}:0]", width - 1))
                    }
                } else {
                    None
                }
            })
        } else {
            None
        }
    }

    /// Get signal handle for a variable node
    fn get_signal_handle(&self, node: NodeRef) -> Option<SignalHandle> {
        if let NodeRef::Var(var_ref) = node {
            let var = &self.hierarchy[var_ref];
            let sig_ref = var.signal_ref();
            Some(sig_ref.index() as SignalHandle)
        } else {
            None
        }
    }

    /// Get full hierarchical path for a node
    fn get_full_path(&self, node: NodeRef) -> String {
        match node {
            NodeRef::Root => String::new(),
            NodeRef::Scope(scope_ref) => {
                self.hierarchy[scope_ref].full_name(&self.hierarchy).to_string()
            }
            NodeRef::Var(var_ref) => {
                self.hierarchy[var_ref].full_name(&self.hierarchy).to_string()
            }
        }
    }

    /// Find node by hierarchical path
    fn find_node_by_path(&self, path: &str) -> Option<NodeRef> {
        if path.is_empty() {
            return Some(NodeRef::Root);
        }

        // Split path into parts
        let parts: Vec<&str> = path.split('.').collect();
        if parts.is_empty() {
            return None;
        }

        // Try to find as variable using lookup_var
        let (scope_path, var_name) = if parts.len() == 1 {
            (&[][..], parts[0])
        } else {
            (&parts[..parts.len() - 1], parts[parts.len() - 1])
        };

        if let Some(var_ref) = self.hierarchy.lookup_var(scope_path, &var_name) {
            return Some(NodeRef::Var(var_ref));
        }

        // Try to find as scope by traversing the hierarchy
        let mut current_scopes: Vec<ScopeRef> = self.hierarchy.scopes().collect();

        for (i, part) in parts.iter().enumerate() {
            let mut found_scope = None;
            for scope_ref in &current_scopes {
                let scope = &self.hierarchy[*scope_ref];
                if scope.name(&self.hierarchy) == *part {
                    found_scope = Some(*scope_ref);
                    break;
                }
            }

            if let Some(scope_ref) = found_scope {
                if i == parts.len() - 1 {
                    // This is the final part - we found the scope
                    return Some(NodeRef::Scope(scope_ref));
                }
                // Get child scopes for next iteration
                current_scopes = self.hierarchy[scope_ref].scopes(&self.hierarchy).collect();
            } else {
                return None;
            }
        }

        None
    }
}

/// Python bindings for the DesignTreeModel
///
/// We encode NodeRef as a u64 integer for Python interop:
/// - 0 = Root node
/// - 1..=0x7FFF_FFFF_FFFF_FFFF = Scope nodes (ScopeRef index + 1)
/// - 0x8000_0000_0000_0000..=0xFFFF_FFFF_FFFF_FFFF = Var nodes (VarRef index | 0x8000_0000_0000_0000)
#[pyclass]
pub struct PyDesignTreeModel {
    inner: Arc<DesignTreeModel>,
}

impl PyDesignTreeModel {
    /// Encode a NodeRef as a u64 for Python
    fn encode_node_ref(node: NodeRef) -> u64 {
        match node {
            NodeRef::Root => 0,
            NodeRef::Scope(scope_ref) => (scope_ref.index() as u64) + 1,
            NodeRef::Var(var_ref) => (var_ref.index() as u64) | 0x8000_0000_0000_0000,
        }
    }

    /// Decode a u64 from Python as a NodeRef
    fn decode_node_ref(idx: u64) -> NodeRef {
        if idx == 0 {
            NodeRef::Root
        } else if idx & 0x8000_0000_0000_0000 != 0 {
            // Variable node
            let var_idx = ((idx & 0x7FFF_FFFF_FFFF_FFFF) as usize);
            NodeRef::Var(VarRef::from_index(var_idx).expect("Invalid VarRef index"))
        } else {
            // Scope node
            let scope_idx = ((idx - 1) as usize);
            NodeRef::Scope(ScopeRef::from_index(scope_idx).expect("Invalid ScopeRef index"))
        }
    }
}

#[pymethods]
impl PyDesignTreeModel {
    /// Create a new design tree model from a hierarchy
    #[new]
    pub fn new(hierarchy: &Hierarchy) -> Self {
        Self {
            inner: Arc::new(DesignTreeModel::new(hierarchy.0.clone())),
        }
    }

    /// Get node index for a child at the given row under parent
    #[pyo3(signature = (row, _column, parent_idx=None))]
    pub fn index(&self, row: usize, _column: usize, parent_idx: Option<u64>) -> Option<u64> {
        let parent_ref = parent_idx.map(Self::decode_node_ref).unwrap_or(NodeRef::Root);
        self.inner.get_child_ref(parent_ref, row)
            .map(Self::encode_node_ref)
    }

    /// Get parent index for a node
    pub fn parent(&self, node_idx: u64) -> Option<u64> {
        let node_ref = Self::decode_node_ref(node_idx);
        self.inner.get_parent_ref(node_ref)
            .map(Self::encode_node_ref)
    }

    /// Get row of a child node within its parent
    #[pyo3(signature = (parent_idx, child_idx))]
    pub fn get_row_of_child(&self, parent_idx: Option<u64>, child_idx: u64) -> Option<usize> {
        let parent_ref = parent_idx.map(Self::decode_node_ref).unwrap_or(NodeRef::Root);
        let child_ref = Self::decode_node_ref(child_idx);
        self.inner.get_row_of_child_ref(parent_ref, child_ref)
    }

    /// Get number of children for a parent
    #[pyo3(signature = (parent_idx=None))]
    pub fn row_count(&self, parent_idx: Option<u64>) -> usize {
        let node_ref = parent_idx.map(Self::decode_node_ref).unwrap_or(NodeRef::Root);
        self.inner.row_count_ref(node_ref)
    }

    /// Get number of columns (always 3)
    pub fn column_count(&self) -> usize {
        3
    }

    /// Get display text for a node and column
    pub fn get_display_text(&self, node_idx: u64, column: usize) -> Option<String> {
        let node_ref = Self::decode_node_ref(node_idx);
        match column {
            0 => Some(self.inner.get_name(node_ref)),
            1 => self.inner.get_type_string(node_ref),
            2 => self.inner.get_bit_range(node_ref),
            _ => None,
        }
    }

    /// Check if node is a scope
    pub fn is_scope(&self, node_idx: u64) -> bool {
        let node_ref = Self::decode_node_ref(node_idx);
        matches!(node_ref, NodeRef::Root | NodeRef::Scope(_))
    }

    /// Get signal handle for a node
    pub fn get_var_handle(&self, node_idx: u64) -> Option<SignalHandle> {
        let node_ref = Self::decode_node_ref(node_idx);
        self.inner.get_signal_handle(node_ref)
    }

    /// Get Var object for a node
    pub fn get_var(&self, node_idx: u64) -> Option<Var> {
        let node_ref = Self::decode_node_ref(node_idx);
        if let NodeRef::Var(var_ref) = node_ref {
            Some(Var(self.inner.hierarchy[var_ref].clone()))
        } else {
            None
        }
    }

    /// Get Scope object for a node
    pub fn get_scope(&self, node_idx: u64) -> Option<Scope> {
        let node_ref = Self::decode_node_ref(node_idx);
        if let NodeRef::Scope(scope_ref) = node_ref {
            Some(Scope(self.inner.hierarchy[scope_ref].clone()))
        } else {
            None
        }
    }

    /// Get scope type for a scope node
    pub fn get_scope_type(&self, node_idx: u64) -> Option<String> {
        let node_ref = Self::decode_node_ref(node_idx);
        if let NodeRef::Scope(_) = node_ref {
            self.inner.get_type_string(node_ref)
        } else {
            None
        }
    }

    /// Find node by hierarchical path
    pub fn find_by_path(&self, path: &str) -> Option<u64> {
        self.inner.find_node_by_path(path)
            .map(Self::encode_node_ref)
    }

    /// Get full path for a node
    pub fn get_full_path(&self, node_idx: u64) -> Option<String> {
        let node_ref = Self::decode_node_ref(node_idx);
        Some(self.inner.get_full_path(node_ref))
    }
}