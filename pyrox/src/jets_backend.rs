//! JETS backend implementation for trace files with hierarchical events

use crate::traits::*;
use rjets::{TraceData, TraceRecord, TraceEvent};
use std::collections::HashMap;
use std::sync::Arc;

/// Convert clock cycles to picoseconds
fn clock_to_picoseconds(clk: i64, freq_mhz: f64) -> i64 {
    (clk as f64 * 1_000_000.0 / freq_mhz) as i64
}

/// Convert TraceRecord to JSON string
fn record_to_json(record: &TraceRecord) -> String {
    let mut obj = serde_json::Map::new();
    obj.insert("id".to_string(), serde_json::Value::String(record.id.clone()));
    obj.insert("name".to_string(), serde_json::Value::String(record.name.clone()));
    obj.insert("type".to_string(), serde_json::Value::String(record.record_type.clone()));

    if let Some(parent_id) = &record.parent_id {
        obj.insert("parent_id".to_string(), serde_json::Value::String(parent_id.clone()));
    }
    if let Some(data) = &record.data {
        obj.insert("data".to_string(), data.clone());
    }

    serde_json::to_string_pretty(&obj).unwrap_or_else(|_| "{}".to_string())
}

/// Convert TraceEvent to JSON string
fn event_to_json(event: &TraceEvent) -> String {
    let mut obj = serde_json::Map::new();
    obj.insert("name".to_string(), serde_json::Value::String(event.name.clone()));
    if let Some(data) = &event.data {
        obj.insert("data".to_string(), data.clone());
    }

    serde_json::to_string_pretty(&obj).unwrap_or_else(|_| "{}".to_string())
}

/// JETS hierarchy implementation
#[derive(Clone)]
pub struct JetsHierarchy {
    trace_data: Arc<TraceData>,
    clock_freq_mhz: f64,
    record_id_to_handle: HashMap<String, usize>,
    handle_to_record: HashMap<usize, Arc<TraceRecord>>,
}

impl JetsHierarchy {
    pub fn new(trace_data: Arc<TraceData>) -> Self {
        let clock_freq_mhz = trace_data
            .header
            .metadata
            .get("clock_frequency_mhz")
            .and_then(|v| v.as_f64())
            .unwrap_or(1000.0);

        let mut record_id_to_handle = HashMap::new();
        let mut handle_to_record = HashMap::new();
        let mut next_handle = 0;

        fn register_record(
            record: &TraceRecord,
            handle: &mut usize,
            id_map: &mut HashMap<String, usize>,
            handle_map: &mut HashMap<usize, Arc<TraceRecord>>,
        ) {
            let current_handle = *handle;
            id_map.insert(record.id.clone(), current_handle);
            handle_map.insert(current_handle, Arc::new(record.clone()));
            *handle += 1;

            for child in &record.children {
                register_record(child, handle, id_map, handle_map);
            }
        }

        for root in &trace_data.roots {
            register_record(root, &mut next_handle, &mut record_id_to_handle, &mut handle_to_record);
        }

        Self {
            trace_data,
            clock_freq_mhz,
            record_id_to_handle,
            handle_to_record,
        }
    }

    pub fn clock_freq_mhz(&self) -> f64 {
        self.clock_freq_mhz
    }

    pub fn top_records(&self) -> &[TraceRecord] {
        &self.trace_data.roots
    }

    pub fn get_record_by_handle(&self, handle: usize) -> Option<Arc<TraceRecord>> {
        self.handle_to_record.get(&handle).cloned()
    }

    pub fn get_handle_by_id(&self, id: &str) -> Option<usize> {
        self.record_id_to_handle.get(id).copied()
    }

    pub fn generate_signal_changes(&self, record: &Arc<TraceRecord>) -> Vec<(Time, SignalValue)> {
        let mut changes = Vec::new();

        // Initial high-impedance state
        changes.push((0, SignalValue::String("Z".to_string())));

        // Record start
        let start_time_ps = clock_to_picoseconds(record.clk.max(1), self.clock_freq_mhz);
        changes.push((start_time_ps as Time, SignalValue::String(record_to_json(record))));

        // Events
        for event in &record.events {
            let event_time_ps = clock_to_picoseconds(event.clk, self.clock_freq_mhz);
            changes.push((event_time_ps as Time, SignalValue::String(event_to_json(event))));
        }

        // Record end
        if let Some(end_clk) = record.end_clk {
            let end_time_ps = clock_to_picoseconds(end_clk, self.clock_freq_mhz) + 1;
            changes.push((end_time_ps as Time, SignalValue::String("Z".to_string())));
        }

        changes
    }

