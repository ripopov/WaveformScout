//! JETS backend implementation for trace files with hierarchical events

use crate::traits::*;
use rjets::{DynTraceData, DynTraceRecord, TraceData, TraceMetadata, TraceRecord, TraceEvent};
use std::collections::HashMap;
use std::sync::Arc;

/// Convert clock cycles to picoseconds
fn clock_to_picoseconds(clk: i64, freq_mhz: f64) -> i64 {
    (clk as f64 * 1_000_000.0 / freq_mhz) as i64
}

/// Convert TraceRecord to JSON string
fn record_to_json<'a, R: TraceRecord<'a>>(record: &R) -> String {
    let mut obj = serde_json::Map::new();
    obj.insert("id".to_string(), serde_json::Value::Number(record.id().into()));
    obj.insert("name".to_string(), serde_json::Value::String(record.name().to_string()));

    if let Some(parent_id) = record.parent_id() {
        obj.insert("parent_id".to_string(), serde_json::Value::Number(parent_id.into()));
    }

    let data_map = record.data();
    if !data_map.is_empty() {
        obj.insert("data".to_string(), serde_json::Value::Object(
            data_map.into_iter().map(|(k, v)| (k, v)).collect()
        ));
    }

    serde_json::to_string_pretty(&obj).unwrap_or_else(|_| "{}".to_string())
}

/// Convert TraceEvent to JSON string
fn event_to_json<E: TraceEvent>(event: &E) -> String {
    let mut obj = serde_json::Map::new();
    obj.insert("name".to_string(), serde_json::Value::String(event.name().to_string()));

    let data_map = event.data();
    if !data_map.is_empty() {
        obj.insert("data".to_string(), serde_json::Value::Object(
            data_map.into_iter().map(|(k, v)| (k, v)).collect()
        ));
    }

    serde_json::to_string_pretty(&obj).unwrap_or_else(|_| "{}".to_string())
}

/// JETS hierarchy implementation
#[derive(Clone)]
pub struct JetsHierarchy {
    trace_data: Arc<DynTraceData>,
    clock_freq_mhz: f64,
    record_id_to_handle: HashMap<u64, usize>,
}

impl JetsHierarchy {
    pub fn new(trace_data: Arc<DynTraceData>) -> Self {
        let metadata = trace_data.metadata();
        let clock_freq_mhz = metadata.header_data()
            .get("clock_frequency_mhz")
            .and_then(|v| v.as_f64())
            .unwrap_or(1000.0);

        let mut record_id_to_handle = HashMap::new();
        let mut next_handle = 0;

        fn register_record<'a>(
            record: &DynTraceRecord<'a>,
            handle: &mut usize,
            id_map: &mut HashMap<u64, usize>,
        ) {
            let current_handle = *handle;
            id_map.insert(record.id(), current_handle);
            *handle += 1;

            // Use index-based access for children
            for i in 0..record.num_children() {
                if let Some(child) = record.child_at(i) {
                    register_record(&child, handle, id_map);
                }
            }
        }

        for root_id in trace_data.root_ids() {
            if let Some(root) = trace_data.get_record(root_id) {
                register_record(&root, &mut next_handle, &mut record_id_to_handle);
            }
        }

