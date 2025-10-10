# Trait-Based Trace Reader API for JETS GUI

## 1. Use Cases and Requirements Analysis

### Core Functionality
The feature implements a trait-based abstraction layer for reading trace files in jets-gui, enabling support for multiple trace file formats (.json/.jets and future .bin formats) through a unified API.

### User Requirements (From Prompt)

#### Trait Definitions
The API must define the following traits:

1. **TraceReader**: API to read trace files and return TraceData
   - Opens and parses trace files (both .json/.jets and potentially .bin formats)
   - Returns a TraceData implementation

2. **TraceData**: API to access trace data
   - Provides access to metadata (information from headers and footers)
   - Returns root records
   - Acts as the entry point to the trace hierarchy

3. **TraceMetadata**: API to access trace metadata
   - Extracts information from headers (version, hardware model, clock frequency, etc.)
   - Extracts information from footers (capture_end_clk, total counts)

4. **TraceRecord**: API to access trace record
   - Provides: timestamp (clk), name, id, parent_id, description
   - Provides: data - a key-value dictionary that includes:
     - All record data fields from the original record
     - All annotations merged in (annotations are NOT separate)
   - Provides: children - vector of TraceRecord
   - Provides: events - vector of TraceEvent

5. **TraceEvent**: API to access trace event
   - Provides: timestamp (clk), name, record_id, description
   - Provides: data - key-value dictionary with all event data fields

#### Key Design Requirements
- **No explicit TraceAnnotations**: Annotations are merged into TraceRecord's data dictionary
- **Concrete Implementations**: Current structs in `parser.rs` will be renamed:
  - Current structs → `JetsTraceReader`, `JetsTraceData`, `JetsTraceMetadata`, `JetsTraceRecord`, `JetsTraceEvent`
  - These will implement the corresponding traits
- **Trait Dispatch**: GUI (`main.rs`) interacts with parsers **only** via `dyn TraceReader` trait
- **Virtual Reader**: Add `virtual_reader.rs` with `VirtualTraceReader`:
  - Generates infinite tree of random records
  - No file I/O
  - Used for testing and development
- **Test Migration**: Rewrite `integration_test.rs` to use TraceReader trait instead of direct parser access

### Format Support
- **JSON/JETS format** (.json, .jets, .jsonl): Line-by-line JSON (existing format)
- **Binary format** (.bin): Future format support (trait enables this extensibility)

### Architecture Goals
1. **Abstraction**: GUI code should not know about specific file format implementations
2. **Extensibility**: Easy to add new trace formats by implementing traits
3. **Testability**: Virtual reader enables testing without files
4. **Type Safety**: Strong typing through Rust traits

## 2. Codebase Research

### Current Architecture (jets/rjets)

#### Current File Structure
```
jets/rjets/src/
├── lib.rs          - Public API exports (TraceData, TraceRecord, etc.)
├── parser.rs       - JETS JSON parser implementation
├── writer.rs       - JETS JSON writer
├── main.rs         - GUI application (egui-based)
└── tracegen.rs     - Trace generator
```

#### Current Data Structures (parser.rs)

**TraceHeader** (lines 7-11):
- version: String
- metadata: serde_json::Value

**TraceFooter** (lines 13-19):
- capture_end_clk: Option<i64>
- total_records: Option<usize>
- total_annotations: Option<usize>
- total_events: Option<usize>

**TraceAnnotation** (lines 21-29):
- line_type: String
- name: String
- record_id: u64
- description: String
- data: serde_json::Value

**TraceEvent** (lines 31-41):
- clk: i64
- line_type: String
- name: String
- record_id: u64
- description: String
- data: Option<serde_json::Value>

**TraceRecord** (lines 43-65):
- clk: i64
- name: String
- record_type: String
- id: u64
- parent_id: Option<u64>
- description: String
- data: Option<serde_json::Value>
- Computed fields (skip serde):
  - end_clk: Option<i64>
  - duration: Option<i64>
  - children: Vec<TraceRecord>
  - annotations: Vec<TraceAnnotation>
  - events: Vec<TraceEvent>

