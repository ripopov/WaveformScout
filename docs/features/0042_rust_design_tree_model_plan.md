# Rust DesignTreeModel Implementation Plan

## Executive Summary

This plan details moving the DesignTreeModel implementation from Python to Rust/pyrox to address severe performance issues with waveforms containing millions of variables and scopes. While wellen loads hierarchies quickly, building the tree in Python becomes a bottleneck. The Rust implementation will satisfy Qt's QAbstractItemModel requirements while remaining framework-agnostic for broader applicability.

**Performance Impact**: Expected 10-100x speedup for hierarchy tree building with large designs
**Risk**: Medium - requires careful FFI design to satisfy Qt model contract
**Scope**: New Rust implementation in pyrox, minimal Python wrapper in wavescout

## 1. Use Cases and Requirements Analysis

### Core Problem
- Current Python DesignTreeModel builds hierarchy tree slowly for large designs (millions of variables/scopes)
- The bottleneck is Python iteration over wellen hierarchy data and tree node construction
- Wellen loads the hierarchy quickly in Rust, but Python tree building negates this performance

### Specific Requirements from User
1. **Rust Implementation**: pyrox will implement DesignTreeModel meeting QAbstractItemModel requirements
2. **Framework Agnostic**: Generic design allowing use with other GUI frameworks beyond Qt
3. **Minimal Python Wrapper**: wavescout's DesignTreeModel becomes a thin wrapper around pyrox implementation with minimal overhead

### Performance Requirements
- Handle waveforms with millions of variables/scopes efficiently
- Tree building should complete in < 1 second for designs with 1M+ nodes
- Memory efficient - avoid duplicating hierarchy data between Rust and Python

### Compatibility Requirements
- Must satisfy Qt's QAbstractItemModel interface methods:
  - `index(row, column, parent)` - create QModelIndex for item
  - `parent(index)` - get parent of item
  - `rowCount(parent)` - number of child rows
  - `columnCount(parent)` - number of columns (3: Name, Type, Bit Range)
  - `data(index, role)` - provide display data, icons, user roles
  - `headerData(section, orientation, role)` - column headers
  - `flags(index)` - item flags (selectable, enabled)
- Support existing DesignTreeView functionality:
  - Scope navigation and expansion
  - Variable selection for waveform display
  - Efficient lookups by path for navigation

## 2. Codebase Research

### Current Python Implementation (`wavescout/design_tree_model.py`)

**DesignTreeNode Class** (lines 71-99):
- Stores: name, is_scope, var_type, bit_range, parent, children list
- Stores var_handle (SignalHandle) and var (pyrox.Var) references
- Stores scope (pyrox.Scope) for scope nodes

**DesignTreeModel Class** (lines 101-423):
- Inherits QAbstractItemModel
- Key methods:
  - `load_hierarchy()` - rebuilds tree from WaveformDB (line 128)
  - `_build_hierarchy()` - creates tree structure (line 147)
  - `_build_scope_recursive()` - recursive tree builder (line 177)
  - Qt model interface methods (lines 235-422)

**Performance Optimization** (lines 164-175):
- Builds reverse mapping `_var_to_handle` for O(1) handle lookups
- Maps Python `id(var)` to SignalHandle to avoid linear searches

### pyrox Current Structure (`pyrox/src/lib.rs`)

**Existing Types**:
- `Hierarchy` - wrapper around `Arc<wellen::Hierarchy>` (line 45)
- `Scope` - wraps `wellen::Scope` (line 187)
- `Var` - wraps `wellen::Var` (line 293)
- `SignalHandle = usize` - 0-based signal index (line 15)

**Relevant Methods**:
- `Hierarchy::top_scopes()` - returns iterator of top-level scopes (line 74)
- `Scope::vars()` - returns iterator of variables in scope (line 230)
- `Scope::scopes()` - returns iterator of child scopes (line 248)
- `Var::signal_ref()` - returns SignalHandle (line 351)

