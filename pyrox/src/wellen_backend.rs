//! Wellen backend implementation for VCD, FST, and GHW waveform files

use crate::convert::Mappable;
use crate::traits::*;
use std::fs::File;
use std::io::BufReader;
use std::sync::Arc;
use wellen;

/// Wellen hierarchy implementation
#[derive(Clone)]
pub struct WellenHierarchy {
    pub(crate) inner: Arc<wellen::Hierarchy>,
}

impl WellenHierarchy {
    pub fn new(hierarchy: Arc<wellen::Hierarchy>) -> Self {
        Self { inner: hierarchy }
    }

    pub fn inner(&self) -> &Arc<wellen::Hierarchy> {
        &self.inner
    }
}

impl HierarchyTrait for WellenHierarchy {
    fn as_any(&self) -> &dyn std::any::Any {
        self
    }

    fn all_vars(&self) -> Box<dyn Iterator<Item = Box<dyn VarTrait>> + Send + Sync> {
        fn collect_vars(
            hier: &wellen::Hierarchy,
            scope_ref: wellen::ScopeRef,
            vars: &mut Vec<Box<dyn VarTrait>>,
        ) {
            for var_ref in hier[scope_ref].vars(hier) {
                vars.push(Box::new(WellenVar {
                    inner: hier[var_ref].clone(),
                }) as Box<dyn VarTrait>);
            }
            for child_scope_ref in hier[scope_ref].scopes(hier) {
                collect_vars(hier, child_scope_ref, vars);
            }
        }

        let mut vars = Vec::new();
        for scope_ref in self.inner.scopes() {
            collect_vars(&self.inner, scope_ref, &mut vars);
        }
        Box::new(vars.into_iter())
    }

    fn top_scopes(&self) -> Box<dyn Iterator<Item = Box<dyn ScopeTrait>> + Send + Sync> {
        let scopes: Vec<Box<dyn ScopeTrait>> = self
            .inner
            .scopes()
            .map(|scope_ref| {
                Box::new(WellenScope {
                    inner: self.inner[scope_ref].clone(),
                }) as Box<dyn ScopeTrait>
            })
            .collect();
        Box::new(scopes.into_iter())
    }

    fn find_var_by_path(&self, path: &[String]) -> Option<Box<dyn VarTrait>> {
        if path.is_empty() {
            return None;
        }

        let scope_path = &path[..path.len() - 1];
        let var_name = &path[path.len() - 1];

        let var_ref = self.inner.lookup_var(scope_path, var_name)?;

        Some(Box::new(WellenVar {
            inner: self.inner[var_ref].clone(),
        }))
    }

    fn get_var_by_signal_ref(&self, handle: SignalHandle) -> Option<Box<dyn VarTrait>> {
        let wellen_ref = wellen::SignalRef::from_index(handle)?;
        let var_ref = self.inner.get_var_by_signal_ref(wellen_ref)?;

        Some(Box::new(WellenVar {
            inner: self.inner[var_ref].clone(),
        }))
    }

    fn date(&self) -> String {
        self.inner.date().to_string()
    }

    fn version(&self) -> String {
        self.inner.version().to_string()
    }

    fn timescale(&self) -> Option<(u32, String)> {
        self.inner.timescale().map(|ts| {
            let factor = ts.factor;
            let unit = match ts.unit {
                wellen::TimescaleUnit::FemtoSeconds => "fs",
                wellen::TimescaleUnit::PicoSeconds => "ps",
                wellen::TimescaleUnit::NanoSeconds => "ns",
                wellen::TimescaleUnit::MicroSeconds => "us",
                wellen::TimescaleUnit::MilliSeconds => "ms",
                wellen::TimescaleUnit::Seconds => "s",
                wellen::TimescaleUnit::ZeptoSeconds => "zs",
                wellen::TimescaleUnit::AttoSeconds => "as",
                wellen::TimescaleUnit::Unknown => "unknown",
            };
            (factor, unit.to_string())
        })
    }

    fn file_format(&self) -> String {
        match self.inner.file_format() {
            wellen::FileFormat::Vcd => "vcd".to_string(),
            wellen::FileFormat::Fst => "fst".to_string(),
            wellen::FileFormat::Ghw => "ghw".to_string(),
            wellen::FileFormat::Unknown => "unknown".to_string(),
        }
    }
}

