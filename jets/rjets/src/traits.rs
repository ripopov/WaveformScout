use std::collections::HashMap;

/// Type alias for record IDs (domain identifiers from trace files)
pub type RecordId = u64;

/// Trait for reading trace files and returning TraceData
pub trait TraceReader {
    /// Opens and parses a trace file, returning a TraceData implementation
    fn read(&self, file_path: &str) -> anyhow::Result<Box<dyn TraceData>>;
}

/// Trait for accessing trace data
/// TraceData must be Send to support async loading in background threads
pub trait TraceData: Send {
    /// Returns metadata (information from headers and footers)
    fn metadata(&self) -> &dyn TraceMetadata;

    /// Returns the IDs of root records
    fn root_ids(&self) -> Vec<RecordId>;

    /// Gets a record by ID
    fn get_record(&self, id: RecordId) -> Option<&dyn TraceRecord>;
}

/// Trait for accessing trace metadata
pub trait TraceMetadata {
    /// Returns the trace version
    fn version(&self) -> &str;

    /// Returns the header data (metadata from the header)
    fn header_data(&self) -> &serde_json::Value;

    /// Returns the capture end clock (from footer)
    fn capture_end_clk(&self) -> Option<i64>;

    /// Returns the total number of records (from footer)
    fn total_records(&self) -> Option<usize>;

    /// Returns the total number of annotations (from footer)
    fn total_annotations(&self) -> Option<usize>;

    /// Returns the total number of events (from footer)
    fn total_events(&self) -> Option<usize>;

    /// Returns the trace extent as (min_clk, max_clk) computed during parsing
    fn trace_extent(&self) -> (i64, i64);
}

/// Trait for accessing trace record
pub trait TraceRecord {
    /// Returns the start timestamp (clock value)
    fn clk(&self) -> i64;

    /// Returns the end timestamp (if available)
    fn end_clk(&self) -> Option<i64>;

    /// Returns the computed duration (end_clk - clk)
    fn duration(&self) -> Option<i64>;

    /// Returns the record name
    fn name(&self) -> &str;

    /// Returns the record ID
    fn id(&self) -> RecordId;

    /// Returns the parent ID (if this is a child record)
    fn parent_id(&self) -> Option<RecordId>;

    /// Returns the record description
    fn description(&self) -> &str;

    /// Returns all record data as a key-value map (includes merged annotations)
    fn data(&self) -> HashMap<String, serde_json::Value>;

    /// Returns the children of this record as trait objects
    fn children(&self) -> Vec<&dyn TraceRecord>;

    /// Returns the events associated with this record as trait objects
    fn events(&self) -> Vec<&dyn TraceEvent>;

    /// Returns the depth of the subtree rooted at this record.
    ///
    /// - Returns 0 for leaf records (no children)
    /// - Returns 1 for records with only leaf children
    /// - Returns max(child.subtree_depth()) + 1 for deeper trees
    ///
    /// This method is used by the viewport filter to determine if a record
    /// is a leaf (and should be filtered by clock) or a parent (always shown).
    fn subtree_depth(&self) -> usize;
}

/// Trait for accessing trace event
pub trait TraceEvent {
    /// Returns the event timestamp (clock value)
    fn clk(&self) -> i64;

    /// Returns the event name
    fn name(&self) -> &str;

    /// Returns the ID of the record this event belongs to
    fn record_id(&self) -> RecordId;

    /// Returns the event description
    fn description(&self) -> &str;

    /// Returns all event data as a key-value map
    fn data(&self) -> HashMap<String, serde_json::Value>;
}
