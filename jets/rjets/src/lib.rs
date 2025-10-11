pub mod traits;
pub mod parser;
pub mod writer;
pub mod virtual_reader;

// Export traits
pub use traits::{
    TraceReader, TraceData, TraceMetadata,
    TraceRecord, TraceEvent
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

// Export writer (unchanged)
pub use writer::TraceWriter;