/// Wellen scope implementation
#[derive(Clone)]
pub struct WellenScope {
    pub(crate) inner: wellen::Scope,
}

impl ScopeTrait for WellenScope {
    fn name(&self, hier: &dyn HierarchyTrait) -> String {
        let wellen_hier = hier
            .as_any()
            .downcast_ref::<WellenHierarchy>()
            .expect("Wellen scope requires Wellen hierarchy");
        self.inner.name(&wellen_hier.inner).to_string()
    }

    fn full_name(&self, hier: &dyn HierarchyTrait) -> String {
        let wellen_hier = hier
            .as_any()
            .downcast_ref::<WellenHierarchy>()
            .expect("Wellen scope requires Wellen hierarchy");
        self.inner.full_name(&wellen_hier.inner).to_string()
    }

    fn scope_type(&self) -> String {
        match self.inner.scope_type() {
            wellen::ScopeType::Module => "module",
            wellen::ScopeType::Task => "task",
            wellen::ScopeType::Function => "function",
            wellen::ScopeType::Begin => "begin",
            wellen::ScopeType::Fork => "fork",
            wellen::ScopeType::Generate => "generate",
            wellen::ScopeType::Struct => "struct",
            wellen::ScopeType::Union => "union",
            wellen::ScopeType::Class => "class",
            wellen::ScopeType::Interface => "interface",
            wellen::ScopeType::Package => "package",
            wellen::ScopeType::Program => "program",
            wellen::ScopeType::VhdlArchitecture => "vhdl_architecture",
            wellen::ScopeType::VhdlProcedure => "vhdl_procedure",
            wellen::ScopeType::VhdlFunction => "vhdl_function",
            wellen::ScopeType::VhdlRecord => "vhdl_record",
            wellen::ScopeType::VhdlProcess => "vhdl_process",
            wellen::ScopeType::VhdlBlock => "vhdl_block",
            wellen::ScopeType::VhdlForGenerate => "vhdl_for_generate",
            wellen::ScopeType::VhdlIfGenerate => "vhdl_if_generate",
            wellen::ScopeType::VhdlGenerate => "vhdl_generate",
            wellen::ScopeType::VhdlPackage => "vhdl_package",
            _ => "unknown",
        }
        .to_string()
    }

    fn vars(
        &self,
        hier: &dyn HierarchyTrait,
    ) -> Box<dyn Iterator<Item = Box<dyn VarTrait>> + Send + Sync> {
        let wellen_hier = hier
            .as_any()
            .downcast_ref::<WellenHierarchy>()
            .expect("Wellen scope requires Wellen hierarchy");

        let vars: Vec<Box<dyn VarTrait>> = self
            .inner
            .vars(&wellen_hier.inner)
            .map(|var_ref| {
                Box::new(WellenVar {
                    inner: wellen_hier.inner[var_ref].clone(),
                }) as Box<dyn VarTrait>
            })
            .collect();

        Box::new(vars.into_iter())
    }

    fn scopes(
        &self,
        hier: &dyn HierarchyTrait,
    ) -> Box<dyn Iterator<Item = Box<dyn ScopeTrait>> + Send + Sync> {
        let wellen_hier = hier
            .as_any()
            .downcast_ref::<WellenHierarchy>()
            .expect("Wellen scope requires Wellen hierarchy");

        let scopes: Vec<Box<dyn ScopeTrait>> = self
            .inner
            .scopes(&wellen_hier.inner)
            .map(|scope_ref| {
                Box::new(WellenScope {
                    inner: wellen_hier.inner[scope_ref].clone(),
                }) as Box<dyn ScopeTrait>
            })
            .collect();

        Box::new(scopes.into_iter())
    }

    fn is_record(&self) -> bool {
        false
    }

    fn record(&self) -> Option<Box<dyn RecordTrait>> {
        None
    }
}

/// Wellen variable implementation
#[derive(Clone)]
pub struct WellenVar {
    pub(crate) inner: wellen::Var,
}

impl VarTrait for WellenVar {
    fn name(&self, hier: &dyn HierarchyTrait) -> String {
        let wellen_hier = hier
            .as_any()
            .downcast_ref::<WellenHierarchy>()
            .expect("Wellen var requires Wellen hierarchy");
        self.inner.name(&wellen_hier.inner).to_string()
    }

