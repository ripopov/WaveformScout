use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use rjets::{parse_trace, TraceData, TraceRecord, TraceAnnotation, TraceEvent, TraceHeader};
use std::collections::HashMap;
use std::sync::Arc;

/// Convert clock cycles to picoseconds using clock frequency
fn clock_to_picoseconds(clk: i64, freq_mhz: f64) -> i64 {
    // clk cycles * (1/freq_mhz microseconds) * 1_000_000 ps/us
    // = clk * 1_000_000 / freq_mhz picoseconds
    (clk as f64 * 1_000_000.0 / freq_mhz) as i64
}

/// Serialize TraceRecord to pretty-printed JSON string
fn record_to_json(record: &TraceRecord) -> String {
    let mut obj = serde_json::Map::new();
    obj.insert("id".to_string(), serde_json::Value::String(record.id.clone()));
    obj.insert("parent_id".to_string(), match &record.parent_id {
        Some(pid) => serde_json::Value::String(pid.clone()),
        None => serde_json::Value::Null,
    });
    obj.insert("record_type".to_string(), serde_json::Value::String(record.record_type.clone()));
    obj.insert("clk".to_string(), serde_json::Value::Number(record.clk.into()));
    obj.insert("name".to_string(), serde_json::Value::String(record.name.clone()));

    if let Some(data) = &record.data {
        obj.insert("data".to_string(), data.clone());
    }

    if let Some(end_clk) = record.end_clk {
        obj.insert("end_clk".to_string(), serde_json::Value::Number(end_clk.into()));
    }

    if let Some(duration) = record.duration {
        obj.insert("duration".to_string(), serde_json::Value::Number(duration.into()));
    }

    serde_json::to_string_pretty(&obj).unwrap_or_else(|_| "{}".to_string())
}

/// Serialize TraceEvent to pretty-printed JSON string
fn event_to_json(event: &TraceEvent) -> String {
    let mut obj = serde_json::Map::new();
    obj.insert("name".to_string(), serde_json::Value::String(event.name.clone()));
    obj.insert("clk".to_string(), serde_json::Value::Number(event.clk.into()));

    if let Some(data) = &event.data {
        obj.insert("data".to_string(), data.clone());
    }

    serde_json::to_string_pretty(&obj).unwrap_or_else(|_| "{}".to_string())
}

/// Python-exposed Record class
#[pyclass]
#[derive(Clone)]
pub struct Record {
    pub(crate) inner: Arc<TraceRecord>,
    pub(crate) clock_freq_mhz: f64,
}

#[pymethods]
impl Record {
    #[getter]
    fn id(&self) -> String {
        self.inner.id.clone()
    }

    #[getter]
    fn parent_id(&self) -> Option<String> {
        self.inner.parent_id.clone()
    }

    #[getter]
    fn record_type(&self) -> String {
        self.inner.record_type.clone()
    }

    #[getter]
    fn clk(&self) -> i64 {
        self.inner.clk
    }

    #[getter]
    fn name(&self) -> String {
        self.inner.name.clone()
    }

    #[getter]
    fn data(&self, py: Python) -> PyResult<PyObject> {
        match &self.inner.data {
            Some(value) => {
                // Convert JSON value to Python dict/list/etc
                python_from_json(py, value)
            }
            None => Ok(py.None()),
        }
    }

    #[getter]
    fn end_clk(&self) -> Option<i64> {
        self.inner.end_clk
    }

    #[getter]
    fn duration(&self) -> Option<i64> {
        self.inner.duration
    }

    fn annotations(&self, py: Python) -> PyResult<PyObject> {
        let list = PyList::empty(py);
        for ann in &self.inner.annotations {
            let dict = PyDict::new(py);
            dict.set_item("name", &ann.name)?;
            dict.set_item("data", python_from_json(py, &ann.data)?)?;
            list.append(dict)?;
        }
        Ok(list.into())
    }

    fn events(&self, py: Python) -> PyResult<PyObject> {
        let list = PyList::empty(py);
        for evt in &self.inner.events {
            let dict = PyDict::new(py);
            dict.set_item("name", &evt.name)?;
            dict.set_item("clk", evt.clk)?;
            if let Some(data) = &evt.data {
                dict.set_item("data", python_from_json(py, data)?)?;
            } else {
                dict.set_item("data", py.None())?;
            }
            list.append(dict)?;
        }
        Ok(list.into())
    }

    fn children(&self) -> Vec<Record> {
        self.inner.children.iter()
            .map(|child| Record {
                inner: Arc::new(child.clone()),
                clock_freq_mhz: self.clock_freq_mhz,
            })
            .collect()
    }

    fn start_time_ps(&self) -> i64 {
        clock_to_picoseconds(self.inner.clk, self.clock_freq_mhz)
    }

