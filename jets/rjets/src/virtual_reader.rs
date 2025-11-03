use std::collections::HashMap;
use rand::{Rng, SeedableRng};
use rand::rngs::StdRng;
use crate::traits::{TraceReader, TraceData, TraceMetadata, TraceRecord, TraceEvent, DynTraceData, AttributeAccessor};

const DEFAULT_MAX_DEPTH: usize = 5;
const DEFAULT_MAX_CHILDREN: usize = 10;

pub struct VirtualTraceReader {
    max_depth: usize,
    max_children: usize,
    seed: u64,
}

impl VirtualTraceReader {
    pub fn new() -> Self {
        Self {
            max_depth: DEFAULT_MAX_DEPTH,
            max_children: DEFAULT_MAX_CHILDREN,
            seed: 42, // Default seed for reproducibility
        }
    }

    pub fn with_config(max_depth: usize, max_children: usize, seed: u64) -> Self {
        Self {
            max_depth,
            max_children,
            seed,
        }
    }
}

impl TraceReader for VirtualTraceReader {
    fn read(&self, _file_path: &str) -> anyhow::Result<DynTraceData> {
        let mut rng = StdRng::seed_from_u64(self.seed);

        // Generate 1-5 root records
        let num_roots = rng.gen_range(1..=5);
        let mut roots = Vec::new();
        let mut next_id = 1;

        for _ in 0..num_roots {
            let record = VirtualTraceRecord::generate(&mut rng, next_id, None, 0, 0, self.max_depth, self.max_children, &mut next_id);
            roots.push(record);
            next_id += 1; // Increment for next root
        }

        Ok(DynTraceData::Virtual(VirtualTraceData::new(roots)))
    }
}

#[derive(Clone)]
pub struct VirtualTraceData {
    roots: Vec<VirtualTraceRecord>,
    records_by_id: HashMap<u64, VirtualTraceRecord>,
    trace_extent: (i64, i64),
}

impl VirtualTraceData {
    fn new(roots: Vec<VirtualTraceRecord>) -> Self {
        let mut records_by_id = HashMap::new();

        fn collect_records(record: &VirtualTraceRecord, map: &mut HashMap<u64, VirtualTraceRecord>) {
            map.insert(record.id, record.clone());
            for child in &record.children {
                collect_records(child, map);
            }
        }

        for root in &roots {
            collect_records(root, &mut records_by_id);
        }

        // Calculate trace extent
        let trace_extent = calculate_virtual_trace_extent(&records_by_id);

        Self {
            roots,
            records_by_id,
            trace_extent,
        }
    }
}

/// Computes the minimum and maximum clock values across all virtual records.
fn calculate_virtual_trace_extent(records: &HashMap<u64, VirtualTraceRecord>) -> (i64, i64) {
    if records.is_empty() {
        return (0, 1000);
    }

    let mut min_clk = i64::MAX;
    let mut max_clk = i64::MIN;

    for record in records.values() {
        min_clk = min_clk.min(record.clk);
        if let Some(end_clk) = record.end_clk {
            max_clk = max_clk.max(end_clk);
        } else {
            max_clk = max_clk.max(record.clk);
        }
    }

    if min_clk == i64::MAX {
        (0, 1000)
    } else {
        (min_clk, max_clk)
    }
}

// Wrapper types for GAT references
pub struct VirtualTraceDataRef<'a>(&'a VirtualTraceData);

impl<'a> TraceMetadata for VirtualTraceDataRef<'a> {
    fn version(&self) -> String {
        self.0.version()
    }

    fn header_data(&self) -> &serde_json::Value {
        self.0.header_data()
    }

    fn capture_end_clk(&self) -> Option<i64> {
        self.0.capture_end_clk()
    }

    fn total_records(&self) -> Option<usize> {
        self.0.total_records()
    }

    fn total_annotations(&self) -> Option<usize> {
        self.0.total_annotations()
    }

    fn total_events(&self) -> Option<usize> {
        self.0.total_events()
    }

    fn trace_extent(&self) -> (i64, i64) {
        self.0.trace_extent()
    }
}

#[derive(Clone, Copy)]
pub struct VirtualTraceRecordRef<'a>(&'a VirtualTraceRecord);

impl<'a> AttributeAccessor for VirtualTraceRecordRef<'a> {
    fn attr_count(&self) -> u64 {
        self.0.data.len() as u64
    }

    fn attr(&self, key: &str) -> Option<serde_json::Value> {
        self.0.data.get(key).cloned()
    }

    fn attr_at(&self, index: u64) -> Option<(String, serde_json::Value)> {
        self.0.data.iter()
            .nth(index as usize)
            .map(|(k, v)| (k.clone(), v.clone()))
    }

    fn attrs(&self) -> Vec<(String, serde_json::Value)> {
        self.0.data.iter()
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect()
    }
}

