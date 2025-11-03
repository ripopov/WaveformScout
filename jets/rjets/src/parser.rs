use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::sync::Arc;
use once_cell::sync::OnceCell;
use anyhow::{Result, Context, anyhow};
use brotli::Decompressor;
use crate::traits::{TraceReader, TraceData, TraceMetadata, TraceRecord, TraceEvent, RecordId, DynTraceData, AttributeAccessor};
use crate::string_intern::StringInterner;

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
    #[serde(serialize_with = "serialize_arc_str", deserialize_with = "deserialize_arc_str")]
    pub line_type: Arc<str>,
    #[serde(serialize_with = "serialize_arc_str", deserialize_with = "deserialize_arc_str")]
    pub name: Arc<str>,
    pub record_id: RecordId,
    #[serde(serialize_with = "serialize_arc_str", deserialize_with = "deserialize_arc_str")]
    pub description: Arc<str>,
    pub data: serde_json::Value,
}

// Serde helper functions for Arc<str>
fn serialize_arc_str<S>(arc: &Arc<str>, serializer: S) -> Result<S::Ok, S::Error>
where
    S: serde::Serializer,
{
    serializer.serialize_str(arc)
}

fn deserialize_arc_str<'de, D>(deserializer: D) -> Result<Arc<str>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let s = String::deserialize(deserializer)?;
    Ok(Arc::from(s))
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JetsTraceEvent {
    pub clk: i64,
    #[serde(rename = "type")]
    #[serde(serialize_with = "serialize_arc_str", deserialize_with = "deserialize_arc_str")]
    pub line_type: Arc<str>,
    #[serde(serialize_with = "serialize_arc_str", deserialize_with = "deserialize_arc_str")]
    pub name: Arc<str>,
    pub record_id: RecordId,
    #[serde(serialize_with = "serialize_arc_str", deserialize_with = "deserialize_arc_str")]
    pub description: Arc<str>,
    #[serde(default)]
    pub data: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JetsTraceRecord {
    pub clk: i64,
    #[serde(serialize_with = "serialize_arc_str", deserialize_with = "deserialize_arc_str")]
    pub name: Arc<str>,
    #[serde(serialize_with = "serialize_arc_str", deserialize_with = "deserialize_arc_str")]
    pub record_type: Arc<str>,
    pub id: RecordId,
    pub parent_id: Option<RecordId>,
    #[serde(serialize_with = "serialize_arc_str", deserialize_with = "deserialize_arc_str")]
    pub description: Arc<str>,
    #[serde(default)]
    pub data: Option<serde_json::Value>,

    // These are added during parsing
    #[serde(skip)]
    pub end_clk: Option<i64>,
    #[serde(skip)]
    pub duration: Option<i64>,
    #[serde(skip)]
    pub child_indices: Vec<usize>,  // Indices into the arena, not owned children
    #[serde(skip)]
    pub annotations: Vec<JetsTraceAnnotation>,
    #[serde(skip)]
    pub events: Vec<JetsTraceEvent>,

    // Shared reference to the arena for resolving child indices
    // Uses OnceCell for lazy initialization to enable self-referential structure
    #[serde(skip)]
    arena: OnceCell<Arc<Vec<JetsTraceRecord>>>,
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
    pub root_indices: Vec<usize>,                  // Indices of root records in all_records
    pub records_by_id: HashMap<RecordId, usize>,   // Maps record ID to vector index in arena
    pub all_records: Arc<Vec<JetsTraceRecord>>,    // Arena: flat list of all records
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
        id: RecordId,
        parent_id: Option<RecordId>,
        description: String,
        #[serde(default)]
        data: Option<serde_json::Value>,
    },
    #[serde(rename = "record_end")]
    RecordEnd {
        clk: i64,
        record_id: RecordId,
    },
    #[serde(rename = "annotation")]
    Annotation {
        name: String,
        record_id: RecordId,
        description: String,
        data: serde_json::Value,
    },
    #[serde(rename = "event")]
    Event {
        clk: i64,
        name: String,
        record_id: RecordId,
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

/// Parses a JETS trace file from disk.
///
/// Automatically detects and decompresses Brotli-compressed traces
/// based on file extension (`.br`).
///
/// # Supported Formats
///
/// - `.jets` — Uncompressed JSON Lines
/// - `.jsonl` — Uncompressed JSON Lines
/// - `.jets.br` — Brotli-compressed JETS
/// - `.jsonl.br` — Brotli-compressed JSON Lines
///
/// # Examples
///
/// ```no_run
/// # use rjets::parse_trace;
/// # fn main() -> anyhow::Result<()> {
/// // Parse uncompressed trace
/// let trace = parse_trace("trace.jets")?;
///
/// // Parse compressed trace (automatic decompression)
/// let trace = parse_trace("trace.jets.br")?;
/// # Ok(())
/// # }
/// ```
pub fn parse_trace(file_path: &str) -> Result<JetsTraceData> {
    let file = File::open(file_path)
        .with_context(|| format!("Failed to open file: {}", file_path))?;

    let reader: Box<dyn BufRead> = if file_path.ends_with(".br") {
        // Brotli decompression enabled
        let decompressor = Decompressor::new(file, 4096);
        Box::new(BufReader::new(decompressor))
    } else {
        // No decompression
        Box::new(BufReader::new(file))
    };

    // Create string interner to deduplicate repeated strings
    let mut interner = StringInterner::with_capacity(8192);

    // Pre-intern common literal strings
    let annotation_type = interner.intern("annotation");
    let event_type = interner.intern("event");

    let mut header: Option<JetsTraceHeader> = None;
    let mut footer: Option<JetsTraceFooter> = None;
    let mut records_by_id: HashMap<RecordId, JetsTraceRecord> = HashMap::new();

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
                    name: interner.intern(&name),
                    record_type: interner.intern(&record_type),
                    id: id.clone(),
                    parent_id,
                    description: interner.intern(&description),
                    data,
                    end_clk: None,
                    duration: None,
                    child_indices: Vec::new(),
                    annotations: Vec::new(),
                    events: Vec::new(),
                    arena: OnceCell::new(),
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
                    line_type: Arc::clone(&annotation_type),
                    name: interner.intern(&name),
                    record_id,
                    description: interner.intern(&description),
                    data,
                });
            }

            TraceLine::Event { clk, name, record_id, description, data } => {
                let record = records_by_id.get_mut(&record_id)
                    .ok_or_else(|| anyhow!("event references unknown record '{}' at line {}", record_id, line_num + 1))?;

                record.events.push(JetsTraceEvent {
                    clk,
                    line_type: Arc::clone(&event_type),
                    name: interner.intern(&name),
                    record_id,
                    description: interner.intern(&description),
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

    // Build flat arena with all records
    let mut all_records: Vec<JetsTraceRecord> = records_by_id.into_values().collect();

    // Sort records to ensure consistent ordering (parents before children when possible)
    all_records.sort_by(|a, b| {
        a.clk.cmp(&b.clk).then_with(|| a.name.cmp(&b.name))
    });

    // Build index mapping: record ID -> vector index in arena
    let mut id_to_index: HashMap<RecordId, usize> = HashMap::new();
    for (index, record) in all_records.iter().enumerate() {
        id_to_index.insert(record.id, index);
    }

    // Build parent-child relationships using indices
    let mut children_by_parent: HashMap<usize, Vec<usize>> = HashMap::new();
    let mut root_indices = Vec::new();

    for (index, record) in all_records.iter().enumerate() {
        if let Some(parent_id) = record.parent_id {
            if let Some(&parent_index) = id_to_index.get(&parent_id) {
                children_by_parent.entry(parent_index)
                    .or_insert_with(Vec::new)
                    .push(index);
            }
        } else {
            root_indices.push(index);
        }
    }

    // Sort children indices by clock time and name
    for children in children_by_parent.values_mut() {
        children.sort_by(|&a, &b| {
            let rec_a = &all_records[a];
            let rec_b = &all_records[b];
            rec_a.clk.cmp(&rec_b.clk).then_with(|| rec_a.name.cmp(&rec_b.name))
        });
    }

    // Assign child_indices to each record
    for (parent_index, child_indices) in children_by_parent {
        all_records[parent_index].child_indices = child_indices;
    }

    // Wrap in Arc - arena references will be set lazily on first access
    let arena = Arc::new(all_records);

    // Calculate trace extent (min_clk, max_clk)
    let trace_extent = calculate_trace_extent(&arena);

    Ok(JetsTraceData {
        metadata: JetsTraceMetadata { header, footer, trace_extent },
        root_indices,
        records_by_id: id_to_index,
        all_records: arena,
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

// Wrapper types for GAT references

#[derive(Clone, Copy)]
pub struct JetsTraceMetadataRef<'a>(&'a JetsTraceMetadata);

impl<'a> TraceMetadata for JetsTraceMetadataRef<'a> {
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
pub struct JetsTraceRecordRef<'a>(&'a JetsTraceRecord);

impl<'a> JetsTraceRecordRef<'a> {
    /// Helper method to iterate over children (for compatibility)
    pub fn children(self) -> impl Iterator<Item = JetsTraceRecordRef<'a>> + 'a {
        (0..self.num_children()).filter_map(move |i| self.child_at(i))
    }
}

impl<'a> AttributeAccessor for JetsTraceRecordRef<'a> {
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

impl<'a> TraceRecord<'a> for JetsTraceRecordRef<'a> {
    type Event<'b> = JetsTraceEventRef<'b> where Self: 'b;

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

    fn id(&self) -> RecordId {
        self.0.id()
    }

    fn parent_id(&self) -> Option<RecordId> {
        self.0.parent_id()
    }

    fn description(&self) -> String {
        self.0.description()
    }

    fn num_children(&self) -> usize {
        self.0.num_children()
    }

    fn child_at(&self, index: usize) -> Option<Self> {
        // Access the child directly from the arena to preserve the 'a lifetime
        let arena = self.0.arena.get()?;
        let &child_idx = self.0.child_indices.get(index)?;
        let child = arena.get(child_idx)?;
        // Lazily initialize arena for children too
        let _ = child.arena.get_or_init(|| Arc::clone(arena));
        Some(JetsTraceRecordRef(child))
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

#[derive(Clone, Copy)]
pub struct JetsTraceEventRef<'a>(&'a JetsTraceEvent);

impl<'a> AttributeAccessor for JetsTraceEventRef<'a> {
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

impl<'a> TraceEvent for JetsTraceEventRef<'a> {
    fn clk(&self) -> i64 {
        self.0.clk()
    }

    fn name(&self) -> String {
        self.0.name()
    }

    fn record_id(&self) -> RecordId {
        self.0.record_id()
    }

    fn description(&self) -> String {
        self.0.description()
    }
}

// Trait implementations

impl TraceReader for JetsTraceReader {
    fn read(&self, file_path: &str) -> anyhow::Result<DynTraceData> {
        let data = parse_trace(file_path)?;
        Ok(DynTraceData::Jets(data))
    }
}

impl TraceMetadata for JetsTraceMetadata {
    fn version(&self) -> String {
        self.header.version.clone()
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
    type Metadata<'a> = JetsTraceMetadataRef<'a> where Self: 'a;
    type Record<'a> = JetsTraceRecordRef<'a> where Self: 'a;

    fn metadata(&self) -> Self::Metadata<'_> {
        JetsTraceMetadataRef(&self.metadata)
    }

    fn root_ids(&self) -> Vec<u64> {
        self.root_indices.iter()
            .filter_map(|&idx| self.all_records.get(idx))
            .map(|r| r.id)
            .collect()
    }

    fn get_record(&self, id: u64) -> Option<Self::Record<'_>> {
        self.records_by_id.get(&id)
            .and_then(|&index| self.all_records.get(index))
            .map(|record| {
                // Lazily initialize arena reference on first access
                let _ = record.arena.get_or_init(|| Arc::clone(&self.all_records));
                JetsTraceRecordRef(record)
            })
    }
}

impl<'a> TraceRecord<'a> for &'a JetsTraceRecord {
    type Event<'b> = JetsTraceEventRef<'b> where Self: 'b;

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
        self.name.to_string()
    }

    fn id(&self) -> RecordId {
        self.id
    }

    fn parent_id(&self) -> Option<RecordId> {
        self.parent_id
    }

    fn description(&self) -> String {
        self.description.to_string()
    }

    fn num_children(&self) -> usize {
        self.child_indices.len()
    }

    fn child_at(&self, index: usize) -> Option<Self> {
        let arena = self.arena.get()?;
        let &child_idx = self.child_indices.get(index)?;
        let child = arena.get(child_idx)?;
        // Lazily initialize arena for children too, enabling transitive resolution
        let _ = child.arena.get_or_init(|| Arc::clone(arena));
        Some(child)
    }

    fn num_events(&self) -> usize {
        self.events.len()
    }

    fn event_at(&self, index: usize) -> Option<Self::Event<'_>> {
        self.events.get(index).map(JetsTraceEventRef)
    }

    fn subtree_depth(&self) -> usize {
        // Leaf node (no children)
        if self.child_indices.is_empty() {
            return 0;
        }

        // Get arena reference
        let arena = match self.arena.get() {
            Some(a) => a,
            None => return 1, // Conservative: assume depth 1 if arena not initialized
        };

        // Calculate max depth of children + 1
        let max_child_depth = self.child_indices.iter()
            .filter_map(|&idx| arena.get(idx))
            .map(|child| {
                // Ensure child has arena reference
                let _ = child.arena.get_or_init(|| Arc::clone(arena));
                child.subtree_depth()
            })
            .max()
            .unwrap_or(0);

        max_child_depth + 1
    }
}

impl AttributeAccessor for &JetsTraceRecord {
    fn attr_count(&self) -> u64 {
        let mut count = 0u64;
        
        // Count original data fields
        if let Some(serde_json::Value::Object(map)) = &self.data {
            count += map.len() as u64;
        } else if self.data.is_some() {
            count += 1;
        }
        
        // Count annotations (merged into attributes)
        count += self.annotations.len() as u64;
        
        count
    }

    fn attr(&self, key: &str) -> Option<serde_json::Value> {
        // First check annotations (they take precedence in merged view)
        for annotation in &self.annotations {
            if annotation.name.as_ref() == key {
                return Some(annotation.data.clone());
            }
        }
        
        // Then check original data
        if let Some(data) = &self.data {
            if let serde_json::Value::Object(map) = data {
                return map.get(key).cloned();
            } else if key == "data" {
                return Some(data.clone());
            }
        }
        
        None
    }

    fn attr_at(&self, index: u64) -> Option<(String, serde_json::Value)> {
        let mut current_index = 0u64;
        
        // First iterate over original data fields
        if let Some(data) = &self.data {
            if let serde_json::Value::Object(map) = data {
                for (key, value) in map {
                    if current_index == index {
                        return Some((key.clone(), value.clone()));
                    }
                    current_index += 1;
                }
            } else {
                if current_index == index {
                    return Some(("data".to_string(), data.clone()));
                }
                current_index += 1;
            }
        }
        
        // Then iterate over annotations
        let annotation_index = (index - current_index) as usize;
        self.annotations.get(annotation_index).map(|ann| {
            (ann.name.to_string(), ann.data.clone())
        })
    }

    fn attrs(&self) -> Vec<(String, serde_json::Value)> {
        let mut result = Vec::new();
        
        // Add original data fields
        if let Some(data) = &self.data {
            if let serde_json::Value::Object(map) = data {
                for (key, value) in map {
                    result.push((key.clone(), value.clone()));
                }
            } else {
                result.push(("data".to_string(), data.clone()));
            }
        }
        
        // Add annotations (merged into attributes)
        for annotation in &self.annotations {
            result.push((annotation.name.to_string(), annotation.data.clone()));
        }
        
        result
    }
}

impl AttributeAccessor for JetsTraceEvent {
    fn attr_count(&self) -> u64 {
        if let Some(serde_json::Value::Object(map)) = &self.data {
            map.len() as u64
        } else if self.data.is_some() {
            1
        } else {
            0
        }
    }

    fn attr(&self, key: &str) -> Option<serde_json::Value> {
        if let Some(data) = &self.data {
            if let serde_json::Value::Object(map) = data {
                return map.get(key).cloned();
            } else if key == "data" {
                return Some(data.clone());
            }
        }
        None
    }

    fn attr_at(&self, index: u64) -> Option<(String, serde_json::Value)> {
        if let Some(data) = &self.data {
            if let serde_json::Value::Object(map) = data {
                return map.iter()
                    .nth(index as usize)
                    .map(|(k, v)| (k.clone(), v.clone()));
            } else if index == 0 {
                return Some(("data".to_string(), data.clone()));
            }
        }
        None
    }

    fn attrs(&self) -> Vec<(String, serde_json::Value)> {
        let mut result = Vec::new();
        
        if let Some(data) = &self.data {
            if let serde_json::Value::Object(map) = data {
                for (key, value) in map {
                    result.push((key.clone(), value.clone()));
                }
            } else {
                result.push(("data".to_string(), data.clone()));
            }
        }
        
        result
    }
}

impl TraceEvent for JetsTraceEvent {
    fn clk(&self) -> i64 {
        self.clk
    }

    fn name(&self) -> String {
        self.name.to_string()
    }

    fn record_id(&self) -> RecordId {
        self.record_id
    }

    fn description(&self) -> String {
        self.description.to_string()
    }
}
