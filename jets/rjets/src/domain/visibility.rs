//! Visibility strategy pattern for tree traversal.
//!
//! This module provides a unified interface for controlling which nodes are visible
//! during tree traversal. Different strategies can implement different visibility
//! policies (e.g., unfiltered, viewport-filtered, search-filtered).
//!
//! The strategy pattern separates traversal mechanics (implemented once) from
//! visibility policy (implemented per strategy), making it easy to add new
//! filtering modes without duplicating traversal logic.

use rjets::TraceRecord;
use std::marker::PhantomData;

/// Kind of tree node (parent or leaf).
#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub enum NodeKind {
    /// Node with children (parent)
    Parent,
    /// Node without children (leaf)
    Leaf,
}

/// A visible node in the traversal with its metadata.
///
/// This is the output type of the visibility-aware traversal.
/// It includes the record, depth, and node kind.
#[derive(Clone)]
pub struct VisibleNode<'a, R: TraceRecord<'a>> {
    /// The trace record
    pub record: R,
    /// Depth in the tree hierarchy (0 for root)
    pub depth: usize,
    /// Whether this is a parent or leaf node
    #[allow(dead_code)]
    pub kind: NodeKind,
    /// Tree branch context: For each depth level (0 to depth-1), indicates
    /// whether there are more siblings below this node at that level.
    pub branch_context: Vec<bool>,
    /// Whether this is the last child of its parent
    pub is_last_child: bool,
    /// Phantom data to mark the lifetime
    _phantom: PhantomData<&'a ()>,
}

/// Strategy for determining node visibility during tree traversal.
///
/// Implementors of this trait define policies for:
/// - Which parent nodes to include in output
/// - Which leaf nodes to include in output
/// - Whether to descend into a parent's children
/// - Optional hints for optimizing wide-node traversal
pub trait VisibilityStrategy<'a, R: TraceRecord<'a>> {
    /// Should the parent node be included in the output at the given depth?
    ///
    /// # Arguments
    /// * `parent` - The parent record to check
    /// * `depth` - Current depth in the tree
    ///
    /// # Returns
    /// `true` if this parent should be yielded, `false` otherwise
    fn include_parent(&self, parent: &R, depth: usize) -> bool;

    /// Should the leaf node be included in the output at the given depth?
    ///
    /// # Arguments
    /// * `leaf` - The leaf record to check
    /// * `depth` - Current depth in the tree
    ///
    /// # Returns
    /// `true` if this leaf should be yielded, `false` otherwise
    fn include_leaf(&self, leaf: &R, depth: usize) -> bool;

    /// Should the traversal descend into the given parent at the given depth?
    ///
    /// Note: Even when `include_parent()` returns false, we may still descend
    /// to find visible leaves within the subtree.
    ///
    /// # Arguments
    /// * `parent` - The parent record to check
    /// * `depth` - Current depth in the tree
    ///
    /// # Returns
    /// `true` if children should be visited, `false` to skip the subtree
    fn descend_into(&self, parent: &R, depth: usize) -> bool;

    /// Optional window hint for wide-child optimization.
    ///
    /// If the strategy can compute a subset of children that need to be visited
    /// (e.g., via binary search on sorted children), it can return an index range
    /// here. The traversal may use this to limit child iteration.
    ///
    /// # Arguments
    /// * `_parent` - The parent record whose children are being considered
    /// * `_depth` - Current depth in the tree
    ///
    /// # Returns
    /// `Some((start, end))` to visit children[start..end], or `None` for all children
    fn child_window_hint(
        &self,
        _parent: &R,
        _depth: usize,
    ) -> Option<(usize, usize)> {
        None
    }
}

/// Baseline visibility strategy: include all nodes and always descend.
///
/// This strategy produces the complete unfiltered tree traversal.
pub struct UnfilteredStrategy;

impl<'a, R: TraceRecord<'a>> VisibilityStrategy<'a, R> for UnfilteredStrategy {
    fn include_parent(&self, _parent: &R, _depth: usize) -> bool {
        true
    }

    fn include_leaf(&self, _leaf: &R, _depth: usize) -> bool {
        true
    }

    fn descend_into(&self, _parent: &R, _depth: usize) -> bool {
        true
    }
}