impl<'a> TraceRecord<'a> for VirtualTraceRecordRef<'a> {
    type Event<'b> = VirtualTraceEventRef<'b> where Self: 'b;

    fn clk(&self) -> i64 {
        self.0.clk()
    }

    fn end_clk(&self) -> Option<i64> {
        self.0.end_clk()
    }

    fn duration(&self) -> Option<i64> {
        self.0.duration()
    }

    fn name(&self) -> String {
        self.0.name()
    }

    fn id(&self) -> u64 {
        self.0.id()
    }

    fn parent_id(&self) -> Option<u64> {
        self.0.parent_id()
    }

    fn description(&self) -> String {
        self.0.description()
    }

    fn num_children(&self) -> usize {
        self.0.num_children()
    }

    fn child_at(&self, index: usize) -> Option<Self> {
        // Access children directly to preserve the 'a lifetime
        self.0.children.get(index).map(VirtualTraceRecordRef)
    }

    fn num_events(&self) -> usize {
        self.0.num_events()
    }

    fn event_at(&self, index: usize) -> Option<Self::Event<'_>> {
        self.0.event_at(index)
    }

    fn subtree_depth(&self) -> usize {
        self.0.subtree_depth()
    }
}

pub struct VirtualTraceEventRef<'a>(&'a VirtualTraceEvent);

impl<'a> AttributeAccessor for VirtualTraceEventRef<'a> {
    fn attr_count(&self) -> u64 {
        self.0.data.len() as u64
    }

    fn attr(&self, key: &str) -> Option<serde_json::Value> {
        self.0.data.get(key).cloned()
    }

    fn attr_at(&self, index: u64) -> Option<(String, serde_json::Value)> {
        self.0.data.iter()
            .nth(index as usize)
            .map(|(k, v)| (k.clone(), v.clone()))
    }

    fn attrs(&self) -> Vec<(String, serde_json::Value)> {
        self.0.data.iter()
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect()
    }
}

impl<'a> TraceEvent for VirtualTraceEventRef<'a> {
    fn clk(&self) -> i64 {
        self.0.clk()
    }

    fn name(&self) -> String {
        self.0.name()
    }

    fn record_id(&self) -> u64 {
        self.0.record_id()
    }

    fn description(&self) -> String {
        self.0.description()
    }
}

impl TraceData for VirtualTraceData {
    type Metadata<'a> = VirtualTraceDataRef<'a> where Self: 'a;
    type Record<'a> = VirtualTraceRecordRef<'a> where Self: 'a;

    fn metadata(&self) -> Self::Metadata<'_> {
        VirtualTraceDataRef(self)
    }

    fn root_ids(&self) -> Vec<u64> {
        self.roots.iter().map(|r| r.id).collect()
    }

    fn get_record(&self, id: u64) -> Option<Self::Record<'_>> {
        self.records_by_id.get(&id).map(VirtualTraceRecordRef)
    }
}

impl TraceMetadata for VirtualTraceData {
    fn version(&self) -> String {
        "virtual-1.0".to_string()
    }

    fn header_data(&self) -> &serde_json::Value {
        static HEADER_DATA: once_cell::sync::Lazy<serde_json::Value> = once_cell::sync::Lazy::new(|| {
            serde_json::json!({
                "generator": "VirtualTraceReader",
                "description": "Synthetic trace data for testing"
            })
        });
        &HEADER_DATA
    }

    fn capture_end_clk(&self) -> Option<i64> {
        Some(1000000)
    }

    fn total_records(&self) -> Option<usize> {
        None // Unknown for virtual data
    }

    fn total_annotations(&self) -> Option<usize> {
        None
    }

    fn total_events(&self) -> Option<usize> {
        None
    }

    fn trace_extent(&self) -> (i64, i64) {
        self.trace_extent
    }
}

#[derive(Clone)]
pub struct VirtualTraceRecord {
    id: u64,
    name: String,
    description: String,
    clk: i64,
    end_clk: Option<i64>,
    duration: Option<i64>,
    parent_id: Option<u64>,
    data: HashMap<String, serde_json::Value>,
    children: Vec<VirtualTraceRecord>,
    events: Vec<VirtualTraceEvent>,
}