    fn full_name(&self, hier: &dyn HierarchyTrait) -> String {
        let wellen_hier = hier
            .as_any()
            .downcast_ref::<WellenHierarchy>()
            .expect("Wellen var requires Wellen hierarchy");
        self.inner.full_name(&wellen_hier.inner).to_string()
    }

    fn scope_path(&self, hier: &dyn HierarchyTrait) -> Vec<String> {
        fn collect_scope_path(hier: &wellen::Hierarchy, scope_ref: wellen::ScopeRef) -> Vec<String> {
            let mut path = Vec::new();
            if let Some(parent_ref) = hier[scope_ref].parent(hier) {
                path = collect_scope_path(hier, parent_ref);
            }
            path.push(hier[scope_ref].name(hier).to_string());
            path
        }

        let wellen_hier = hier
            .as_any()
            .downcast_ref::<WellenHierarchy>()
            .expect("Wellen var requires Wellen hierarchy");

        if let Some(parent_ref) = self.inner.parent(&wellen_hier.inner) {
            collect_scope_path(&wellen_hier.inner, parent_ref)
        } else {
            Vec::new()
        }
    }

    fn signal_handle(&self) -> SignalHandle {
        self.inner.signal_ref().index()
    }

    fn bitwidth(&self) -> Option<u32> {
        self.inner.length()
    }

    fn var_type(&self) -> String {
        format!("{:?}", self.inner.var_type())
    }

    fn enum_type(&self, hier: &dyn HierarchyTrait) -> Option<(String, Vec<(String, String)>)> {
        let wellen_hier = hier
            .as_any()
            .downcast_ref::<WellenHierarchy>()
            .expect("Wellen var requires Wellen hierarchy");

        self.inner.enum_type(&wellen_hier.inner).map(|(name, mapping)| {
            let mapping_str = mapping
                .iter()
                .map(|(k, v)| (k.to_string(), v.to_string()))
                .collect();
            (name.to_string(), mapping_str)
        })
    }

    fn vhdl_type_name(&self, hier: &dyn HierarchyTrait) -> Option<String> {
        let wellen_hier = hier
            .as_any()
            .downcast_ref::<WellenHierarchy>()
            .expect("Wellen var requires Wellen hierarchy");

        self.inner.vhdl_type_name(&wellen_hier.inner).map(|s| s.to_string())
    }

    fn direction(&self) -> String {
        format!("{:?}", self.inner.direction())
    }

    fn length(&self) -> Option<u32> {
        self.inner.length()
    }

    fn is_real(&self) -> bool {
        self.inner.is_real()
    }

    fn is_string(&self) -> bool {
        self.inner.is_string()
    }

    fn is_bit_vector(&self) -> bool {
        self.inner.is_bit_vector()
    }

    fn is_1bit(&self) -> bool {
        self.inner.is_1bit()
    }

    fn index(&self) -> Option<VarIndex> {
        self.inner.index().map(|idx| VarIndex {
            msb: idx.msb(),
            lsb: idx.lsb(),
        })
    }
}

/// Wellen signal implementation
pub struct WellenSignal {
    pub(crate) signal: Arc<wellen::Signal>,
    pub(crate) time_table: Arc<WellenTimeTable>,
}

impl SignalTrait for WellenSignal {
    fn value_at_time(&self, time: Time) -> Option<SignalValue> {
        // Binary search in time table
        // Note: wellen uses i64 for time but we use u64 in the trait
        match self.time_table.inner.as_ref().binary_search(&(time as u64)) {
            Ok(idx) => self.value_at_idx(idx as TimeTableIdx),
            Err(idx) => {
                if idx > 0 {
                    self.value_at_idx((idx - 1) as TimeTableIdx)
                } else {
                    None
                }
            }
        }
    }

    fn value_at_idx(&self, idx: TimeTableIdx) -> Option<SignalValue> {
        let data_offset = self.signal.get_offset(idx)?;
        let value = self.signal.get_value_at(&data_offset, 0);
        Some(convert_wellen_value_to_signal_value(&value))
    }

