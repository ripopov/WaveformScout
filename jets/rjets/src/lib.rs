pub mod traits;
pub mod parser;
pub mod writer;
pub mod virtual_reader;
pub mod pipetrace_reader;
pub mod theme;
pub mod string_intern;

// Export traits
pub use traits::{
    TraceReader, TraceData, TraceMetadata,
    TraceRecord, TraceEvent, RecordId,
    DynTraceData, DynTraceMetadata, DynTraceRecord, DynTraceEvent,
    AttributeAccessor
};

// Export JETS implementation
pub use parser::{
    JetsTraceReader, JetsTraceData, JetsTraceMetadata,
    JetsTraceRecord, JetsTraceEvent, parse_trace
};

// Export virtual implementation
pub use virtual_reader::{
    VirtualTraceReader, VirtualTraceData,
    VirtualTraceRecord, VirtualTraceEvent
};

// Export pipetrace implementation
pub use pipetrace_reader::{
    PipetraceReader, PipetraceData, PipetraceMetadataRef,
    PipetraceRecordRef, PipetraceEventRef
};

// Export writer (unchanged)
pub use writer::TraceWriter;

// Export theme support
pub use theme::{Theme, ThemeColors, ThemeManager, hex_to_color32, adjust_brightness, with_alpha};

// Export string interning utility
pub use string_intern::StringInterner;