        Self {
            trace_data,
            clock_freq_mhz,
            record_id_to_handle,
        }
    }

    pub fn clock_freq_mhz(&self) -> f64 {
        self.clock_freq_mhz
    }

    pub fn get_root_ids(&self) -> Vec<u64> {
        self.trace_data.root_ids()
    }

    pub fn get_record_by_handle(&self, handle: usize) -> Option<DynTraceRecord<'_>> {
        // Find the record ID that corresponds to this handle
        let id = self.record_id_to_handle
            .iter()
            .find(|(_, &h)| h == handle)
            .map(|(&id, _)| id)?;

        self.trace_data.get_record(id)
    }

    pub fn get_record_by_id(&self, id: u64) -> Option<DynTraceRecord<'_>> {
        self.trace_data.get_record(id)
    }

    pub fn get_handle_by_id(&self, id: u64) -> Option<usize> {
        self.record_id_to_handle.get(&id).copied()
    }

    pub fn generate_signal_changes(&self, record: &DynTraceRecord<'_>) -> Vec<(Time, SignalValue)> {
        let mut changes = Vec::new();

        // Initial high-impedance state
        changes.push((0, SignalValue::String("Z".to_string())));

        // Record start
        let start_time_ps = clock_to_picoseconds(record.clk().max(1), self.clock_freq_mhz);
        changes.push((start_time_ps as Time, SignalValue::String(record_to_json(record))));

        // Events - use index-based access
        for i in 0..record.num_events() {
            if let Some(event) = record.event_at(i) {
                let event_time_ps = clock_to_picoseconds(event.clk(), self.clock_freq_mhz);
                changes.push((event_time_ps as Time, SignalValue::String(event_to_json(&event))));
            }
        }

        // Record end
        if let Some(end_clk) = record.end_clk() {
            let end_time_ps = clock_to_picoseconds(end_clk, self.clock_freq_mhz) + 1;
            changes.push((end_time_ps as Time, SignalValue::String("Z".to_string())));
        }

        changes
    }

    pub fn date(&self) -> String {
        let metadata = self.trace_data.metadata();
        metadata.header_data()
            .get("date")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string()
    }

    pub fn version(&self) -> String {
        self.trace_data.metadata().version().to_string()
    }

    pub fn get_max_time(&self) -> Time {
        let metadata = self.trace_data.metadata();
        let (_, max_clk) = metadata.trace_extent();
        clock_to_picoseconds(max_clk, self.clock_freq_mhz) as Time
    }

    pub fn trace_data(&self) -> &Arc<DynTraceData> {
        &self.trace_data
    }
}

impl HierarchyTrait for JetsHierarchy {
    fn as_any(&self) -> &dyn std::any::Any {
        self
    }

    fn all_vars(&self) -> Box<dyn Iterator<Item = Box<dyn VarTrait>> + Send + Sync> {
        let mut vars = Vec::new();
        for (&id, &handle) in &self.record_id_to_handle {
            if let Some(_record) = self.trace_data.get_record(id) {
                vars.push(Box::new(JetsVar {
                    record_id: id,
                    signal_handle: handle,
                    clock_freq_mhz: self.clock_freq_mhz,
                }) as Box<dyn VarTrait>);
            }
        }
        Box::new(vars.into_iter())
    }

    fn top_scopes(&self) -> Box<dyn Iterator<Item = Box<dyn ScopeTrait>> + Send + Sync> {
        let scopes: Vec<Box<dyn ScopeTrait>> = self.get_root_ids()
            .iter()
            .filter_map(|&root_id| {
                self.record_id_to_handle.get(&root_id).map(|&_handle| {
                    Box::new(JetsScope {
                        record_id: root_id,
                        clock_freq_mhz: self.clock_freq_mhz,
                    }) as Box<dyn ScopeTrait>
                })
            })
            .collect();
        Box::new(scopes.into_iter())
    }

    fn find_var_by_path(&self, path: &[String]) -> Option<Box<dyn VarTrait>> {
        if path.is_empty() {
            return None;
        }

        // Navigate through scopes to find the record
        let mut current_ids: Vec<u64> = self.get_root_ids();

        for (i, scope_name) in path.iter().enumerate() {
            let is_last = i == path.len() - 1;

            let found_id = current_ids
                .iter()
                .find(|&&id| {
                    if let Some(record) = self.trace_data.get_record(id) {
                        record.name() == scope_name.as_str()
                    } else {
                        false
                    }
                })
                .copied();

            if let Some(id) = found_id {
                if is_last {
                    // Found the target variable
                    let handle = self.record_id_to_handle.get(&id)?;
                    return Some(Box::new(JetsVar {
                        record_id: id,
                        signal_handle: *handle,
                        clock_freq_mhz: self.clock_freq_mhz,
                    }));
                } else {
                    // Navigate to children - use index-based access
                    if let Some(record) = self.trace_data.get_record(id) {
                        let mut child_ids = Vec::new();
                        for i in 0..record.num_children() {
                            if let Some(child) = record.child_at(i) {
                                child_ids.push(child.id());
                            }
                        }
                        current_ids = child_ids;
                    } else {
                        return None;
                    }
                }
            } else {
                return None;
            }
        }

        None
    }