impl VirtualTraceRecord {
    fn generate(
        rng: &mut StdRng,
        id: u64,
        parent_id: Option<u64>,
        parent_clk: i64,
        depth: usize,
        max_depth: usize,
        max_children: usize,
        next_id: &mut u64,
    ) -> Self {
        let clk = parent_clk + rng.gen_range(10..100);
        let end_clk = clk + rng.gen_range(50..500);
        let duration = end_clk - clk;

        let name = format!("Record_{}", id);
        let description = format!("Virtual record {}", id);

        // Generate 3-7 random data fields
        let mut data = HashMap::new();
        let num_fields = rng.gen_range(3..=7);
        for i in 0..num_fields {
            let key = format!("field_{}", i);
            let value = serde_json::json!(rng.gen_range(0..1000));
            data.insert(key, value);
        }

        // Generate 0-5 random events
        let mut events = Vec::new();
        let num_events = rng.gen_range(0..=5);
        for i in 0..num_events {
            let event_clk = clk + rng.gen_range(0..duration);
            events.push(VirtualTraceEvent::generate(rng, id, event_clk, i));
        }

        // Generate children if depth allows
        let mut children = Vec::new();
        if depth < max_depth {
            let num_children = rng.gen_range(0..=max_children.min(5));
            for _ in 0..num_children {
                *next_id += 1;
                let child = VirtualTraceRecord::generate(
                    rng,
                    *next_id,
                    Some(id),
                    end_clk,
                    depth + 1,
                    max_depth,
                    max_children,
                    next_id,
                );
                children.push(child);
            }
        }

        Self {
            id,
            name,
            description,
            clk,
            end_clk: Some(end_clk),
            duration: Some(duration),
            parent_id,
            data,
            children,
            events,
        }
    }
}

impl<'a> TraceRecord<'a> for &'a VirtualTraceRecord {
    type Event<'b> = VirtualTraceEventRef<'b> where Self: 'b;

    fn clk(&self) -> i64 {
        self.clk
    }

    fn end_clk(&self) -> Option<i64> {
        self.end_clk
    }

    fn duration(&self) -> Option<i64> {
        self.duration
    }

    fn name(&self) -> String {
        self.name.clone()
    }

    fn id(&self) -> u64 {
        self.id
    }

    fn parent_id(&self) -> Option<u64> {
        self.parent_id
    }

    fn description(&self) -> String {
        self.description.clone()
    }

    fn num_children(&self) -> usize {
        self.children.len()
    }

    fn child_at(&self, index: usize) -> Option<Self> {
        self.children.get(index)
    }

    fn num_events(&self) -> usize {
        self.events.len()
    }

    fn event_at(&self, index: usize) -> Option<Self::Event<'_>> {
        self.events.get(index).map(VirtualTraceEventRef)
    }

    fn subtree_depth(&self) -> usize {
        // Leaf node (no children)
        if self.children.is_empty() {
            return 0;
        }

        // Calculate max depth of children + 1
        let max_child_depth = self.children.iter()
            .map(|child| child.subtree_depth())
            .max()
            .unwrap_or(0);

        max_child_depth + 1
    }
}

#[derive(Clone)]
pub struct VirtualTraceEvent {
    clk: i64,
    name: String,
    record_id: u64,
    description: String,
    data: HashMap<String, serde_json::Value>,
}

impl VirtualTraceEvent {
    fn generate(rng: &mut StdRng, record_id: u64, clk: i64, index: usize) -> Self {
        let name = format!("Event_{}", index);
        let description = format!("Virtual event {} for record {}", index, record_id);

        let mut data = HashMap::new();
        let num_fields = rng.gen_range(1..=3);
        for i in 0..num_fields {
            let key = format!("event_field_{}", i);
            let value = serde_json::json!(rng.gen_range(0..100));
            data.insert(key, value);
        }

        Self {
            clk,
            name,
            record_id,
            description,
            data,
        }
    }
}

impl AttributeAccessor for &VirtualTraceRecord {
    fn attr_count(&self) -> u64 {
        self.data.len() as u64
    }

    fn attr(&self, key: &str) -> Option<serde_json::Value> {
        self.data.get(key).cloned()
    }

    fn attr_at(&self, index: u64) -> Option<(String, serde_json::Value)> {
        self.data.iter()
            .nth(index as usize)
            .map(|(k, v)| (k.clone(), v.clone()))
    }

    fn attrs(&self) -> Vec<(String, serde_json::Value)> {
        self.data.iter()
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect()
    }
}

impl AttributeAccessor for VirtualTraceEvent {
    fn attr_count(&self) -> u64 {
        self.data.len() as u64
    }

    fn attr(&self, key: &str) -> Option<serde_json::Value> {
        self.data.get(key).cloned()
    }

    fn attr_at(&self, index: u64) -> Option<(String, serde_json::Value)> {
        self.data.iter()
            .nth(index as usize)
            .map(|(k, v)| (k.clone(), v.clone()))
    }

    fn attrs(&self) -> Vec<(String, serde_json::Value)> {
        self.data.iter()
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect()
    }
}

impl TraceEvent for VirtualTraceEvent {
    fn clk(&self) -> i64 {
        self.clk
    }

    fn name(&self) -> String {
        self.name.clone()
    }

    fn record_id(&self) -> u64 {
        self.record_id
    }

    fn description(&self) -> String {
        self.description.clone()
    }
}
