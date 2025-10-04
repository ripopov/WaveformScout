# JETS Format Specification

**JETS**: JSON Event Trace Streaming

## Version

**Current Version:** 2.0

## Overview

This document specifies **JETS** (JSON Event Trace Streaming), a streaming JSON format for hardware execution traces. JETS captures the complete execution pipeline as a hierarchical tree structure, from host dispatch through individual hardware operations, with precise clock timestamps.

JETS is designed to:
- Allow **real-time streaming** during hardware simulator execution
- Support incremental writing without buffering entire trace in memory
- Enable parsers to begin processing before simulation completes
- Represent execution trace data as a hierarchical pipeline tree

## Design Principles

1. **Stream-First Design**: JSON Lines format allows appending records, annotations, and events as they occur
2. **Separation of Concerns**: Three distinct node types (Records, Annotations, Events) for different trace data
3. **No Forward References**: All records must be emitted before their children/annotations/events
4. **Clock Timestamps**: All temporal data uses hardware clock cycles (CLK) as the time unit
5. **Extensibility**: Support arbitrary data fields for vendor-specific or architecture-specific information

---

## Streaming Format: JSON Lines

JETS uses **JSON Lines** format (`.jets` or `.jsonl` extension) where each line is a complete, valid JSON object. This enables:
- Writing records/events/annotations immediately as they occur
- Reading and processing traces incrementally (line-by-line)
- No need to close arrays or know total trace size in advance

### Line Types

Each line contains exactly one object with a `type` field indicating the line type:

1. **`header`** - File metadata (must be first line)
2. **`record`** - A hierarchical trace record (marks start)
3. **`record_end`** - Marks completion of a record with end timestamp
4. **`annotation`** - Non-timed metadata for a record
5. **`event`** - Timed operation/state change for a record
6. **`footer`** - Optional trace summary (last line)

---

## File Structure

```
<header line>
<record/record_end/annotation/event lines>
<optional footer line>
```

### Constraints

1. **Header First**: First line must be `type: "header"`
2. **No Forward References**: Records must appear before any annotations/events/record_end lines that reference them
3. **Parent Before Child**: Parent records must appear before their children
4. **Record End After Record**: `record_end` for a record must appear after the `record` line
5. **Footer Last**: If present, footer must be last line

## Line Type Schemas

### 1. Header Line

The **header** line contains metadata about the trace. Must be the first line.

#### Schema

```json
{
  "type": "header",
  "version": "2.0",
  "metadata": {
    "hardware_model": "Custom Processor v2",
    "architecture": "RISC Pipeline",
    "clock_frequency_mhz": 2520,
    "tool": "hwtracer v0.1",
    "timestamp": "2025-10-03T14:30:00Z"
  }
}
```

#### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Must be `"header"` |
| `version` | string | Yes | Format version (e.g., "2.0") |
| `metadata` | object | Yes | Trace metadata (hardware model, arch, clock freq, etc.) |

---

### 2. Record Line

**Records** form the hierarchical tree structure. Each represents a logical entity in the hardware execution pipeline. The `record` line marks the **start** of a record.

#### Schema

```json
{
  "type": "record",
  "id": "rec_001",
  "parent_id": null,
  "record_type": "HostProgram",
  "clk": 1000,
  "name": "ProcessTask",
  "data": {
    "process_id": 12345,
    "thread_id": 67890
  }
}
```

#### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Must be `"record"` |
| `id` | string | Yes | Globally unique identifier for this record |
| `parent_id` | string/null | Yes | ID of parent record; `null` for root nodes |
| `record_type` | string | Yes | Semantic type (e.g., "Pipeline", "Instruction", "ExecutionUnit") |
| `clk` | integer | Yes | Hardware clock cycle when this record/operation **begins** |
| `name` | string | Yes | Human-readable name or description |
| `data` | object | No | Arbitrary JSON object with additional fields |

**Streaming Constraint**: A record's parent must appear in the file **before** the record itself.

#### Visualization Metadata (Optional in `data` field)

For optimal Gantt chart rendering, records may include these optional fields in the `data` object:

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `color` | string | Hex color override for this record | `"#ff5722"` |
| `unit_id` | integer | Execution unit ID for swimlane grouping | `0` |
| `thread_id` | integer | Thread/lane ID within unit | `5` |
| `subunit_id` | integer | Sub-unit ID within execution unit | `16` |
| `display_label` | string | Short label to show on Gantt bar | `"LD R4"` |
| `status` | string | Visual state hint | `"running"`, `"stalled"`, `"complete"` |
| `criticality` | float | Critical path weight (0.0-1.0) | `0.85` |

---

### 3. Record End Line

**Record End** marks the completion of a record with an end timestamp. This allows calculating the exact duration of any operation.

#### Schema

```json
{
  "type": "record_end",
  "id": "rec_001",
  "clk": 1500
}
```

#### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Must be `"record_end"` |
| `id` | string | Yes | ID of the record that is ending (must reference existing record) |
| `clk` | integer | Yes | Hardware clock cycle when this record/operation **completes** |

**Streaming Constraint**: The referenced record must appear in the file **before** this record_end line.

**Duration Calculation**: Duration = `record_end.clk` - `record.clk`

**Note**: Not all records require a `record_end`. Some records (like configuration or metadata records) may not have a meaningful end time.

---

### 4. Annotation Line

**Annotations** attach non-timed metadata to records.

#### Schema

```json
{
  "type": "annotation",
  "record_id": "rec_005",
  "name": "GridDimensions",
  "data": {
    "x": 1024,
    "y": 1024,
    "z": 1
  }
}
```

#### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Must be `"annotation"` |
| `record_id` | string | Yes | ID of the record this annotation describes |
| `name` | string | Yes | Annotation name (e.g., "GridDimensions", "RegisterAllocation") |
| `data` | any | Yes | Arbitrary JSON value (object, array, primitive) |