    fn get_var_by_signal_ref(&self, handle: SignalHandle) -> Option<Box<dyn VarTrait>> {
        let record = self.get_record_by_handle(handle)?;
        Some(Box::new(JetsVar {
            record_id: record.id(),
            signal_handle: handle,
            clock_freq_mhz: self.clock_freq_mhz,
        }))
    }

    fn date(&self) -> String {
        self.date()
    }

    fn version(&self) -> String {
        self.version()
    }

    fn timescale(&self) -> Option<(u32, String)> {
        // JETS uses picoseconds
        Some((1, "ps".to_string()))
    }

    fn file_format(&self) -> String {
        "JETS".to_string()
    }
}

/// JETS scope implementation
#[derive(Clone)]
pub struct JetsScope {
    record_id: u64,
    clock_freq_mhz: f64,
}

impl ScopeTrait for JetsScope {
    fn name(&self, hier: &dyn HierarchyTrait) -> String {
        let jets_hier = hier
            .as_any()
            .downcast_ref::<JetsHierarchy>()
            .expect("JETS scope requires JETS hierarchy");

        jets_hier.get_record_by_id(self.record_id)
            .map(|r| r.name().to_string())
            .unwrap_or_default()
    }

    fn full_name(&self, hier: &dyn HierarchyTrait) -> String {
        let jets_hier = hier
            .as_any()
            .downcast_ref::<JetsHierarchy>()
            .expect("JETS scope requires JETS hierarchy");

        let mut path_parts = Vec::new();
        let mut current_id = Some(self.record_id);

        while let Some(id) = current_id {
            if let Some(record) = jets_hier.get_record_by_id(id) {
                path_parts.push(record.name().to_string());
                current_id = record.parent_id();
            } else {
                break;
            }
        }

        path_parts.reverse();
        path_parts.join(".")
    }

    fn scope_type(&self) -> String {
        "record".to_string()
    }

    fn vars(
        &self,
        hier: &dyn HierarchyTrait,
    ) -> Box<dyn Iterator<Item = Box<dyn VarTrait>> + Send + Sync> {
        let jets_hier = hier
            .as_any()
            .downcast_ref::<JetsHierarchy>()
            .expect("JETS scope requires JETS hierarchy");

        let handle = jets_hier
            .get_handle_by_id(self.record_id)
            .unwrap_or(0);

        let vars: Vec<Box<dyn VarTrait>> = vec![Box::new(JetsVar {
            record_id: self.record_id,
            signal_handle: handle,
            clock_freq_mhz: self.clock_freq_mhz,
        })];

        Box::new(vars.into_iter())
    }

    fn scopes(
        &self,
        hier: &dyn HierarchyTrait,
    ) -> Box<dyn Iterator<Item = Box<dyn ScopeTrait>> + Send + Sync> {
        let jets_hier = hier
            .as_any()
            .downcast_ref::<JetsHierarchy>()
            .expect("JETS scope requires JETS hierarchy");

        let scopes: Vec<Box<dyn ScopeTrait>> = if let Some(record) = jets_hier.get_record_by_id(self.record_id) {
            // Use index-based access for children
            (0..record.num_children())
                .filter_map(|i| record.child_at(i))
                .map(|child| {
                    Box::new(JetsScope {
                        record_id: child.id(),
                        clock_freq_mhz: self.clock_freq_mhz,
                    }) as Box<dyn ScopeTrait>
                })
                .collect()
        } else {
            Vec::new()
        };

        Box::new(scopes.into_iter())
    }

