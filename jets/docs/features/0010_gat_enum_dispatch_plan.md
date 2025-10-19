# JETS Feature Plan: GAT-Based Traits with Enum Dispatch

**Feature ID:** 0010
**Feature Name:** GAT-Based Traits with Enum Dispatch
**Author:** JETS Agentic Coding Feature Architect
**Date:** 2025-10-19
**Target Version:** JETS v0.3.0

---

## 1. Use Cases and Requirements Analysis

### 1.1 Problem Statement

The current trait system in `jets/rjets/src/traits.rs` uses trait objects (`Box<dyn TraceData>`, `&dyn TraceRecord`, etc.) which introduces several critical limitations when integrating with C library backends:

1. **Lifetime Constraint Violations**: Trait object returns (`&dyn TraceRecord`) require that references outlive the trait object, but C library implementations need records that borrow from an opaque context pointer with a specific lifetime relationship
2. **Double Pointer Pattern Incompatibility**: C libraries use two pointers (context + element), but trait objects erase the lifetime connection between the context (TraceData) and elements (TraceRecord/TraceEvent)
3. **Performance Overhead**: Trait objects require heap allocation for `Box<dyn TraceData>` and vtable indirection for every method call, which is expensive in hot paths (tree traversal, rendering)
4. **Send Constraint Issues**: Trait objects with lifetime parameters are difficult to make `Send`, blocking async loading in background threads

**Specific C Library Requirements:**
- Context pointer owns all trace data (e.g., `TraceContext*`)
- C structs are opaque (unknown/unstable layouts)
- All C API functions require TWO pointers: context + element (e.g., `get_record_name(TraceContext*, Record*)`)
- Pointers to records are stable for entire context lifetime
- Cannot store pre-computed copies (too expensive for large traces)

### 1.2 Solution Overview

Redesign the trait system using **Generic Associated Types (GATs)** to express lifetime relationships between contexts and borrowed data, combined with **enum dispatch** to eliminate vtable overhead while preserving polymorphism:

**Phase 1: GAT-Based Traits**
- Replace `&dyn TraceMetadata` with `type Metadata<'a>: TraceMetadata where Self: 'a`
- Replace `&dyn TraceRecord` with `type Record<'a>: TraceRecord where Self: 'a`
- Replace `Vec<&dyn TraceRecord>` with `Vec<Self::Record<'_>>`
- Replace `Vec<&dyn TraceEvent>` with `Vec<Self::Event<'_>>`

**Phase 2: Enum Dispatch Layer**
- Create `DynTraceData` enum wrapping all `TraceData` implementations
- Create `DynTraceMetadata`, `DynTraceRecord`, `DynTraceEvent` enums
- Implement trait forwarding via match statements (zero-cost abstraction)
- Update GUI code to use enums instead of `Box<dyn Trait>`

This approach:
- **Enables C library integration**: Lifetimes tie records to context
- **Achieves zero-cost abstraction**: Enums compile to direct calls (no vtables)
- **Preserves type safety**: Compile-time verification of lifetime relationships
- **Maintains Send**: Enums are Send when all variants are Send

### 1.3 Functional Requirements

#### FR-1: GAT-Based TraceData Trait
**Priority:** MUST HAVE

**Description:** Redesign `TraceData` trait using GATs to express lifetime relationships between trace context and borrowed data elements.

**New Trait Signature:**
```rust
pub trait TraceData: Send {
    type Metadata<'a>: TraceMetadata where Self: 'a;
    type Record<'a>: TraceRecord where Self: 'a;

    fn metadata(&self) -> Self::Metadata<'_>;
    fn root_ids(&self) -> Vec<RecordId>;
    fn get_record(&self, id: RecordId) -> Option<Self::Record<'_>>;
}
```

**Rationale:**
- `Self: 'a` bound ensures metadata/record cannot outlive the trace context
- `Self::Record<'_>` allows C implementations to return wrapper structs containing `(&'self Context, *const CRecord)`
- Associated types enable concrete implementations to use stack-allocated wrappers (zero allocation)

**Acceptance Criteria:**
- Trait compiles with GAT syntax
- All existing implementations (`JetsTraceData`, `VirtualTraceData`, `PipetraceData`) updated
- `Send` constraint preserved for async loading

---

#### FR-2: GAT-Based TraceRecord Trait
**Priority:** MUST HAVE

**Description:** Redesign `TraceRecord` trait using GATs for child records and events.

**New Trait Signature:**
```rust
pub trait TraceRecord {
    type ChildRecord<'a>: TraceRecord where Self: 'a;
    type Event<'a>: TraceEvent where Self: 'a;

    fn clk(&self) -> i64;
    fn end_clk(&self) -> Option<i64>;
    fn duration(&self) -> Option<i64>;
    fn name(&self) -> &str;
    fn id(&self) -> RecordId;
    fn parent_id(&self) -> Option<RecordId>;
    fn description(&self) -> &str;
    fn data(&self) -> HashMap<String, serde_json::Value>;

    // Index-based access for children and events (supports binary search)
    fn num_children(&self) -> usize;
    fn child_at(&self, index: usize) -> Option<Self::ChildRecord<'_>>;
    fn num_events(&self) -> usize;
    fn event_at(&self, index: usize) -> Option<Self::Event<'_>>;

    fn subtree_depth(&self) -> usize;
}
```