**Streaming Constraint**: The referenced record must appear in the file **before** this annotation.

---

### 5. Event Line

**Events** represent timed operations or state changes.

#### Schema

```json
{
  "type": "event",
  "record_id": "rec_042",
  "name": "DecodeStage",
  "clk": 1151,
  "data": {
    "stage": "frontend"
  }
}
```

#### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Must be `"event"` |
| `record_id` | string | Yes | ID of the record this event is associated with |
| `name` | string | Yes | Event name (e.g., "DecodeStage", "CacheLookup") |
| `clk` | integer | Yes | Hardware clock cycle when this event occurs |
| `data` | any | No | Optional additional data about the event |

**Streaming Constraint**: The referenced record must appear in the file **before** this event.

#### Visualization Metadata (Optional in `data` field)

For Gantt chart event markers, events may include these optional fields:

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `color` | string | Hex color for event marker | `"#e74c3c"` |
| `icon` | string | Icon identifier for event type | `"cache_miss"`, `"stall"` |
| `severity` | string | Visual severity level | `"info"`, `"warning"`, `"error"` |
| `marker_style` | string | Visual style hint | `"box"`, `"diamond"`, `"circle"`, `"line"` |

---

### 6. Footer Line (Optional)

The **footer** line provides summary statistics. If present, must be the last line.

#### Schema

```json
{
  "type": "footer",
  "capture_end_clk": 50000,
  "total_records": 12458,
  "total_annotations": 3421,
  "total_events": 45892
}
```

#### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Must be `"footer"` |
| `capture_end_clk` | integer | No | Final hardware clock timestamp |
| `total_records` | integer | No | Total number of records written |
| `total_annotations` | integer | No | Total number of annotations written |
| `total_events` | integer | No | Total number of events written |
| (custom) | any | No | Additional summary fields as needed |

## Complete Streaming Example

Below is a complete trace file in JSON Lines format. Each line is a separate JSON object:

```jsonl
{"type":"header","version":"2.0","metadata":{"hardware_model":"Custom Processor v2","architecture":"RISC Pipeline","clock_frequency_mhz":1830,"tool":"hwtracer v0.1","timestamp":"2025-10-03T14:30:00Z"}}
{"type":"record","id":"rec_001","parent_id":null,"record_type":"HostProgram","clk":1000,"name":"main"}
{"type":"record","id":"rec_002","parent_id":"rec_001","record_type":"TaskSubmission","clk":1010}
{"type":"record","id":"rec_003","parent_id":"rec_002","record_type":"DispatchTask","clk":1040,"data":{"task_count":1024,"thread_count":16}}
{"type":"record","id":"rec_004","parent_id":"rec_003","record_type":"ExecutionEngine","clk":1050}
{"type":"record","id":"rec_005","parent_id":"rec_004","record_type":"DispatchRecord","clk":1060}
{"type":"annotation","record_id":"rec_005","name":"TaskDimensions","data":{"x":1024,"y":1024,"z":1}}
{"type":"annotation","record_id":"rec_005","name":"ThreadDimensions","data":{"x":16,"y":16,"z":1}}
{"type":"annotation","record_id":"rec_005","name":"SharedMemSize","data":"48KB"}
{"type":"record","id":"rec_010","parent_id":"rec_005","record_type":"ExecutionBlock","clk":1120,"data":{"block_idx":[0,0,0],"unit_id":0,"core_id":0}}
{"type":"record","id":"rec_011","parent_id":"rec_010","record_type":"ThreadGroup","clk":1130,"data":{"group_id":0,"thread_range":[0,31]}}
{"type":"annotation","record_id":"rec_011","name":"RegisterAllocation","data":"R0-R63 per thread"}
{"type":"annotation","record_id":"rec_011","name":"SchedulerSlot","data":{"scheduler":"Scheduler_0","slot":5}}
{"type":"record","id":"rec_020","parent_id":"rec_011","record_type":"Instruction","clk":1150,"data":{"pc":"0x0000","opcode":"MOV","disassembly":"MOV R0, #0x20"}}
{"type":"event","record_id":"rec_020","name":"DecodeStage","clk":1151}
{"type":"event","record_id":"rec_020","name":"ScoreboardCheck","clk":1152,"data":{"hazard":"RAW","status":"clear"}}
{"type":"event","record_id":"rec_020","name":"OperandCollect","clk":1153}
{"type":"event","record_id":"rec_020","name":"Execute_ALU","clk":1155,"data":{"alu_id":0}}
{"type":"event","record_id":"rec_020","name":"Writeback","clk":1156,"data":{"destination":"R0"}}
{"type":"record_end","id":"rec_020","clk":1156}
{"type":"record","id":"rec_021","parent_id":"rec_011","record_type":"Instruction","clk":1170,"data":{"pc":"0x0020","opcode":"LD","disassembly":"LD R4, [R2+0x1000]"}}
{"type":"event","record_id":"rec_021","name":"DecodeStage","clk":1171}
{"type":"event","record_id":"rec_021","name":"ScoreboardCheck","clk":1172,"data":{"hazard":"RAW","status":"R2 ready"}}
{"type":"event","record_id":"rec_021","name":"LoadUnit_AddressCalc","clk":1173}
{"type":"record","id":"rec_030","parent_id":"rec_021","record_type":"LoadUnit_Coalescing","clk":1180}
{"type":"record","id":"rec_031","parent_id":"rec_030","record_type":"MemoryRequest","clk":1181,"data":{"size_bytes":128,"aligned":true,"lanes":"0-31"}}
{"type":"event","record_id":"rec_031","name":"L1_Cache_Lookup","clk":1182}
{"type":"event","record_id":"rec_031","name":"L1_Cache_Miss","clk":1183,"data":{"tag":"0x200001000"}}
{"type":"event","record_id":"rec_031","name":"L2_Lookup","clk":1187,"data":{"result":"MISS"}}
{"type":"event","record_id":"rec_031","name":"Memory_Activate","clk":1191,"data":{"bank":5,"row":"0x4000"}}
{"type":"event","record_id":"rec_031","name":"Memory_Read","clk":1192,"data":{"column":"0x40","burst_length":8}}
{"type":"record_end","id":"rec_031","clk":1205}
{"type":"record_end","id":"rec_030","clk":1205}
{"type":"record_end","id":"rec_021","clk":1206}
{"type":"record_end","id":"rec_011","clk":1300}
{"type":"record_end","id":"rec_010","clk":1301}
{"type":"footer","capture_end_clk":1301,"total_records":11,"total_annotations":5,"total_events":13,"total_record_ends":6}
```

