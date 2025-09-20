// Design Tree Model - High-performance hierarchical tree for waveform viewers
//
// This module provides a Rust implementation of a tree model that efficiently
// handles large design hierarchies with millions of variables and scopes.
// It is designed to work with Qt's QAbstractItemModel interface while remaining
// framework-agnostic for broader applicability.

use std::collections::HashMap;
use std::sync::Arc;

use pyo3::prelude::*;
use wellen::{Hierarchy as WellenHierarchy, ScopeRef, VarRef};

use crate::{Hierarchy, SignalHandle, Var, Scope};

/// Represents a single node in the design tree
#[derive(Debug, Clone)]
pub struct TreeNode {
    /// Display name of the node
    pub name: String,
    /// True if this is a scope (module), false if it's a signal
    pub is_scope: bool,
    /// Signal type (e.g., "wire", "reg") or scope type
    pub var_type: Option<String>,
    /// Bit range for multi-bit signals (e.g., "[31:0]")
    pub bit_range: Option<String>,
    /// Index of parent node in the nodes vector
    pub parent_idx: Option<usize>,
    /// Indices of child nodes
    pub children: Vec<usize>,
    /// Reference to wellen variable (for signals)
    pub var_ref: Option<VarRef>,
    /// Reference to wellen scope (for scopes)
    pub scope_ref: Option<ScopeRef>,
    /// Signal handle for database lookups (0-based index)
    pub signal_handle: Option<SignalHandle>,
    /// Full hierarchical path for fast lookups
    pub full_path: String,
}

/// High-performance tree model for design hierarchies
pub struct DesignTreeModel {
    /// Flat storage of all tree nodes for cache efficiency
    nodes: Vec<TreeNode>,
    /// Index of the root node
    root_idx: usize,
    /// Shared reference to the hierarchy
    hierarchy: Arc<WellenHierarchy>,
    /// Mapping from variable index to signal handle for fast lookups
    var_to_handle: HashMap<u32, SignalHandle>,
    /// Mapping from full path to node index for navigation
    path_to_node: HashMap<String, usize>,
}

impl DesignTreeModel {
    /// Create a new tree model from a wellen hierarchy
    pub fn new(hierarchy: Arc<WellenHierarchy>) -> Self {
        let mut model = DesignTreeModel {
            nodes: Vec::new(),
            root_idx: 0,
            hierarchy: hierarchy.clone(),
            var_to_handle: HashMap::new(),
            path_to_node: HashMap::new(),
        };

        // Create root node
        let root_node = TreeNode {
            name: "ROOT".to_string(),
            is_scope: true,
            var_type: Some("root".to_string()),
            bit_range: None,
            parent_idx: None,
            children: Vec::new(),
            var_ref: None,
            scope_ref: None,
            signal_handle: None,
            full_path: "".to_string(),
        };
        model.nodes.push(root_node);

        // Build the tree from top-level scopes
        let top_scopes: Vec<ScopeRef> = hierarchy.scopes().collect();
        for scope_ref in top_scopes {
            model.build_scope_recursive(scope_ref, 0, "".to_string());
        }

        model
    }