**TraceData** (lines 67-72):
- header: TraceHeader
- roots: Vec<TraceRecord>
- footer: Option<TraceFooter>

**parse_trace()** function (lines 123-267):
- Opens file, reads line-by-line JSON
- Builds HashMap of records by ID
- Builds parent-child tree structure
- Attaches annotations and events to records
- Sorts children by clk then name

#### Current GUI Usage (main.rs)

**JetsViewerApp** struct (lines 21-28):
- trace_data: Option<TraceData> - directly uses concrete type
- file_path: Option<PathBuf>
- selected_record_id: Option<u64>
- expanded_nodes: HashSet<u64>
- error_message: Option<String>

**open_file()** (lines 31-44):
- Calls `parse_trace(path)` directly
- Stores TraceData concrete type
- No abstraction

**Rendering** (lines 87-244):
- Direct field access: `trace.header.metadata`
- Clones roots: `trace.roots.clone()`
- Recursive tree rendering with direct struct access

#### Current Test Structure (integration_test.rs)

**Tests** (lines 6-230):
- Use `TraceWriter` to create test files
- Call `parse_trace()` directly
- Assert on concrete struct fields
- Two main tests:
  1. test_write_and_read_basic_trace
  2. test_write_and_read_hierarchical_trace

### Key Architecture Patterns

#### Data Flow
1. File → parse_trace() → TraceData (concrete)
2. TraceData → GUI direct access
3. No abstraction layer currently exists

#### Memory Model
- Tree structure built in memory completely
- Children owned by parents (Vec<TraceRecord>)
- Annotations/events owned by records
- Cloning used for GUI rendering (avoids borrow checker issues)

#### Tree Building Algorithm (parser.rs:222-260)
1. Parse all records into HashMap<u64, TraceRecord>
2. Separate roots (parent_id = None) from children
3. Build children_map: HashMap<u64, Vec<TraceRecord>>
4. Recursively attach children via attach_children()
5. Sort children by clk then name

## 3. Implementation Planning

### Phase 1: Define Trait Hierarchy

#### File: `jets/rjets/src/traits.rs` (NEW)

**Purpose**: Define all trait interfaces for the trace reader API

**Traits to Define**:

1. **TraceReader trait**
   - Method: `read(&self, file_path: &str) -> Result<Box<dyn TraceData>>`
   - Returns trait object for maximum flexibility

2. **TraceData trait**
   - Method: `metadata(&self) -> &dyn TraceMetadata`
   - Method: `root_ids(&self) -> Vec<u64>`
   - Method: `get_record(&self, id: u64) -> Option<&dyn TraceRecord>`
   - Provides access to top-level trace data

3. **TraceMetadata trait**
   - Method: `version(&self) -> &str`
   - Method: `header_data(&self) -> &serde_json::Value`
   - Method: `capture_end_clk(&self) -> Option<i64>`
   - Method: `total_records(&self) -> Option<usize>`
   - Method: `total_annotations(&self) -> Option<usize>`
   - Method: `total_events(&self) -> Option<usize>`

4. **TraceRecord trait**
   - Method: `clk(&self) -> i64` - start timestamp
   - Method: `end_clk(&self) -> Option<i64>` - end timestamp
   - Method: `duration(&self) -> Option<i64>` - computed duration
   - Method: `name(&self) -> &str`
   - Method: `id(&self) -> u64`
   - Method: `parent_id(&self) -> Option<u64>`
   - Method: `description(&self) -> &str`
   - Method: `data(&self) -> HashMap<String, serde_json::Value>` - **MERGED data + annotations**
   - Method: `children(&self) -> Vec<&dyn TraceRecord>` - children as trait objects
   - Method: `events(&self) -> Vec<&dyn TraceEvent>` - events as trait objects

5. **TraceEvent trait**
   - Method: `clk(&self) -> i64` - event timestamp
   - Method: `name(&self) -> &str`
   - Method: `record_id(&self) -> u64`
   - Method: `description(&self) -> &str`
   - Method: `data(&self) -> HashMap<String, serde_json::Value>` - all event data