**Key Changes:**
- Replaced `children()` iterator with `num_children()` + `child_at(index)`
- Replaced `events()` vector with `num_events()` + `event_at(index)`
- Index-based access enables efficient binary search without enforcing specific data structures
- Implementations can use Vec, sorted arrays, or C API calls with pointer arithmetic
- Supports lazy evaluation (C implementations call C functions per access)

**Acceptance Criteria:**
- Trait compiles with GAT syntax
- Existing implementations updated (`JetsTraceRecord`, `VirtualTraceRecord`, `PipetraceRecord`)
- Tree traversal code (`domain/tree_operations.rs`, `domain/visibility.rs`) updated to use index-based access

---

#### FR-3: GAT-Based TraceMetadata Trait
**Priority:** MUST HAVE

**Description:** Update `TraceMetadata` to support GAT-based ownership model (no method changes needed, but trait must be usable as associated type).

**Current Trait (unchanged methods):**
```rust
pub trait TraceMetadata {
    fn version(&self) -> &str;
    fn header_data(&self) -> &serde_json::Value;
    fn capture_end_clk(&self) -> Option<i64>;
    fn total_records(&self) -> Option<usize>;
    fn total_annotations(&self) -> Option<usize>;
    fn total_events(&self) -> Option<usize>;
    fn trace_extent(&self) -> (i64, i64);
}
```

**Acceptance Criteria:**
- Trait usable as `type Metadata<'a>: TraceMetadata`
- All implementations updated to be returned as associated types

---

#### FR-4: Enum Dispatch for TraceData
**Priority:** MUST HAVE

**Description:** Create `DynTraceData` enum wrapping all concrete `TraceData` implementations for zero-cost polymorphism.

**Enum Definition:**
```rust
pub enum DynTraceData {
    Jets(JetsTraceData),
    Virtual(VirtualTraceData),
    Pipetrace(PipetraceData),
}
```

**Trait Implementation Pattern:**
```rust
impl TraceData for DynTraceData {
    type Metadata<'a> = DynTraceMetadata<'a> where Self: 'a;
    type Record<'a> = DynTraceRecord<'a> where Self: 'a;

    fn metadata(&self) -> Self::Metadata<'_> {
        match self {
            DynTraceData::Jets(d) => DynTraceMetadata::Jets(d.metadata()),
            DynTraceData::Virtual(d) => DynTraceMetadata::Virtual(d.metadata()),
            DynTraceData::Pipetrace(d) => DynTraceMetadata::Pipetrace(d.metadata()),
        }
    }

    fn get_record(&self, id: RecordId) -> Option<Self::Record<'_>> {
        match self {
            DynTraceData::Jets(d) => d.get_record(id).map(DynTraceRecord::Jets),
            DynTraceData::Virtual(d) => d.get_record(id).map(DynTraceRecord::Virtual),
            DynTraceData::Pipetrace(d) => d.get_record(id).map(DynTraceRecord::Pipetrace),
        }
    }

    // ... other methods
}
```

**Acceptance Criteria:**
- Enum compiles with all variants
- All `TraceData` methods implemented via match delegation
- Compiler inlines match arms (verify with `cargo asm` or benchmarks)

---

#### FR-5: Enum Dispatch for TraceRecord
**Priority:** MUST HAVE

**Description:** Create `DynTraceRecord` enum wrapping all concrete `TraceRecord` implementations.

**Enum Definition:**
```rust
pub enum DynTraceRecord<'a> {
    Jets(&'a JetsTraceRecord),
    Virtual(&'a VirtualTraceRecord),
    Pipetrace(&'a PipetraceRecord),
}
```

**Trait Implementation Pattern:**
```rust
impl<'a> TraceRecord for DynTraceRecord<'a> {
    type ChildRecord<'b> = DynTraceRecord<'b> where Self: 'b;
    type Event<'b> = DynTraceEvent<'b> where Self: 'b;

    fn clk(&self) -> i64 {
        match self {
            DynTraceRecord::Jets(r) => r.clk(),
            DynTraceRecord::Virtual(r) => r.clk(),
            DynTraceRecord::Pipetrace(r) => r.clk(),
        }
    }

    fn num_children(&self) -> usize {
        match self {
            DynTraceRecord::Jets(r) => r.num_children(),
            DynTraceRecord::Virtual(r) => r.num_children(),
            DynTraceRecord::Pipetrace(r) => r.num_children(),
        }
    }

    fn child_at(&self, index: usize) -> Option<Self::ChildRecord<'_>> {
        match self {
            DynTraceRecord::Jets(r) => r.child_at(index).map(DynTraceRecord::Jets),
            DynTraceRecord::Virtual(r) => r.child_at(index).map(DynTraceRecord::Virtual),
            DynTraceRecord::Pipetrace(r) => r.child_at(index).map(DynTraceRecord::Pipetrace),
        }
    }

    fn num_events(&self) -> usize {
        match self {
            DynTraceRecord::Jets(r) => r.num_events(),
            DynTraceRecord::Virtual(r) => r.num_events(),
            DynTraceRecord::Pipetrace(r) => r.num_events(),
        }
    }

    fn event_at(&self, index: usize) -> Option<Self::Event<'_>> {
        match self {
            DynTraceRecord::Jets(r) => r.event_at(index).map(DynTraceEvent::Jets),
            DynTraceRecord::Virtual(r) => r.event_at(index).map(DynTraceEvent::Virtual),
            DynTraceRecord::Pipetrace(r) => r.event_at(index).map(DynTraceEvent::Pipetrace),
        }
    }

    // ... other methods
}
```