    fn all_changes(&self) -> Box<dyn Iterator<Item = (Time, SignalValue)> + Send + Sync> {
        let signal = self.signal.clone();
        let time_table = self.time_table.clone();
        let time_indices = signal.time_indices().to_vec();

        Box::new(time_indices.into_iter().filter_map(move |time_idx| {
            let time = time_table.get(time_idx as usize)?;
            let offset = signal.get_offset(time_idx)?;
            let value = signal.get_value_at(&offset, 0);
            Some((time, convert_wellen_value_to_signal_value(&value)))
        }))
    }

    fn all_changes_after(
        &self,
        start_time: Time,
    ) -> Box<dyn Iterator<Item = (Time, SignalValue)> + Send + Sync> {
        // Find the time table index for start_time
        let start_idx = match self.time_table.inner.as_ref().binary_search(&(start_time as u64)) {
            Ok(idx) => idx,
            Err(idx) => idx,
        };

        let time_indices = self.signal.time_indices();

        // Find position in time_indices where >= start_idx
        let start_offset = time_indices
            .iter()
            .position(|&idx| idx >= start_idx as u32)
            .unwrap_or(time_indices.len());

        let signal = self.signal.clone();
        let time_table = self.time_table.clone();
        let indices_vec = time_indices[start_offset..].to_vec();

        Box::new(indices_vec.into_iter().filter_map(move |time_idx| {
            let time = time_table.get(time_idx as usize)?;
            let offset = signal.get_offset(time_idx)?;
            let value = signal.get_value_at(&offset, 0);
            Some((time, convert_wellen_value_to_signal_value(&value)))
        }))
    }

    fn query_signal(&self, query_time: Time) -> Result<QueryResult, SignalError> {
        let time_idx = match self.time_table.inner.as_ref().binary_search(&(query_time as u64)) {
            Ok(idx) => idx,
            Err(idx) => {
                if idx > 0 {
                    idx - 1
                } else {
                    return Err(SignalError::OutOfRange(query_time));
                }
            }
        };

        let offset = self
            .signal
            .get_offset(time_idx as u32)
            .ok_or_else(|| SignalError::Backend("Failed to get offset".to_string()))?;

        let value = self
            .signal
            .get_value_at(&offset, offset.elements - 1);

        let actual_time = self.time_table.get(time_idx).unwrap();

        let next_change = offset
            .next_index
            .map(|nz| nz.get())
            .and_then(|next_idx| self.time_table.get(next_idx as usize));

        Ok(QueryResult {
            value: convert_wellen_value_to_signal_value(&value),
            actual_time,
            next_change,
        })
    }

    fn get_global_range(&self, data_format: u8, bit_width: u32) -> Result<(f64, f64), SignalError> {
        let mut min_val = f64::MAX;
        let mut max_val = f64::MIN;

        for time_idx in self.signal.time_indices() {
            if let Some(offset) = self.signal.get_offset(*time_idx) {
                // Get the last value in the time step (as done in original implementation)
                let value = self.signal.get_value_at(&offset, offset.elements - 1);
                if let Some(float_val) = convert_wellen_value_to_float(&value, data_format, bit_width) {
                    if !float_val.is_nan() && float_val.is_finite() {
                        min_val = min_val.min(float_val);
                        max_val = max_val.max(float_val);
                    }
                }
            }
        }

        // Handle case where no valid values found (match original behavior)
        if !min_val.is_finite() || !max_val.is_finite() {
            return Ok((0.0, 1.0));
        }

        // Add margin if range is zero
        if (min_val - max_val).abs() < f64::EPSILON {
            let margin = if min_val.abs() > f64::EPSILON {
                min_val.abs() * 0.1
            } else {
                1.0
            };
            min_val -= margin;
            max_val += margin;
        }

        Ok((min_val, max_val))
    }

    fn signal_eq(&self, other: &dyn SignalTrait) -> bool {
        if let Some(other_wellen) = other.as_any().downcast_ref::<WellenSignal>() {
            self.signal.signal_ref() == other_wellen.signal.signal_ref()
        } else {
            false
        }
    }

    fn signal_hash(&self) -> u64 {
        self.signal.signal_ref().index() as u64
    }

    fn as_any(&self) -> &dyn std::any::Any {
        self
    }
}

/// Wellen time table implementation
pub struct WellenTimeTable {
    pub(crate) inner: Arc<wellen::TimeTable>,
}

