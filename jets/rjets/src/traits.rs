use std::collections::HashMap;

/// Type alias for record IDs (domain identifiers from trace files)
pub type RecordId = u64;

// Forward declarations for enum types (defined at end of file)
pub enum DynTraceData {
    Jets(crate::parser::JetsTraceData),
    Virtual(crate::virtual_reader::VirtualTraceData),
    Pipetrace(crate::pipetrace_reader::PipetraceData),
}

pub enum DynTraceMetadata<'a> {
    Jets(crate::parser::JetsTraceMetadataRef<'a>),
    Virtual(crate::virtual_reader::VirtualTraceDataRef<'a>),
    Pipetrace(crate::pipetrace_reader::PipetraceMetadataRef<'a>),
}

#[derive(Clone)]
pub enum DynTraceRecord<'a> {
    Jets(crate::parser::JetsTraceRecordRef<'a>),
    Virtual(crate::virtual_reader::VirtualTraceRecordRef<'a>),
    Pipetrace(crate::pipetrace_reader::PipetraceRecordRef<'a>),
}

pub enum DynTraceEvent<'a> {
    Jets(crate::parser::JetsTraceEventRef<'a>),
    Virtual(crate::virtual_reader::VirtualTraceEventRef<'a>),
    Pipetrace(crate::pipetrace_reader::PipetraceEventRef<'a>),
}

/// Trait for reading trace files and returning TraceData
pub trait TraceReader {
    /// Opens and parses a trace file, returning a DynTraceData enum
    fn read(&self, file_path: &str) -> anyhow::Result<DynTraceData>;
}

/// Trait for accessing trace data
/// TraceData must be Send to support async loading in background threads
pub trait TraceData: Send {
    type Metadata<'a>: TraceMetadata where Self: 'a;
    type Record<'a>: TraceRecord<'a> where Self: 'a;

    /// Returns metadata (information from headers and footers)
    fn metadata(&self) -> Self::Metadata<'_>;

    /// Returns the IDs of root records
    fn root_ids(&self) -> Vec<RecordId>;

    /// Gets a record by ID
    fn get_record(&self, id: RecordId) -> Option<Self::Record<'_>>;
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
///
/// The lifetime parameter 'data represents the lifetime of the underlying TraceData storage.
/// All records from the same TraceData share this lifetime, allowing children to have
/// the same lifetime as their parents.
pub trait TraceRecord<'data>: Clone {
    type Event<'a>: TraceEvent where Self: 'a;

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

    /// Returns the number of children
    fn num_children(&self) -> usize;

    /// Returns the child at the given index
    ///
    /// The returned child has the same lifetime as the parent (both tied to TraceData).
    fn child_at(&self, index: usize) -> Option<Self>;

    /// Returns the number of events
    fn num_events(&self) -> usize;

    /// Returns the event at the given index
    fn event_at(&self, index: usize) -> Option<Self::Event<'_>>;

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

// ============================================================================
// Enum Dispatch Implementations
// ============================================================================

impl DynTraceData {
    /// Helper method to get metadata as a borrowed reference (for compatibility)
    pub fn metadata(&self) -> DynTraceMetadata<'_> {
        <Self as TraceData>::metadata(self)
    }
}

impl TraceData for DynTraceData {
    type Metadata<'a> = DynTraceMetadata<'a> where Self: 'a;
    type Record<'a> = DynTraceRecord<'a> where Self: 'a;

    #[inline]
    fn metadata(&self) -> Self::Metadata<'_> {
        match self {
            DynTraceData::Jets(d) => DynTraceMetadata::Jets(d.metadata()),
            DynTraceData::Virtual(d) => DynTraceMetadata::Virtual(d.metadata()),
            DynTraceData::Pipetrace(d) => DynTraceMetadata::Pipetrace(d.metadata()),
        }
    }

    #[inline]
    fn root_ids(&self) -> Vec<RecordId> {
        match self {
            DynTraceData::Jets(d) => d.root_ids(),
            DynTraceData::Virtual(d) => d.root_ids(),
            DynTraceData::Pipetrace(d) => d.root_ids(),
        }
    }

    #[inline]
    fn get_record(&self, id: RecordId) -> Option<Self::Record<'_>> {
        match self {
            DynTraceData::Jets(d) => d.get_record(id).map(DynTraceRecord::Jets),
            DynTraceData::Virtual(d) => d.get_record(id).map(DynTraceRecord::Virtual),
            DynTraceData::Pipetrace(d) => d.get_record(id).map(DynTraceRecord::Pipetrace),
        }
    }
}

impl<'a> TraceMetadata for DynTraceMetadata<'a> {
    #[inline]
    fn version(&self) -> &str {
        match self {
            DynTraceMetadata::Jets(m) => m.version(),
            DynTraceMetadata::Virtual(m) => m.version(),
            DynTraceMetadata::Pipetrace(m) => m.version(),
        }
    }

    #[inline]
    fn header_data(&self) -> &serde_json::Value {
        match self {
            DynTraceMetadata::Jets(m) => m.header_data(),
            DynTraceMetadata::Virtual(m) => m.header_data(),
            DynTraceMetadata::Pipetrace(m) => m.header_data(),
        }
    }

    #[inline]
    fn capture_end_clk(&self) -> Option<i64> {
        match self {
            DynTraceMetadata::Jets(m) => m.capture_end_clk(),
            DynTraceMetadata::Virtual(m) => m.capture_end_clk(),
            DynTraceMetadata::Pipetrace(m) => m.capture_end_clk(),
        }
    }

    #[inline]
    fn total_records(&self) -> Option<usize> {
        match self {
            DynTraceMetadata::Jets(m) => m.total_records(),
            DynTraceMetadata::Virtual(m) => m.total_records(),
            DynTraceMetadata::Pipetrace(m) => m.total_records(),
        }
    }

    #[inline]
    fn total_annotations(&self) -> Option<usize> {
        match self {
            DynTraceMetadata::Jets(m) => m.total_annotations(),
            DynTraceMetadata::Virtual(m) => m.total_annotations(),
            DynTraceMetadata::Pipetrace(m) => m.total_annotations(),
        }
    }

    #[inline]
    fn total_events(&self) -> Option<usize> {
        match self {
            DynTraceMetadata::Jets(m) => m.total_events(),
            DynTraceMetadata::Virtual(m) => m.total_events(),
            DynTraceMetadata::Pipetrace(m) => m.total_events(),
        }
    }

    #[inline]
    fn trace_extent(&self) -> (i64, i64) {
        match self {
            DynTraceMetadata::Jets(m) => m.trace_extent(),
            DynTraceMetadata::Virtual(m) => m.trace_extent(),
            DynTraceMetadata::Pipetrace(m) => m.trace_extent(),
        }
    }
}

impl<'a> DynTraceRecord<'a> {
    /// Helper method to iterate over children (for compatibility during migration)
    pub fn children(&self) -> impl Iterator<Item = DynTraceRecord<'_>> + '_ {
        (0..self.num_children()).filter_map(|i| self.child_at(i))
    }
}

impl<'a> TraceRecord<'a> for DynTraceRecord<'a> {
    type Event<'b> = DynTraceEvent<'b> where Self: 'b;

    #[inline]
    fn clk(&self) -> i64 {
        match self {
            DynTraceRecord::Jets(r) => r.clk(),
            DynTraceRecord::Virtual(r) => r.clk(),
            DynTraceRecord::Pipetrace(r) => r.clk(),
        }
    }

    #[inline]
    fn end_clk(&self) -> Option<i64> {
        match self {
            DynTraceRecord::Jets(r) => r.end_clk(),
            DynTraceRecord::Virtual(r) => r.end_clk(),
            DynTraceRecord::Pipetrace(r) => r.end_clk(),
        }
    }

    #[inline]
    fn duration(&self) -> Option<i64> {
        match self {
            DynTraceRecord::Jets(r) => r.duration(),
            DynTraceRecord::Virtual(r) => r.duration(),
            DynTraceRecord::Pipetrace(r) => r.duration(),
        }
    }

    #[inline]
    fn name(&self) -> &str {
        match self {
            DynTraceRecord::Jets(r) => r.name(),
            DynTraceRecord::Virtual(r) => r.name(),
            DynTraceRecord::Pipetrace(r) => r.name(),
        }
    }

    #[inline]
    fn id(&self) -> RecordId {
        match self {
            DynTraceRecord::Jets(r) => r.id(),
            DynTraceRecord::Virtual(r) => r.id(),
            DynTraceRecord::Pipetrace(r) => r.id(),
        }
    }

    #[inline]
    fn parent_id(&self) -> Option<RecordId> {
        match self {
            DynTraceRecord::Jets(r) => r.parent_id(),
            DynTraceRecord::Virtual(r) => r.parent_id(),
            DynTraceRecord::Pipetrace(r) => r.parent_id(),
        }
    }

    #[inline]
    fn description(&self) -> &str {
        match self {
            DynTraceRecord::Jets(r) => r.description(),
            DynTraceRecord::Virtual(r) => r.description(),
            DynTraceRecord::Pipetrace(r) => r.description(),
        }
    }

    #[inline]
    fn data(&self) -> HashMap<String, serde_json::Value> {
        match self {
            DynTraceRecord::Jets(r) => r.data(),
            DynTraceRecord::Virtual(r) => r.data(),
            DynTraceRecord::Pipetrace(r) => r.data(),
        }
    }

    #[inline]
    fn num_children(&self) -> usize {
        match self {
            DynTraceRecord::Jets(r) => r.num_children(),
            DynTraceRecord::Virtual(r) => r.num_children(),
            DynTraceRecord::Pipetrace(r) => r.num_children(),
        }
    }

    #[inline]
    fn child_at(&self, index: usize) -> Option<Self> {
        match self {
            DynTraceRecord::Jets(r) => r.child_at(index).map(DynTraceRecord::Jets),
            DynTraceRecord::Virtual(r) => r.child_at(index).map(DynTraceRecord::Virtual),
            DynTraceRecord::Pipetrace(r) => r.child_at(index).map(DynTraceRecord::Pipetrace),
        }
    }

    #[inline]
    fn num_events(&self) -> usize {
        match self {
            DynTraceRecord::Jets(r) => r.num_events(),
            DynTraceRecord::Virtual(r) => r.num_events(),
            DynTraceRecord::Pipetrace(r) => r.num_events(),
        }
    }

    #[inline]
    fn event_at(&self, index: usize) -> Option<Self::Event<'_>> {
        match self {
            DynTraceRecord::Jets(r) => r.event_at(index).map(DynTraceEvent::Jets),
            DynTraceRecord::Virtual(r) => r.event_at(index).map(DynTraceEvent::Virtual),
            DynTraceRecord::Pipetrace(r) => r.event_at(index).map(DynTraceEvent::Pipetrace),
        }
    }

    #[inline]
    fn subtree_depth(&self) -> usize {
        match self {
            DynTraceRecord::Jets(r) => r.subtree_depth(),
            DynTraceRecord::Virtual(r) => r.subtree_depth(),
            DynTraceRecord::Pipetrace(r) => r.subtree_depth(),
        }
    }
}

impl<'a> TraceEvent for DynTraceEvent<'a> {
    #[inline]
    fn clk(&self) -> i64 {
        match self {
            DynTraceEvent::Jets(e) => e.clk(),
            DynTraceEvent::Virtual(e) => e.clk(),
            DynTraceEvent::Pipetrace(e) => e.clk(),
        }
    }

    #[inline]
    fn name(&self) -> &str {
        match self {
            DynTraceEvent::Jets(e) => e.name(),
            DynTraceEvent::Virtual(e) => e.name(),
            DynTraceEvent::Pipetrace(e) => e.name(),
        }
    }

    #[inline]
    fn record_id(&self) -> RecordId {
        match self {
            DynTraceEvent::Jets(e) => e.record_id(),
            DynTraceEvent::Virtual(e) => e.record_id(),
            DynTraceEvent::Pipetrace(e) => e.record_id(),
        }
    }

    #[inline]
    fn description(&self) -> &str {
        match self {
            DynTraceEvent::Jets(e) => e.description(),
            DynTraceEvent::Virtual(e) => e.description(),
            DynTraceEvent::Pipetrace(e) => e.description(),
        }
    }

    #[inline]
    fn data(&self) -> HashMap<String, serde_json::Value> {
        match self {
            DynTraceEvent::Jets(e) => e.data(),
            DynTraceEvent::Virtual(e) => e.data(),
            DynTraceEvent::Pipetrace(e) => e.data(),
        }
    }
}