### Pretty-Printed Example (Selected Lines)

For readability, here are some lines formatted with record_end examples:

```json
{
  "type": "header",
  "version": "2.0",
  "metadata": {
    "hardware_model": "Custom Processor v2",
    "architecture": "RISC Pipeline",
    "clock_frequency_mhz": 1830,
    "tool": "hwtracer v0.1",
    "timestamp": "2025-10-03T14:30:00Z"
  }
}

{
  "type": "record",
  "id": "rec_020",
  "parent_id": "rec_011",
  "record_type": "Instruction",
  "clk": 1150,
  "data": {
    "pc": "0x0000",
    "opcode": "MOV",
    "disassembly": "MOV R0, #0x20"
  }
}

{
  "type": "event",
  "record_id": "rec_020",
  "name": "DecodeStage",
  "clk": 1151
}

{
  "type": "event",
  "record_id": "rec_020",
  "name": "Writeback",
  "clk": 1156,
  "data": {
    "destination": "R0"
  }
}

{
  "type": "record_end",
  "id": "rec_020",
  "clk": 1156
}
```

**Duration Calculation**: Instruction `rec_020` duration = 1156 - 1150 = **6 cycles**

---

## Tree Reconstruction

To reconstruct the hierarchical tree from streaming format:

1. Read file line-by-line
2. Parse header line, extract metadata
3. For each subsequent line:
   - If `type == "record"`: Add to records map indexed by `id`
   - If `type == "record_end"`: Set end timestamp on the record
   - If `type == "annotation"`: Attach to record identified by `record_id`
   - If `type == "event"`: Attach to record identified by `record_id`
   - If `type == "footer"`: Process summary statistics
4. Build tree by linking children to parents via `parent_id`

**Pseudocode:**

```python
def parse_streaming_trace(file_path):
    records_by_id = {}
    header = None
    footer = None

    with open(file_path, 'r') as f:
        for line in f:
            obj = json.loads(line)

            if obj['type'] == 'header':
                header = obj

            elif obj['type'] == 'record':
                record = obj
                record['children'] = []
                record['annotations'] = []
                record['events'] = []
                record['end_clk'] = None  # Will be set by record_end
                record['duration'] = None
                records_by_id[record['id']] = record

                # Link to parent
                if record['parent_id'] is not None:
                    parent = records_by_id[record['parent_id']]
                    parent['children'].append(record)

            elif obj['type'] == 'record_end':
                record = records_by_id[obj['id']]
                record['end_clk'] = obj['clk']
                record['duration'] = obj['clk'] - record['clk']

            elif obj['type'] == 'annotation':
                record = records_by_id[obj['record_id']]
                record['annotations'].append(obj)

            elif obj['type'] == 'event':
                record = records_by_id[obj['record_id']]
                record['events'].append(obj)

            elif obj['type'] == 'footer':
                footer = obj

    # Return root nodes
    roots = [r for r in records_by_id.values() if r['parent_id'] is None]
    return {
        'header': header,
        'roots': roots,
        'footer': footer
    }
```

---

## Streaming Writer Example

Simulator code can write trace as events occur:

```python
class TraceWriter:
    def __init__(self, file_path):
        self.file = open(file_path, 'w')
        self.record_count = 0
        self.annotation_count = 0
        self.event_count = 0
        self.record_end_count = 0

    def write_header(self, metadata):
        line = json.dumps({
            'type': 'header',
            'version': '2.0',
            'metadata': metadata
        })
        self.file.write(line + '\n')
        self.file.flush()

    def write_record(self, id, parent_id, record_type, clk, name=None, data=None):
        line = json.dumps({
            'type': 'record',
            'id': id,
            'parent_id': parent_id,
            'record_type': record_type,
            'clk': clk,
            'name': name,
            'data': data
        }, separators=(',', ':'))
        self.file.write(line + '\n')
        self.file.flush()
        self.record_count += 1

    def write_record_end(self, id, clk):
        line = json.dumps({
            'type': 'record_end',
            'id': id,
            'clk': clk
        }, separators=(',', ':'))
        self.file.write(line + '\n')
        self.file.flush()
        self.record_end_count += 1

    def write_annotation(self, record_id, name, data):
        line = json.dumps({
            'type': 'annotation',
            'record_id': record_id,
            'name': name,
            'data': data
        }, separators=(',', ':'))
        self.file.write(line + '\n')
        self.file.flush()
        self.annotation_count += 1

    def write_event(self, record_id, name, clk, data=None):
        line = json.dumps({
            'type': 'event',
            'record_id': record_id,
            'name': name,
            'clk': clk,
            'data': data
        }, separators=(',', ':'))
        self.file.write(line + '\n')
        self.file.flush()
        self.event_count += 1

    def write_footer(self, capture_end_clk):
        line = json.dumps({
            'type': 'footer',
            'capture_end_clk': capture_end_clk,
            'total_records': self.record_count,
            'total_annotations': self.annotation_count,
            'total_events': self.event_count,
            'total_record_ends': self.record_end_count
        })
        self.file.write(line + '\n')
        self.file.flush()

    def close(self):
        self.file.close()

# Usage in simulator
trace = TraceWriter('trace.jsonl')
trace.write_header({'hardware_model': 'Custom Processor v2', 'tool': 'hwtracer'})

# As simulation runs...
trace.write_record('rec_001', None, 'HostProgram', clk=1000)
trace.write_record('rec_002', 'rec_001', 'Dispatch', clk=1010)
trace.write_event('rec_002', 'Issue', clk=1015)

# ... instruction executes ...
trace.write_record('inst_001', 'rec_002', 'Instruction', clk=1020)
trace.write_event('inst_001', 'DecodeStage', clk=1021)
trace.write_event('inst_001', 'Execute', clk=1025)
trace.write_event('inst_001', 'Writeback', clk=1027)
trace.write_record_end('inst_001', clk=1027)  # Instruction completes (7 cycle duration)

trace.write_record_end('rec_002', clk=1030)
trace.write_footer(capture_end_clk=1030)
trace.close()
```