/// Viewport-based temporal filtering strategy.
///
/// This strategy mirrors Feature #0008 (viewport filter) semantics:
/// - Parent nodes are always included (structural anchors)
/// - Leaf nodes are included only if their start_clk is in [start, end]
/// - Early subtree pruning when parent starts after viewport end
pub struct ViewportFilterStrategy {
    /// Start of viewport time range (inclusive)
    pub start: i64,
    /// End of viewport time range (inclusive)
    pub end: i64,
}

impl<'a, R: TraceRecord<'a>> VisibilityStrategy<'a, R> for ViewportFilterStrategy {
    fn include_parent(&self, _parent: &R, _depth: usize) -> bool {
        // Always include parent nodes as structural anchors
        true
    }

    fn include_leaf(&self, leaf: &R, _depth: usize) -> bool {
        // Include leaf only if its clock is in the viewport range
        let c = leaf.clk();
        c >= self.start && c <= self.end
    }

    fn descend_into(&self, parent: &R, _depth: usize) -> bool {
        // Early prune: if parent starts after viewport end, skip entire subtree
        // This is safe because children have start times >= parent start time
        parent.clk() <= self.end
    }

    fn child_window_hint(
        &self,
        parent: &R,
        _depth: usize,
    ) -> Option<(usize, usize)> {
        // If the parent has children and they are leaves, we can use binary search
        // to find the subset that falls within [start, end]
        let num_children = parent.num_children();
        if num_children == 0 {
            return None;
        }

        // Check if first child is a leaf (subtree_depth == 0)
        let first_child = parent.child_at(0)?;
        if first_child.subtree_depth() != 0 {
            // Children are not leaves, must visit all to find visible descendants
            return None;
        }

        // Binary search for first child with clk >= start
        let mut left = 0;
        let mut right = num_children;
        while left < right {
            let mid = left + (right - left) / 2;
            if let Some(child) = parent.child_at(mid) {
                if child.clk() < self.start {
                    left = mid + 1;
                } else {
                    right = mid;
                }
            } else {
                break;
            }
        }
        let first_idx = left;

        // Binary search for last child with clk <= end
        left = 0;
        right = num_children;
        while left < right {
            let mid = left + (right - left) / 2;
            if let Some(child) = parent.child_at(mid) {
                if child.clk() <= self.end {
                    left = mid + 1;
                } else {
                    right = mid;
                }
            } else {
                break;
            }
        }
        let last_idx = if left == 0 { 0 } else { left - 1 };

        // Return the window if there's overlap
        if first_idx <= last_idx && last_idx < num_children {
            Some((first_idx, last_idx + 1)) // Exclusive end
        } else {
            None
        }
    }
}

/// Stack frame for iterative depth-first traversal.
#[derive(Clone)]
struct TraversalFrame<'a, R: TraceRecord<'a>> {
    record: R,
    depth: usize,
    /// If Some, we've already yielded this parent and are processing children
    /// at the given index. If None, we haven't processed this node yet.
    child_index: Option<usize>,
    /// For each ancestor level, whether there are more siblings below
    branch_context: Vec<bool>,
    /// Whether this node is the last child of its parent
    is_last_child: bool,
    /// Phantom data to mark the lifetime
    _phantom: PhantomData<&'a ()>,
}

/// Iterator that yields visible nodes according to a visibility strategy.
///
/// This iterator performs a depth-first traversal using an explicit stack
/// to avoid recursion and enable lazy evaluation. It consults the strategy
/// at each step to determine visibility and whether to descend.
pub struct TraversalIter<'a, R: TraceRecord<'a>, S: VisibilityStrategy<'a, R>> {
    stack: Vec<TraversalFrame<'a, R>>,
    strategy: &'a S,
}

