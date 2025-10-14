use std::collections::HashMap;
use crate::traits::{TraceReader, TraceData, TraceMetadata, TraceRecord, TraceEvent};

/// stub implementation for now.

pub struct PipetraceReader;

impl PipetraceReader {
    pub fn new() -> Self { PipetraceReader }
}

impl TraceReader for PipetraceReader {
    fn read(&self, _file_path: &str) -> anyhow::Result<Box<dyn TraceData>> {
        // Return an empty PipetraceData stub
        Ok(Box::new(PipetraceData::default()))
    }
}

#[derive(Clone, Default)]
pub struct PipetraceData;

impl TraceData for PipetraceData {
    fn metadata(&self) -> &dyn TraceMetadata {
        // Return reference to a static empty metadata
        &EMPTY_PIPETRACE_METADATA
    }

    fn root_ids(&self) -> Vec<u64> { Vec::new() }

    fn get_record(&self, _id: u64) -> Option<&dyn TraceRecord> { None }
}

#[derive(Clone)]
pub struct PipetraceMetadata;

impl Default for PipetraceMetadata { fn default() -> Self { PipetraceMetadata } }

static EMPTY_JSON: once_cell::sync::Lazy<serde_json::Value> = once_cell::sync::Lazy::new(|| serde_json::json!({}));
static EMPTY_PIPETRACE_METADATA: PipetraceMetadata = PipetraceMetadata;

impl TraceMetadata for PipetraceMetadata {
    fn version(&self) -> &str { "pipetrace-stub" }
    fn header_data(&self) -> &serde_json::Value { &EMPTY_JSON }
    fn capture_end_clk(&self) -> Option<i64> { None }
    fn total_records(&self) -> Option<usize> { None }
    fn total_annotations(&self) -> Option<usize> { None }
    fn total_events(&self) -> Option<usize> { None }
    fn trace_extent(&self) -> (i64, i64) { (0, 0) }
}

#[derive(Clone)]
pub struct PipetraceRecord;

impl TraceRecord for PipetraceRecord {
    fn clk(&self) -> i64 { 0 }
    fn end_clk(&self) -> Option<i64> { None }
    fn duration(&self) -> Option<i64> { None }
    fn name(&self) -> &str { "" }
    fn id(&self) -> u64 { 0 }
    fn parent_id(&self) -> Option<u64> { None }
    fn description(&self) -> &str { "" }
    fn data(&self) -> HashMap<String, serde_json::Value> { HashMap::new() }
    fn children(&self) -> Vec<&dyn TraceRecord> { Vec::new() }
    fn events(&self) -> Vec<&dyn TraceEvent> { Vec::new() }
}

#[derive(Clone)]
pub struct PipetraceEvent;

impl TraceEvent for PipetraceEvent {
    fn clk(&self) -> i64 { 0 }
    fn name(&self) -> &str { "" }
    fn record_id(&self) -> u64 { 0 }
    fn description(&self) -> &str { "" }
    fn data(&self) -> HashMap<String, serde_json::Value> { HashMap::new() }
}