    fn is_record(&self) -> bool {
        true
    }

    fn record(&self) -> Option<Box<dyn RecordTrait>> {
        Some(Box::new(JetsRecord {
            record_id: self.record_id,
            clock_freq_mhz: self.clock_freq_mhz,
        }))
    }
}

/// JETS variable implementation
#[derive(Clone)]
pub struct JetsVar {
    record_id: u64,
    signal_handle: usize,
    clock_freq_mhz: f64,
}

impl VarTrait for JetsVar {
    fn name(&self, hier: &dyn HierarchyTrait) -> String {
        let jets_hier = hier
            .as_any()
            .downcast_ref::<JetsHierarchy>()
            .expect("JETS var requires JETS hierarchy");

        jets_hier.get_record_by_id(self.record_id)
            .map(|r| r.name().to_string())
            .unwrap_or_default()
    }

    fn full_name(&self, hier: &dyn HierarchyTrait) -> String {
        let jets_hier = hier
            .as_any()
            .downcast_ref::<JetsHierarchy>()
            .expect("JETS var requires JETS hierarchy");

        let mut path_parts = Vec::new();
        let mut current_id = Some(self.record_id);

        while let Some(id) = current_id {
            if let Some(record) = jets_hier.get_record_by_id(id) {
                path_parts.push(record.name().to_string());
                current_id = record.parent_id();
            } else {
                break;
            }
        }

        path_parts.reverse();
        path_parts.join(".")
    }

    fn scope_path(&self, hier: &dyn HierarchyTrait) -> Vec<String> {
        let jets_hier = hier
            .as_any()
            .downcast_ref::<JetsHierarchy>()
            .expect("JETS var requires JETS hierarchy");

        let mut path_parts = Vec::new();
        let mut current_id = jets_hier.get_record_by_id(self.record_id).and_then(|r| r.parent_id());

        while let Some(id) = current_id {
            if let Some(record) = jets_hier.get_record_by_id(id) {
                path_parts.push(record.name().to_string());
                current_id = record.parent_id();
            } else {
                break;
            }
        }

        path_parts.reverse();
        path_parts
    }

    fn signal_handle(&self) -> SignalHandle {
        self.signal_handle
    }

    fn bitwidth(&self) -> Option<u32> {
        None
    }

    fn var_type(&self) -> String {
        "String".to_string()
    }

    fn enum_type(&self, _hier: &dyn HierarchyTrait) -> Option<(String, Vec<(String, String)>)> {
        None
    }

    fn vhdl_type_name(&self, _hier: &dyn HierarchyTrait) -> Option<String> {
        None
    }

    fn direction(&self) -> String {
        "Unknown".to_string()
    }

    fn length(&self) -> Option<u32> {
        None
    }

    fn is_real(&self) -> bool {
        false
    }

    fn is_string(&self) -> bool {
        true
    }

    fn is_bit_vector(&self) -> bool {
        false
    }

    fn is_1bit(&self) -> bool {
        false
    }

    fn index(&self) -> Option<VarIndex> {
        None
    }
}

/// JETS signal implementation
pub struct JetsSignal {
    changes: Arc<Vec<(Time, SignalValue)>>,
}

impl JetsSignal {
    pub fn new(changes: Vec<(Time, SignalValue)>) -> Self {
        Self {
            changes: Arc::new(changes),
        }
    }
}

impl SignalTrait for JetsSignal {
    fn value_at_time(&self, time: Time) -> Option<SignalValue> {
        // Binary search for last change at or before time
        match self.changes.binary_search_by_key(&time, |(t, _)| *t) {
            Ok(idx) => Some(self.changes[idx].1.clone()),
            Err(idx) => {
                if idx > 0 {
                    Some(self.changes[idx - 1].1.clone())
                } else {
                    None
                }
            }
        }
    }