**Acceptance Criteria:**
- Enum with lifetime parameter compiles
- All `TraceRecord` methods implemented via index-based access
- Binary search can be implemented by callers using `num_children()` / `child_at()`

---

#### FR-6: Enum Dispatch for TraceMetadata and TraceEvent
**Priority:** MUST HAVE

**Description:** Create enum wrappers for metadata and events.

**Enum Definitions:**
```rust
pub enum DynTraceMetadata<'a> {
    Jets(&'a JetsTraceMetadata),
    Virtual(&'a VirtualTraceData), // VirtualTraceData implements TraceMetadata
    Pipetrace(&'a PipetraceMetadata),
}

pub enum DynTraceEvent<'a> {
    Jets(&'a JetsTraceEvent),
    Virtual(&'a VirtualTraceEvent),
    Pipetrace(&'a PipetraceEvent),
}
```

**Acceptance Criteria:**
- Both enums implement respective traits via match delegation
- All methods forwarded correctly

---

#### FR-7: Update TraceReader to Return DynTraceData
**Priority:** MUST HAVE

**Description:** Change `TraceReader::read()` signature to return `DynTraceData` instead of `Box<dyn TraceData>`.

**New Signature:**
```rust
pub trait TraceReader {
    fn read(&self, file_path: &str) -> anyhow::Result<DynTraceData>;
}
```

**Implementation Updates:**
```rust
impl TraceReader for JetsTraceReader {
    fn read(&self, file_path: &str) -> anyhow::Result<DynTraceData> {
        let data = parse_trace(file_path)?;
        Ok(DynTraceData::Jets(data))
    }
}
```

**Acceptance Criteria:**
- All reader implementations updated (`JetsTraceReader`, `VirtualTraceReader`, `PipetraceReader`)
- `Box<dyn TraceData>` removed from all code

---

#### FR-8: Update GUI State Management
**Priority:** MUST HAVE

**Description:** Update `TraceState` and `AsyncLoader` to use `DynTraceData` instead of `Box<dyn TraceData>`.

**Changes in `state/trace_state.rs`:**
```rust
pub struct TraceState {
    trace_data: Option<DynTraceData>,  // Changed from Box<dyn TraceData>
    file_path: Option<PathBuf>,
    min_clk: i64,
    max_clk: i64,
}

impl TraceState {
    pub fn load_trace(&mut self, data: DynTraceData, path: Option<PathBuf>) {
        let (min, max) = data.metadata().trace_extent();
        self.trace_data = Some(data);
        self.file_path = path;
        self.min_clk = min;
        self.max_clk = max;
    }

    pub fn trace_data(&self) -> Option<&DynTraceData> {
        self.trace_data.as_ref()
    }
}
```

**Changes in `io/async_loader.rs`:**
```rust
pub enum LoadResult {
    Success {
        data: DynTraceData,  // Changed from Box<dyn TraceData>
        path: Option<PathBuf>,
    },
    Error(String),
    None,
}

// Update channel type
loading_receiver: Option<Receiver<Result<DynTraceData, String>>>,
```

**Acceptance Criteria:**
- `TraceState` stores `Option<DynTraceData>`
- `AsyncLoader` uses `DynTraceData` in channels
- No `Box<dyn TraceData>` remains in codebase

---

#### FR-9: Update Tree Traversal and Rendering
**Priority:** MUST HAVE

**Description:** Update tree operations, visibility strategies, and rendering code to work with GAT-based records and enum dispatch.

**Key Files to Update:**
- `domain/tree_operations.rs`: Tree traversal using child iterators
- `domain/visibility.rs`: `VisibilityStrategy` trait methods updated to use `DynTraceRecord`
- `rendering/tree_renderer.rs`: Rendering loops updated
- `ui/` modules: All panel rendering code

**Pattern Changes:**
```rust
// OLD (trait objects)
fn traverse(record: &dyn TraceRecord) {
    for child in record.children() {  // Vec<&dyn TraceRecord>
        process(child);
    }
}

// NEW (GATs with enum dispatch)
fn traverse(record: &DynTraceRecord) {
    for child in record.children() {  // DynRecordIterator
        process(&child);  // child is DynTraceRecord
    }
}
```

**Acceptance Criteria:**
- All tree traversal code compiles
- All rendering code compiles
- Tests pass (`cargo test`)
- GUI runs without errors

---

## 2. Codebase Research

### 2.1 Current Trait System Architecture

**`jets/rjets/src/traits.rs`** (109 lines) - Core trait definitions:
- `TraceReader` trait: Returns `Box<dyn TraceData>`
- `TraceData` trait: Methods return `&dyn TraceMetadata`, `&dyn TraceRecord`
- `TraceRecord` trait: Methods return `Vec<&dyn TraceRecord>`, `Vec<&dyn TraceEvent>`
- `TraceMetadata` trait: Pure data access methods
- `TraceEvent` trait: Pure data access methods

**Existing Implementations:**

1. **JETS Format Implementation** (`parser.rs`, ~560 lines):
   - `JetsTraceData`: Uses arena pattern (`Arc<Vec<JetsTraceRecord>>`)
   - `JetsTraceRecord`: Stores `child_indices: Vec<usize>`, uses `OnceCell<Arc<Vec<...>>>` for lazy arena resolution
   - `children()` method (lines 510-523): Resolves indices to references, returns `Vec<&dyn TraceRecord>`
   - Arena pattern enables self-referential structure without cyclic ownership

