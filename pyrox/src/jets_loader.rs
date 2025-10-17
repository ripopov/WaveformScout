use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use rjets::{parse_trace, JetsTraceData, TraceData, TraceRecord, TraceEvent};
use std::collections::HashMap;

/// Convert clock cycles to picoseconds using clock frequency
fn clock_to_picoseconds(clk: i64, freq_mhz: f64) -> i64 {
    // clk cycles * (1/freq_mhz microseconds) * 1_000_000 ps/us
    // = clk * 1_000_000 / freq_mhz picoseconds
    (clk as f64 * 1_000_000.0 / freq_mhz) as i64
}

/// Serialize TraceRecord to pretty-printed JSON string
fn record_to_json(record: &dyn TraceRecord) -> String {
    let mut obj = serde_json::Map::new();
    obj.insert("id".to_string(), serde_json::Value::Number(record.id().into()));
    obj.insert("parent_id".to_string(), match record.parent_id() {
        Some(pid) => serde_json::Value::Number(pid.into()),
        None => serde_json::Value::Null,
    });
    obj.insert("name".to_string(), serde_json::Value::String(record.name().to_string()));
    obj.insert("clk".to_string(), serde_json::Value::Number(record.clk().into()));

    // Add data fields from the trait method
    let data_map = record.data();
    if !data_map.is_empty() {
        obj.insert("data".to_string(), serde_json::Value::Object(
            data_map.into_iter()
                .map(|(k, v)| (k, v))
                .collect()
        ));
    }

    if let Some(end_clk) = record.end_clk() {
        obj.insert("end_clk".to_string(), serde_json::Value::Number(end_clk.into()));
    }

    if let Some(duration) = record.duration() {
        obj.insert("duration".to_string(), serde_json::Value::Number(duration.into()));
    }

    serde_json::to_string_pretty(&obj).unwrap_or_else(|_| "{}".to_string())
}

/// Serialize TraceEvent to pretty-printed JSON string
fn event_to_json(event: &dyn TraceEvent) -> String {
    let mut obj = serde_json::Map::new();
    obj.insert("name".to_string(), serde_json::Value::String(event.name().to_string()));
    obj.insert("clk".to_string(), serde_json::Value::Number(event.clk().into()));

    // Add data fields from the trait method
    let data_map = event.data();
    if !data_map.is_empty() {
        obj.insert("data".to_string(), serde_json::Value::Object(
            data_map.into_iter()
                .map(|(k, v)| (k, v))
                .collect()
        ));
    }

    serde_json::to_string_pretty(&obj).unwrap_or_else(|_| "{}".to_string())
}

/// Annotation attached to a record (name/value pair)
#[pyclass]
#[derive(Clone)]
pub struct Annotation {
    name: String,
    value: serde_json::Value,
}

#[pymethods]
impl Annotation {
    #[getter]
    fn name(&self) -> String {
        self.name.clone()
    }

    #[getter]
    fn value(&self, py: Python) -> PyResult<PyObject> {
        python_from_json(py, &self.value)
    }
}

/// Timed annotation (event occurring within a record's time range)
#[pyclass]
#[derive(Clone)]
pub struct TimedAnnotation {
    name: String,
    time: u64,
    value: Option<serde_json::Value>,
}

#[pymethods]
impl TimedAnnotation {
    #[getter]
    fn name(&self) -> String {
        self.name.clone()
    }

    #[getter]
    fn time(&self) -> u64 {
        self.time
    }

    #[getter]
    fn value(&self, py: Python) -> PyResult<PyObject> {
        match &self.value {
            Some(val) => python_from_json(py, val),
            None => Ok(py.None()),
        }
    }
}

/// Python-exposed Record class
#[pyclass]
pub struct Record {
    pub(crate) id: u64,
    pub(crate) clk: i64,
    pub(crate) end_clk: Option<i64>,
    pub(crate) name: String,
    pub(crate) data_map: HashMap<String, serde_json::Value>,
    pub(crate) events_cache: Vec<(String, i64, Option<serde_json::Value>)>,
    pub(crate) clock_freq_mhz: f64,
}

#[pymethods]
impl Record {
    /// Record name (human-readable)
    fn name(&self) -> String {
        self.name.clone()
    }

