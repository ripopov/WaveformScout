//! Backend-agnostic trait definitions for Pyrox waveform viewer
//!
//! This module defines pure virtual interfaces that abstract over different
//! waveform backends (Wellen, JETS, VPD, etc.) without exposing backend-specific types.

use std::sync::Arc;

// === Type Aliases and Structs (Backend-Agnostic) ===

/// Time in timescale units (as defined by HierarchyTrait::timescale())
/// Backends convert their native time representation to these units.
/// For example, JETS converts clock cycles to picoseconds internally.
pub type Time = u64;

/// Time table index
pub type TimeTableIdx = u32;

/// Signal handle (0-based index)
pub type SignalHandle = usize;

/// Variable bit range index (backend-agnostic)
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct VarIndex {
    pub msb: i64,
    pub lsb: i64,
}

/// Annotation is a simple name/value tuple (kept lightweight for trace overlays)
pub type Annotation = (String, String);

/// Timed annotation couples a timestamp with its annotation payload
pub type TimedAnnotation = (Time, Annotation);

/// Domain error emitted by signal accessors before PyO3 conversion
#[derive(Debug)]
pub enum SignalError {
    OutOfRange(Time),
    UnsupportedFormat(&'static str),
    Backend(String),
}

impl std::fmt::Display for SignalError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            SignalError::OutOfRange(time) => write!(f, "time {} outside available range", time),
            SignalError::UnsupportedFormat(fmt) => {
                write!(f, "value format not supported by backend: {}", fmt)
            }
            SignalError::Backend(msg) => write!(f, "backend error: {}", msg),
        }
    }
}

impl std::error::Error for SignalError {}

/// Backend-agnostic signal value representation
#[derive(Debug, Clone, PartialEq)]
pub enum SignalValue {
    Scalar(SignalScalar),
    Vector(Vec<SignalScalar>),
    Real(f64),
    String(String),
    /// Integer value (stored as bytes in little-endian order with bit_width)
    Integer(Vec<u8>, u32),  // (bytes, bit_width)
    EnumVariant { name: String, index: u32 },
    Opaque(Vec<u8>),
    Unknown,
}

/// Individual scalar value used inside vectors/bitfields
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SignalScalar {
    Zero,
    One,
    X,
    Z,
}

/// Result returned by `query_signal` before PyO3 wrapping
#[derive(Debug, Clone)]
pub struct QueryResult {
    pub value: SignalValue,
    pub actual_time: Time,
    pub next_change: Option<Time>,
}

// === HierarchyTrait ===

/// Design hierarchy operations
pub trait HierarchyTrait: Send + Sync {
    /// Return all variables in the hierarchy
    fn all_vars(&self) -> Box<dyn Iterator<Item = Box<dyn VarTrait>> + Send + Sync>;

    /// Return top-level scopes
    fn top_scopes(&self) -> Box<dyn Iterator<Item = Box<dyn ScopeTrait>> + Send + Sync>;

    /// Find variable by hierarchical path (scope1, scope2, ..., var_name)
    fn find_var_by_path(&self, path: &[String]) -> Option<Box<dyn VarTrait>>;

    /// Get variable by signal handle (0-based index)
    fn get_var_by_signal_ref(&self, handle: SignalHandle) -> Option<Box<dyn VarTrait>>;

    /// Get file metadata
    fn date(&self) -> String;
    fn version(&self) -> String;

    /// Get timescale (factor and unit as strings, e.g., (1, "ps") for 1 picosecond)
    fn timescale(&self) -> Option<(u32, String)>;

    fn file_format(&self) -> String;

    /// Downcast to concrete type (needed for some internal operations)
    fn as_any(&self) -> &dyn std::any::Any;
}

// === ScopeTrait ===

/// Scope/module operations
pub trait ScopeTrait: Send + Sync {
    /// Scope name (local)
    fn name(&self, hier: &dyn HierarchyTrait) -> String;

    /// Scope full hierarchical name
    fn full_name(&self, hier: &dyn HierarchyTrait) -> String;

    /// Scope type string ("module", "task", "record", etc.)
    fn scope_type(&self) -> String;

