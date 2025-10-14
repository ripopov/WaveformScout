# Feature Plan: Visibility Strategy Pattern for Tree Traversal

**Feature ID:** 0009
**Feature Name:** visibility_strategy
**Status:** Planning
**Created:** 2025-10-14
**Last Updated:** 2025-10-14

---

## 1. Problem Statement

The jets GUI currently duplicates traversal logic for multiple visibility modes (unfiltered vs. viewport-filtered). Filtering rules are special-cased in several call sites, making behavior inconsistent and maintenance costly. This duplication complicates the addition of new visibility modes (e.g., search results, predicate filters) and increases the risk of subtle bugs when traversal invariants evolve.

Symptoms observed:
- Separate traversal code paths for filtered vs. unfiltered rendering.
- Each call site makes ad-hoc decisions about which parents/leaves to include and when to descend.
- Optimizations (e.g., early subtree culling, binary search for wide nodes) are difficult to reuse consistently.

## 2. Goals and Non‑Goals

Goals:
- Introduce a single, generic traversal that yields visible nodes based on a strategy interface.
- Centralize traversal invariants: depth handling, subtree skipping, parent/leaf inclusion, and optional binary-search windows for wide children.
- Implement two first-class strategies:
  - UnfilteredStrategy (baseline behavior)
  - ViewportFilterStrategy { start, end } (leaf-only by start_clk, consistent with Feature #0008)
- Keep UI call sites simple: they consume an iterator of VisibleNode values.

Non‑Goals:
- Implementing search/predicate filters now (leave extensibility hooks).
- Changing the data model or on-disk format.
- Replacing Virtual Scrolling (Feature #0006); this complements it.

## 3. High-Level Design

We define a VisibilityStrategy trait that is queried during a depth-first traversal. The traversal function uses the strategy to decide:
- Whether to include a parent in the output (include_parent)
- Whether to include a leaf in the output (include_leaf)
- Whether to descend into a parent (descend_into)

The traversal lives in a single module (domain/tree_operations) and returns an iterator of VisibleNode. Strategies encode policy; traversal encodes mechanics and performance (e.g., culling and optional binary search hooks).

## 4. API Design (Rust)

### 4.1 Types and Trait

```rust
// domain/visibility.rs (or rjets/src/domain/visibility.rs)
use crate::traits::{TraceData, TraceRecord, RecordId};

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub enum NodeKind { Parent, Leaf }

#[derive(Debug, Clone)]
pub struct VisibleNode<'a> {
    pub record: &'a dyn TraceRecord,
    pub depth: usize,
    pub kind: NodeKind,
}

/// Strategy consulted by the traversal for inclusion/culling decisions.
pub trait VisibilityStrategy {
    /// Should the parent node be included in the output at the given depth?
    fn include_parent(&self, parent: &dyn TraceRecord, depth: usize) -> bool;

    /// Should the leaf node be included in the output at the given depth?
    fn include_leaf(&self, leaf: &dyn TraceRecord, depth: usize) -> bool;

    /// Should the traversal descend into the given parent at the given depth?
    /// Even when include_parent() is false, we may still descend (e.g., to find visible leaves).
    fn descend_into(&self, parent: &dyn TraceRecord, depth: usize) -> bool;

    /// Optional window hint for wide-child optimization.
    /// If provided, traversal may use this to limit child iteration (e.g., binary search bounds).
    fn child_window_hint(
        &self,
        _parent: &dyn TraceRecord,
        _depth: usize,
    ) -> Option<(usize, usize)> { None }
}
```

### 4.2 Concrete Strategies

```rust
/// Baseline visibility: include every node and always descend into parents.
pub struct UnfilteredStrategy;

impl VisibilityStrategy for UnfilteredStrategy {
    fn include_parent(&self, _parent: &dyn TraceRecord, _depth: usize) -> bool { true }
    fn include_leaf(&self, _leaf: &dyn TraceRecord, _depth: usize) -> bool { true }
    fn descend_into(&self, _parent: &dyn TraceRecord, _depth: usize) -> bool { true }
}

/// Viewport-based leaf filtering by record start clock.
/// Mirrors Feature #0008 semantics: parents are included; leaves included iff
/// start_clk in [start, end].
pub struct ViewportFilterStrategy {
    pub start: i64,
    pub end: i64,
}

impl VisibilityStrategy for ViewportFilterStrategy {
    fn include_parent(&self, _parent: &dyn TraceRecord, _depth: usize) -> bool { true }
    fn include_leaf(&self, leaf: &dyn TraceRecord, _depth: usize) -> bool {
        let c = leaf.clk();
        c >= self.start && c <= self.end
    }
    fn descend_into(&self, parent: &dyn TraceRecord, _depth: usize) -> bool {
        // Early prune: if the first child starts after end, or parent starts after end,
        // traversal can skip (actual optimization is delegated to traversal implementation).
        // Keep policy permissive; mechanics decide concrete skipping.
        parent.clk() <= self.end
    }
}
```

Note: Binary-search child window narrowing is provided via child_window_hint if the strategy can compute it cheaply. For ViewportFilterStrategy, this can be implemented when the parent’s children are known to be sorted by clk (see Feature #0008 for details).

### 4.3 Traversal API

```rust
/// Unified traversal that produces only visible nodes under `strategy`.
pub fn traverse_visible<'a, S: VisibilityStrategy + ?Sized>(
    roots: impl IntoIterator<Item = &'a dyn TraceRecord>,
    strategy: &S,
) -> impl Iterator<Item = VisibleNode<'a>> {
    // Implementation sketch: use a Vec stack of (record, depth, state),
    // consult `strategy` at each step, optionally honor child_window_hint
    // for parent nodes to bound iteration. Yields VisibleNode lazily.
    TraversalIter::new(roots, strategy)
}
```

## 5. Traversal Mechanics and Optimizations

- Depth-first, stack-based iteration to avoid recursion and enable lazy yield.
- At each parent:
  - If include_parent is true, yield VisibleNode { kind: Parent }.
  - If descend_into is true, push children onto stack for visit.
  - If strategy provides child_window_hint, restrict child index range accordingly to avoid O(N) scans on very wide nodes (e.g., binary search by clk per Feature #0008).
- At each leaf:
  - Yield only if include_leaf is true.
- Maintain depth consistent with current expansion state (UI may pass expanded parents as roots, or provide an expansion predicate hook in a later iteration of the design).

## 6. Integration Plan

Where to integrate:
- domain/tree_operations: add traverse_visible and VisibleNode.
- rjets/src/ui tree components: replace ad-hoc traversal with the unified iterator.
- Header/UI filter toggle (from Feature #0008): choose strategy instance based on checkbox.

Migration steps:
1. Introduce VisibilityStrategy, VisibleNode, and traverse_visible behind a new module (no call-site changes yet).
2. Convert the unfiltered path to use UnfilteredStrategy + traverse_visible; verify parity in row counts and ordering.
3. Convert the viewport-filtered path to use ViewportFilterStrategy + traverse_visible; verify parity with existing behavior and tests from Feature #0008.
4. Remove duplicated traversal utilities and special-casing from call sites.

## 7. Testing Strategy

Unit tests:
- Strategy behavior:
  - UnfilteredStrategy: includes all nodes; traverse counts == total nodes.
  - ViewportFilterStrategy: parent inclusion always true; leaf inclusion matches [start, end].
- Traversal mechanics:
  - Depth correctness on mixed parent/leaf trees.
  - Early culling/skipping does not affect correctness.
  - child_window_hint honored (add a mock strategy that narrows children to a subrange).

Property tests (optional):
- Random tree generation; compare naive filtered traversal with strategy-driven traversal for equivalence.

Integration tests:
- Large, wide-node scenarios (100K children) verify that counts and order match previous implementation but with significantly fewer iterations (when hints supplied).
- UI toggle parity: switching filter on/off updates visible counts consistent with Feature #0008 (“Showing X / Y records”).

## 8. Performance Considerations

- The single traversal reduces duplicate work; policy/strategy enables pruning earlier.
- ViewportFilterStrategy can expose child_window_hint enabling O(log N) binary search bounds on wide nodes (as per Feature #0008), reducing child iteration from O(N) to O(log N + K).
- Iterator is lazy; virtual scrolling (Feature #0006) continues to limit materialization to the on-screen window.

## 9. Risks and Mitigations

- Risk: Strategy decisions may diverge subtly from historical behavior.
  - Mitigation: Golden tests comparing prior outputs vs. new traversal for representative traces.
- Risk: Incorrect depth handling when integrating with expansion state.
  - Mitigation: Add explicit tests for depth and ordering; consider passing an expansion predicate in a follow-up if needed.
- Risk: Over-eager pruning causing missed leaves.
  - Mitigation: Keep descend_into permissive in strategies and delegate hard skipping to traversal only when safe (e.g., via explicit hints or sorted assumptions).

## 10. Acceptance Criteria

- A VisibilityStrategy trait exists with include_parent, include_leaf, and descend_into methods; optional child_window_hint for optimization.
- UnfilteredStrategy and ViewportFilterStrategy implemented and used by tree traversal.
- A single traversal function (traverse_visible) yields VisibleNode iterator consumed by the UI.
- All previous behaviors for unfiltered and viewport-filtered modes are preserved; duplicated traversal code removed.
- Tests cover core strategy decisions and traversal mechanics; performance improves or stays equal in worst cases, and improves for wide-node viewport filtering cases.

## 11. Appendix: Traversal Pseudocode

```text
stack = []
for root in roots:
  push (root, depth=0)

while stack not empty:
  (node, depth) = pop()
  if node has children:
    if strategy.include_parent(node, depth):
      yield VisibleNode(node, depth, Parent)
    if strategy.descend_into(node, depth):
      children = node.children()
      if let Some((lo, hi)) = strategy.child_window_hint(node, depth):
        for i in (lo..hi):
          push(children[i], depth+1)
      else:
        for child in reversed(children):
          push(child, depth+1)
  else:
    if strategy.include_leaf(node, depth):
      yield VisibleNode(node, depth, Leaf)
```

## 12. Related Work

- Feature #0006: Virtual Scrolling — continues to bound rendering; this change provides a unified visibility pipeline feeding it.
- Feature #0008: Viewport Filter — this feature’s policy becomes a strategy; binary search bounds become an optional hint.