    /// Start time in timescale units
    fn start_time(&self) -> u64 {
        clock_to_picoseconds(self.clk, self.clock_freq_mhz) as u64
    }

    /// End time in timescale units (None if ongoing or unbounded)
    fn end_time(&self) -> Option<u64> {
        self.end_clk.map(|end_clk| clock_to_picoseconds(end_clk, self.clock_freq_mhz) as u64)
    }

    /// Annotations attached to this record (name/value pairs)
    fn annotations(&self) -> Vec<Annotation> {
        let mut result = Vec::new();
        for (name, value) in &self.data_map {
            result.push(Annotation {
                name: name.clone(),
                value: value.clone(),
            });
        }
        result
    }

    /// Events occurring within this record's time range (timed annotations)
    fn events(&self) -> Vec<TimedAnnotation> {
        let mut result = Vec::new();
        for (name, clk, value) in &self.events_cache {
            result.push(TimedAnnotation {
                name: name.clone(),
                time: clock_to_picoseconds(*clk, self.clock_freq_mhz) as u64,
                value: value.clone(),
            });
        }
        result
    }
}

/// Convert serde_json::Value to Python object
#[allow(deprecated)]
fn python_from_json(py: Python, value: &serde_json::Value) -> PyResult<PyObject> {
    match value {
        serde_json::Value::Null => Ok(py.None()),
        serde_json::Value::Bool(b) => Ok(b.into_py(py)),
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                Ok(i.into_py(py))
            } else if let Some(f) = n.as_f64() {
                Ok(f.into_py(py))
            } else {
                Ok(py.None())
            }
        }
        serde_json::Value::String(s) => Ok(s.into_py(py)),
        serde_json::Value::Array(arr) => {
            let list = PyList::empty(py);
            for item in arr {
                list.append(python_from_json(py, item)?)?;
            }
            Ok(list.into())
        }
        serde_json::Value::Object(obj) => {
            let dict = PyDict::new(py);
            for (k, v) in obj {
                dict.set_item(k, python_from_json(py, v)?)?;
            }
            Ok(dict.into())
        }
    }
}

/// JETS hierarchy wrapper
pub(crate) struct JetsHierarchy {
    trace_data: JetsTraceData,
    clock_freq_mhz: f64,
    record_id_to_handle: HashMap<u64, usize>,
}

impl JetsHierarchy {
    pub fn new(trace_data: JetsTraceData) -> Result<Self, String> {
        // Extract clock frequency from header metadata
        let metadata = trace_data.metadata();
        let clock_freq_mhz = metadata.header_data()
            .get("clock_frequency_mhz")
            .and_then(|v| v.as_f64())
            .ok_or_else(|| "Missing clock_frequency_mhz in header metadata".to_string())?;

        // Build record ID to handle mapping
        let mut record_id_to_handle = HashMap::new();
        let mut next_handle = 0;

        fn collect_records(
            record: &dyn TraceRecord,
            id_map: &mut HashMap<u64, usize>,
            next_handle: &mut usize,
        ) {
            let handle = *next_handle;
            *next_handle += 1;
            id_map.insert(record.id(), handle);

            for child in record.children() {
                collect_records(child, id_map, next_handle);
            }
        }

        for root_id in trace_data.root_ids() {
            if let Some(root) = trace_data.get_record(root_id) {
                collect_records(root, &mut record_id_to_handle, &mut next_handle);
            }
        }

        Ok(JetsHierarchy {
            trace_data,
            clock_freq_mhz,
            record_id_to_handle,
        })
    }

    pub(crate) fn clock_freq_mhz(&self) -> f64 {
        self.clock_freq_mhz
    }

    pub(crate) fn get_root_ids(&self) -> Vec<u64> {
        self.trace_data.root_ids()
    }

    pub(crate) fn get_record_by_handle(&self, handle: usize) -> Option<&dyn TraceRecord> {
        // Find the record ID that corresponds to this handle
        let id = self.record_id_to_handle
            .iter()
            .find(|(_, &h)| h == handle)
            .map(|(&id, _)| id)?;

        self.trace_data.get_record(id)
    }