    /// Variables in this scope
    fn vars(
        &self,
        hier: &dyn HierarchyTrait,
    ) -> Box<dyn Iterator<Item = Box<dyn VarTrait>> + Send + Sync>;

    /// Child scopes
    fn scopes(
        &self,
        hier: &dyn HierarchyTrait,
    ) -> Box<dyn Iterator<Item = Box<dyn ScopeTrait>> + Send + Sync>;

    /// Check if this scope represents a hierarchical record with events
    /// (used by trace-based backends like JETS, VPD, UVM logs, etc.)
    fn is_record(&self) -> bool;

    /// Get Record object for trace-based backends
    /// Returns None for waveform backends (Wellen)
    fn record(&self) -> Option<Box<dyn RecordTrait>>;
}

// === VarTrait ===

/// Variable/signal reference operations
pub trait VarTrait: Send + Sync {
    /// Variable name (local)
    fn name(&self, hier: &dyn HierarchyTrait) -> String;

    /// Variable full hierarchical name
    fn full_name(&self, hier: &dyn HierarchyTrait) -> String;

    /// Scope path (list of scope names from root to parent)
    fn scope_path(&self, hier: &dyn HierarchyTrait) -> Vec<String>;

    /// Signal handle for this variable (0-based)
    fn signal_handle(&self) -> SignalHandle;

    /// Type information
    fn bitwidth(&self) -> Option<u32>;
    fn var_type(&self) -> String;
    fn enum_type(&self, hier: &dyn HierarchyTrait) -> Option<(String, Vec<(String, String)>)>;
    fn vhdl_type_name(&self, hier: &dyn HierarchyTrait) -> Option<String>;
    fn direction(&self) -> String;
    fn length(&self) -> Option<u32>;
    fn is_real(&self) -> bool;
    fn is_string(&self) -> bool;
    fn is_bit_vector(&self) -> bool;
    fn is_1bit(&self) -> bool;
    fn index(&self) -> Option<VarIndex>;
}

// === SignalTrait ===

/// Signal waveform data. Backend implementations are self-contained and manage
/// their own time representation (indexed vs absolute timestamps).
pub trait SignalTrait: Send + Sync {
    /// Get signal value at a specific time
    fn value_at_time(&self, time: Time) -> Option<SignalValue>;

    /// Get signal value at time table index (converted to time internally if needed)
    fn value_at_idx(&self, idx: TimeTableIdx) -> Option<SignalValue>;

    /// Iterator over all signal changes (time, value) pairs in timescale units
    fn all_changes(&self) -> Box<dyn Iterator<Item = (Time, SignalValue)> + Send + Sync>;

    /// Iterator over changes after a specific time
    fn all_changes_after(
        &self,
        start_time: Time,
    ) -> Box<dyn Iterator<Item = (Time, SignalValue)> + Send + Sync>;

    /// Query signal at time (returns value, actual_time, next transition info)
    fn query_signal(&self, query_time: Time) -> Result<QueryResult, SignalError>;

    /// Compute global min/max range for analog signals
    fn get_global_range(&self, data_format: u8, bit_width: u32) -> Result<(f64, f64), SignalError>;

    /// Signal equality (same underlying signal)
    fn signal_eq(&self, other: &dyn SignalTrait) -> bool;

    /// Signal hash (for use in HashMap)
    fn signal_hash(&self) -> u64;

    /// Downcast to concrete type (needed for signal equality checks)
    fn as_any(&self) -> &dyn std::any::Any;
}

// === TimeTableTrait ===

/// Time table access operations
pub trait TimeTableTrait: Send + Sync {
    /// Get time at index (in timescale units)
    fn get(&self, idx: usize) -> Option<Time>;

    /// Length of time table
    fn len(&self) -> usize;

    /// Check if empty
    fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// Binary search for time (in timescale units)
    fn binary_search(&self, time: Time) -> Result<usize, usize>;

    /// Downcast to concrete type (needed for some internal operations)
    fn as_any(&self) -> &dyn std::any::Any;
}

// === RecordTrait ===