---

## Clock Timestamp Semantics

- **`clk` (Records)**: The hardware clock cycle when this record/operation **begins** or is **issued**
- **`clk` (Record End)**: The hardware clock cycle when this record/operation **completes**
- **`clk` (Events)**: The hardware clock cycle when this event **occurs**

### Duration Calculation

For any record with a corresponding `record_end`:
```
duration = record_end.clk - record.clk
```

Examples:
- **Instruction latency**: Time from instruction issue to writeback complete
- **Memory transaction**: Time from request issue to data return
- **Thread group execution**: Time from thread group launch to all threads complete
- **Task duration**: Time from dispatch to all execution blocks complete

### Timestamp Guidelines

For instruction execution:
- **Record `clk`**: Instruction issue time (when it enters the pipeline)
- **Event `clk`**: Specific pipeline stage timestamps (Decode, Execute, Writeback)
- **Record End `clk`**: Instruction completion time (typically same as last event)

For memory operations:
- **Record `clk`**: Memory request issue
- **Event `clk`**: Cache lookup, memory access stages
- **Record End `clk`**: Data return/write acknowledgment

---

## Common Record Types

Suggested standardized `type` values for records:

| Type | Description |
|------|-------------|
| `HostProgram` | Host application/process |
| `TaskSubmission` | Task/work submission |
| `CommandBuffer` | Command buffer |
| `DispatchTask` | Task dispatch |
| `ExecutionEngine` | Execution engine |
| `DispatchRecord` | Dispatch metadata |
| `ExecutionBlock` | Execution block/work group |
| `ThreadGroup` | Thread group |
| `Instruction` | Hardware instruction |
| `MemoryRequest` | Memory request |
| `CacheOperation` | Cache lookup/fill operation |
| `MemoryTransaction` | Memory-level transaction |

Vendors may define additional types as needed.

---

## Common Event Names

Suggested standardized event names:

### Pipeline Stages
- `DecodeStage`
- `ScoreboardCheck`
- `OperandCollect`
- `Execute_<unit>` (e.g., `Execute_ALU`, `Execute_FPU`, `Execute_VectorUnit`)
- `Writeback`

### Memory Operations
- `L0_Cache_Lookup`, `L1_Cache_Lookup`, `L2_Cache_Lookup`
- `L0_Cache_Miss`, `L1_Cache_Miss`, `L2_Cache_Miss`
- `L0_Cache_Hit`, `L1_Cache_Hit`, `L2_Cache_Hit`
- `Cache_Fill`
- `Memory_Activate`, `Memory_Read`, `Memory_Write`, `Memory_Precharge`

### Resource Access
- `SharedMem_Read`, `SharedMem_Write`
- `ConstantMem_Access`
- `ScratchMem_Access`
- `RegisterFile_Read`, `RegisterFile_Write`

### Stalls
- `Stall_RAW` (Read-After-Write dependency)
- `Stall_WAW` (Write-After-Write dependency)
- `Stall_Memory`
- `Stall_Scoreboard`
- `Stall_Barrier`

### Synchronization
- `Barrier_Arrive`
- `Barrier_Release`
- `Fence_Acquire`
- `Fence_Release`

---

## Validation Rules

1. **ID Uniqueness**: All `id` fields in `records` must be globally unique
2. **Parent References**: All non-null `parent_id` values must reference existing record IDs
3. **No Cycles**: The parent-child relationships must form a directed acyclic graph (DAG) - typically a tree or forest
4. **Annotation/Event References**: All `record_id` fields in annotations and events must reference existing record IDs
5. **Clock Monotonicity**: Timestamps must follow logical ordering constraints
   - Within a parent-child relationship, child `clk` should be ≥ parent `clk` (children start after parents)
   - Events attached to the same record must have non-decreasing `clk` values (multiple events can occur at the same cycle)
   - Record end times must be strictly greater than record start times (`record_end.clk > record.clk`)

---

## Extensions

### Custom Fields

Implementations may add vendor-specific or tool-specific fields to any object:

```json
{
  "id": "rec_001",
  "parent_id": null,
  "type": "ThreadGroup",
  "clk": 1000,
  "_vendor_custom": {
    "hw_version": "2.0",
    "feature_set": "extended"
  },
  "_tool_hwtracer": {
    "trace_session_id": "abc123"
  }
}
```

Convention: prefix custom fields with `_vendor_<name>` or `_tool_<name>` to avoid conflicts.

### Binary Payload

For very large traces, binary sections may be referenced:

```json
{
  "record_id": "rec_100",
  "type": "WarpRegisterDump",
  "data": {
    "_binary_ref": {
      "file": "trace_001.bin",
      "offset": 1024,
      "length": 8192,
      "format": "float32_array"
    }
  }
}
```

---

## File Conventions