impl TimeTableTrait for WellenTimeTable {
    fn get(&self, idx: usize) -> Option<Time> {
        // Wellen uses u64 for time, which matches our Time type
        self.inner.get(idx).copied()
    }

    fn len(&self) -> usize {
        self.inner.len()
    }

    fn binary_search(&self, time: Time) -> Result<usize, usize> {
        // Time is u64, which matches wellen's time type
        self.inner.as_ref().binary_search(&time)
    }

    fn as_any(&self) -> &dyn std::any::Any {
        self
    }
}

// Helper functions

fn convert_wellen_value_to_signal_value(value: &wellen::SignalValue) -> SignalValue {
    match value {
        wellen::SignalValue::Real(f) => SignalValue::Real(*f),
        wellen::SignalValue::String(s) => SignalValue::String(s.to_string()),
        wellen::SignalValue::Binary(_bytes, bit_width) => {
            // Try to convert to BigUint for 2-state values
            if let Some(biguint) = num_bigint::BigUint::try_from_signal(*value) {
                // It's a 2-state value
                // For single-bit signals, return as scalar
                if *bit_width == 1 {
                    let bit = if biguint.bit(0) { SignalScalar::One } else { SignalScalar::Zero };
                    SignalValue::Scalar(bit)
                } else {
                    // For multi-bit signals, return as Integer (BigUint bytes in little-endian)
                    // Convert BigUint to little-endian bytes
                    let bytes = biguint.to_bytes_le();
                    SignalValue::Integer(bytes, *bit_width)
                }
            } else {
                // Has X or Z values, convert to string representation
                SignalValue::String(value.to_bit_string().unwrap_or_default())
            }
        }
        _ => SignalValue::Unknown,
    }
}

fn convert_bit_to_scalar(bit: u8) -> SignalScalar {
    match bit {
        b'0' => SignalScalar::Zero,
        b'1' => SignalScalar::One,
        b'x' | b'X' => SignalScalar::X,
        b'z' | b'Z' => SignalScalar::Z,
        _ => SignalScalar::X,
    }
}

fn convert_wellen_value_to_float(
    value: &wellen::SignalValue,
    data_format: u8,
    bit_width: u32,
) -> Option<f64> {
    match data_format {
        4 => {
            // Float format
            if let wellen::SignalValue::Real(f) = value {
                Some(*f)
            } else {
                None
            }
        }
        _ => {
            // Numeric formats (unsigned, signed, hex, bin)
            if let Some(biguint) = num_bigint::BigUint::try_from_signal(*value) {
                let bits = biguint.to_u64_digits();
                if bits.is_empty() {
                    return Some(0.0);
                }

                let raw_value = bits[0];

                match data_format {
                    0 => Some(raw_value as f64), // Unsigned
                    1 => {
                        // Signed (2's complement)
                        if bit_width > 0 && bit_width <= 64 {
                            let sign_bit = 1u64 << (bit_width - 1);
                            if raw_value & sign_bit != 0 {
                                // Negative number
                                let mask = (1u64 << bit_width) - 1;
                                let positive = (!raw_value & mask) + 1;
                                Some(-(positive as f64))
                            } else {
                                Some(raw_value as f64)
                            }
                        } else {
                            Some(raw_value as f64)
                        }
                    }
                    2 | 3 => Some(raw_value as f64), // Hex/Bin as unsigned
                    _ => None,
                }
            } else {
                None
            }
        }
    }
}

// === WaveSourceTrait Implementation ===

/// Wellen signal source wrapper that implements WaveSourceTrait
pub struct WellenSignalSource {
    source: wellen::SignalSource,
    time_table: Arc<WellenTimeTable>,
}

impl WellenSignalSource {
    pub fn new(source: wellen::SignalSource, time_table: Arc<WellenTimeTable>) -> Self {
        Self { source, time_table }
    }
}