    fn value_at_idx(&self, _idx: TimeTableIdx) -> Option<SignalValue> {
        // JETS doesn't support indexed access
        None
    }

    fn all_changes(&self) -> Box<dyn Iterator<Item = (Time, SignalValue)> + Send + Sync> {
        let changes = self.changes.clone();
        Box::new(changes.iter().cloned().collect::<Vec<_>>().into_iter())
    }

    fn all_changes_after(
        &self,
        start_time: Time,
    ) -> Box<dyn Iterator<Item = (Time, SignalValue)> + Send + Sync> {
        let changes = self.changes.clone();
        let start_idx = self
            .changes
            .iter()
            .position(|(t, _)| *t >= start_time)
            .unwrap_or(self.changes.len());

        Box::new(
            changes[start_idx..]
                .iter()
                .cloned()
                .collect::<Vec<_>>()
                .into_iter(),
        )
    }

    fn query_signal(&self, query_time: Time) -> Result<QueryResult, SignalError> {
        let idx = match self.changes.binary_search_by_key(&query_time, |(t, _)| *t) {
            Ok(idx) => idx,
            Err(idx) => {
                if idx > 0 {
                    idx - 1
                } else {
                    return Err(SignalError::OutOfRange(query_time));
                }
            }
        };

        let (actual_time, value) = &self.changes[idx];
        let next_change = if idx + 1 < self.changes.len() {
            Some(self.changes[idx + 1].0)
        } else {
            None
        };

        Ok(QueryResult {
            value: value.clone(),
            actual_time: *actual_time,
            next_change,
        })
    }

    fn get_global_range(&self, _data_format: u8, _bit_width: u32) -> Result<(f64, f64), SignalError> {
        // JETS signals are strings, not analog
        Ok((0.0, 1.0))
    }

    fn signal_eq(&self, other: &dyn SignalTrait) -> bool {
        if let Some(other_jets) = other.as_any().downcast_ref::<JetsSignal>() {
            Arc::ptr_eq(&self.changes, &other_jets.changes)
        } else {
            false
        }
    }

    fn signal_hash(&self) -> u64 {
        Arc::as_ptr(&self.changes) as u64
    }

    fn as_any(&self) -> &dyn std::any::Any {
        self
    }
}

/// JETS time table implementation (synthetic: [0, max_time])
pub struct JetsTimeTable {
    times: Arc<Vec<Time>>,
}

impl JetsTimeTable {
    pub fn new(max_time: Time) -> Self {
        Self {
            times: Arc::new(vec![0, max_time]),
        }
    }
}

impl TimeTableTrait for JetsTimeTable {
    fn get(&self, idx: usize) -> Option<Time> {
        self.times.get(idx).copied()
    }

    fn len(&self) -> usize {
        self.times.len()
    }

    fn binary_search(&self, time: Time) -> Result<usize, usize> {
        self.times.as_ref().binary_search(&time)
    }

    fn as_any(&self) -> &dyn std::any::Any {
        self
    }
}

/// JETS record implementation
pub struct JetsRecord {
    pub record_id: u64,
    pub clock_freq_mhz: f64,
}

impl JetsRecord {
    fn get_record<'a>(&self, hier: &'a dyn HierarchyTrait) -> Option<DynTraceRecord<'a>> {
        let jets_hier = hier
            .as_any()
            .downcast_ref::<JetsHierarchy>()
            .expect("JETS record requires JETS hierarchy");
        jets_hier.get_record_by_id(self.record_id)
    }
}

impl RecordTrait for JetsRecord {
    fn record_type(&self) -> String {
        // Return empty string - we need hierarchy to get this
        String::new()
    }

    fn name(&self) -> String {
        // We can't access hierarchy here without passing it, so return empty string
        // This method should be deprecated in favor of passing hier parameter
        String::new()
    }