2. **Virtual Trace Implementation** (`virtual_reader.rs`, ~300 lines):
   - `VirtualTraceData`: Stores `roots: Vec<VirtualTraceRecord>`, `records_by_id: HashMap<...>`
   - `VirtualTraceRecord`: Directly owns children (`children: Vec<VirtualTraceRecord>`)
   - `children()` method: Returns owned children as trait objects

3. **Pipetrace Stub Implementation** (`pipetrace_reader.rs`, ~79 lines):
   - `PipetraceData`: Empty stub (returns empty vectors)
   - Placeholder for future C library integration

### 2.2 GUI Usage Patterns

**State Management** (`state/trace_state.rs`):
- `TraceState` stores `Option<Box<dyn TraceData>>`
- Accessed via `trace_data(&self) -> Option<&dyn TraceData>`
- Used by tree operations and rendering

**Async Loading** (`io/async_loader.rs`):
- `LoadResult::Success` contains `Box<dyn TraceData>`
- Background thread calls `TraceReader::read()` returning `Box<dyn TraceData>`
- Sent through `mpsc::channel` (requires `Send`)

**Tree Traversal** (`domain/tree_operations.rs`):
- Functions accept `&dyn TraceData` and `&dyn TraceRecord`
- Recursively traverse via `record.children()`

**Visibility Strategies** (`domain/visibility.rs`):
- `VisibilityStrategy` trait methods accept `&dyn TraceRecord`
- Strategies: `UnfilteredStrategy`, `ViewportFilterStrategy`
- Used by rendering pipeline

**Rendering** (`rendering/tree_renderer.rs`, `rendering/timeline_renderer.rs`):
- Render loops iterate over visible records (`&dyn TraceRecord`)
- Call trait methods for display data

### 2.3 Performance-Critical Paths