**Key Design Decisions**:
- Return types use trait objects (`&dyn Trait`) for maximum flexibility
- `data()` methods return `HashMap` for the required key-value API
- Annotations merged into record's data dictionary (no separate annotations in API)
- All methods return references or copies (no ownership transfer)

### Phase 2: Rename and Adapt Current Implementation

#### File: `jets/rjets/src/parser.rs`

**Renaming**:
- `TraceHeader` → `JetsTraceHeader` (internal only, not in trait)
- `TraceFooter` → `JetsTraceFooter` (internal only, not in trait)
- `TraceAnnotation` → `JetsTraceAnnotation` (internal only, not in trait)
- `TraceEvent` → `JetsTraceEvent` (implements TraceEvent trait)
- `TraceRecord` → `JetsTraceRecord` (implements TraceRecord trait)
- `TraceData` → `JetsTraceData` (implements TraceData trait)
- Create: `JetsTraceMetadata` struct (implements TraceMetadata trait)
- Create: `JetsTraceReader` struct (implements TraceReader trait)

**New Struct: JetsTraceMetadata**
- Wraps header and footer
- Implements TraceMetadata trait methods

**New Struct: JetsTraceReader**
- Empty struct (stateless)
- impl TraceReader with `read()` calling existing parse logic

**JetsTraceRecord Implementation**:
- Add `fn data(&self) -> HashMap<String, serde_json::Value>`:
  1. Start with self.data.clone() or empty map
  2. Merge all annotations into the map:
     - For each annotation: insert with key = annotation.name
     - Value = annotation.data
  3. Return merged HashMap
- Implement all other TraceRecord trait methods by delegating to struct fields

**JetsTraceEvent Implementation**:
- Implement TraceEvent trait
- `data()` returns self.data as HashMap (wrap Option in map)

**JetsTraceData Implementation**:
- Store JetsTraceMetadata internally
- Implement TraceData trait methods
- Build record lookup: HashMap<u64, &JetsTraceRecord> for get_record()
- root_ids() returns IDs from self.roots

**parse_trace() function**:
- Keep existing logic
- Return `JetsTraceData` (concrete type)
- Used internally by JetsTraceReader

#### File: `jets/rjets/src/lib.rs`

**Updates**:
- Export traits: `pub use traits::*;`
- Export JETS implementations:
  ```rust
  pub use parser::{
      JetsTraceReader, JetsTraceData, JetsTraceMetadata,
      JetsTraceRecord, JetsTraceEvent
  };
  ```
- Keep backward compatibility exports for now (deprecated):
  ```rust
  #[deprecated(note = "Use JetsTraceData instead")]
  pub use parser::JetsTraceData as TraceData;
  // ... etc
  ```

### Phase 3: Implement Virtual Reader

#### File: `jets/rjets/src/virtual_reader.rs` (NEW)

**Purpose**: Provide a testing/demo trace reader that generates infinite random tree

**Structs**:

1. **VirtualTraceReader** (implements TraceReader):
   - Config: max_depth, max_children, seed
   - `read()` returns VirtualTraceData (ignores file_path parameter)

2. **VirtualTraceData** (implements TraceData):
   - Stores generated root records
   - Implements metadata(), root_ids(), get_record()

3. **VirtualTraceMetadata** (implements TraceMetadata):
   - Returns hardcoded metadata values
   - version = "virtual-1.0"
   - Synthetic header data

4. **VirtualTraceRecord** (implements TraceRecord):
   - Generates random: id, name, description, clk, end_clk
   - Lazy generation of children (on-demand)
   - Random data fields (3-7 key-value pairs)
   - Random events (0-5 events per record)

5. **VirtualTraceEvent** (implements TraceEvent):
   - Random event data

**Generation Algorithm**:
```
VirtualTraceReader::read():
  1. Initialize RNG from seed
  2. Generate 1-5 root records
  3. Return VirtualTraceData

VirtualTraceRecord::children():
  1. If depth < max_depth:
     - Generate 0-max_children random child records
     - Recursively generate children's children
  2. Cache children after first generation
  3. Return cached children

Random record generation:
  - id: sequential counter
  - name: format!("Record_{}", id)
  - description: format!("Virtual record {}", id)
  - clk: parent_clk + random(10..100)
  - end_clk: clk + random(50..500)
  - data: 3-7 random key-value pairs
  - events: 0-5 random events
```

