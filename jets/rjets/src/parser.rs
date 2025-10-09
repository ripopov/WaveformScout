use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs::File;
use std::io::{BufRead, BufReader};
use anyhow::{Result, Context, anyhow};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TraceHeader {
    pub version: String,
    pub metadata: serde_json::Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TraceFooter {
    pub capture_end_clk: Option<i64>,
    pub total_records: Option<usize>,
    pub total_annotations: Option<usize>,
    pub total_events: Option<usize>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TraceAnnotation {
    #[serde(rename = "type")]
    pub line_type: String,
    pub name: String,
    pub record_id: u64,
    pub description: String,
    pub data: serde_json::Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TraceEvent {
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
pub struct TraceRecord {
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
    pub children: Vec<TraceRecord>,
    #[serde(skip)]
    pub annotations: Vec<TraceAnnotation>,
    #[serde(skip)]
    pub events: Vec<TraceEvent>,
}

#[derive(Debug, Clone)]
pub struct TraceData {
    pub header: TraceHeader,
    pub roots: Vec<TraceRecord>,
    pub footer: Option<TraceFooter>,
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

pub fn parse_trace(file_path: &str) -> Result<TraceData> {
    let file = File::open(file_path)
        .with_context(|| format!("Failed to open file: {}", file_path))?;
    let reader = BufReader::new(file);

    let mut header: Option<TraceHeader> = None;
    let mut footer: Option<TraceFooter> = None;
    let mut records_by_id: HashMap<u64, TraceRecord> = HashMap::new();

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
                header = Some(TraceHeader { version, metadata });
            }

            TraceLine::Record { clk, name, record_type, id, parent_id, description, data } => {
                if records_by_id.contains_key(&id) {
                    return Err(anyhow!("Duplicate record ID '{}' at line {}", id, line_num + 1));
                }

                let record = TraceRecord {
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

                record.annotations.push(TraceAnnotation {
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

                record.events.push(TraceEvent {
                    clk,
                    line_type: "event".to_string(),
                    name,
                    record_id,
                    description,
                    data,
                });
            }

            TraceLine::Footer { capture_end_clk, total_records, total_annotations, total_events } => {
                footer = Some(TraceFooter {
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
    let mut all_records: Vec<TraceRecord> = records_by_id.into_values().collect();

    // Separate roots from children
    let mut children_map: HashMap<u64, Vec<TraceRecord>> = HashMap::new();

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
    fn attach_children(record: &mut TraceRecord, children_map: &mut HashMap<u64, Vec<TraceRecord>>) {
        if let Some(mut children) = children_map.remove(&record.id) {
            for child in &mut children {
                attach_children(child, children_map);
            }
            record.children = children;
        }
    }

    for root in &mut roots {
        attach_children(root, &mut children_map);
    }

    Ok(TraceData {
        header,
        roots,
        footer,
    })
}