### Design Tree View Integration (`wavescout/design_tree_view.py`)

**Key Integration Points**:
- Uses DesignTreeModel at line 112: `self.design_tree_model = DesignTreeModel(waveform_db)`
- Expects DesignTreeNode objects with var_handle and var attributes
- Navigation methods rely on tree structure (lines 226-353)

### ScopeTreeModel Pattern (`wavescout/scope_tree_model.py`)

Shows split architecture where scope-only tree is built separately from variables, suggesting potential for optimization by separating concerns.

## 3. Implementation Planning

### Rust Side Architecture (pyrox)

#### New File: `pyrox/src/design_tree_model.rs`

**Core Structures**:
```rust
// Tree node representation
struct TreeNode {
    name: String,
    is_scope: bool,
    var_type: Option<String>,
    bit_range: Option<String>,
    parent_idx: Option<usize>,  // Index in nodes vector
    children: Vec<usize>,        // Indices of children
    var_ref: Option<VarRef>,     // Reference to wellen Var
    scope_ref: Option<ScopeRef>, // Reference to wellen Scope
    signal_handle: Option<SignalHandle>, // 0-based signal handle
}

// Main model structure
pub struct DesignTreeModel {
    nodes: Vec<TreeNode>,        // Flat storage for cache efficiency
    root_idx: usize,             // Index of root node
    hierarchy: Arc<Hierarchy>,   // Shared hierarchy reference
    var_to_handle: HashMap<VarRef, SignalHandle>, // For fast lookups
}
```

**Key Methods**:
- `new(hierarchy: Arc<Hierarchy>) -> Self` - Build tree from hierarchy
- `index(row, column, parent_idx) -> Option<usize>` - Get node index
- `parent(node_idx) -> Option<usize>` - Get parent index
- `row_count(parent_idx) -> usize` - Number of children
- `column_count() -> usize` - Always returns 3
- `get_node_data(node_idx, column) -> NodeData` - Get display data
- `get_var_handle(node_idx) -> Option<SignalHandle>` - Get signal handle
- `find_node_by_path(path: &str) -> Option<usize>` - Path-based lookup

**Performance Optimizations**:
- Use flat vector storage with indices instead of heap-allocated tree
- Pre-compute all node data during construction
- Build path lookup table for O(1) navigation
- Use Arc for shared hierarchy to avoid copies

#### Updates to `pyrox/src/lib.rs`

**New PyClass**:
```rust
#[pyclass]
struct PyDesignTreeModel {
    inner: Arc<DesignTreeModel>,
}

#[pymethods]
impl PyDesignTreeModel {
    #[new]
    fn new(hierarchy: &Hierarchy) -> Self {
        Self {
            inner: Arc::new(DesignTreeModel::new(hierarchy.0.clone()))
        }
    }

    // Qt model interface methods
    fn index(row: usize, column: usize, parent_idx: Option<usize>) -> Option<usize>
    fn parent(node_idx: usize) -> Option<usize>
    fn row_count(parent_idx: Option<usize>) -> usize
    fn column_count() -> usize

    // Data access
    fn get_display_text(node_idx: usize, column: usize) -> Option<String>
    fn is_scope(node_idx: usize) -> bool
    fn get_var_handle(node_idx: usize) -> Option<SignalHandle>
    fn get_var(node_idx: usize) -> Option<Var>

    // Navigation
    fn find_by_path(path: &str) -> Option<usize>
}
```

### Python Side Changes

#### File: `wavescout/design_tree_model.py`