    pub fn date(&self) -> String {
        self.trace_data
            .header
            .metadata
            .get("date")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string()
    }

    pub fn version(&self) -> String {
        self.trace_data
            .header
            .metadata
            .get("version")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string()
    }

    pub fn get_max_time(&self) -> Time {
        // Get max time from all records
        fn max_clk_recursive(records: &[TraceRecord]) -> i64 {
            let mut max = 0;
            for record in records {
                max = max.max(record.clk);
                if let Some(end) = record.end_clk {
                    max = max.max(end);
                }
                max = max.max(max_clk_recursive(&record.children));
            }
            max
        }

        let max_clk = max_clk_recursive(&self.trace_data.roots);
        clock_to_picoseconds(max_clk, self.clock_freq_mhz) as Time
    }

    pub fn trace_data(&self) -> &Arc<TraceData> {
        &self.trace_data
    }
}

impl HierarchyTrait for JetsHierarchy {
    fn as_any(&self) -> &dyn std::any::Any {
        self
    }

    fn all_vars(&self) -> Box<dyn Iterator<Item = Box<dyn VarTrait>> + Send + Sync> {
        fn collect_record_vars(
            record: &Arc<TraceRecord>,
            handle: usize,
            freq_mhz: f64,
            vars: &mut Vec<Box<dyn VarTrait>>,
        ) {
            vars.push(Box::new(JetsVar {
                record: record.clone(),
                signal_handle: handle,
                clock_freq_mhz: freq_mhz,
            }) as Box<dyn VarTrait>);

            // Note: children are handled through the hierarchy traversal, not here
        }

        let mut vars = Vec::new();
        for (handle, record) in &self.handle_to_record {
            collect_record_vars(record, *handle, self.clock_freq_mhz, &mut vars);
        }
        Box::new(vars.into_iter())
    }