**Configuration**:
- max_depth: default 5
- max_children: default 10
- seed: default from system time

### Phase 4: Update GUI to Use Traits

#### File: `jets/rjets/src/main.rs`

**JetsViewerApp struct modifications**:
- Change: `trace_data: Option<Box<dyn TraceData>>` (trait object)
- Change: `reader: Box<dyn TraceReader>` (configurable reader)
- Add: constructor to choose reader type

**open_file() modifications**:
- Use: `self.reader.read(path.to_str().unwrap())?`
- Store: trait object instead of concrete type
- Handle errors through trait Result

**Rendering modifications** (render_header, render_tree, render_details):
- Access via trait methods instead of direct field access:
  - `trace.metadata().header_data()` instead of `trace.header.metadata`
  - `trace.root_ids()` to get root IDs
  - `trace.get_record(id)` to fetch records
- Use trait object references throughout
- Remove `.clone()` where possible (work with references)

**Recursive rendering** (render_record_tree):
- Change parameter: `record: &dyn TraceRecord`
- Access via: `record.children()` returns `Vec<&dyn TraceRecord>`
- Access data: `record.data()` for merged data + annotations

**Details panel rendering** (render_details):
- Show merged data from `record.data()`
- Show events from `record.events()`
- No separate annotations section (merged into data)

**Reader selection** : Always use JetsTraceReader for now

### Phase 5: Update Tests

#### File: `jets/rjets/tests/integration_test.rs`

**Modifications**:

**Test: test_write_and_read_basic_trace**:
- Change: Use `Box<dyn TraceReader>` instead of direct parse_trace()
- Create: `let reader: Box<dyn TraceReader> = Box::new(JetsTraceReader::new());`
- Read: `let trace = reader.read(test_file)?;`
- Access via traits:
  - `trace.metadata().version()` instead of `trace.header.version`
  - `trace.root_ids()` to get roots
  - `trace.get_record(root_id)` to access records
- Verify: merged data includes annotations

**Test: test_write_and_read_hierarchical_trace**:
- Same trait-based access pattern
- Verify: children accessed via `record.children()`
- Verify: events accessed via `record.events()`

**New Test: test_virtual_reader**:
```rust
fn test_virtual_reader() -> Result<()> {
    let reader: Box<dyn TraceReader> = Box::new(VirtualTraceReader::new());
    let trace = reader.read("")?; // path ignored

    assert_eq!(trace.metadata().version(), "virtual-1.0");
    assert!(trace.root_ids().len() > 0);

    for root_id in trace.root_ids() {
        let record = trace.get_record(root_id).unwrap();
        assert!(record.id() == root_id);
        // Verify children generation
        let children = record.children();
        // Verify data and events
        assert!(record.data().len() >= 3);
    }
    Ok(())
}
```

**New Test: test_trait_polymorphism**:
```rust
fn test_trait_polymorphism() -> Result<()> {
    let readers: Vec<Box<dyn TraceReader>> = vec![
        Box::new(JetsTraceReader::new()),
        Box::new(VirtualTraceReader::new()),
    ];

    for reader in readers {
        let trace = reader.read("test.jets")?;
        // Verify trait interface works identically
        assert!(trace.metadata().version().len() > 0);
        assert!(trace.root_ids().len() > 0);
    }
    Ok(())
}
```

### Phase 6: Update Module Structure

#### File: `jets/rjets/src/lib.rs`

**Final exports**:
```rust
pub mod traits;
pub mod parser;
pub mod writer;
pub mod virtual_reader;

// Export traits
pub use traits::{
    TraceReader, TraceData, TraceMetadata,
    TraceRecord, TraceEvent
};

// Export JETS implementation
pub use parser::{
    JetsTraceReader, JetsTraceData, JetsTraceMetadata,
    JetsTraceRecord, JetsTraceEvent
};

// Export virtual implementation
pub use virtual_reader::{
    VirtualTraceReader, VirtualTraceData, VirtualTraceMetadata,
    VirtualTraceRecord, VirtualTraceEvent
};

// Export writer (unchanged)
pub use writer::TraceWriter;
```