    fn end_time_ps(&self) -> Option<i64> {
        self.inner.end_clk.map(|end_clk| clock_to_picoseconds(end_clk, self.clock_freq_mhz))
    }
}

/// Convert serde_json::Value to Python object
fn python_from_json(py: Python, value: &serde_json::Value) -> PyResult<PyObject> {
    match value {
        serde_json::Value::Null => Ok(py.None()),
        serde_json::Value::Bool(b) => Ok(b.to_object(py)),
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                Ok(i.to_object(py))
            } else if let Some(f) = n.as_f64() {
                Ok(f.to_object(py))
            } else {
                Ok(py.None())
            }
        }
        serde_json::Value::String(s) => Ok(s.to_object(py)),
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
    trace_data: Arc<TraceData>,
    clock_freq_mhz: f64,
    record_id_to_handle: HashMap<String, usize>,
    handle_to_record: HashMap<usize, Arc<TraceRecord>>,
}

impl JetsHierarchy {
    pub fn new(trace_data: TraceData) -> Result<Self, String> {
        // Extract clock frequency from header metadata
        let clock_freq_mhz = trace_data.header.metadata
            .get("clock_frequency_mhz")
            .and_then(|v| v.as_f64())
            .ok_or_else(|| "Missing clock_frequency_mhz in header metadata".to_string())?;

        // Build record ID to handle mapping
        let mut record_id_to_handle = HashMap::new();
        let mut handle_to_record = HashMap::new();
        let mut next_handle = 0;

        fn collect_records(
            record: &TraceRecord,
            id_map: &mut HashMap<String, usize>,
            handle_map: &mut HashMap<usize, Arc<TraceRecord>>,
            next_handle: &mut usize,
        ) {
            let handle = *next_handle;
            *next_handle += 1;
            id_map.insert(record.id.clone(), handle);
            handle_map.insert(handle, Arc::new(record.clone()));

            for child in &record.children {
                collect_records(child, id_map, handle_map, next_handle);
            }
        }

        for root in &trace_data.roots {
            collect_records(root, &mut record_id_to_handle, &mut handle_to_record, &mut next_handle);
        }

        Ok(JetsHierarchy {
            trace_data: Arc::new(trace_data),
            clock_freq_mhz,
            record_id_to_handle,
            handle_to_record,
        })
    }

    pub(crate) fn clock_freq_mhz(&self) -> f64 {
        self.clock_freq_mhz
    }

    pub(crate) fn top_records(&self) -> &[TraceRecord] {
        &self.trace_data.roots
    }

    pub(crate) fn get_record_by_handle(&self, handle: usize) -> Option<Arc<TraceRecord>> {
        self.handle_to_record.get(&handle).cloned()
    }

    pub(crate) fn get_handle_by_id(&self, id: &str) -> Option<usize> {
        self.record_id_to_handle.get(id).copied()
    }

    pub(crate) fn create_record_wrapper(&self, record: &TraceRecord) -> Record {
        Record {
            inner: Arc::new(record.clone()),
            clock_freq_mhz: self.clock_freq_mhz,
        }
    }

    /// Generate signal changes for a record
    pub(crate) fn generate_signal_changes(&self, record: &TraceRecord) -> Vec<(i64, String)> {
        let mut changes = Vec::new();

        // Initial value: "Z" at time 0 (outside record range)
        changes.push((0, "Z".to_string()));

        // Record start: transition to record JSON
        // Ensure start time is at least 1 to avoid collision with initial Z at time 0
        let start_time_ps = clock_to_picoseconds(record.clk, self.clock_freq_mhz).max(1);
        changes.push((start_time_ps, record_to_json(record)));

        // Events (sorted by clock)
        let mut events = record.events.clone();
        events.sort_by_key(|e| e.clk);

        for event in &events {
            let event_time_ps = clock_to_picoseconds(event.clk, self.clock_freq_mhz);
            changes.push((event_time_ps, event_to_json(event)));
        }

        // End marker (if end_clk exists): transition back to "Z"
        if let Some(end_clk) = record.end_clk {
            let end_time_ps = clock_to_picoseconds(end_clk, self.clock_freq_mhz);
            changes.push((end_time_ps + 1, "Z".to_string()));
        }

        changes
    }

    pub(crate) fn file_format(&self) -> &str {
        "JETS"
    }

    pub(crate) fn timescale_str(&self) -> String {
        "1ps".to_string()
    }

    pub(crate) fn date(&self) -> String {
        // Extract from metadata if available
        self.trace_data.header.metadata
            .get("date")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string()
    }

    pub(crate) fn version(&self) -> String {
        self.trace_data.header.version.clone()
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