    pub(crate) fn get_record_by_id(&self, id: u64) -> Option<&dyn TraceRecord> {
        self.trace_data.get_record(id)
    }

    pub(crate) fn get_handle_by_id(&self, id: u64) -> Option<usize> {
        self.record_id_to_handle.get(&id).copied()
    }

    #[allow(dead_code)]
    pub(crate) fn create_record_wrapper(&self, record: &dyn TraceRecord) -> Record {
        let events_cache: Vec<_> = record.events()
            .iter()
            .map(|e| {
                let name = e.name().to_string();
                let clk = e.clk();
                let data = e.data();
                let value = if data.is_empty() {
                    None
                } else {
                    Some(serde_json::Value::Object(
                        data.into_iter().map(|(k, v)| (k, v)).collect()
                    ))
                };
                (name, clk, value)
            })
            .collect();

        Record {
            id: record.id(),
            clk: record.clk(),
            end_clk: record.end_clk(),
            name: record.name().to_string(),
            data_map: record.data(),
            events_cache,
            clock_freq_mhz: self.clock_freq_mhz,
        }
    }

    /// Generate signal changes for a record
    pub(crate) fn generate_signal_changes(&self, record: &dyn TraceRecord) -> Vec<(i64, String)> {
        let mut changes = Vec::new();

        // Initial value: "Z" at time 0 (outside record range)
        changes.push((0, "Z".to_string()));

        // Record start: transition to record JSON
        // Ensure start time is at least 1 to avoid collision with initial Z at time 0
        let start_time_ps = clock_to_picoseconds(record.clk(), self.clock_freq_mhz).max(1);
        changes.push((start_time_ps, record_to_json(record)));

        // Events (sorted by clock)
        let mut events: Vec<_> = record.events();
        events.sort_by_key(|e| e.clk());

        for event in &events {
            let event_time_ps = clock_to_picoseconds(event.clk(), self.clock_freq_mhz);
            changes.push((event_time_ps, event_to_json(*event)));
        }

        // End marker (if end_clk exists): transition back to "Z"
        if let Some(end_clk) = record.end_clk() {
            let end_time_ps = clock_to_picoseconds(end_clk, self.clock_freq_mhz);
            changes.push((end_time_ps + 1, "Z".to_string()));
        }

        changes
    }

    #[allow(dead_code)]
    pub(crate) fn file_format(&self) -> &str {
        "JETS"
    }

    #[allow(dead_code)]
    pub(crate) fn timescale_str(&self) -> String {
        "1ps".to_string()
    }

    pub(crate) fn date(&self) -> String {
        // Extract from metadata if available
        let metadata = self.trace_data.metadata();
        metadata.header_data()
            .get("date")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string()
    }

    pub(crate) fn version(&self) -> String {
        self.trace_data.metadata().version().to_string()
    }

    /// Get the maximum time in picoseconds based on capture_end_clk
    pub(crate) fn get_max_time(&self) -> Option<i64> {
        let metadata = self.trace_data.metadata();
        metadata.capture_end_clk()
            .map(|end_clk| clock_to_picoseconds(end_clk, self.clock_freq_mhz))
    }
}

/// Load JETS file and create hierarchy
pub(crate) fn load_jets_file(path: &str) -> Result<JetsHierarchy, String> {
    let trace_data = parse_trace(path)
        .map_err(|e| format!("Failed to parse JETS file: {}", e))?;

    JetsHierarchy::new(trace_data)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_clock_conversion() {
        // At 1830 MHz, 1 clock = 1_000_000 / 1830 ≈ 546.4 picoseconds
        let ps = clock_to_picoseconds(1, 1830.0);
        assert_eq!(ps, 546);

        // At 1000 MHz (1 GHz), 1 clock = 1_000_000 / 1000 = 1000 picoseconds
        let ps = clock_to_picoseconds(1, 1000.0);
        assert_eq!(ps, 1000);

        // At 1830 MHz, 2181 clocks = 2181 * 1_000_000 / 1830 ≈ 1,191,803 picoseconds
        let ps = clock_to_picoseconds(2181, 1830.0);
        assert_eq!(ps, 1_191_803);
    }
}
