use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs::File;
use std::io::{BufRead, BufReader};
use anyhow::{Result, Context, anyhow};
use crate::traits::{TraceReader, TraceData, TraceMetadata, TraceRecord, TraceEvent};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JetsTraceHeader {
    pub version: String,
    pub metadata: serde_json::Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JetsTraceFooter {
    pub capture_end_clk: Option<i64>,
    pub total_records: Option<usize>,
    pub total_annotations: Option<usize>,
    pub total_events: Option<usize>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JetsTraceAnnotation {
    #[serde(rename = "type")]
    pub line_type: String,
    pub name: String,
    pub record_id: u64,
    pub description: String,
    pub data: serde_json::Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JetsTraceEvent {
    pub clk: i64,
    #[serde(rename = "type")]
    pub line_type: String,
    pub name: String,
    pub record_id: u64,
    pub description: String,
    #[serde(default)]
    pub data: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JetsTraceRecord {
    pub clk: i64,
    pub name: String,
    pub record_type: String,
    pub id: u64,
    pub parent_id: Option<u64>,
    pub description: String,
    #[serde(default)]
    pub data: Option<serde_json::Value>,

    // These are added during parsing
    #[serde(skip)]
    pub end_clk: Option<i64>,
    #[serde(skip)]
    pub duration: Option<i64>,
    #[serde(skip)]
    pub children: Vec<JetsTraceRecord>,
    #[serde(skip)]
    pub annotations: Vec<JetsTraceAnnotation>,
    #[serde(skip)]
    pub events: Vec<JetsTraceEvent>,
}

#[derive(Debug, Clone)]
pub struct JetsTraceMetadata {
    pub header: JetsTraceHeader,
    pub footer: Option<JetsTraceFooter>,
    pub trace_extent: (i64, i64), // (min_clk, max_clk)
}

#[derive(Debug, Clone)]
pub struct JetsTraceData {
    pub metadata: JetsTraceMetadata,
    pub roots: Vec<JetsTraceRecord>,
    pub records_by_id: HashMap<u64, usize>, // Maps ID to index in flattened record list
    pub all_records: Vec<JetsTraceRecord>,  // Flattened list of all records for lookup
}

pub struct JetsTraceReader;

impl JetsTraceReader {
    pub fn new() -> Self {
        JetsTraceReader
    }
}

#[derive(Debug, Deserialize)]
#[serde(tag = "type")]
enum TraceLine {
    #[serde(rename = "header")]
    Header {
        version: String,
        metadata: serde_json::Value,
    },
    #[serde(rename = "record")]
    Record {
        clk: i64,
        name: String,
        record_type: String,
        id: u64,
        parent_id: Option<u64>,
        description: String,
        #[serde(default)]
        data: Option<serde_json::Value>,
    },
    #[serde(rename = "record_end")]
    RecordEnd {
        clk: i64,
        record_id: u64,
    },
    #[serde(rename = "annotation")]
    Annotation {
        name: String,
        record_id: u64,
        description: String,
        data: serde_json::Value,
    },
    #[serde(rename = "event")]
    Event {
        clk: i64,
        name: String,
        record_id: u64,
        description: String,
        #[serde(default)]
        data: Option<serde_json::Value>,
    },
    #[serde(rename = "footer")]
    Footer {
        capture_end_clk: Option<i64>,
        total_records: Option<usize>,
        total_annotations: Option<usize>,
        total_events: Option<usize>,
    },
}

pub fn parse_trace(file_path: &str) -> Result<JetsTraceData> {
    let file = File::open(file_path)
        .with_context(|| format!("Failed to open file: {}", file_path))?;
    let reader = BufReader::new(file);

    let mut header: Option<JetsTraceHeader> = None;
    let mut footer: Option<JetsTraceFooter> = None;
    let mut records_by_id: HashMap<u64, JetsTraceRecord> = HashMap::new();

    for (line_num, line_result) in reader.lines().enumerate() {
        let line = line_result
            .with_context(|| format!("Failed to read line {}", line_num + 1))?;

        if line.trim().is_empty() {
            continue;
        }

        let trace_line: TraceLine = serde_json::from_str(&line)
            .with_context(|| format!("Failed to parse JSON at line {}", line_num + 1))?;

        match trace_line {
            TraceLine::Header { version, metadata } => {
                if line_num != 0 {
                    return Err(anyhow!("Header must be first line (found at line {})", line_num + 1));
                }
                header = Some(JetsTraceHeader { version, metadata });
            }

            TraceLine::Record { clk, name, record_type, id, parent_id, description, data } => {
                if records_by_id.contains_key(&id) {
                    return Err(anyhow!("Duplicate record ID '{}' at line {}", id, line_num + 1));
                }

                let record = JetsTraceRecord {
                    clk,
                    name,
                    record_type,
                    id: id.clone(),
                    parent_id,
                    description,
                    data,
                    end_clk: None,
                    duration: None,
                    children: Vec::new(),
                    annotations: Vec::new(),
                    events: Vec::new(),
                };

                records_by_id.insert(id, record);
            }

            TraceLine::RecordEnd { clk, record_id } => {
                let record = records_by_id.get_mut(&record_id)
                    .ok_or_else(|| anyhow!("record_end references unknown record '{}' at line {}", record_id, line_num + 1))?;

                record.end_clk = Some(clk);
                record.duration = Some(clk - record.clk);
            }

            TraceLine::Annotation { name, record_id, description, data } => {
                let record = records_by_id.get_mut(&record_id)
                    .ok_or_else(|| anyhow!("annotation references unknown record '{}' at line {}", record_id, line_num + 1))?;

                record.annotations.push(JetsTraceAnnotation {
                    line_type: "annotation".to_string(),
                    name,
                    record_id,
                    description,
                    data,
                });
            }

            TraceLine::Event { clk, name, record_id, description, data } => {
                let record = records_by_id.get_mut(&record_id)
                    .ok_or_else(|| anyhow!("event references unknown record '{}' at line {}", record_id, line_num + 1))?;

                record.events.push(JetsTraceEvent {
                    clk,
                    line_type: "event".to_string(),
                    name,
                    record_id,
                    description,
                    data,
                });
            }

            TraceLine::Footer { capture_end_clk, total_records, total_annotations, total_events } => {
                footer = Some(JetsTraceFooter {
                    capture_end_clk,
                    total_records,
                    total_annotations,
                    total_events,
                });
            }
        }
    }

    let header = header.ok_or_else(|| anyhow!("Missing header line"))?;

    // Build tree structure
    let mut roots = Vec::new();
    let mut all_records: Vec<JetsTraceRecord> = records_by_id.into_values().collect();

    // Separate roots from children
    let mut children_map: HashMap<u64, Vec<JetsTraceRecord>> = HashMap::new();

    for record in all_records.drain(..) {
        if let Some(parent_id) = record.parent_id {
            children_map.entry(parent_id)
                .or_insert_with(Vec::new)
                .push(record);
        } else {
            roots.push(record);
        }
    }

    // Recursively attach children
    fn attach_children(record: &mut JetsTraceRecord, children_map: &mut HashMap<u64, Vec<JetsTraceRecord>>) {
        if let Some(mut children) = children_map.remove(&record.id) {
            for child in &mut children {
                attach_children(child, children_map);
            }
            // Sort children by clk first, then by name
            children.sort_by(|a, b| {
                a.clk.cmp(&b.clk).then_with(|| a.name.cmp(&b.name))
            });
            record.children = children;
        }
    }

    for root in &mut roots {
        attach_children(root, &mut children_map);
    }

    // Sort roots by clk first, then by name
    roots.sort_by(|a, b| {
        a.clk.cmp(&b.clk).then_with(|| a.name.cmp(&b.name))
    });

    // Flatten all records for lookup
    let mut all_records_flat = Vec::new();
    let mut id_to_index = HashMap::new();

    fn flatten_records(record: &JetsTraceRecord, all_records: &mut Vec<JetsTraceRecord>, id_map: &mut HashMap<u64, usize>) {
        let index = all_records.len();
        id_map.insert(record.id, index);
        all_records.push(record.clone());

        for child in &record.children {
            flatten_records(child, all_records, id_map);
        }
    }

    for root in &roots {
        flatten_records(root, &mut all_records_flat, &mut id_to_index);
    }

    // Calculate trace extent (min_clk, max_clk)
    let trace_extent = calculate_trace_extent(&all_records_flat);

    Ok(JetsTraceData {
        metadata: JetsTraceMetadata { header, footer, trace_extent },
        roots,
        records_by_id: id_to_index,
        all_records: all_records_flat,
    })
}

/// Computes the minimum and maximum clock values across all records in the trace.
fn calculate_trace_extent(all_records: &[JetsTraceRecord]) -> (i64, i64) {
    if all_records.is_empty() {
        return (0, 1000);
    }

    let mut min_clk = i64::MAX;
    let mut max_clk = i64::MIN;

    for record in all_records {
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

// Trait implementations

impl TraceReader for JetsTraceReader {
    fn read(&self, file_path: &str) -> anyhow::Result<Box<dyn TraceData>> {
        let data = parse_trace(file_path)?;
        Ok(Box::new(data))
    }
}

impl TraceMetadata for JetsTraceMetadata {
    fn version(&self) -> &str {
        &self.header.version
    }

    fn header_data(&self) -> &serde_json::Value {
        &self.header.metadata
    }

    fn capture_end_clk(&self) -> Option<i64> {
        self.footer.as_ref().and_then(|f| f.capture_end_clk)
    }

    fn total_records(&self) -> Option<usize> {
        self.footer.as_ref().and_then(|f| f.total_records)
    }

    fn total_annotations(&self) -> Option<usize> {
        self.footer.as_ref().and_then(|f| f.total_annotations)
    }

    fn total_events(&self) -> Option<usize> {
        self.footer.as_ref().and_then(|f| f.total_events)
    }

    fn trace_extent(&self) -> (i64, i64) {
        self.trace_extent
    }
}

impl TraceData for JetsTraceData {
    fn metadata(&self) -> &dyn TraceMetadata {
        &self.metadata
    }

    fn root_ids(&self) -> Vec<u64> {
        self.roots.iter().map(|r| r.id).collect()
    }

    fn get_record(&self, id: u64) -> Option<&dyn TraceRecord> {
        self.records_by_id.get(&id)
            .and_then(|&index| self.all_records.get(index))
            .map(|r| r as &dyn TraceRecord)
    }
}

impl TraceRecord for JetsTraceRecord {
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
        let mut result = HashMap::new();

        // Add original data fields
        if let Some(data) = &self.data {
            if let serde_json::Value::Object(map) = data {
                for (key, value) in map {
                    result.insert(key.clone(), value.clone());
                }
            } else {
                result.insert("data".to_string(), data.clone());
            }
        }

        // Merge annotations into the data dictionary
        for annotation in &self.annotations {
            result.insert(annotation.name.clone(), annotation.data.clone());
        }

        result
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

impl TraceEvent for JetsTraceEvent {
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
        let mut result = HashMap::new();

        if let Some(data) = &self.data {
            if let serde_json::Value::Object(map) = data {
                for (key, value) in map {
                    result.insert(key.clone(), value.clone());
                }
            } else {
                result.insert("data".to_string(), data.clone());
            }
        }

        result
    }
}