- **File Extension**: `.jets` (preferred) or `.jsonl` (for compatibility)
- **Compression**: May be compressed with gzip (`.jets.gz` or `.jsonl.gz`)
- **Line Format**: Each line must be a complete, valid JSON object
- **Line Separator**: Unix newline (`\n`) or Windows CRLF (`\r\n`)
- **Encoding**: UTF-8

---

## Implementation Notes

### Performance Considerations

- **Streaming Write**: Flush after each line to ensure trace survives simulator crashes
- **Memory Efficient**: No need to buffer entire trace in memory
- **Parallel Parsing**: Multiple threads can process different sections (after initial pass to build ID map)
- **Fast IDs**: Use integer-based IDs (e.g., `"rec_00001234"`) for faster lookups than UUIDs
- **Compression**: gzip compression reduces file size by ~70-90% for typical traces

### Simulator Integration

When integrating into a hardware simulator:

1. **Initialization**: Open trace file, write header line
2. **Record Emission**: Emit records in depth-first tree traversal order (parent before children)
3. **Immediate Writes**: Call `flush()` after each write to ensure data persists
4. **Annotations**: Write immediately after parent record is emitted
5. **Events**: Write as they occur during execution
6. **Cleanup**: Write footer line, close file

**Important**: Always emit a record before emitting any annotations or events that reference it.

### Gantt Chart Visualization

JETS is specifically designed to support **best-in-class Gantt charts** for hardware pipeline profiling:

#### 1. Record Tree (Vertical Axis)
- **Hierarchical Layout**: Records arranged in parent-child tree structure
- **Collapsible Nodes**: Expand/collapse branches to manage complexity
- **Visual Indent**: Child records indented under parents
- **Type Icons**: Different icons per `record_type` (ThreadGroup, Instruction, MemoryRequest, etc.)

#### 2. Timeline Axis (Horizontal Axis)
- **Clock Cycle Scale**: X-axis shows hardware clock cycles
- **Flexible Zoom**: Support nanosecond to millisecond ranges (use `metadata.clock_frequency_mhz` for conversion)
- **Grid Lines**: Vertical lines at regular intervals (every 10/100/1000 cycles)
- **Time Labels**: Show both cycles and real time (µs, ms)

#### 3. Record Bars
- **Start Position**: `record.clk` determines left edge
- **End Position**: `record_end.clk` determines right edge (if present)
- **Duration**: Bar width = `record_end.clk - record.clk`
- **Open Records**: Records without `record_end` shown as ongoing (dashed right edge or extending to viewport edge)
- **Color by Type**: Each `record_type` has consistent color (see Color Coding section)
- **Transparency**: Nested records use alpha blending to show overlap

#### 4. Event Markers
- **Position**: Events placed at their `clk` timestamp within parent record bar
- **Visual Style**: Small boxes, diamonds, or vertical lines inside record bars
- **Color by Event**: Different colors per event `name` (DecodeStage=blue, CacheMiss=red, etc.)
- **Tooltips**: Hover shows event details from `data` field
- **Stacking**: Multiple events at same timestamp stacked vertically

#### 5. Annotation Display
- **Metadata Tooltips**: Annotations shown on record hover
- **Detail Panel**: Click record to show all annotations in side panel
- **Inline Labels**: Key annotations (e.g., PC address, thread ID) displayed on bar

#### 6. Color Coding Strategy

**Record Types** (using HSL for consistent brightness):
```
HostProgram:        #1f77b4 (blue)
TaskSubmission:     #ff7f0e (orange)
DispatchTask:       #2ca02c (green)
ExecutionEngine:    #d62728 (red)
ExecutionBlock:     #9467bd (purple)
ThreadGroup:        #8c564b (brown)
Instruction:        #e377c2 (pink)
MemoryRequest:      #7f7f7f (gray)
CacheOperation:     #bcbd22 (olive)
MemoryTransaction:  #17becf (cyan)
```

**Event Categories**:
- Pipeline Stages: Blue shades (`#3498db`, `#5dade2`, `#85c1e2`)
- Cache Hits: Green (`#27ae60`)
- Cache Misses: Red (`#e74c3c`)
- Memory Access: Orange (`#e67e22`)
- Stalls: Dark red (`#c0392b`)
- Synchronization: Purple (`#8e44ad`)

**Status/State Colors**:
- Active/Running: Bright colors
- Stalled/Blocked: Desaturated colors with crosshatch pattern
- Completed: Semi-transparent

#### 7. Advanced Visualization Features

**Dependency Lines**:
- Use record parent-child relationships to draw dependency arrows
- Show data flow between operations

**Critical Path Highlighting**:
- Calculate longest latency path through records
- Highlight critical path records in bold/different color

**Heatmap Mode**:
- Color intensity based on duration (longer operations = warmer colors)

**Filtering**:
- Show/hide record types
- Filter by `record_type`, time range, or data fields

**Multi-Unit View**:
- Group records by execution unit ID (from `data.unit_id`)
- Show parallel execution across units in swimlanes

### Querying

Example queries on this format:
- **Find all L2 cache misses**: Filter event lines where `name == "L2_Cache_Miss"`
- **Calculate instruction latency**: For records with `record_end`, use `duration` field or compute `end_clk - clk`
- **Identify memory bottlenecks**: Count memory access events per thread group record
- **Trace critical path**: Follow longest dependency chain through events
- **Extract execution unit activity**: Filter records where `record_type == "ThreadGroup"` and group by `data.unit_id`
- **Find slowest operations**: Sort records by `duration` field (descending)
- **Timeline analysis**: Plot records on timeline using `clk` (start) and `end_clk` (end) for Gantt chart visualization

### Streaming Parser

For real-time monitoring of a running simulation:

```python
import json
import time

def tail_trace(file_path):
    """Read and process trace file as it's being written"""
    records_by_id = {}

    with open(file_path, 'r') as f:
        # Read header
        header = json.loads(f.readline())
        print(f"Trace started: {header['metadata']}")

        # Follow file as it grows
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.1)  # Wait for more data
                continue

            obj = json.loads(line)

            if obj['type'] == 'record':
                records_by_id[obj['id']] = obj
                print(f"[CLK {obj['clk']}] Record START: {obj['record_type']} ({obj['id']})")

            elif obj['type'] == 'record_end':
                record = records_by_id[obj['id']]
                duration = obj['clk'] - record['clk']
                print(f"[CLK {obj['clk']}] Record END: {record['record_type']} ({obj['id']}) - Duration: {duration} cycles")

            elif obj['type'] == 'event':
                print(f"[CLK {obj['clk']}] Event: {obj['name']} on {obj['record_id']}")

            elif obj['type'] == 'footer':
                print(f"Trace completed: {obj}")
                break
```

---

## Validation Rules

1. **Header First**: First line must be `type: "header"`
2. **ID Uniqueness**: All record `id` fields must be globally unique
3. **Parent References**: All non-null `parent_id` values must reference record IDs that appeared earlier in the file
4. **Record End References**: All `record_end` `id` fields must reference record IDs that appeared earlier in the file
5. **Annotation/Event References**: All `record_id` fields must reference record IDs that appeared earlier in the file
6. **No Cycles**: The parent-child relationships must form a directed acyclic graph (DAG)
7. **Clock Monotonicity**:
   - Within a parent-child relationship, child `clk` should be ≥ parent `clk`
   - For `record_end`, `clk` must be > corresponding record's `clk` (strictly greater - duration must be positive)
   - Events for the same record must have non-decreasing `clk` values (multiple events can occur at the same clock cycle)
8. **Valid Durations**: Records with `record_end` must have positive duration (`record_end.clk > record.clk`)
9. **Footer Last**: If present, footer must be the last line
10. **Valid JSON**: Each line must be valid, parseable JSON
11. **Record End Uniqueness**: Each record should have at most one `record_end` line

---

## Advantages of Streaming Format

| Feature | Benefit |
|---------|---------|
| **Real-time Writing** | Simulator can write trace as execution progresses, no buffering needed |
| **Crash Recovery** | Partial traces are still valid and usable if simulator crashes |
| **Memory Efficiency** | No need to hold entire trace in memory before writing |
| **Parallel Processing** | Parsers can begin processing before simulation completes |
| **Incremental Analysis** | Tools can analyze trace in real-time during simulation |
| **Large Traces** | Can handle traces that exceed available RAM |
| **Simple Format** | Line-oriented format is easy to parse and debug |
| **Explicit Durations** | `record_end` provides precise operation timing without post-processing |

---

## Conversion Tools

### Convert to Legacy Format

To convert streaming format to the legacy array-based JSON format:

```python
def convert_to_legacy(jsonl_path):
    records = []
    annotations = []
    events = []
    header = None

    with open(jsonl_path, 'r') as f:
        for line in f:
            obj = json.loads(line)
            if obj['type'] == 'header':
                header = obj
            elif obj['type'] == 'record':
                records.append({k: v for k, v in obj.items() if k != 'type'})
            elif obj['type'] == 'annotation':
                annotations.append({k: v for k, v in obj.items() if k != 'type'})
            elif obj['type'] == 'event':
                events.append({k: v for k, v in obj.items() if k != 'type'})

    return {
        'version': header['version'],
        'metadata': header['metadata'],
        'records': records,
        'annotations': annotations,
        'events': events
    }
```

### Validate Streaming Trace

```python
def validate_trace(jsonl_path):
    seen_ids = set()
    record_ends = {}
    line_num = 0

    with open(jsonl_path, 'r') as f:
        # Check header
        line = f.readline()
        line_num += 1
        header = json.loads(line)
        assert header['type'] == 'header', f"Line {line_num}: First line must be header"

        for line in f:
            line_num += 1
            obj = json.loads(line)

            if obj['type'] == 'record':
                assert obj['id'] not in seen_ids, f"Line {line_num}: Duplicate ID {obj['id']}"
                seen_ids.add(obj['id'])
                if obj['parent_id'] is not None:
                    assert obj['parent_id'] in seen_ids, f"Line {line_num}: Unknown parent {obj['parent_id']}"

            elif obj['type'] == 'record_end':
                assert obj['id'] in seen_ids, f"Line {line_num}: Unknown record {obj['id']}"
                assert obj['id'] not in record_ends, f"Line {line_num}: Duplicate record_end for {obj['id']}"
                record_ends[obj['id']] = obj['clk']

            elif obj['type'] in ['annotation', 'event']:
                assert obj['record_id'] in seen_ids, f"Line {line_num}: Unknown record {obj['record_id']}"

            elif obj['type'] == 'footer':
                # Must be last line
                assert f.readline() == '', f"Line {line_num}: Footer must be last line"

    print(f"Validation passed: {line_num} lines, {len(seen_ids)} records, {len(record_ends)} record_ends")
```

---

## Gantt Chart Implementation Guide

This section provides concrete guidance for implementing a high-quality Gantt chart visualizer.

### Data Structures

```python
class GanttRecord:
    def __init__(self, record_obj):
        self.id = record_obj['id']
        self.parent_id = record_obj['parent_id']
        self.record_type = record_obj['record_type']
        self.clk_start = record_obj['clk']
        self.clk_end = None  # Set by record_end
        self.name = record_obj.get('name', '')
        self.data = record_obj.get('data', {})
        self.children = []
        self.events = []
        self.annotations = []

    @property
    def duration(self):
        return (self.clk_end - self.clk_start) if self.clk_end else None

    @property
    def color(self):
        # Override color if specified
        if 'color' in self.data:
            return self.data['color']
        # Default color by type
        return COLOR_MAP.get(self.record_type, '#808080')

    @property
    def display_label(self):
        if 'display_label' in self.data:
            return self.data['display_label']
        return self.name or f"{self.record_type} {self.id}"
```