/// Represents hierarchical objects with properties and timed events.
/// Used by trace-based backends (JETS, VPD, UVM logs, etc.) to represent
/// execution records, transactions, or other time-bounded hierarchical events.
///
/// All time values are in the timescale units defined by HierarchyTrait::timescale().
/// Backends convert their native time representation (e.g., clock cycles) internally.
pub trait RecordTrait: Send + Sync {
    /// Record type classification (e.g., "HostProgram", "KernelExecution", "Transaction")
    fn record_type(&self) -> String;

    /// Record name (human-readable)
    fn name(&self) -> String;

    /// Start time in timescale units (from HierarchyTrait::timescale())
    fn start_time(&self) -> Time;

    /// End time in timescale units (None if ongoing or unbounded)
    fn end_time(&self) -> Option<Time>;

    /// Annotations attached to this record (name/value pairs)
    fn annotations(&self) -> Vec<Annotation>;

    /// Events occurring within this record's time range (timed annotations)
    fn events(&self) -> Vec<TimedAnnotation>;

    /// Downcast to concrete type (needed for conversions)
    fn as_any(&self) -> &dyn std::any::Any;
}

// === WaveSourceTrait ===

/// Backend-agnostic signal loading interface.
/// This trait abstracts the signal loading mechanism for different backends.
pub trait WaveSourceTrait: Send + Sync {
    /// Load signals for the given handles.
    /// Returns a vector of (handle, signal) pairs for successfully loaded signals.
    fn load_signals(
        &mut self,
        handles: &[SignalHandle],
        hier: &dyn HierarchyTrait,
    ) -> Vec<(SignalHandle, Arc<dyn SignalTrait>)>;
}

// === WaveformTrait ===

/// Backend-agnostic waveform file loading interface.
///
/// This trait abstracts the process of loading waveform files into their constituent parts:
/// hierarchy (design structure), time table (timestamp index), and signal source (waveform data).
///
/// Backends may implement different loading strategies:
/// - **Two-phase loading** (Wellen): `load_header()` reads hierarchy, `load_body()` reads signal data
/// - **Atomic loading** (JETS): `load_header()` loads everything, `load_body()` is a no-op
///
/// All methods are synchronous; async orchestration is handled by the PyO3 layer.
///
/// # Non-Blocking Constructor Requirement
///
/// Backend constructors (`new()`) **must not perform I/O** to ensure non-blocking construction
/// for GUI applications. All file parsing must be deferred to `load_header()` / `load_body()`.
pub trait WaveformTrait: Send + Sync {
    /// Get the hierarchy (returns None if header not loaded)
    fn hierarchy(&self) -> Option<Arc<dyn HierarchyTrait>>;

    /// Get the time table (returns None if body not loaded)
    fn time_table(&self) -> Option<Arc<dyn TimeTableTrait>>;

    /// Load file header/hierarchy synchronously.
    ///
    /// For backends with two-phase loading (Wellen), this reads the hierarchy and prepares
    /// for body loading. For backends with atomic loading (JETS), this may load everything.
    ///
    /// This method is idempotent: calling multiple times has no additional effect.
    ///
    /// Returns: Ok(()) on success, Err(msg) on failure
    fn load_header(&mut self) -> Result<(), String>;

    /// Check if header is loaded
    fn header_loaded(&self) -> bool;

    /// Load signal waveform data synchronously.
    ///
    /// For backends with two-phase loading (Wellen), this reads the signal data using
    /// a continuation from the header phase. For backends with atomic loading (JETS),
    /// this is a no-op (returns immediately).
    ///
    /// This method is idempotent: calling multiple times has no additional effect.
    ///
    /// Returns: Ok(()) on success, Err(msg) on failure
    fn load_body(&mut self) -> Result<(), String>;

    /// Check if body is loaded
    fn body_loaded(&self) -> bool;

    /// Get shared reference to wave source (for concurrent access).
    ///
    /// Returns an Arc<Mutex<...>> that can be cloned and held without
    /// blocking access to the backend. Backends that support concurrent
    /// signal loading should override this method.
    ///
    /// This enables fine-grained locking where the backend mutex can be
    /// released immediately after cloning the Arc, and only the wave_source
    /// mutex needs to be held during actual signal loading operations.
    fn wave_source_arc(&mut self) -> Option<Arc<std::sync::Mutex<dyn WaveSourceTrait>>> {
        None  // Default: not supported
    }
}