    /// Recursively build tree nodes for a scope and its contents
    fn build_scope_recursive(&mut self, scope_ref: ScopeRef, parent_idx: usize, parent_path: String) {
        let scope = &self.hierarchy[scope_ref];
        let scope_name = scope.name(&self.hierarchy).to_string();

        // Build full path for this scope
        let full_path = if parent_path.is_empty() {
            scope_name.clone()
        } else {
            format!("{}.{}", parent_path, scope_name)
        };

        // Create node for this scope
        let scope_node_idx = self.nodes.len();
        let scope_node = TreeNode {
            name: scope_name,
            is_scope: true,
            var_type: Some(format!("{:?}", scope.scope_type()).to_lowercase()),
            bit_range: None,
            parent_idx: Some(parent_idx),
            children: Vec::new(),
            var_ref: None,
            scope_ref: Some(scope_ref),
            signal_handle: None,
            full_path: full_path.clone(),
        };
        self.nodes.push(scope_node);
        self.path_to_node.insert(full_path.clone(), scope_node_idx);

        // Add this scope to parent's children
        self.nodes[parent_idx].children.push(scope_node_idx);

        // Process variables in this scope
        for var_ref in scope.vars(&self.hierarchy) {
            let var = &self.hierarchy[var_ref];
            let var_name = var.name(&self.hierarchy).to_string();
            let var_full_path = format!("{}.{}", full_path, var_name);

            // Calculate bit range if multi-bit signal
            let bit_range = var.length().and_then(|width| {
                if width > 1 {
                    // Check for variable index to get actual MSB/LSB
                    if let Some(index) = var.index() {
                        Some(format!("[{}:{}]", index.msb(), index.lsb()))
                    } else {
                        // Default to [width-1:0] if no explicit index
                        Some(format!("[{}:0]", width - 1))
                    }
                } else {
                    None
                }
            });

            // Get signal handle from signal reference
            let signal_handle = {
                let sig_ref = var.signal_ref();
                let sig_idx = sig_ref.index();
                Some(sig_idx as SignalHandle)
            };

            // Store var to handle mapping (use var_ref index as u32)
            if let Some(handle) = signal_handle {
                self.var_to_handle.insert(var_ref.index() as u32, handle);
            }

            // Create node for this variable
            let var_node_idx = self.nodes.len();
            let var_node = TreeNode {
                name: var_name,
                is_scope: false,
                var_type: Some(format!("{:?}", var.var_type()).to_lowercase()),
                bit_range,
                parent_idx: Some(scope_node_idx),
                children: Vec::new(),
                var_ref: Some(var_ref),
                scope_ref: None,
                signal_handle,
                full_path: var_full_path.clone(),
            };
            self.nodes.push(var_node);
            self.path_to_node.insert(var_full_path, var_node_idx);

            // Add to parent scope's children
            self.nodes[scope_node_idx].children.push(var_node_idx);
        }

        // Recursively process child scopes
        let child_scopes: Vec<ScopeRef> = scope.scopes(&self.hierarchy).collect();
        for child_ref in child_scopes {
            self.build_scope_recursive(child_ref, scope_node_idx, full_path.clone());
        }
    }

    /// Get node at specified index
    pub fn get_node(&self, idx: usize) -> Option<&TreeNode> {
        self.nodes.get(idx)
    }

    /// Get node index for a child at the given row under parent
    pub fn index(&self, row: usize, _column: usize, parent_idx: Option<usize>) -> Option<usize> {
        let parent_idx = parent_idx.unwrap_or(self.root_idx);
        let parent_node = self.nodes.get(parent_idx)?;
        parent_node.children.get(row).copied()
    }

    /// Get parent index for a node
    pub fn parent(&self, node_idx: usize) -> Option<usize> {
        self.nodes.get(node_idx)?.parent_idx
    }

    /// Get row of a child node within its parent
    pub fn get_row_of_child(&self, parent_idx: Option<usize>, child_idx: usize) -> Option<usize> {
        let parent_idx = parent_idx.unwrap_or(self.root_idx);
        let parent_node = self.nodes.get(parent_idx)?;
        parent_node.children.iter().position(|&idx| idx == child_idx)
    }

    /// Get number of children for a parent
    pub fn row_count(&self, parent_idx: Option<usize>) -> usize {
        let parent_idx = parent_idx.unwrap_or(self.root_idx);
        self.nodes.get(parent_idx)
            .map(|node| node.children.len())
            .unwrap_or(0)
    }

    /// Get number of columns (always 3: Name, Type, Bit Range)
    pub fn column_count(&self) -> usize {
        3
    }

    /// Get display text for a node and column
    pub fn get_display_text(&self, node_idx: usize, column: usize) -> Option<String> {
        let node = self.nodes.get(node_idx)?;
        match column {
            0 => Some(node.name.clone()),
            1 => node.var_type.clone(),
            2 => node.bit_range.clone(),
            _ => None,
        }
    }