### Rendering Algorithm

```python
def render_gantt_chart(trace_data, viewport_start_clk, viewport_end_clk):
    """
    Render Gantt chart for given time range
    """
    # 1. Build tree and calculate layout
    records = build_record_tree(trace_data)
    row_positions = calculate_row_positions(records)

    # 2. Calculate time scale
    pixels_per_cycle = calculate_time_scale(viewport_start_clk, viewport_end_clk, canvas_width)

    # 3. Render timeline axis
    render_timeline_axis(viewport_start_clk, viewport_end_clk, pixels_per_cycle)

    # 4. Render record bars
    for record in records:
        if is_visible(record, viewport_start_clk, viewport_end_clk):
            render_record_bar(record, row_positions[record.id], pixels_per_cycle)

            # 5. Render events within bar
            for event in record.events:
                if viewport_start_clk <= event['clk'] <= viewport_end_clk:
                    render_event_marker(event, row_positions[record.id], pixels_per_cycle)

def calculate_row_positions(records):
    """
    Calculate Y position for each record in tree layout
    """
    positions = {}
    y_offset = 0
    ROW_HEIGHT = 30

    def traverse(record, depth, is_expanded):
        nonlocal y_offset
        positions[record.id] = {
            'y': y_offset,
            'depth': depth,
            'height': ROW_HEIGHT
        }
        y_offset += ROW_HEIGHT

        # Render children if expanded
        if is_expanded and record.children:
            for child in sorted(record.children, key=lambda r: r.clk_start):
                traverse(child, depth + 1, is_expanded)

    for root in records:
        traverse(root, 0, True)

    return positions

def render_record_bar(record, position, pixels_per_cycle):
    """
    Draw horizontal bar for record
    """
    x_start = record.clk_start * pixels_per_cycle

    if record.clk_end:
        x_end = record.clk_end * pixels_per_cycle
        width = x_end - x_start
        style = 'solid'
    else:
        # Open-ended record
        x_end = canvas_width
        width = x_end - x_start
        style = 'dashed'

    # Draw bar with color and style
    draw_rect(
        x=x_start,
        y=position['y'],
        width=width,
        height=position['height'] - 2,  # 2px gap
        fill=record.color,
        opacity=get_opacity(record),
        stroke_style=style
    )

    # Draw label
    if width > 50:  # Only show label if bar is wide enough
        draw_text(
            text=record.display_label,
            x=x_start + 5,
            y=position['y'] + position['height'] / 2,
            color='white' if is_dark(record.color) else 'black'
        )

def render_event_marker(event, position, pixels_per_cycle):
    """
    Draw event marker inside record bar
    """
    x = event['clk'] * pixels_per_cycle
    y = position['y'] + position['height'] / 2

    marker_style = event['data'].get('marker_style', 'box')
    color = event['data'].get('color', get_event_color(event['name']))

    if marker_style == 'box':
        draw_rect(x - 3, y - 3, 6, 6, fill=color)
    elif marker_style == 'diamond':
        draw_diamond(x, y, size=6, fill=color)
    elif marker_style == 'circle':
        draw_circle(x, y, radius=3, fill=color)
    elif marker_style == 'line':
        draw_line(x, position['y'], x, position['y'] + position['height'], color=color)

    # Tooltip on hover
    attach_tooltip(x, y, event_tooltip_html(event))
```

### Color Scheme Implementation

```python
COLOR_MAP = {
    'HostProgram': '#1f77b4',
    'TaskSubmission': '#ff7f0e',
    'DispatchTask': '#2ca02c',
    'ExecutionEngine': '#d62728',
    'ExecutionBlock': '#9467bd',
    'ThreadGroup': '#8c564b',
    'Instruction': '#e377c2',
    'MemoryRequest': '#7f7f7f',
    'CacheOperation': '#bcbd22',
    'MemoryTransaction': '#17becf',
}

EVENT_COLORS = {
    'DecodeStage': '#3498db',
    'Execute_ALU': '#5dade2',
    'Writeback': '#85c1e2',
    'L1_Cache_Hit': '#27ae60',
    'L1_Cache_Miss': '#e74c3c',
    'L2_Cache_Hit': '#27ae60',
    'L2_Cache_Miss': '#e74c3c',
    'Memory_Read': '#e67e22',
    'Memory_Write': '#d35400',
    'Stall_RAW': '#c0392b',
    'Stall_Memory': '#a93226',
    'Barrier_Arrive': '#8e44ad',
    'Barrier_Release': '#9b59b6',
}

def get_event_color(event_name):
    return EVENT_COLORS.get(event_name, '#95a5a6')

def get_opacity(record):
    """Calculate opacity based on status"""
    status = record.data.get('status', 'running')
    if status == 'complete':
        return 0.6
    elif status == 'stalled':
        return 0.8
    else:
        return 1.0
```

### Timeline Axis Rendering

```python
def render_timeline_axis(start_clk, end_clk, pixels_per_cycle, clock_freq_mhz):
    """
    Render timeline with cycle and real-time labels
    """
    total_cycles = end_clk - start_clk

    # Determine tick interval (powers of 10)
    if total_cycles < 100:
        tick_interval = 10
    elif total_cycles < 1000:
        tick_interval = 100
    else:
        tick_interval = 1000

    # Draw ticks and labels
    for clk in range(start_clk, end_clk, tick_interval):
        x = (clk - start_clk) * pixels_per_cycle

        # Vertical grid line
        draw_line(x, 0, x, canvas_height, color='#e0e0e0', width=1)

        # Cycle label
        draw_text(f"{clk}", x, 10, size=10, color='#333')

        # Real time label (if clock frequency known)
        if clock_freq_mhz:
            time_ns = (clk * 1000) / clock_freq_mhz
            if time_ns < 1000:
                draw_text(f"{time_ns:.1f}ns", x, 25, size=9, color='#666')
            else:
                time_us = time_ns / 1000
                draw_text(f"{time_us:.2f}µs", x, 25, size=9, color='#666')
```