impl<'a, R: TraceRecord<'a>, S: VisibilityStrategy<'a, R>> TraversalIter<'a, R, S> {
    fn new<I>(roots: I, strategy: &'a S) -> Self
    where
        I: IntoIterator<Item = R>,
    {
        // Collect roots into a vec to determine which are last
        let roots_vec: Vec<_> = roots.into_iter().collect();
        let num_roots = roots_vec.len();

        // Collect into Vec first, then reverse for correct LIFO stack order
        let mut stack: Vec<TraversalFrame<'a, R>> = roots_vec
            .into_iter()
            .enumerate()
            .map(|(i, record)| TraversalFrame {
                record,
                depth: 0,
                child_index: None,
                branch_context: Vec::new(),
                is_last_child: i == num_roots - 1,
                _phantom: PhantomData,
            })
            .collect();

        stack.reverse();

        TraversalIter { stack, strategy }
    }
}

impl<'a, R: TraceRecord<'a>, S: VisibilityStrategy<'a, R>> Iterator for TraversalIter<'a, R, S> {
    type Item = VisibleNode<'a, R>;

    fn next(&mut self) -> Option<Self::Item> {
        while let Some(frame) = self.stack.pop() {
            let depth = frame.depth;
            let num_children = frame.record.num_children();

            // Determine if this is a parent or leaf
            let is_parent = num_children > 0;

            if is_parent {
                // Parent node
                if frame.child_index.is_none() {
                    // First time visiting this parent

                    // Check if we should descend into children
                    let should_descend = self.strategy.descend_into(&frame.record, depth);

                    // Clone frame data that we'll need
                    let parent_branch_context = frame.branch_context.clone();
                    let parent_is_last_child = frame.is_last_child;
                    let parent_record = frame.record;

                    if should_descend {
                        // Determine which children to process
                        let child_range = if let Some((start, end)) = self.strategy.child_window_hint(&parent_record, depth) {
                            // Use the hint to limit children
                            start..end.min(num_children)
                        } else {
                            // Process all children
                            0..num_children
                        };

                        // Collect indices first
                        let child_indices: Vec<(usize, usize)> = child_range.rev().enumerate().collect();

                        // Collect all children with clones - use a for loop to avoid closure lifetime issues
                        let mut children_to_push = Vec::new();
                        for (child_idx, i) in child_indices {
                            if let Some(child) = parent_record.child_at(i) {
                                let mut child_branch_context = parent_branch_context.clone();
                                child_branch_context.push(!parent_is_last_child);
                                let is_last = child_idx == 0;
                                children_to_push.push((child.clone(), depth + 1, child_branch_context, is_last));
                            }
                        }

                        // Now push all children (parent_record is no longer borrowed)
                        for (child_record, child_depth, child_branch_context, is_last) in children_to_push {
                            self.stack.push(TraversalFrame {
                                record: child_record,
                                depth: child_depth,
                                child_index: None,
                                branch_context: child_branch_context,
                                is_last_child: is_last,
                                _phantom: PhantomData,
                            });
                        }
                    }

                    // Check if we should include this parent in output
                    if self.strategy.include_parent(&parent_record, depth) {
                        return Some(VisibleNode {
                            record: parent_record.clone(), // Clone to avoid lifetime issues
                            depth,
                            kind: NodeKind::Parent,
                            branch_context: parent_branch_context,
                            is_last_child: parent_is_last_child,
                            _phantom: PhantomData,
                        });
                    }
                } else {
                    // We've already processed this parent and its children
                    // This frame was pushed back for children processing,
                    // but we don't yield anything here
                    continue;
                }
            } else {
                // Leaf node
                if self.strategy.include_leaf(&frame.record, depth) {
                    return Some(VisibleNode {
                        record: frame.record,
                        depth,
                        kind: NodeKind::Leaf,
                        branch_context: frame.branch_context,
                        is_last_child: frame.is_last_child,
                        _phantom: PhantomData,
                    });
                }
            }
        }

        None
    }
}

/// Unified traversal that produces visible nodes according to a strategy.
///
/// This function returns a lazy iterator that yields `VisibleNode` items
/// for all nodes that pass the visibility checks defined by the strategy.
///
/// # Arguments
/// * `roots` - Iterator of root records to start traversal from
/// * `strategy` - The visibility strategy to apply
///
/// # Returns
/// An iterator yielding `VisibleNode` items in depth-first order
///
/// # Example
/// ```ignore
/// use jets::domain::visibility::{traverse_visible, UnfilteredStrategy};
///
/// let strategy = UnfilteredStrategy;
/// let roots = trace.root_ids().iter()
///     .filter_map(|&id| trace.get_record(id));
///
/// for node in traverse_visible(roots, &strategy) {
///     println!("Record {} at depth {}", node.record.name(), node.depth);
/// }
/// ```
pub fn traverse_visible<'a, R, S, I>(
    roots: I,
    strategy: &'a S,
) -> impl Iterator<Item = VisibleNode<'a, R>>
where
    R: TraceRecord<'a>,
    S: VisibilityStrategy<'a, R>,
    I: IntoIterator<Item = R>,
{
    TraversalIter::new(roots, strategy)
}