    /// Check if node is a scope
    pub fn is_scope(&self, node_idx: usize) -> bool {
        self.nodes.get(node_idx)
            .map(|node| node.is_scope)
            .unwrap_or(false)
    }

    /// Get signal handle for a node
    pub fn get_var_handle(&self, node_idx: usize) -> Option<SignalHandle> {
        self.nodes.get(node_idx)?.signal_handle
    }

    /// Find node by hierarchical path
    pub fn find_node_by_path(&self, path: &str) -> Option<usize> {
        self.path_to_node.get(path).copied()
    }

    /// Get the hierarchy reference
    pub fn hierarchy(&self) -> &Arc<WellenHierarchy> {
        &self.hierarchy
    }

    /// Get variable reference for a node
    pub fn get_var_ref(&self, node_idx: usize) -> Option<VarRef> {
        self.nodes.get(node_idx)?.var_ref
    }

    /// Get scope reference for a node
    pub fn get_scope_ref(&self, node_idx: usize) -> Option<ScopeRef> {
        self.nodes.get(node_idx)?.scope_ref
    }

    /// Get scope type for a scope node
    pub fn get_scope_type(&self, node_idx: usize) -> Option<String> {
        let node = self.nodes.get(node_idx)?;
        if node.is_scope {
            node.var_type.clone()
        } else {
            None
        }
    }
}

/// Python bindings for the DesignTreeModel
#[pyclass]
pub struct PyDesignTreeModel {
    inner: Arc<DesignTreeModel>,
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
    #[pyo3(signature = (row, column, parent_idx=None))]
    pub fn index(&self, row: usize, column: usize, parent_idx: Option<usize>) -> Option<usize> {
        self.inner.index(row, column, parent_idx)
    }

    /// Get parent index for a node
    pub fn parent(&self, node_idx: usize) -> Option<usize> {
        self.inner.parent(node_idx)
    }

    /// Get row of a child node within its parent
    #[pyo3(signature = (parent_idx, child_idx))]
    pub fn get_row_of_child(&self, parent_idx: Option<usize>, child_idx: usize) -> Option<usize> {
        self.inner.get_row_of_child(parent_idx, child_idx)
    }

    /// Get number of children for a parent
    #[pyo3(signature = (parent_idx=None))]
    pub fn row_count(&self, parent_idx: Option<usize>) -> usize {
        self.inner.row_count(parent_idx)
    }

    /// Get number of columns (always 3)
    pub fn column_count(&self) -> usize {
        self.inner.column_count()
    }

    /// Get display text for a node and column
    pub fn get_display_text(&self, node_idx: usize, column: usize) -> Option<String> {
        self.inner.get_display_text(node_idx, column)
    }

    /// Check if node is a scope
    pub fn is_scope(&self, node_idx: usize) -> bool {
        self.inner.is_scope(node_idx)
    }

    /// Get signal handle for a node
    pub fn get_var_handle(&self, node_idx: usize) -> Option<SignalHandle> {
        self.inner.get_var_handle(node_idx)
    }

    /// Get Var object for a node
    pub fn get_var(&self, node_idx: usize) -> Option<Var> {
        self.inner.get_var_ref(node_idx)
            .map(|var_ref| Var(self.inner.hierarchy()[var_ref].clone()))
    }

    /// Get Scope object for a node
    pub fn get_scope(&self, node_idx: usize) -> Option<Scope> {
        self.inner.get_scope_ref(node_idx)
            .map(|scope_ref| Scope(self.inner.hierarchy()[scope_ref].clone()))
    }

    /// Get scope type for a scope node
    pub fn get_scope_type(&self, node_idx: usize) -> Option<String> {
        self.inner.get_scope_type(node_idx)
    }

    /// Find node by hierarchical path
    pub fn find_by_path(&self, path: &str) -> Option<usize> {
        self.inner.find_node_by_path(path)
    }

    /// Get full path for a node
    pub fn get_full_path(&self, node_idx: usize) -> Option<String> {
        self.inner.get_node(node_idx).map(|node| node.full_path.clone())
    }
}