    fn top_scopes(&self) -> Box<dyn Iterator<Item = Box<dyn ScopeTrait>> + Send + Sync> {
        let scopes: Vec<Box<dyn ScopeTrait>> = self
            .top_records()
            .iter()
            .filter_map(|record| {
                self.record_id_to_handle.get(&record.id).map(|&handle| {
                    Box::new(JetsScope {
                        record: self.handle_to_record[&handle].clone(),
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
        let mut current_records: Vec<&TraceRecord> = self.top_records().iter().collect();

        for (i, scope_name) in path.iter().enumerate() {
            let is_last = i == path.len() - 1;

            let found = current_records
                .iter()
                .find(|r| r.name == *scope_name)
                .copied();

            if let Some(record) = found {
                if is_last {
                    // Found the target variable
                    let handle = self.record_id_to_handle.get(&record.id)?;
                    return Some(Box::new(JetsVar {
                        record: Arc::new(record.clone()),
                        signal_handle: *handle,
                        clock_freq_mhz: self.clock_freq_mhz,
                    }));
                } else {
                    // Navigate to children
                    current_records = record.children.iter().collect();
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
            record,
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
    record: Arc<TraceRecord>,
    clock_freq_mhz: f64,
}

impl ScopeTrait for JetsScope {
    fn name(&self, _hier: &dyn HierarchyTrait) -> String {
        self.record.name.clone()
    }

    fn full_name(&self, hier: &dyn HierarchyTrait) -> String {
        let jets_hier = hier
            .as_any()
            .downcast_ref::<JetsHierarchy>()
            .expect("JETS scope requires JETS hierarchy");

        let mut path_parts = Vec::new();
        let mut current_id = Some(self.record.id.clone());

        while let Some(id) = current_id {
            if let Some(handle) = jets_hier.get_handle_by_id(&id) {
                if let Some(record) = jets_hier.get_record_by_handle(handle) {
                    path_parts.push(record.name.clone());
                    current_id = record.parent_id.clone();
                } else {
                    break;
                }
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
            .get_handle_by_id(&self.record.id)
            .unwrap_or(0);

        let vars: Vec<Box<dyn VarTrait>> = vec![Box::new(JetsVar {
            record: self.record.clone(),
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

        let scopes: Vec<Box<dyn ScopeTrait>> = self
            .record
            .children
            .iter()
            .filter_map(|child| {
                jets_hier.get_handle_by_id(&child.id).map(|handle| {
                    Box::new(JetsScope {
                        record: jets_hier.get_record_by_handle(handle).unwrap(),
                        clock_freq_mhz: self.clock_freq_mhz,
                    }) as Box<dyn ScopeTrait>
                })
            })
            .collect();

        Box::new(scopes.into_iter())
    }

    fn is_record(&self) -> bool {
        true
    }

    fn record(&self) -> Option<Box<dyn RecordTrait>> {
        Some(Box::new(JetsRecord {
            inner: self.record.clone(),
            clock_freq_mhz: self.clock_freq_mhz,
        }))
    }
}

/// JETS variable implementation
#[derive(Clone)]
pub struct JetsVar {
    record: Arc<TraceRecord>,
    signal_handle: usize,
    clock_freq_mhz: f64,
}

impl VarTrait for JetsVar {
    fn name(&self, _hier: &dyn HierarchyTrait) -> String {
        self.record.name.clone()
    }

    fn full_name(&self, hier: &dyn HierarchyTrait) -> String {
        let jets_hier = hier
            .as_any()
            .downcast_ref::<JetsHierarchy>()
            .expect("JETS var requires JETS hierarchy");

        let mut path_parts = Vec::new();
        let mut current_id = Some(self.record.id.clone());

        while let Some(id) = current_id {
            if let Some(handle) = jets_hier.get_handle_by_id(&id) {
                if let Some(record) = jets_hier.get_record_by_handle(handle) {
                    path_parts.push(record.name.clone());
                    current_id = record.parent_id.clone();
                } else {
                    break;
                }
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
        let mut current_id = self.record.parent_id.clone();

        while let Some(id) = current_id {
            if let Some(handle) = jets_hier.get_handle_by_id(&id) {
                if let Some(record) = jets_hier.get_record_by_handle(handle) {
                    path_parts.push(record.name.clone());
                    current_id = record.parent_id.clone();
                } else {
                    break;
                }
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
    pub inner: Arc<TraceRecord>,
    pub clock_freq_mhz: f64,
}

impl RecordTrait for JetsRecord {
    fn record_type(&self) -> String {
        self.inner.record_type.clone()
    }

    fn name(&self) -> String {
        self.inner.name.clone()
    }

    fn start_time(&self) -> Time {
        clock_to_picoseconds(self.inner.clk, self.clock_freq_mhz) as Time
    }

    fn end_time(&self) -> Option<Time> {
        self.inner
            .end_clk
            .map(|clk| clock_to_picoseconds(clk, self.clock_freq_mhz) as Time)
    }

    fn annotations(&self) -> Vec<Annotation> {
        let mut annotations = Vec::new();

        // Add standard fields
        annotations.push(("id".to_string(), self.inner.id.clone()));
        annotations.push(("record_type".to_string(), self.inner.record_type.clone()));

        if let Some(parent_id) = &self.inner.parent_id {
            annotations.push(("parent_id".to_string(), parent_id.clone()));
        }

        // Add data fields
        if let Some(data) = &self.inner.data {
            if let Some(obj) = data.as_object() {
                for (key, value) in obj {
                    annotations.push((key.clone(), value.to_string()));
                }
            }
        }

        // Add explicit annotations
        for annotation in &self.inner.annotations {
            annotations.push((annotation.name.clone(), annotation.data.to_string()));
        }

        annotations
    }

    fn events(&self) -> Vec<TimedAnnotation> {
        self.inner
            .events
            .iter()
            .map(|event| {
                let time = clock_to_picoseconds(event.clk, self.clock_freq_mhz) as Time;
                let annotation = (event.name.clone(), event_to_json(event));
                (time, annotation)
            })
            .collect()
    }

    fn as_any(&self) -> &dyn std::any::Any {
        self
    }
}