**Modified DesignTreeModel Class**:
```python
class DesignTreeModel(QAbstractItemModel):
    """Qt wrapper around Rust DesignTreeModel."""

    def __init__(self, waveform_db: Optional[WaveformDBProtocol] = None, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.waveform_db = waveform_db
        self._rust_model: Optional[pyrox.PyDesignTreeModel] = None
        self._icon_cache = get_icon_cache()

        if waveform_db:
            self.load_hierarchy(waveform_db)

    def load_hierarchy(self, waveform_db: WaveformDBProtocol) -> None:
        self.beginResetModel()
        self.waveform_db = waveform_db

        if waveform_db and waveform_db.hierarchy:
            # Create Rust model
            self._rust_model = pyrox.PyDesignTreeModel(waveform_db.hierarchy)
        else:
            self._rust_model = None

        self.endResetModel()

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if not self._rust_model:
            return QModelIndex()

        parent_idx = parent.internalId() if parent.isValid() else None
        node_idx = self._rust_model.index(row, column, parent_idx)

        if node_idx is not None:
            return self.createIndex(row, column, node_idx)
        return QModelIndex()

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid() or not self._rust_model:
            return QModelIndex()

        parent_idx = self._rust_model.parent(index.internalId())
        if parent_idx is not None:
            # Get parent's row in its parent
            grandparent_idx = self._rust_model.parent(parent_idx)
            row = self._rust_model.get_row_of_child(grandparent_idx, parent_idx)
            return self.createIndex(row, 0, parent_idx)
        return QModelIndex()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if not self._rust_model:
            return 0
        parent_idx = parent.internalId() if parent.isValid() else None
        return self._rust_model.row_count(parent_idx)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not self._rust_model:
            return None

        node_idx = index.internalId()
        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return self._rust_model.get_display_text(node_idx, column)
        elif role == Qt.ItemDataRole.DecorationRole and column == 0:
            if self._rust_model.is_scope(node_idx):
                scope_type = self._rust_model.get_scope_type(node_idx) or "unknown"
                return self._icon_cache.get_scope_icon(scope_type)
            else:
                return self._icon_cache.get_signal_icon()
        elif role == Qt.ItemDataRole.UserRole:
            # Return a lightweight node proxy for compatibility
            return DesignTreeNodeProxy(self._rust_model, node_idx)

        return None
```

**New Proxy Class for Compatibility**:
```python
class DesignTreeNodeProxy:
    """Lightweight proxy to Rust node for backward compatibility."""

    def __init__(self, rust_model: pyrox.PyDesignTreeModel, node_idx: int):
        self._model = rust_model
        self._idx = node_idx

    @property
    def name(self) -> str:
        return self._model.get_display_text(self._idx, 0) or ""

    @property
    def is_scope(self) -> bool:
        return self._model.is_scope(self._idx)

    @property
    def var_handle(self) -> Optional[SignalHandle]:
        return self._model.get_var_handle(self._idx)

    @property
    def var(self) -> Optional[pyrox.Var]:
        return self._model.get_var(self._idx)
```

### Algorithm Descriptions

**Tree Building Algorithm (Rust)**:
1. Start with empty nodes vector and create root node at index 0
2. Traverse hierarchy depth-first starting from top_scopes()
3. For each scope:
   - Create TreeNode with scope data
   - Add to nodes vector, store index
   - Add index to parent's children list
   - Process all variables in scope:
     - Create TreeNode for each variable
     - Compute bit_range from var.bitwidth()
     - Store signal_handle from var.signal_ref()
   - Recursively process child scopes
4. Build auxiliary lookup structures:
   - var_to_handle mapping for O(1) handle lookups
   - path_to_node mapping for fast navigation

**Index Mapping Strategy**:
- Use node indices (usize) as QModelIndex internalId
- Root node has no parent (returns None)
- Child indices stored directly in parent's children vector
- Row number computed by position in parent's children list

### Performance Considerations

**Memory Layout**:
- Flat vector storage improves cache locality
- Indices are more memory efficient than pointers
- String data stored inline when possible

**Parallelization Opportunities**:
- Tree building can process sibling scopes in parallel
- Use rayon for parallel iteration where beneficial
- Ensure thread-safe access to shared nodes vector

**Lazy Loading Potential**:
- Could defer loading deep subtrees until expanded
- Trade-off between initial load time and expansion latency
- Consider threshold-based approach (load first N levels eagerly)