    fn start_time(&self) -> Time {
        // Same issue - we need hierarchy to get the record
        0
    }

    fn end_time(&self) -> Option<Time> {
        None
    }

    fn annotations(&self) -> Vec<Annotation> {
        Vec::new()
    }

    fn events(&self) -> Vec<TimedAnnotation> {
        Vec::new()
    }

    fn as_any(&self) -> &dyn std::any::Any {
        self
    }
}

// === WaveSourceTrait Implementation ===

/// JETS signal source wrapper that implements WaveSourceTrait
pub struct JetsSignalSource {
    hierarchy: Arc<JetsHierarchy>,
}

impl JetsSignalSource {
    pub fn new(hierarchy: Arc<JetsHierarchy>) -> Self {
        Self { hierarchy }
    }
}

impl WaveSourceTrait for JetsSignalSource {
    fn load_signals(
        &mut self,
        handles: &[SignalHandle],
        _hier: &dyn HierarchyTrait,
    ) -> Vec<(SignalHandle, Arc<dyn SignalTrait>)> {
        let mut loaded_signals = Vec::new();

        for handle in handles {
            if let Some(record) = self.hierarchy.get_record_by_handle(*handle) {
                let changes = self.hierarchy.generate_signal_changes(&record);
                let signal_trait: Arc<dyn SignalTrait> = Arc::new(JetsSignal::new(changes));
                loaded_signals.push((*handle, signal_trait));
            }
        }

        loaded_signals
    }
}

// === WaveformTrait Implementation ===

/// JETS waveform backend implementing WaveformTrait
pub struct JetsWaveform {
    path: String,
    _opts: wellen::LoadOptions, // Unused by JETS, but kept for API consistency

    // State management
    hierarchy: Option<Arc<JetsHierarchy>>,
    time_table: Option<Arc<JetsTimeTable>>,
    wave_source: Option<JetsSignalSource>,

    // Loading status (both set to true after load_header)
    loaded: bool,
}

impl JetsWaveform {
    /// Create a new JETS waveform backend.
    ///
    /// IMPORTANT: This constructor performs NO I/O and returns immediately.
    /// All file parsing is deferred to load_header() to ensure non-blocking
    /// construction for GUI applications.
    pub fn new(path: String, opts: wellen::LoadOptions) -> Self {
        Self {
            path,
            _opts: opts,
            hierarchy: None,
            time_table: None,
            wave_source: None,
            loaded: false,
        }
    }
}

impl WaveformTrait for JetsWaveform {
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
        if self.loaded {
            return Ok(()); // Idempotent
        }

        // JETS loads ENTIRE FILE in load_header() (all data in one shot)
        // This is the ONLY place where rjets::parse_trace() is called
        // parse_trace returns JetsTraceData, wrap it in DynTraceData::Jets
        let jets_data = rjets::parse_trace(&self.path)
            .map_err(|e| format!("Failed to load JETS file: {}", e))?;

        let trace_data = rjets::DynTraceData::Jets(jets_data);
        let jets_hier = Arc::new(JetsHierarchy::new(Arc::new(trace_data)));
        let max_time = jets_hier.get_max_time();

        self.hierarchy = Some(jets_hier.clone());
        self.time_table = Some(Arc::new(JetsTimeTable::new(max_time)));
        self.wave_source = Some(JetsSignalSource::new(jets_hier));
        self.loaded = true;

        Ok(())
    }

    fn header_loaded(&self) -> bool {
        self.loaded
    }

    fn load_body(&mut self) -> Result<(), String> {
        // JETS loads everything in load_header(), so this is a no-op
        // Returns Ok immediately (no error if header not loaded - backend decision)
        Ok(())
    }

    fn body_loaded(&self) -> bool {
        self.loaded
    }

    fn wave_source(&mut self) -> Option<&mut dyn WaveSourceTrait> {
        self.wave_source
            .as_mut()
            .map(|ws| ws as &mut dyn WaveSourceTrait)
    }
}