impl WaveSourceTrait for WellenSignalSource {
    fn load_signals(
        &mut self,
        handles: &[SignalHandle],
        hier: &dyn HierarchyTrait,
    ) -> Vec<(SignalHandle, Arc<dyn SignalTrait>)> {
        // Downcast to get Wellen hierarchy
        let wellen_hier = if let Some(wh) = hier.as_any().downcast_ref::<WellenHierarchy>() {
            wh
        } else {
            return Vec::new();
        };

        // Convert handles to SignalRefs
        let signal_refs: Vec<wellen::SignalRef> = handles
            .iter()
            .filter_map(|h| wellen::SignalRef::from_index(*h))
            .collect();

        // Batch load all signals
        let loaded = self.source.load_signals(&signal_refs, wellen_hier.inner(), true);

        // Convert to trait objects
        loaded
            .into_iter()
            .map(|(sig_ref, wellen_signal)| {
                let signal_trait: Arc<dyn SignalTrait> = Arc::new(WellenSignal {
                    signal: Arc::new(wellen_signal),
                    time_table: Arc::clone(&self.time_table),
                });
                (sig_ref.index(), signal_trait)
            })
            .collect()
    }
}

// === WaveformTrait Implementation ===

/// Wellen waveform backend implementing WaveformTrait
pub struct WellenWaveform {
    path: String,
    opts: wellen::LoadOptions,

    // State management
    hierarchy: Option<Arc<WellenHierarchy>>,
    time_table: Option<Arc<WellenTimeTable>>,
    wave_source: Option<Arc<std::sync::Mutex<WellenSignalSource>>>,

    // Internal Wellen state
    body_continuation: Option<wellen::viewers::ReadBodyContinuation<BufReader<File>>>,

    // Loading status
    header_loaded: bool,
    body_loaded: bool,
}

impl WellenWaveform {
    /// Create a new Wellen waveform backend.
    ///
    /// IMPORTANT: This constructor performs NO I/O and returns immediately.
    /// All file parsing is deferred to load_header() / load_body() to ensure
    /// non-blocking construction for GUI applications.
    pub fn new(path: String, opts: wellen::LoadOptions) -> Self {
        Self {
            path,
            opts,
            hierarchy: None,
            time_table: None,
            wave_source: None,
            body_continuation: None,
            header_loaded: false,
            body_loaded: false,
        }
    }
}

impl WaveformTrait for WellenWaveform {
    fn hierarchy(&self) -> Option<Arc<dyn HierarchyTrait>> {
        self.hierarchy
            .as_ref()
            .map(|h| h.clone() as Arc<dyn HierarchyTrait>)
    }

    fn time_table(&self) -> Option<Arc<dyn TimeTableTrait>> {
        self.time_table
            .as_ref()
            .map(|tt| tt.clone() as Arc<dyn TimeTableTrait>)
    }

    fn load_header(&mut self) -> Result<(), String> {
        if self.header_loaded {
            return Ok(()); // Idempotent
        }

        let header_result = wellen::viewers::read_header_from_file(&self.path, &self.opts)
            .map_err(|e| e.to_string())?;

        self.hierarchy = Some(Arc::new(WellenHierarchy::new(Arc::new(
            header_result.hierarchy,
        ))));
        self.body_continuation = Some(header_result.body);
        self.header_loaded = true;

        Ok(())
    }

    fn header_loaded(&self) -> bool {
        self.header_loaded
    }

    fn load_body(&mut self) -> Result<(), String> {
        if self.body_loaded {
            return Ok(()); // Idempotent
        }

        if !self.header_loaded {
            return Err("Header must be loaded before body".to_string());
        }

        let body_cont = self
            .body_continuation
            .take()
            .ok_or_else(|| "Body continuation not available".to_string())?;

        let hierarchy = self
            .hierarchy
            .as_ref()
            .ok_or_else(|| "Hierarchy not available".to_string())?;

        let body = wellen::viewers::read_body(body_cont, hierarchy.inner(), None)
            .map_err(|e| e.to_string())?;

        self.time_table = Some(Arc::new(WellenTimeTable {
            inner: Arc::new(body.time_table.clone()),
        }));
        self.wave_source = Some(Arc::new(std::sync::Mutex::new(WellenSignalSource::new(
            body.source,
            Arc::new(WellenTimeTable {
                inner: Arc::new(body.time_table),
            }),
        ))));
        self.body_loaded = true;

        Ok(())
    }

    fn body_loaded(&self) -> bool {
        self.body_loaded
    }

    fn wave_source_arc(&mut self) -> Option<Arc<std::sync::Mutex<dyn WaveSourceTrait>>> {
        self.wave_source
            .as_ref()
            .map(|ws| ws.clone() as Arc<std::sync::Mutex<dyn WaveSourceTrait>>)
    }
}

