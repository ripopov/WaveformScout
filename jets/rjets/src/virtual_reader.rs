use std::collections::HashMap;
use rand::{Rng, SeedableRng};
use rand::rngs::StdRng;
use crate::traits::{TraceReader, TraceData, TraceMetadata, TraceRecord, TraceEvent};

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
    fn read(&self, _file_path: &str) -> anyhow::Result<Box<dyn TraceData>> {
        let mut rng = StdRng::seed_from_u64(self.seed);

        // Generate 1-5 root records
        let num_roots = rng.gen_range(1..=5);
        let mut roots = Vec::new();
        let mut next_id = 1;

        for _ in 0..num_roots {
            let record = VirtualTraceRecord::generate(&mut rng, next_id, None, 0, 0, self.max_depth, self.max_children, &mut next_id);
            roots.push(record);
        }

        Ok(Box::new(VirtualTraceData::new(roots)))
    }
}

#[derive(Clone)]
pub struct VirtualTraceData {
    roots: Vec<VirtualTraceRecord>,
    records_by_id: HashMap<u64, VirtualTraceRecord>,
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

        Self {
            roots,
            records_by_id,
        }
    }
}

impl TraceData for VirtualTraceData {
    fn metadata(&self) -> &dyn TraceMetadata {
        &VirtualTraceMetadata
    }

    fn root_ids(&self) -> Vec<u64> {
        self.roots.iter().map(|r| r.id).collect()
    }

    fn get_record(&self, id: u64) -> Option<&dyn TraceRecord> {
        self.records_by_id.get(&id).map(|r| r as &dyn TraceRecord)
    }
}

pub struct VirtualTraceMetadata;

impl TraceMetadata for VirtualTraceMetadata {
    fn version(&self) -> &str {
        "virtual-1.0"
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

impl TraceRecord for VirtualTraceRecord {
    fn clk(&self) -> i64 {
        self.clk
    }

    fn end_clk(&self) -> Option<i64> {
        self.end_clk
    }

    fn duration(&self) -> Option<i64> {
        self.duration
    }

    fn name(&self) -> &str {
        &self.name
    }

    fn id(&self) -> u64 {
        self.id
    }

    fn parent_id(&self) -> Option<u64> {
        self.parent_id
    }

    fn description(&self) -> &str {
        &self.description
    }

    fn data(&self) -> HashMap<String, serde_json::Value> {
        self.data.clone()
    }

    fn children(&self) -> Vec<&dyn TraceRecord> {
        self.children.iter()
            .map(|c| c as &dyn TraceRecord)
            .collect()
    }

    fn events(&self) -> Vec<&dyn TraceEvent> {
        self.events.iter()
            .map(|e| e as &dyn TraceEvent)
            .collect()
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

impl TraceEvent for VirtualTraceEvent {
    fn clk(&self) -> i64 {
        self.clk
    }

    fn name(&self) -> &str {
        &self.name
    }

    fn record_id(&self) -> u64 {
        self.record_id
    }

    fn description(&self) -> &str {
        &self.description
    }

    fn data(&self) -> HashMap<String, serde_json::Value> {
        self.data.clone()
    }
}