Based on virtual scrolling (Feature #0006) and viewport filtering (Feature #0008):

1. **Tree Traversal**: Called per frame during scrolling (hot path)
2. **Visibility Checks**: Called for every record during traversal
3. **Child Iteration**: Called multiple times per record
4. **Event Access**: Called during timeline rendering

Enum dispatch will eliminate vtable indirection in these paths.

---

## 3. Implementation Planning

### 3.1 File-by-File Changes

#### **File: `jets/rjets/src/traits.rs`**

**Modifications:**
1. **TraceReader trait** (line 7):
   - Change return type from `Box<dyn TraceData>` to `DynTraceData`

2. **TraceData trait** (lines 14-23):
   - Add GAT declarations: `type Metadata<'a>: TraceMetadata where Self: 'a`, `type Record<'a>: TraceRecord where Self: 'a`
   - Change `fn metadata(&self)` return type from `&dyn TraceMetadata` to `Self::Metadata<'_>`
   - Change `fn get_record(&self, id)` return type from `Option<&dyn TraceRecord>` to `Option<Self::Record<'_>>`

3. **TraceRecord trait** (lines 50-90):
   - Add GAT declarations: `type ChildRecord<'a>: TraceRecord where Self: 'a`, `type Event<'a>: TraceEvent where Self: 'a`
   - Replace `fn children(&self) -> Vec<&dyn TraceRecord>` with:
     - `fn num_children(&self) -> usize`
     - `fn child_at(&self, index: usize) -> Option<Self::ChildRecord<'_>>`
   - Replace `fn events(&self) -> Vec<&dyn TraceEvent>` with:
     - `fn num_events(&self) -> usize`
     - `fn event_at(&self, index: usize) -> Option<Self::Event<'_>>`

4. **Add enum dispatch types** (new section at end):
   - Add `DynTraceData` enum with variants `Jets`, `Virtual`, `Pipetrace`
   - Add `DynTraceMetadata<'a>` enum with lifetime parameter
   - Add `DynTraceRecord<'a>` enum with lifetime parameter
   - Add `DynTraceEvent<'a>` enum with lifetime parameter

5. **Implement TraceData for DynTraceData**:
   - Match on self, delegate to variant-specific implementation
   - Wrap results in corresponding enum variant

6. **Implement TraceMetadata for DynTraceMetadata<'_>**:
   - Match on self, delegate to variant-specific implementation

7. **Implement TraceRecord for DynTraceRecord<'_>**:
   - Match on self, delegate to variant-specific implementation
   - Index-based access methods (`num_children()`, `child_at()`, etc.)

8. **Implement TraceEvent for DynTraceEvent<'_>**:
   - Match on self, delegate to variant-specific implementation

**Integration Points:**
- Enums are defined in same file as traits (single source of truth)
- All implementations moved to separate files (`parser.rs`, `virtual_reader.rs`, etc.)

**Dependencies:**
- Requires Rust 1.65+ for GATs (stable since Oct 2022)

---

#### **File: `jets/rjets/src/parser.rs`**

**Modifications:**

1. **JetsTraceReader::read()** (line 400):
   - Change return type from `anyhow::Result<Box<dyn TraceData>>` to `anyhow::Result<DynTraceData>`
   - Wrap result: `Ok(DynTraceData::Jets(data))`

2. **JetsTraceData trait implementation** (lines 436-456):
   - Add associated type declarations:
     ```rust
     type Metadata<'a> = &'a JetsTraceMetadata where Self: 'a;
     type Record<'a> = &'a JetsTraceRecord where Self: 'a;
     ```
   - Change `metadata(&self)` return type from `&dyn TraceMetadata` to `Self::Metadata<'_>` (returns `&self.metadata`)
   - Change `get_record(&self, id)` return type to `Option<Self::Record<'_>>`

3. **JetsTraceRecord trait implementation** (lines 459-560):
   - Add associated type declarations:
     ```rust
     type ChildRecord<'a> = &'a JetsTraceRecord where Self: 'a;
     type Event<'a> = &'a JetsTraceEvent where Self: 'a;
     ```
   - Replace `children(&self) -> Vec<&dyn TraceRecord>` with:
     ```rust
     fn num_children(&self) -> usize {
         self.child_indices.len()
     }

     fn child_at(&self, index: usize) -> Option<Self::ChildRecord<'_>> {
         let arena = self.arena.get()?;
         let &child_idx = self.child_indices.get(index)?;
         let child = arena.get(child_idx)?;
         let _ = child.arena.get_or_init(|| Arc::clone(arena));
         Some(child)
     }
     ```
   - Replace `events(&self) -> Vec<&dyn TraceEvent>` with:
     ```rust
     fn num_events(&self) -> usize {
         self.events.len()
     }

     fn event_at(&self, index: usize) -> Option<Self::Event<'_>> {
         self.events.get(index)
     }
     ```

**Integration Points:**
- Index-based access eliminates heap allocation for `Vec<&dyn TraceRecord>`
- Supports efficient binary search by callers (children sorted by clk)
- Arena pattern unchanged (still uses `Arc<Vec<...>>`)

---

#### **File: `jets/rjets/src/virtual_reader.rs`**

**Modifications:**

1. **VirtualTraceReader::read()** (line 34):
   - Change return type from `anyhow::Result<Box<dyn TraceData>>` to `anyhow::Result<DynTraceData>`
   - Wrap result: `Ok(DynTraceData::Virtual(data))`

2. **VirtualTraceData trait implementation** (lines 110-122):
   - Add associated type declarations:
     ```rust
     type Metadata<'a> = &'a VirtualTraceData where Self: 'a;  // VirtualTraceData implements TraceMetadata
     type Record<'a> = &'a VirtualTraceRecord where Self: 'a;
     ```
   - Change return types accordingly

3. **VirtualTraceRecord trait implementation** (lines 244+):
   - Add associated type declarations:
     ```rust
     type ChildRecord<'a> = &'a VirtualTraceRecord where Self: 'a;
     type Event<'a> = &'a VirtualTraceEvent where Self: 'a;
     ```
   - Replace `children(&self) -> Vec<&dyn TraceRecord>` with:
     ```rust
     fn num_children(&self) -> usize {
         self.children.len()
     }

     fn child_at(&self, index: usize) -> Option<Self::ChildRecord<'_>> {
         self.children.get(index)
     }
     ```
   - Replace `events(&self) -> Vec<&dyn TraceEvent>` with:
     ```rust
     fn num_events(&self) -> usize {
         self.events.len()
     }

     fn event_at(&self, index: usize) -> Option<Self::Event<'_>> {
         self.events.get(index)
     }
     ```

**Integration Points:**
- Direct slice indexing (no arena resolution needed)
- Children owned directly in Vec

---

#### **File: `jets/rjets/src/pipetrace_reader.rs`**

**Modifications:**

1. **PipetraceReader::read()** (line 13):
   - Change return type from `anyhow::Result<Box<dyn TraceData>>` to `anyhow::Result<DynTraceData>`
   - Wrap result: `Ok(DynTraceData::Pipetrace(data))`

2. **PipetraceData trait implementation** (lines 22-31):
   - Add associated type declarations:
     ```rust
     type Metadata<'a> = &'a PipetraceMetadata where Self: 'a;
     type Record<'a> = &'a PipetraceRecord where Self: 'a;
     ```
   - Change return types accordingly

3. **PipetraceRecord trait implementation** (lines 54-66):
   - Add associated type declarations:
     ```rust
     type ChildRecord<'a> = &'a PipetraceRecord where Self: 'a;
     type Event<'a> = &'a PipetraceEvent where Self: 'a;
     ```
   - Replace `children(&self) -> Vec<&dyn TraceRecord>` with:
     ```rust
     fn num_children(&self) -> usize { 0 }
     fn child_at(&self, _index: usize) -> Option<Self::ChildRecord<'_>> { None }
     ```
   - Replace `events(&self) -> Vec<&dyn TraceEvent>` with:
     ```rust
     fn num_events(&self) -> usize { 0 }
     fn event_at(&self, _index: usize) -> Option<Self::Event<'_>> { None }
     ```

**Integration Points:**
- Empty stub implementation
- Future C library implementation will use GATs for context-borrowed records with index-based C API calls

---

#### **File: `jets/rjets/src/state/trace_state.rs`**

**Modifications:**

1. **TraceState struct** (line 18):
   - Change field type from `trace_data: Option<Box<dyn TraceData>>` to `trace_data: Option<DynTraceData>`

2. **load_trace method** (line 43):
   - Change parameter type from `data: Box<dyn TraceData>` to `data: DynTraceData`
   - Remove boxing: `self.trace_data = Some(data)`

3. **trace_data method** (line 60):
   - Change return type from `Option<&dyn TraceData>` to `Option<&DynTraceData>`
   - Change implementation: `self.trace_data.as_ref()`

**Integration Points:**
- `TraceData` trait still implemented by `DynTraceData` (transparent to callers)

---

#### **File: `jets/rjets/src/io/async_loader.rs`**

**Modifications:**

1. **LoadResult enum** (line 19):
   - Change `Success` variant field from `data: Box<dyn TraceData>` to `data: DynTraceData`

2. **AsyncLoader struct** (line 38):
   - Change channel type from `Receiver<Result<Box<dyn TraceData>, String>>` to `Receiver<Result<DynTraceData, String>>`

3. **load_virtual_trace method** (line 124):
   - Change return type from `Result<Box<dyn TraceData>, String>` to `Result<DynTraceData, String>`

**Integration Points:**
- Background thread calls updated `TraceReader::read()` (returns `DynTraceData`)
- `DynTraceData` is `Send` (all variants are `Send`)

---

#### **File: `jets/rjets/src/domain/visibility.rs`**

**Modifications:**

1. **VisibleNode struct** (line 29):
   - Change field type from `pub record: &'a dyn TraceRecord` to `pub record: DynTraceRecord<'a>`

2. **VisibilityStrategy trait** (lines 48-101):
   - Change method signatures:
     - `fn include_parent(&self, parent: &DynTraceRecord, depth: usize) -> bool`
     - `fn include_leaf(&self, leaf: &DynTraceRecord, depth: usize) -> bool`
     - `fn descend_into(&self, parent: &DynTraceRecord, depth: usize) -> bool`
     - `fn child_window_hint(&self, _parent: &DynTraceRecord, _depth: usize) -> Option<(usize, usize)>`

3. **UnfilteredStrategy implementation** (lines 108-120):
   - Update method signatures (no logic changes)

4. **ViewportFilterStrategy implementation** (lines 135-150):
   - Update method signatures (no logic changes)

**Integration Points:**
- Strategies now accept concrete enum type (enables inlining)
- Traversal code updated to work with iterators

---

#### **File: `jets/rjets/src/domain/tree_operations.rs`**

**Modifications:**

1. **All traversal functions**:
   - Change parameter types from `&dyn TraceData` to `&DynTraceData`
   - Change parameter types from `&dyn TraceRecord` to `&DynTraceRecord`
   - Update child iteration to use index-based access

**Pattern Example:**
```rust
// OLD
fn traverse(record: &dyn TraceRecord) {
    for child in record.children() {  // Vec<&dyn TraceRecord>
        traverse(child);
    }
}

// NEW
fn traverse<'a>(record: &DynTraceRecord<'a>) {
    let num_children = record.num_children();
    for i in 0..num_children {
        if let Some(child) = record.child_at(i) {
            traverse(&child);
        }
    }
}

// OR with helper for cleaner code
fn traverse_children<'a>(record: &DynTraceRecord<'a>) {
    (0..record.num_children())
        .filter_map(|i| record.child_at(i))
        .for_each(|child| traverse(&child));
}
```

**Integration Points:**
- Index-based traversal enables binary search for time-based queries
- No semantic changes to tree algorithms
- Supports efficient range queries (e.g., children in viewport)

---

#### **File: `jets/rjets/src/rendering/tree_renderer.rs`**

**Modifications:**

1. **Rendering loops**:
   - Change references from `&dyn TraceRecord` to `&DynTraceRecord`
   - Update child iteration to use index-based access
   - Update event rendering to use `num_events()` / `event_at()`

**Integration Points:**
- Matches on `DynTraceRecord` variants if format-specific rendering needed
- Enables efficient event filtering by time range using binary search

---

#### **File: `jets/rjets/src/ui/` (multiple panel modules)**

**Modifications:**

1. **All panel rendering functions**:
   - Change types from `&dyn TraceData` / `&dyn TraceRecord` to enum types
   - No logic changes (traits implemented identically)

**Integration Points:**
- Transparent migration (trait methods unchanged)

---

#### **File: `jets/rjets/src/lib.rs`**

**Modifications:**

1. **Public exports** (lines 10-13):
   - Add exports for enum types:
     ```rust
     pub use traits::{
         TraceReader, TraceData, TraceMetadata, TraceRecord, TraceEvent, RecordId,
         DynTraceData, DynTraceMetadata, DynTraceRecord, DynTraceEvent
     };
     ```

**Integration Points:**
- GUI code imports enum types from `rjets` crate

---

### 3.2 Migration Strategy

**Phase 1: Traits (No Breaking Changes to GUI)**
1. Update `traits.rs` with GATs
2. Update implementations (`parser.rs`, `virtual_reader.rs`, `pipetrace_reader.rs`)
3. Keep `Box<dyn TraceData>` in GUI temporarily
4. Verify all tests pass

**Phase 2: Enum Dispatch (Replace Trait Objects)**
1. Add enum definitions to `traits.rs`
2. Implement traits for enums
3. Update `TraceReader::read()` to return enums
4. Update `TraceState` and `AsyncLoader`
5. Update `domain/` and `rendering/` modules
6. Update `ui/` modules
7. Remove all `Box<dyn Trait>` and `&dyn Trait` from codebase

**Phase 3: Verification**
1. Run test suite: `cargo test`
2. Run type checker: `cargo check`
3. Test GUI with sample traces
4. Benchmark performance (expect 10-20% improvement in hot paths)

---

### 3.3 Algorithm Descriptions

#### Index-Based Child Access (JETS Format)

**Problem:** Arena-based storage uses indices, need to convert to references on-demand.

**Algorithm (`child_at` implementation):**
1. Validate index is within bounds: `0 <= index < self.child_indices.len()`
2. Retrieve arena reference from `OnceCell` (return `None` if not initialized)
3. Get child index from `self.child_indices[index]`
4. Resolve child index to record reference via `arena.get(child_idx)`
5. Lazily initialize child's arena reference (enables transitive traversal)
6. Return child record reference

**Properties:**
- Zero heap allocation (direct indexing)
- O(1) access time per child
- Supports binary search (children sorted by clk during parsing)
- Lazy arena initialization (only touched records get arena reference)

**Binary Search Example:**
```rust
// Find first child starting after target clock
fn find_child_after_clk(record: &DynTraceRecord, target_clk: i64) -> Option<usize> {
    let mut left = 0;
    let mut right = record.num_children();

    while left < right {
        let mid = left + (right - left) / 2;
        if let Some(child) = record.child_at(mid) {
            if child.clk() <= target_clk {
                left = mid + 1;
            } else {
                right = mid;
            }
        } else {
            break;
        }
    }

    if left < record.num_children() { Some(left) } else { None }
}
```

---

#### Enum Match Optimization

**Expectation:** Rust compiler inlines match arms when enum dispatch is used.

**Verification Strategy:**
1. Use `#[inline]` attribute on hot path methods
2. Use `cargo asm` to inspect generated assembly
3. Confirm no vtable lookups (direct function calls)
4. Benchmark critical paths (tree traversal, rendering)

**Example:**
```rust
#[inline]
fn clk(&self) -> i64 {
    match self {
        DynTraceRecord::Jets(r) => r.clk(),
        DynTraceRecord::Virtual(r) => r.clk(),
        DynTraceRecord::Pipetrace(r) => r.clk(),
    }
}
```

Expected assembly: Direct field access (no indirect call).

---

### 3.4 Performance Considerations

**Expected Improvements:**

1. **Eliminated Heap Allocations:**
   - `Box<dyn TraceData>` → `DynTraceData` (stack-allocated enum, ~24 bytes)
   - `Vec<&dyn TraceRecord>` → index-based access (zero allocation)
   - `Vec<&dyn TraceEvent>` → index-based access (zero allocation)

2. **Eliminated Vtable Indirection:**
   - Trait object method calls → direct function calls via match
   - Enables inlining of small methods (`clk()`, `id()`, etc.)

3. **Better Cache Locality:**
   - Enum discriminant stored inline (single cache line)
   - No pointer chasing for method dispatch

4. **Efficient Queries:**
   - Binary search on children by clk (O(log n) vs O(n))
   - Binary search on events by clk (O(log n) vs O(n))
   - Range queries for viewport filtering (slice window directly)

**Benchmarking Plan:**

1. **Baseline (current trait objects):**
   - Measure time to traverse 100k record tree
   - Measure time to render 10k visible records
   - Measure memory usage (heap allocations)

2. **Post-migration (enum dispatch):**
   - Re-run same benchmarks
   - Expect 10-20% speedup in traversal
   - Expect 5-10% speedup in rendering

3. **Tools:**
   - Use `cargo bench` with criterion.rs
   - Use `cargo flamegraph` for profiling
   - Use `cargo +nightly build -Z build-std` with LTO for release builds

---

### 3.5 Safety and Lifetime Considerations

**Lifetime Guarantees:**

1. **Records Borrow from TraceData:**
   - `type Record<'a>: TraceRecord where Self: 'a` ensures records cannot outlive trace
   - Prevents use-after-free when trace is dropped

2. **Children Borrow from Parent Context:**
   - Iterator lifetime `'a` tied to parent record's borrow
   - Prevents dangling references during traversal

3. **C Library Integration (Future):**
   - C context pointer wrapped in Rust struct
   - Record wrappers store `(&'ctx Context, *const CRecord)`
   - Lifetime `'ctx` prevents record access after context drop

**Send Constraint:**

- `DynTraceData` is `Send` when all variants are `Send`
- `JetsTraceData` uses `Arc` (Send)
- `VirtualTraceData` owns data (Send)
- `PipetraceData` stub (Send)
- Future C library implementations must ensure thread-safe context

---

### 3.6 Testing Strategy

**Unit Tests:**

1. **Index-Based Access Correctness:**
   - Test `num_children()` returns correct count
   - Test `child_at(i)` returns correct child for all valid indices
   - Test `child_at(i)` returns `None` for out-of-bounds indices
   - Test `num_events()` and `event_at(i)` similarly
   - Test transitive traversal (children of children)

2. **Binary Search Correctness:**
   - Test binary search finds correct child by clk
   - Test edge cases (empty children, all children before/after target)
   - Test event binary search similarly

3. **Enum Dispatch Correctness:**
   - Test all trait methods via enum wrappers
   - Test nested enum access (record → events, record → children)

3. **Lifetime Compilation:**
   - Create test cases that should NOT compile (lifetime violations)
   - Use `trybuild` crate for compile-fail tests

**Integration Tests:**

1. **File Loading:**
   - Load sample JETS/virtual/pipetrace files
   - Verify `DynTraceData` returned correctly

2. **Tree Traversal:**
   - Traverse complete tree with enum-based records
   - Verify all records visited

3. **GUI Rendering:**
   - Open trace in GUI
   - Verify tree renders correctly
   - Verify timeline renders correctly

**Performance Tests:**

1. **Benchmark Suite:**
   - Tree traversal (100k records)
   - Visibility filtering (viewport filter with 100k records)
   - Event access (10k events)
   - Binary search benchmarks (find child/event by clk)

2. **Memory Profiling:**
   - Use `valgrind` / `dhat` to measure heap usage
   - Compare before/after trait object removal

---

## 4. Future Extensions

### 4.1 C Library Integration Example

Once GAT-based traits are in place, C library implementations can be added:

```rust
pub struct CTraceData {
    context: *mut ffi::TraceContext,  // Opaque C pointer
    _phantom: PhantomData<ffi::TraceContext>,
}

impl TraceData for CTraceData {
    type Metadata<'a> = CMetadataWrapper<'a> where Self: 'a;
    type Record<'a> = CRecordWrapper<'a> where Self: 'a;

    fn metadata(&self) -> Self::Metadata<'_> {
        CMetadataWrapper { context: self.context }
    }

    fn get_record(&self, id: RecordId) -> Option<Self::Record<'_>> {
        let ptr = unsafe { ffi::trace_get_record(self.context, id) };
        if ptr.is_null() {
            None
        } else {
            Some(CRecordWrapper { context: self.context, record: ptr })
        }
    }
}

pub struct CRecordWrapper<'a> {
    context: *mut ffi::TraceContext,
    record: *const ffi::Record,
    _phantom: PhantomData<&'a ffi::TraceContext>,
}

impl<'a> TraceRecord for CRecordWrapper<'a> {
    type ChildRecord<'b> = CRecordWrapper<'b> where Self: 'b;
    type Event<'b> = CEventWrapper<'b> where Self: 'b;

    fn clk(&self) -> i64 {
        unsafe { ffi::record_get_clk(self.context, self.record) }
    }

    fn num_children(&self) -> usize {
        unsafe { ffi::record_get_num_children(self.context, self.record) }
    }

    fn child_at(&self, index: usize) -> Option<Self::ChildRecord<'_>> {
        let child_ptr = unsafe { ffi::record_get_child_at(self.context, self.record, index) };
        if child_ptr.is_null() {
            None
        } else {
            Some(CRecordWrapper {
                context: self.context,
                record: child_ptr,
                _phantom: PhantomData,
            })
        }
    }

    fn num_events(&self) -> usize {
        unsafe { ffi::record_get_num_events(self.context, self.record) }
    }

    fn event_at(&self, index: usize) -> Option<Self::Event<'_>> {
        let event_ptr = unsafe { ffi::record_get_event_at(self.context, self.record, index) };
        if event_ptr.is_null() {
            None
        } else {
            Some(CEventWrapper {
                context: self.context,
                event: event_ptr,
                _phantom: PhantomData,
            })
        }
    }

    // ... all other methods call C functions with both pointers
}
```

**Key Properties:**
- Zero-copy: Wrappers store pointers only (24 bytes per wrapper)
- Safe public API: Lifetimes prevent misuse (records cannot outlive context)
- Efficient: Direct C function calls (no intermediate allocations)
- Index-based access: C libraries can implement efficient array indexing or binary search
- Lazy evaluation: Children/events only accessed when explicitly requested via `child_at()`

### 4.2 Additional Enum Variants

When new trace formats are added:

1. Add new variant to `DynTraceData` enum
2. Add corresponding variants to `DynTraceRecord`, etc.
3. Add match arms in trait implementations
4. Compiler ensures exhaustive matching (catches missing cases)

---

## 5. Risks and Mitigations

### Risk 1: GAT Complexity
**Description:** GAT syntax is complex, may introduce compilation errors.
**Mitigation:** Incremental implementation, extensive testing at each phase.

### Risk 2: Index-Based Access Overhead
**Description:** Repeated `child_at()` calls might be slower than pre-allocated Vec.
**Mitigation:** Benchmark index-based access vs. Vec, use `#[inline]` liberally, leverage binary search opportunities.

### Risk 3: Enum Size
**Description:** Large enum size could hurt cache performance.
**Mitigation:** Profile enum sizes, consider `Box<T>` for large variants if needed.

### Risk 4: Breaking Changes
**Description:** Major refactor could introduce subtle bugs.
**Mitigation:** Comprehensive test suite, careful code review, gradual rollout.

---

## 6. Success Criteria

1. **Compilation:** All code compiles without errors or warnings
2. **Tests:** All existing tests pass (`cargo test`)
3. **Type Safety:** No `unsafe` in public API, proper lifetime enforcement
4. **Performance:** Benchmark shows 10-20% improvement in tree traversal
5. **GUI Functionality:** Viewer loads and displays traces correctly
6. **Code Quality:** No `Box<dyn Trait>` remains in codebase
7. **Documentation:** Inline docs updated for GAT-based traits

---

## 7. References

- **Rust GAT RFC:** https://rust-lang.github.io/rfcs/1598-generic_associated_types.html
- **Enum Dispatch Pattern:** https://www.possiblerust.com/pattern/enum-dispatch
- **Zero-Cost Abstractions:** https://blog.rust-lang.org/2015/05/11/traits.html
- **Feature #0008:** Viewport Filter (demonstrates hot path performance needs)
- **Feature #0006:** Virtual Scrolling (demonstrates tree traversal frequency)