### Algorithm: Merging Annotations into Record Data

**Location**: JetsTraceRecord::data() implementation

**Algorithm**:
```
fn data(&self) -> HashMap<String, serde_json::Value>:
  1. Create result = HashMap::new()

  2. If self.data is Some(value):
     - If value is Object:
       - For each (key, val) in object:
         - result.insert(key, val)
     - Else:
       - result.insert("data", value)

  3. For each annotation in self.annotations:
     - key = annotation.name
     - value = annotation.data
     - result.insert(key, value)
     - Note: Later annotations with same name override earlier

  4. Return result
```

**Rationale**:
- Annotations merge into data dictionary as requested
- Original data fields preserved
- Annotation name becomes dictionary key
- Annotation data becomes dictionary value
- Simple, flat key-value structure

### Data Structure Comparison

#### Before (Current):
```rust
TraceRecord {
    data: Option<serde_json::Value>,
    annotations: Vec<TraceAnnotation>,
    events: Vec<TraceEvent>,
    children: Vec<TraceRecord>,
    // ... other fields
}

// Annotations separate
TraceAnnotation {
    name: String,
    data: serde_json::Value,
    // ...
}
```

#### After (Trait API):
```rust
trait TraceRecord {
    fn data(&self) -> HashMap<String, serde_json::Value>; // Merged!
    fn events(&self) -> Vec<&dyn TraceEvent>;
    fn children(&self) -> Vec<&dyn TraceRecord>;
    // ... other methods
}

// Annotations merged into data() HashMap
// No separate annotations in trait API
```

### Binary Format Future Support

The trait architecture enables future binary format support:

**Future File**: `jets/rjets/src/binary_reader.rs`
```rust
pub struct BinaryTraceReader { /* ... */ }
impl TraceReader for BinaryTraceReader {
    fn read(&self, path: &str) -> Result<Box<dyn TraceData>> {
        // Parse binary format
        // Return BinaryTraceData implementing TraceData trait
    }
}
```

**No GUI changes required** - polymorphism handles it:
```rust
let reader: Box<dyn TraceReader> = if path.ends_with(".bin") {
    Box::new(BinaryTraceReader::new())
} else {
    Box::new(JetsTraceReader::new())
};
```

## 4. Implementation Checklist

### File Changes Summary

**New Files**:
1. `jets/rjets/src/traits.rs` - Trait definitions
2. `jets/rjets/src/virtual_reader.rs` - Virtual reader implementation

**Modified Files**:
1. `jets/rjets/src/parser.rs` - Rename structs, implement traits
2. `jets/rjets/src/lib.rs` - Update exports
3. `jets/rjets/src/main.rs` - Use trait objects
4. `jets/rjets/tests/integration_test.rs` - Use trait API

**Unchanged Files**:
- `jets/rjets/src/writer.rs` - No changes needed
- `jets/rjets/src/tracegen.rs` - No changes needed

### Implementation Order

1. ✅ Create `traits.rs` with all trait definitions
2. ✅ Rename structs in `parser.rs` (JetsTrace*)
3. ✅ Implement traits for JETS structs
4. ✅ Update `lib.rs` exports
5. ✅ Create `virtual_reader.rs` with virtual implementation
6. ✅ Update `main.rs` to use trait objects
7. ✅ Update `integration_test.rs` to use traits
8. ✅ Add new tests for virtual reader and polymorphism
9. ✅ Test and verify all functionality

### Testing Strategy

**Unit Tests**:
- Test each trait implementation independently
- Verify annotation merging in JetsTraceRecord::data()
- Verify virtual record generation

**Integration Tests**:
- Existing tests updated to use traits
- New test: virtual reader functionality
- New test: trait polymorphism (both readers)

**Manual Testing**:
- GUI with JETS reader on real trace files
- GUI with virtual reader (demo mode)
- Verify merged annotations display correctly

### Backward Compatibility

NOT NEEDED! YAY