### Multi-Unit Swimlane View

```python
def render_unit_swimlanes(trace_data):
    """
    Group records by execution unit and render in parallel swimlanes
    """
    # Group by execution unit
    unit_records = defaultdict(list)
    for record in all_records:
        unit_id = record.data.get('unit_id', 0)
        unit_records[unit_id].append(record)

    # Render each unit in its own swimlane
    y_offset = 0
    UNIT_LANE_HEIGHT = 200

    for unit_id in sorted(unit_records.keys()):
        # Draw lane separator
        draw_line(0, y_offset, canvas_width, y_offset, color='#333', width=2)

        # Draw unit label
        draw_text(f"Unit {unit_id}", 10, y_offset + 20, size=14, bold=True)

        # Render records in this unit
        render_records_in_lane(unit_records[unit_id], y_offset + 30, UNIT_LANE_HEIGHT - 30)

        y_offset += UNIT_LANE_HEIGHT
```

### Interactive Features

```python
class GanttInteraction:
    def on_record_click(self, record):
        """Show detailed panel for record"""
        show_detail_panel({
            'Record ID': record.id,
            'Type': record.record_type,
            'Duration': f"{record.duration} cycles",
            'Start': record.clk_start,
            'End': record.clk_end,
            'Annotations': record.annotations,
            'Events': len(record.events)
        })

    def on_record_hover(self, record):
        """Show tooltip"""
        show_tooltip(f"""
            {record.display_label}
            Start: {record.clk_start} cycles
            Duration: {record.duration} cycles
            {len(record.events)} events
        """)

    def on_zoom(self, zoom_factor, center_clk):
        """Zoom timeline around center point"""
        new_range = (viewport_end_clk - viewport_start_clk) / zoom_factor
        viewport_start_clk = center_clk - new_range / 2
        viewport_end_clk = center_clk + new_range / 2
        redraw()

    def on_pan(self, delta_clk):
        """Pan timeline left/right"""
        viewport_start_clk += delta_clk
        viewport_end_clk += delta_clk
        redraw()
```

### Export Formats

JETS supports exporting Gantt charts to:
- **SVG**: Vector format for publications
- **PNG/PDF**: Raster/print formats
- **Chrome Trace Format**: For viewing in chrome://tracing
- **Perfetto**: For advanced timeline analysis

---

## Visual Gantt Chart Example

Here's how a hardware trace should appear in a Gantt chart visualizer:

```
Record Tree                 Timeline (Hardware Clock Cycles) →
(Vertical Axis)     1000      1050      1100      1150      1200      1250      1300

▼ HostProgram       ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  └▼ Dispatch       ···━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
     └▼ ExecEng     ·········━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
       └▼ ExecBlk   ···················━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
         └▼ TG0     ·························━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
           ├─ MOV   ·····························█D█S█E█W█··························
           │                                     ↑ ↑ ↑ ↑ ↑
           │                               Events: D=Decode, S=Scoreboard,
           │                                       E=Execute, W=Writeback
           └─ LD    ·········································█D█S█A█L█L█L█M█··········
                                                              ↑ ↑ ↑ ↑🔴↑🔴↑
                                                  Events: Cache Miss (🔴), Memory Access

Legend:
━━━  Record bar (solid = has end time)
···  Record bar (dashed = no end time / ongoing)
█    Event marker (colored box)
🔴   Cache miss event (red)
↑    Event timestamp marker
```

### Gantt Chart Layout Breakdown

**Record Tree Column (Left)**
- Hierarchical indentation shows parent-child relationships
- `▼` indicates collapsible nodes (click to expand/collapse)
- Record type shown with abbreviated names
- Depth represented by horizontal spacing

**Timeline Area (Right)**
- Horizontal bars span from `record.clk` to `record_end.clk`
- Bar color indicates `record_type` (see color map)
- Small colored boxes/markers show events at specific clock cycles
- Grid lines at regular intervals for easy time reading

**Interactive Elements**
- **Hover** record bar → show tooltip with duration, annotations
- **Click** record → expand detail panel
- **Hover** event marker → show event details
- **Zoom** with mouse wheel on timeline
- **Pan** by dragging timeline
- **Filter** by record type checkboxes

### Example with Color Coding

```
Unit 0 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ThreadGrp 0  [========= 170 cycles =========] (#8c564b brown)
    Inst MOV   |▪Decode ▪Exec ▪Write|           (pipeline events in blue)
    Inst LD    |▪Decode ▪Addr 🔴Miss ⚠Mem|      (cache miss in red, Memory in orange)

  ThreadGrp 1  [============ 185 cycles ============]
    Inst ADD   |▪▪▪|
    Inst ST    |▪▪🔴▪|

Unit 1 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ThreadGrp 0  [========= 165 cycles =========]
    ...

Legend:
[====]  Record duration bar
|      Record boundary
▪      Pipeline stage event (blue)
🔴     Cache miss event (red)
⚠      Critical event (orange)
```

### Critical Path Highlighting

For performance analysis, the Gantt chart can highlight the critical path:

```
Timeline →

  ExecutionBlock[0]  [====================================] 300 cycles
    ThreadGrp 0      [█████████████] 150 cycles ← CRITICAL PATH (bold red)
      LD             [████] 50 cycles (bottleneck: cache miss)
    ThreadGrp 1      [========] 100 cycles
    ThreadGrp 2      [======] 80 cycles
```

The critical path shows the longest dependency chain determining total execution time.

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 2.0 | 2025-10-03 | Redesigned for streaming format using JSON Lines, added record_end, Gantt chart support |
| 1.0 | 2025-10-03 | Initial specification (array-based JSON, deprecated) |