#[cfg(test)]
mod tests {
    use super::*;
    use rjets::TraceEvent;

    // Mock TraceRecord for testing
    #[derive(Clone)]
    struct MockRecord {
        id: u64,
        clk: i64,
        children: Vec<MockRecord>,
    }

    // Mock TraceEvent for testing
    #[derive(Clone, Copy)]
    struct MockEvent<'a>(&'a ());

    impl<'a> rjets::AttributeAccessor for MockEvent<'a> {
        fn attr_count(&self) -> u64 { 0 }
        fn attr(&self, _key: &str) -> Option<serde_json::Value> { None }
        fn attr_at(&self, _index: u64) -> Option<(String, serde_json::Value)> { None }
        fn attrs(&self) -> Vec<(String, serde_json::Value)> { Vec::new() }
    }

    impl<'a> TraceEvent for MockEvent<'a> {
        fn clk(&self) -> i64 { 0 }
        fn name(&self) -> String { "".to_string() }
        fn record_id(&self) -> u64 { 0 }
        fn description(&self) -> String { "".to_string() }
    }

    impl<'a> rjets::AttributeAccessor for &'a MockRecord {
        fn attr_count(&self) -> u64 { 0 }
        fn attr(&self, _key: &str) -> Option<serde_json::Value> { None }
        fn attr_at(&self, _index: u64) -> Option<(String, serde_json::Value)> { None }
        fn attrs(&self) -> Vec<(String, serde_json::Value)> { Vec::new() }
    }

    impl<'a> TraceRecord<'a> for &'a MockRecord {
        type Event<'b> = MockEvent<'b> where Self: 'b;
        fn clk(&self) -> i64 {
            self.clk
        }
        fn end_clk(&self) -> Option<i64> {
            None
        }
        fn duration(&self) -> Option<i64> {
            None
        }
        fn name(&self) -> String {
            "mock".to_string()
        }
        fn id(&self) -> u64 {
            self.id
        }
        fn parent_id(&self) -> Option<u64> {
            None
        }
        fn description(&self) -> String {
            "".to_string()
        }
        fn num_children(&self) -> usize {
            self.children.len()
        }
        fn child_at(&self, index: usize) -> Option<Self> {
            self.children.get(index)
        }
        fn num_events(&self) -> usize {
            0
        }
        fn event_at(&self, _index: usize) -> Option<Self::Event<'_>> {
            None
        }
        fn subtree_depth(&self) -> usize {
            if self.children.is_empty() {
                0
            } else {
                1 + (0..self.children.len())
                    .filter_map(|i| self.child_at(i))
                    .map(|c| c.subtree_depth())
                    .max()
                    .unwrap_or(0)
            }
        }
    }

    #[test]
    fn test_unfiltered_strategy_includes_all() {
        let strategy = UnfilteredStrategy;
        let record = MockRecord { id: 1, clk: 100, children: vec![] };
        let record_ref = &record;

        assert!(strategy.include_parent(&record_ref, 0));
        assert!(strategy.include_leaf(&record_ref, 0));
        assert!(strategy.descend_into(&record_ref, 0));
    }

    #[test]
    fn test_viewport_filter_strategy_parents_always_included() {
        let strategy = ViewportFilterStrategy { start: 100, end: 200 };
        let record = MockRecord { id: 1, clk: 50, children: vec![] };
        let record_ref = &record;

        assert!(strategy.include_parent(&record_ref, 0));
    }

    #[test]
    fn test_viewport_filter_strategy_leaf_in_range() {
        let strategy = ViewportFilterStrategy { start: 100, end: 200 };
        let leaf_in = MockRecord { id: 1, clk: 150, children: vec![] };
        let leaf_before = MockRecord { id: 2, clk: 50, children: vec![] };
        let leaf_after = MockRecord { id: 3, clk: 250, children: vec![] };

        assert!(strategy.include_leaf(&&leaf_in, 0));
        assert!(!strategy.include_leaf(&&leaf_before, 0));
        assert!(!strategy.include_leaf(&&leaf_after, 0));
    }

    #[test]
    fn test_viewport_filter_strategy_descend_logic() {
        let strategy = ViewportFilterStrategy { start: 100, end: 200 };
        let parent_before_end = MockRecord { id: 1, clk: 150, children: vec![] };
        let parent_after_end = MockRecord { id: 2, clk: 250, children: vec![] };

        assert!(strategy.descend_into(&&parent_before_end, 0));
        assert!(!strategy.descend_into(&&parent_after_end, 0));
    }

    #[test]
    fn test_viewport_filter_child_window_hint() {
        let strategy = ViewportFilterStrategy { start: 100, end: 200 };

        // Parent with leaf children sorted by clk
        let parent = MockRecord {
            id: 1,
            clk: 0,
            children: vec![
                MockRecord { id: 2, clk: 50, children: vec![] },
                MockRecord { id: 3, clk: 100, children: vec![] },
                MockRecord { id: 4, clk: 150, children: vec![] },
                MockRecord { id: 5, clk: 200, children: vec![] },
                MockRecord { id: 6, clk: 250, children: vec![] },
            ],
        };

        let hint = strategy.child_window_hint(&&parent, 0);
        assert_eq!(hint, Some((1, 4))); // Indices 1, 2, 3 (clk 100, 150, 200)
    }

    #[test]
    fn test_traverse_visible_unfiltered_simple() {
        let strategy = UnfilteredStrategy;

        // Build a simple tree: root -> child1, child2
        let root = MockRecord {
            id: 1,
            clk: 0,
            children: vec![
                MockRecord { id: 2, clk: 10, children: vec![] },
                MockRecord { id: 3, clk: 20, children: vec![] },
            ],
        };

        let roots = vec![&root];
        let nodes: Vec<_> = traverse_visible(roots, &strategy).collect();

        assert_eq!(nodes.len(), 3);
        assert_eq!(nodes[0].record.id(), 1);
        assert_eq!(nodes[0].depth, 0);
        assert_eq!(nodes[0].kind, NodeKind::Parent);

        assert_eq!(nodes[1].record.id(), 2);
        assert_eq!(nodes[1].depth, 1);
        assert_eq!(nodes[1].kind, NodeKind::Leaf);

        assert_eq!(nodes[2].record.id(), 3);
        assert_eq!(nodes[2].depth, 1);
        assert_eq!(nodes[2].kind, NodeKind::Leaf);
    }

    #[test]
    fn test_traverse_visible_nested() {
        let strategy = UnfilteredStrategy;

        // Build a nested tree: root -> parent1 -> leaf1, leaf2
        let root = MockRecord {
            id: 1,
            clk: 0,
            children: vec![MockRecord {
                id: 2,
                clk: 10,
                children: vec![
                    MockRecord { id: 3, clk: 20, children: vec![] },
                    MockRecord { id: 4, clk: 30, children: vec![] },
                ],
            }],
        };

        let roots = vec![&root];
        let nodes: Vec<_> = traverse_visible(roots, &strategy).collect();

        assert_eq!(nodes.len(), 4);
        assert_eq!(nodes[0].record.id(), 1);
        assert_eq!(nodes[0].depth, 0);
        assert_eq!(nodes[1].record.id(), 2);
        assert_eq!(nodes[1].depth, 1);
        assert_eq!(nodes[2].record.id(), 3);
        assert_eq!(nodes[2].depth, 2);
        assert_eq!(nodes[3].record.id(), 4);
        assert_eq!(nodes[3].depth, 2);
    }

    #[test]
    fn test_traverse_visible_viewport_filter() {
        let strategy = ViewportFilterStrategy { start: 100, end: 200 };

        // Build tree with leaves at different times
        let root = MockRecord {
            id: 1,
            clk: 0,
            children: vec![
                MockRecord { id: 2, clk: 50, children: vec![] },   // Before viewport
                MockRecord { id: 3, clk: 150, children: vec![] },  // In viewport
                MockRecord { id: 4, clk: 250, children: vec![] },  // After viewport
            ],
        };

        let roots = vec![&root];
        let nodes: Vec<_> = traverse_visible(roots, &strategy).collect();

        // Should include parent (always) and only the leaf in viewport
        assert_eq!(nodes.len(), 2);
        assert_eq!(nodes[0].record.id(), 1);
        assert_eq!(nodes[0].kind, NodeKind::Parent);
        assert_eq!(nodes[1].record.id(), 3);
        assert_eq!(nodes[1].kind, NodeKind::Leaf);
    }

    #[test]
    fn test_traverse_visible_viewport_filter_prune() {
        let strategy = ViewportFilterStrategy { start: 100, end: 200 };

        // Build tree where parent starts after viewport (children should be pruned)
        let root = MockRecord {
            id: 1,
            clk: 0,
            children: vec![
                MockRecord {
                    id: 2,
                    clk: 300, // After viewport
                    children: vec![
                        MockRecord { id: 3, clk: 310, children: vec![] },
                        MockRecord { id: 4, clk: 320, children: vec![] },
                    ],
                },
                MockRecord { id: 5, clk: 150, children: vec![] }, // In viewport
            ],
        };

        let roots = vec![&root];
        let nodes: Vec<_> = traverse_visible(roots, &strategy).collect();

        // Should include: root parent, parent at clk 300 (always included), leaf at 150
        // Parent's children at clk 310, 320 should NOT be included (subtree pruned)
        assert_eq!(nodes.len(), 3);
        assert_eq!(nodes[0].record.id(), 1);
        assert_eq!(nodes[0].kind, NodeKind::Parent);
        assert_eq!(nodes[1].record.id(), 2);
        assert_eq!(nodes[1].kind, NodeKind::Parent);
        assert_eq!(nodes[2].record.id(), 5);
        assert_eq!(nodes[2].kind, NodeKind::Leaf);
    }

    #[test]
    fn test_traverse_visible_empty() {
        let strategy = UnfilteredStrategy;
        let roots: Vec<&MockRecord> = vec![];
        let nodes: Vec<_> = traverse_visible(roots, &strategy).collect();
        assert_eq!(nodes.len(), 0);
    }

    #[test]
    fn test_traverse_visible_multiple_roots() {
        let strategy = UnfilteredStrategy;

        let root1 = MockRecord {
            id: 1,
            clk: 0,
            children: vec![MockRecord { id: 2, clk: 10, children: vec![] }],
        };
        let root2 = MockRecord {
            id: 3,
            clk: 0,
            children: vec![MockRecord { id: 4, clk: 20, children: vec![] }],
        };

        let roots = vec![&root1, &root2];
        let nodes: Vec<_> = traverse_visible(roots, &strategy).collect();

        assert_eq!(nodes.len(), 4);
        assert_eq!(nodes[0].record.id(), 1);
        assert_eq!(nodes[1].record.id(), 2);
        assert_eq!(nodes[2].record.id(), 3);
        assert_eq!(nodes[3].record.id(), 4);
    }
}
