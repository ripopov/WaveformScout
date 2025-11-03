use crate::traits::{TraceReader, TraceData, TraceMetadata, TraceRecord, TraceEvent, DynTraceData, AttributeAccessor};

/// stub implementation for now.

pub struct PipetraceReader;

impl PipetraceReader {
    pub fn new() -> Self { PipetraceReader }
}

impl TraceReader for PipetraceReader {
    fn read(&self, _file_path: &str) -> anyhow::Result<DynTraceData> {
        // Return an empty PipetraceData stub
        Ok(DynTraceData::Pipetrace(PipetraceData::default()))
    }
}

// Wrapper types for GAT references
pub struct PipetraceMetadataRef<'a>(&'a PipetraceMetadata);

impl<'a> TraceMetadata for PipetraceMetadataRef<'a> {
    fn version(&self) -> String { self.0.version() }
    fn header_data(&self) -> &serde_json::Value { self.0.header_data() }
    fn capture_end_clk(&self) -> Option<i64> { self.0.capture_end_clk() }
    fn total_records(&self) -> Option<usize> { self.0.total_records() }
    fn total_annotations(&self) -> Option<usize> { self.0.total_annotations() }
    fn total_events(&self) -> Option<usize> { self.0.total_events() }
    fn trace_extent(&self) -> (i64, i64) { self.0.trace_extent() }
}

#[derive(Clone, Copy)]
pub struct PipetraceRecordRef<'a>(&'a PipetraceRecord);

impl<'a> AttributeAccessor for PipetraceRecordRef<'a> {
    fn attr_count(&self) -> u64 {
        self.0.attr_count()
    }

    fn attr(&self, key: &str) -> Option<serde_json::Value> {
        self.0.attr(key)
    }

    fn attr_at(&self, index: u64) -> Option<(String, serde_json::Value)> {
        self.0.attr_at(index)
    }

    fn attrs(&self) -> Vec<(String, serde_json::Value)> {
        self.0.attrs()
    }
}

impl<'a> TraceRecord<'a> for PipetraceRecordRef<'a> {
    type Event<'b> = PipetraceEventRef<'b> where Self: 'b;

    fn clk(&self) -> i64 { self.0.clk() }
    fn end_clk(&self) -> Option<i64> { self.0.end_clk() }
    fn duration(&self) -> Option<i64> { self.0.duration() }
    fn name(&self) -> String { self.0.name() }
    fn id(&self) -> u64 { self.0.id() }
    fn parent_id(&self) -> Option<u64> { self.0.parent_id() }
    fn description(&self) -> String { self.0.description() }
    fn num_children(&self) -> usize { self.0.num_children() }
    fn child_at(&self, index: usize) -> Option<Self> {
        self.0.child_at(index).map(PipetraceRecordRef)
    }
    fn num_events(&self) -> usize { self.0.num_events() }
    fn event_at(&self, index: usize) -> Option<Self::Event<'_>> {
        self.0.event_at(index)
    }
    fn subtree_depth(&self) -> usize { self.0.subtree_depth() }
}

pub struct PipetraceEventRef<'a>(&'a PipetraceEvent);

impl<'a> AttributeAccessor for PipetraceEventRef<'a> {
    fn attr_count(&self) -> u64 {
        self.0.attr_count()
    }

    fn attr(&self, key: &str) -> Option<serde_json::Value> {
        self.0.attr(key)
    }

    fn attr_at(&self, index: u64) -> Option<(String, serde_json::Value)> {
        self.0.attr_at(index)
    }

    fn attrs(&self) -> Vec<(String, serde_json::Value)> {
        self.0.attrs()
    }
}

impl<'a> TraceEvent for PipetraceEventRef<'a> {
    fn clk(&self) -> i64 { self.0.clk() }
    fn name(&self) -> String { self.0.name() }
    fn record_id(&self) -> u64 { self.0.record_id() }
    fn description(&self) -> String { self.0.description() }
}

#[derive(Clone, Default)]
pub struct PipetraceData;

impl TraceData for PipetraceData {
    type Metadata<'a> = PipetraceMetadataRef<'a> where Self: 'a;
    type Record<'a> = PipetraceRecordRef<'a> where Self: 'a;

    fn metadata(&self) -> Self::Metadata<'_> {
        // Return reference to a static empty metadata
        PipetraceMetadataRef(&EMPTY_PIPETRACE_METADATA)
    }

    fn root_ids(&self) -> Vec<u64> { Vec::new() }

    fn get_record(&self, _id: u64) -> Option<Self::Record<'_>> { None }
}

#[derive(Clone)]
pub struct PipetraceMetadata;

impl Default for PipetraceMetadata { fn default() -> Self { PipetraceMetadata } }

static EMPTY_JSON: once_cell::sync::Lazy<serde_json::Value> = once_cell::sync::Lazy::new(|| serde_json::json!({}));
static EMPTY_PIPETRACE_METADATA: PipetraceMetadata = PipetraceMetadata;

impl TraceMetadata for PipetraceMetadata {
    fn version(&self) -> String { "pipetrace-stub".to_string() }
    fn header_data(&self) -> &serde_json::Value { &EMPTY_JSON }
    fn capture_end_clk(&self) -> Option<i64> { None }
    fn total_records(&self) -> Option<usize> { None }
    fn total_annotations(&self) -> Option<usize> { None }
    fn total_events(&self) -> Option<usize> { None }
    fn trace_extent(&self) -> (i64, i64) { (0, 0) }
}

#[derive(Clone)]
pub struct PipetraceRecord;

impl AttributeAccessor for &PipetraceRecord {
    fn attr_count(&self) -> u64 {
        0
    }

    fn attr(&self, _key: &str) -> Option<serde_json::Value> {
        None
    }

    fn attr_at(&self, _index: u64) -> Option<(String, serde_json::Value)> {
        None
    }

    fn attrs(&self) -> Vec<(String, serde_json::Value)> {
        Vec::new()
    }
}

impl<'a> TraceRecord<'a> for &'a PipetraceRecord {
    type Event<'b> = PipetraceEventRef<'b> where Self: 'b;

    fn clk(&self) -> i64 { 0 }
    fn end_clk(&self) -> Option<i64> { None }
    fn duration(&self) -> Option<i64> { None }
    fn name(&self) -> String { "".to_string() }
    fn id(&self) -> u64 { 0 }
    fn parent_id(&self) -> Option<u64> { None }
    fn description(&self) -> String { "".to_string() }
    fn num_children(&self) -> usize { 0 }
    fn child_at(&self, _index: usize) -> Option<Self> { None }
    fn num_events(&self) -> usize { 0 }
    fn event_at(&self, _index: usize) -> Option<Self::Event<'_>> { None }
    fn subtree_depth(&self) -> usize { 0 }
}

#[derive(Clone)]
pub struct PipetraceEvent;

impl AttributeAccessor for PipetraceEvent {
    fn attr_count(&self) -> u64 {
        0
    }

    fn attr(&self, _key: &str) -> Option<serde_json::Value> {
        None
    }

    fn attr_at(&self, _index: u64) -> Option<(String, serde_json::Value)> {
        None
    }

    fn attrs(&self) -> Vec<(String, serde_json::Value)> {
        Vec::new()
    }
}

impl TraceEvent for PipetraceEvent {
    fn clk(&self) -> i64 { 0 }
    fn name(&self) -> String { "".to_string() }
    fn record_id(&self) -> u64 { 0 }
    fn description(&self) -> String { "".to_string() }
}

