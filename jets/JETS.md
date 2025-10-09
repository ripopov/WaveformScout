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
  "clk": 1000,
  "type": "record",
  "name": "ProcessTask",
  "record_type": "HostProgram",
  "id": 1,
  "parent_id": null,
  "description": "Main process task for user application",
  "data": {
    "process_id": 12345,
    "thread_id": 67890
  }
}
```

#### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `clk` | integer | Yes | Hardware clock cycle when this record/operation **begins** |
| `type` | string | Yes | Must be `"record"` |
| `name` | string | Yes | Short human-readable name (used in tree viewers and UI labels) |
| `record_type` | string | Yes | Semantic type (e.g., "Pipeline", "Instruction", "ExecutionUnit") |
| `id` | unsigned integer | Yes | Globally unique identifier for this record (u64) |
| `parent_id` | unsigned integer/null | Yes | ID of parent record; `null` for root nodes |
| `description` | string | Yes | Human-readable description providing additional context |
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
  "clk": 1500,
  "type": "record_end",
  "record_id": 1
}
```

#### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `clk` | integer | Yes | Hardware clock cycle when this record/operation **completes** |
| `type` | string | Yes | Must be `"record_end"` |
| `record_id` | unsigned integer | Yes | ID of the record that is ending (must reference existing record) |

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
  "name": "GridDimensions",
  "record_id": 5,
  "description": "Execution grid dimensions for this dispatch",
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
| `name` | string | Yes | Short annotation name (used in tree viewers and UI labels) |
| `record_id` | unsigned integer | Yes | ID of the record this annotation describes |
| `description` | string | Yes | Human-readable description of the annotation's purpose |
| `data` | any | Yes | Arbitrary JSON value (object, array, primitive) |

**Streaming Constraint**: The referenced record must appear in the file **before** this annotation.

---

### 5. Event Line

**Events** represent timed operations or state changes.

#### Schema

```json
{
  "clk": 1151,
  "type": "event",
  "name": "DecodeStage",
  "record_id": 42,
  "description": "Instruction decode pipeline stage",
  "data": {
    "stage": "frontend"
  }
}
```

#### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `clk` | integer | Yes | Hardware clock cycle when this event occurs |
| `type` | string | Yes | Must be `"event"` |
| `name` | string | Yes | Short event name (used in tree viewers and UI labels) |
| `record_id` | unsigned integer | Yes | ID of the record this event is associated with |
| `description` | string | Yes | Human-readable description of the event |
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