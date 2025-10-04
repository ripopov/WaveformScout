pub mod parser;
pub mod writer;

pub use parser::{
    TraceData, TraceRecord, TraceAnnotation, TraceEvent,
    TraceHeader, TraceFooter, parse_trace
};

pub use writer::TraceWriter;
