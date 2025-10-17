mod convert;
mod jets_loader;
mod traits;
mod wellen_backend;
mod jets_backend;
// mod design_tree_model;  // Removed - DesignTreeModel no longer used

use std::sync::{Arc, Mutex};
use std::thread;

use convert::Mappable;
use crossbeam_channel::{unbounded, Receiver, Sender};
use num_bigint::BigUint;
use pyo3::types::PyInt;
use pyo3::{exceptions::PyRuntimeError, prelude::*};
use tokio::runtime::Runtime;

use traits::{SignalValue, TimeTableIdx};
use wellen::LoadOptions;

/// Opaque handle exposed to Python for signal lookups (0-based index).
pub type SignalHandle = usize;

/// Events emitted during async operations
enum AsyncEvent {
    HeaderStartLoad,
    HeaderLoaded,
    BodyStartLoad,
    BodyLoaded,
    SignalStartLoad(Vec<SignalHandle>),
    SignalLoaded(Vec<(SignalHandle, Arc<dyn traits::SignalTrait>)>),
    Error(String),
}

/// Request types for async operations
#[derive(Debug)]
enum AsyncRequest {
    LoadHeader(LoadOptions),
    LoadBody,
    LoadSignals(Vec<SignalHandle>),
    #[allow(dead_code)]
    Shutdown,
}

/// Shared state between main thread and worker
struct SharedState {
    file_path: String,
    backend: Mutex<Option<Box<dyn traits::WaveformTrait>>>,
    callback: Mutex<Option<PyObject>>,
}

pub trait PyErrExt<T> {
    fn toerr(self) -> PyResult<T>;
}

impl<T> PyErrExt<T> for wellen::Result<T> {
    fn toerr(self) -> PyResult<T> {
        self.map_err(|err| PyRuntimeError::new_err(err.to_string()))
    }
}

#[pymodule]
fn pyrox(py: Python, m: Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Var>()?;
    m.add_class::<VarIndex>()?;
    m.add_class::<VarIter>()?;
    m.add_class::<Waveform>()?;
    m.add_class::<Signal>()?;
    m.add_class::<SignalChangeIter>()?;
    m.add_class::<Hierarchy>()?;
    m.add_class::<Timescale>()?;
    m.add_class::<TimescaleUnit>()?;
    m.add_class::<QueryResult>()?;
    m.add_class::<TimeTable>()?;
    m.add_class::<jets_loader::Record>()?;
    m.add_class::<jets_loader::Annotation>()?;
    m.add_class::<jets_loader::TimedAnnotation>()?;
    // m.add_class::<design_tree_model::PyDesignTreeModel>()?;  // Removed - DesignTreeModel no longer used

    // Export SignalHandle as a type alias (using the int type object)
    m.add("SignalHandle", py.get_type::<pyo3::types::PyInt>())?;

    Ok(())
}

#[pyclass]
#[derive(Clone)]
pub(crate) struct Hierarchy(pub(crate) Arc<dyn traits::HierarchyTrait>);

#[pymethods]
impl Hierarchy {
    fn all_vars(&self) -> VarIter {
        let vars_iter = self.0.all_vars();
        let vars: Vec<Var> = vars_iter.map(|v| Var(v)).collect();
        VarIter(Box::new(vars.into_iter()))
    }

    fn top_scopes(&self) -> ScopeIter {
        let scopes_iter = self.0.top_scopes();
        let scopes: Vec<Scope> = scopes_iter.map(|s| Scope(s)).collect();
        ScopeIter(Box::new(scopes.into_iter()))
    }

    /// Find a variable by its hierarchical path.
    /// The path is a list where all elements except the last are scope names,
    /// and the last element is the variable's local name (which may contain dots).
    ///
    /// Args:
    ///     path: List of path segments [scope1, scope2, ..., var_name]
    ///
    /// Returns:
    ///     The Var if found, None otherwise
    fn find_var_by_path(&self, path: Vec<String>) -> Option<Var> {
        self.0.find_var_by_path(&path).map(|v| Var(v))
    }

    /// Get the first variable that references this signal (0-based index)
    fn get_var_by_signal_ref(&self, handle: SignalHandle) -> Option<Var> {
        self.0.get_var_by_signal_ref(handle).map(|v| Var(v))
    }

    /// Get the date metadata from the waveform file
    fn date(&self) -> String {
        self.0.date()
    }

    /// Get the version metadata from the waveform file
    fn version(&self) -> String {
        self.0.version()
    }

    /// Get the timescale metadata from the waveform file
    fn timescale(&self) -> Option<Timescale> {
        self.0.timescale().map(|(factor, unit)| {
            let unit_enum = match unit.as_str() {
                "fs" => wellen::TimescaleUnit::FemtoSeconds,
                "ps" => wellen::TimescaleUnit::PicoSeconds,
                "ns" => wellen::TimescaleUnit::NanoSeconds,
                "us" => wellen::TimescaleUnit::MicroSeconds,
                "ms" => wellen::TimescaleUnit::MilliSeconds,
                "s" => wellen::TimescaleUnit::Seconds,
                _ => wellen::TimescaleUnit::Unknown,
            };
            Timescale(wellen::Timescale::new(factor, unit_enum))
        })
    }

    /// Get the file format of the waveform file
    fn file_format(&self) -> String {
        self.0.file_format()
    }
}

#[pyclass]
pub(crate) struct Scope(pub(crate) Box<dyn traits::ScopeTrait>);

#[pymethods]
impl Scope {
    pub fn name(&self, hier: Bound<'_, Hierarchy>) -> String {
        self.0.name(hier.borrow().0.as_ref())
    }

    pub fn full_name(&self, hier: Bound<'_, Hierarchy>) -> String {
        self.0.full_name(hier.borrow().0.as_ref())
    }

    pub fn scope_type(&self) -> String {
        self.0.scope_type()
    }

    pub fn vars(&self, hier: Bound<'_, Hierarchy>) -> VarIter {
        let vars_iter = self.0.vars(hier.borrow().0.as_ref());
        let vars: Vec<Var> = vars_iter.map(|v| Var(v)).collect();
        VarIter(Box::new(vars.into_iter()))
    }

    pub fn scopes(&self, hier: Bound<'_, Hierarchy>) -> ScopeIter {
        let scopes_iter = self.0.scopes(hier.borrow().0.as_ref());
        let scopes: Vec<Scope> = scopes_iter.map(|s| Scope(s)).collect();
        ScopeIter(Box::new(scopes.into_iter()))
    }

    /// Check if this scope is a JETS record
    /// For non-JETS waveforms, always returns false
    pub fn is_record(&self) -> bool {
        self.0.is_record()
    }

    /// Get the Record object if this scope is a JETS record
    /// For non-JETS waveforms, always returns None
    /// Note: This API is deprecated and returns None until we refactor JETS record access
    pub fn record(&self) -> Option<jets_loader::Record> {
        // TODO: Refactor this API to work with the new trait-based Jets API
        // The old approach of exposing jets_loader::Record is no longer compatible
        None
    }
}

#[pyclass]
struct ScopeIter(Box<dyn Iterator<Item = Scope> + Send + Sync>);
#[pymethods]
impl ScopeIter {
    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }
    fn __next__(mut slf: PyRefMut<'_, Self>) -> Option<Scope> {
        slf.0.next()
    }
}

#[pyclass]
struct VarIndex(pub(crate) traits::VarIndex);

#[pymethods]
impl VarIndex {
    pub fn msb(&self) -> i64 {
        self.0.msb
    }
    pub fn lsb(&self) -> i64 {
        self.0.lsb
    }
}

#[pyclass]
pub(crate) struct Var(pub(crate) Box<dyn traits::VarTrait>);

#[pymethods]
impl Var {
    pub fn name(&self, hier: Bound<'_, Hierarchy>) -> String {
        self.0.name(hier.borrow().0.as_ref())
    }

    pub fn full_name(&self, hier: Bound<'_, Hierarchy>) -> String {
        self.0.full_name(hier.borrow().0.as_ref())
    }

    pub fn bitwidth(&self) -> Option<u32> {
        self.0.bitwidth()
    }

    pub fn var_type(&self) -> String {
        self.0.var_type()
    }

    pub fn enum_type(&self, hier: Bound<'_, Hierarchy>) -> Option<(String, Vec<(String, String)>)> {
        self.0.enum_type(hier.borrow().0.as_ref())
    }

    pub fn vhdl_type_name(&self, hier: Bound<'_, Hierarchy>) -> Option<String> {
        self.0.vhdl_type_name(hier.borrow().0.as_ref())
    }

    pub fn direction(&self) -> String {
        self.0.direction()
    }

    pub fn length(&self) -> Option<u32> {
        self.0.length()
    }

    pub fn is_real(&self) -> bool {
        self.0.is_real()
    }

    pub fn is_string(&self) -> bool {
        self.0.is_string()
    }

    pub fn is_bit_vector(&self) -> bool {
        self.0.is_bit_vector()
    }

    pub fn is_1bit(&self) -> bool {
        self.0.is_1bit()
    }

    pub fn index(&self) -> Option<VarIndex> {
        self.0.index().map(VarIndex)
    }

    /// Get the signal reference as an integer for internal use.
    /// Two vars with the same `signal_handle()` are aliases.
    /// Returns a 0-based `SignalHandle` for Python code.
    pub fn signal_handle(&self) -> SignalHandle {
        self.0.signal_handle()
    }

    /// Get the scope path for this variable as a list of scope names.
    /// The returned list contains scope names from root to immediate parent (excluding the variable name itself).
    /// Returns an empty list for top-level variables.
    pub fn scope_path(&self, hier: Bound<'_, Hierarchy>) -> Vec<String> {
        self.0.scope_path(hier.borrow().0.as_ref())
    }
}

// NOTE: Var equality and hashing are not implemented because:
// 1. Multiple Var objects can legitimately reference the same signal (aliasing)
// 2. Each iteration through the hierarchy creates new Var Python objects
// 3. We cannot reliably compare Var structs by their internal fields
//
// Instead, use:
// - signal_handle() to check if two Vars reference the same signal (var1.signal_handle() == var2.signal_handle())
// - full_name() to get a unique identifier for a Var

#[pyclass]
struct VarIter(Box<dyn Iterator<Item = Var> + Send + Sync>);

#[pymethods]
impl VarIter {
    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }
    fn __next__(mut slf: PyRefMut<'_, Self>) -> Option<Var> {
        slf.0.next()
    }
}

#[pyclass(name = "TimescaleUnit")]
#[derive(Clone)]
struct TimescaleUnit(pub(crate) wellen::TimescaleUnit);

#[pymethods]
impl TimescaleUnit {
    fn __str__(&self) -> String {
        match self.0 {
            wellen::TimescaleUnit::ZeptoSeconds => "zs".to_string(),
            wellen::TimescaleUnit::AttoSeconds => "as".to_string(),
            wellen::TimescaleUnit::FemtoSeconds => "fs".to_string(),
            wellen::TimescaleUnit::PicoSeconds => "ps".to_string(),
            wellen::TimescaleUnit::NanoSeconds => "ns".to_string(),
            wellen::TimescaleUnit::MicroSeconds => "us".to_string(),
            wellen::TimescaleUnit::MilliSeconds => "ms".to_string(),
            wellen::TimescaleUnit::Seconds => "s".to_string(),
            wellen::TimescaleUnit::Unknown => "unknown".to_string(),
        }
    }

    fn __repr__(&self) -> String {
        format!("TimescaleUnit.{}", self.__str__())
    }

    fn to_exponent(&self) -> Option<i8> {
        self.0.to_exponent()
    }
}

#[pyclass(name = "Timescale")]
#[derive(Clone)]
struct Timescale(pub(crate) wellen::Timescale);

#[pymethods]
impl Timescale {
    #[getter]
    fn factor(&self) -> u32 {
        self.0.factor
    }

    #[getter]
    fn unit(&self) -> TimescaleUnit {
        TimescaleUnit(self.0.unit)
    }

    fn __str__(&self) -> String {
        format!("{}{}", self.0.factor, TimescaleUnit(self.0.unit).__str__())
    }

    fn __repr__(&self) -> String {
        format!(
            "Timescale(factor={}, unit={})",
            self.0.factor,
            TimescaleUnit(self.0.unit).__repr__()
        )
    }
}

#[pyclass]
#[derive(Clone)]
struct TimeTable(Arc<dyn traits::TimeTableTrait>);

/// Converts python index to a usize
/// e.g. in python a[-1] is a common way to get an obj from a list
fn convert_py_idx(idx: isize, len: usize) -> usize {
    if idx < 0 {
        (idx + len as isize) as usize
    } else {
        idx as usize
    }
}

/// Convert a backend-agnostic SignalValue to a Python object
fn convert_signal_value_to_py<'a>(signal: SignalValue, py: Python<'a>) -> PyResult<Py<PyAny>> {
    match signal {
        SignalValue::Real(val) => Ok(val.into_pyobject(py).unwrap().into()),
        SignalValue::String(s) => Ok(s.into_pyobject(py).unwrap().into()),
        SignalValue::Scalar(scalar) => {
            // For single-bit scalars, return as "0" or "1" string (or x/z)
            let s = match scalar {
                traits::SignalScalar::Zero => "0",
                traits::SignalScalar::One => "1",
                traits::SignalScalar::X => "x",
                traits::SignalScalar::Z => "z",
            };
            Ok(s.into_pyobject(py).unwrap().into())
        }
        SignalValue::Integer(bytes, _bit_width) => {
            // Convert bytes to BigUint then to Python int
            // Bytes are in little-endian format
            let biguint = num_bigint::BigUint::from_bytes_le(&bytes);
            Ok(biguint.into_pyobject(py).unwrap().into())
        }
        SignalValue::Vector(bits) => {
            // Check if this is a 2-state vector (no X or Z values)
            let has_xz = bits.iter().any(|b| {
                matches!(b, traits::SignalScalar::X | traits::SignalScalar::Z)
            });

            if !has_xz {
                // 2-state vector: convert to BigUint then to Python int
                let mut biguint = num_bigint::BigUint::new(vec![]);
                for (i, bit) in bits.iter().enumerate() {
                    if matches!(bit, traits::SignalScalar::One) {
                        biguint.set_bit(i as u64, true);
                    }
                }
                Ok(biguint.into_pyobject(py).unwrap().into())
            } else {
                // Has X/Z values: convert to bit string
                let s: String = bits.iter().map(|bit| match bit {
                    traits::SignalScalar::Zero => '0',
                    traits::SignalScalar::One => '1',
                    traits::SignalScalar::X => 'x',
                    traits::SignalScalar::Z => 'z',
                }).collect();
                Ok(s.into_pyobject(py).unwrap().into())
            }
        }
        SignalValue::EnumVariant { name, index: _ } => {
            Ok(name.into_pyobject(py).unwrap().into())
        }
        SignalValue::Opaque(bytes) => {
            // Convert bytes to hex string
            let hex_string = bytes.iter().map(|b| format!("{:02x}", b)).collect::<String>();
            Ok(hex_string.into_pyobject(py).unwrap().into())
        }
        SignalValue::Unknown => {
            Ok("?".into_pyobject(py).unwrap().into())
        }
    }
}

#[pymethods]
impl TimeTable {
    fn __getitem__<'a>(&self, idx: isize, py: Python<'a>) -> PyResult<Option<Bound<'a, PyInt>>> {
        let len = self.0.len();
        let idx = convert_py_idx(idx, len);
        Ok(self
            .0
            .get(idx)
            .map(|val| val.into_pyobject(py).unwrap()))
    }

    fn __len__(&self) -> usize {
        self.0.len()
    }
}

/// Create a waveform backend based on file extension
fn create_waveform_backend(
    path: &str,
    opts: LoadOptions,
) -> Result<Box<dyn traits::WaveformTrait>, String> {
    // Detect file type from extension
    let path_lower = path.to_lowercase();

    if path_lower.ends_with(".jets") || path_lower.ends_with(".jsonl") {
        // JETS backend
        Ok(Box::new(jets_backend::JetsWaveform::new(
            path.to_string(),
            opts,
        )))
    } else if path_lower.ends_with(".vcd")
        || path_lower.ends_with(".fst")
        || path_lower.ends_with(".ghw")
    {
        // Wellen backend
        Ok(Box::new(wellen_backend::WellenWaveform::new(
            path.to_string(),
            opts,
        )))
    } else {
        Err(format!("Unsupported file format: {}", path))
    }
}

/// Worker thread function for async operations
fn async_worker(receiver: Receiver<AsyncRequest>, shared_state: Arc<SharedState>) {
    // Create a tokio runtime for this thread
    let runtime = Runtime::new().expect("Failed to create Tokio runtime");

    runtime.block_on(async {
        while let Ok(request) = receiver.recv() {
            match request {
                AsyncRequest::Shutdown => break,

                AsyncRequest::LoadHeader(_opts) => {
                    // Emit start event
                    emit_event(&shared_state, AsyncEvent::HeaderStartLoad);

                    // Acquire backend lock only during header loading (minimize lock holding time)
                    let result = {
                        let mut backend_guard = shared_state.backend.lock().unwrap();
                        backend_guard
                            .as_mut()
                            .ok_or_else(|| "Backend not initialized".to_string())
                            .and_then(|b| b.load_header())
                    }; // backend_guard dropped here

                    // Process results after releasing the lock
                    match result {
                        Ok(()) => emit_event(&shared_state, AsyncEvent::HeaderLoaded),
                        Err(e) => emit_event(&shared_state, AsyncEvent::Error(e)),
                    }
                }

                AsyncRequest::LoadBody => {
                    // Emit start event
                    emit_event(&shared_state, AsyncEvent::BodyStartLoad);

                    // Acquire backend lock only during body loading (minimize lock holding time)
                    let result = {
                        let mut backend_guard = shared_state.backend.lock().unwrap();
                        backend_guard
                            .as_mut()
                            .ok_or_else(|| "Backend not initialized".to_string())
                            .and_then(|b| b.load_body())
                    }; // backend_guard dropped here

                    // Process results after releasing the lock
                    match result {
                        Ok(()) => emit_event(&shared_state, AsyncEvent::BodyLoaded),
                        Err(e) => emit_event(&shared_state, AsyncEvent::Error(e)),
                    }
                }

                AsyncRequest::LoadSignals(handles) => {
                    // Emit start event
                    emit_event(&shared_state, AsyncEvent::SignalStartLoad(handles.clone()));

                    // Acquire backend lock only during signal loading (minimize lock holding time)
                    let result = {
                        let mut backend_guard = shared_state.backend.lock().unwrap();
                        if let Some(backend) = backend_guard.as_mut() {
                            match (backend.hierarchy(), backend.wave_source()) {
                                (Some(hier_trait), Some(source)) => {
                                    // Load signals while holding the lock (but in a minimal scope)
                                    Ok(source.load_signals(&handles, &*hier_trait))
                                }
                                (None, _) => Err("Hierarchy not loaded".to_string()),
                                (_, None) => Err("Wave source not available".to_string()),
                            }
                        } else {
                            Err("Backend not initialized".to_string())
                        }
                    }; // backend_guard dropped here

                    // Process results after releasing the lock
                    match result {
                        Ok(loaded_signals) => {
                            if !loaded_signals.is_empty() {
                                emit_event(&shared_state, AsyncEvent::SignalLoaded(loaded_signals));
                            }
                        }
                        Err(err_msg) => {
                            emit_event(&shared_state, AsyncEvent::Error(err_msg));
                        }
                    }
                }
            }
        }
    });
}

/// Helper to emit events to Python callback
#[allow(deprecated)]
fn emit_event(shared_state: &SharedState, event: AsyncEvent) {
    if let Some(callback) = shared_state.callback.lock().unwrap().as_ref() {
        Python::with_gil(|py| {
            // Convert event to Python dict
            let event_dict = match &event {
                AsyncEvent::HeaderStartLoad => {
                    let dict = pyo3::types::PyDict::new(py);
                    dict.set_item("type", "HeaderStartLoad").ok();
                    dict
                }
                AsyncEvent::HeaderLoaded => {
                    let dict = pyo3::types::PyDict::new(py);
                    dict.set_item("type", "HeaderLoaded").ok();
                    dict
                }
                AsyncEvent::BodyStartLoad => {
                    let dict = pyo3::types::PyDict::new(py);
                    dict.set_item("type", "BodyStartLoad").ok();
                    dict
                }
                AsyncEvent::BodyLoaded => {
                    let dict = pyo3::types::PyDict::new(py);
                    dict.set_item("type", "BodyLoaded").ok();
                    dict
                }
                AsyncEvent::SignalStartLoad(handles) => {
                    let dict = pyo3::types::PyDict::new(py);
                    dict.set_item("type", "SignalStartLoad").ok();
                    dict.set_item("handles", handles.clone()).ok();
                    dict
                }
                AsyncEvent::SignalLoaded(signals) => {
                    let dict = pyo3::types::PyDict::new(py);
                    dict.set_item("type", "SignalLoaded").ok();

                    // Create Python Signal objects from trait objects
                    let py_list = pyo3::types::PyList::empty(py);
                    for (handle, signal_trait) in signals.iter() {
                        // Signal is already a trait object - just wrap it
                        if let Ok(py_signal) = Bound::new(
                            py,
                            Signal {
                                backend: signal_trait.clone(),
                            },
                        ) {
                            let tuple = pyo3::types::PyTuple::new(py, &[handle.into_py(py), py_signal.into_py(py)]).unwrap();
                            py_list.append(tuple).ok();
                        }
                    }
                    dict.set_item("signals", py_list).ok();
                    dict
                }
                AsyncEvent::Error(msg) => {
                    let dict = pyo3::types::PyDict::new(py);
                    dict.set_item("type", "Error").ok();
                    dict.set_item("error", msg.clone()).ok();
                    dict
                }
            };

            // Call the Python callback
            let _ = callback.call1(py, (event_dict,));
        });
    }
}

#[pyclass]
struct Waveform {
    // All state is in shared_state for async access
    shared_state: Arc<SharedState>,
    request_sender: Option<Sender<AsyncRequest>>,
    _worker_handle: Option<thread::JoinHandle<()>>,
}

#[pymethods]
/// Top level waveform class that end users should use
/// The "egress" point from which all users can read waveforms
impl Waveform {
    #[new]
    #[pyo3(signature = (path, multi_threaded = true, remove_scopes_with_empty_name = false, load_header = true, load_body = true))]
    fn new(
        path: String,
        multi_threaded: bool,
        remove_scopes_with_empty_name: bool,
        load_header: bool,
        load_body: bool,
    ) -> PyResult<Self> {
        let opts = LoadOptions {
            multi_thread: multi_threaded,
            remove_scopes_with_empty_name,
        };

        // Create backend using factory function
        let mut backend = create_waveform_backend(&path, opts)
            .map_err(|e| PyRuntimeError::new_err(e))?;

        // Optionally load header and/or body
        if load_header {
            backend
                .load_header()
                .map_err(|e| PyRuntimeError::new_err(e))?;

            if load_body {
                backend
                    .load_body()
                    .map_err(|e| PyRuntimeError::new_err(e))?;
            }
        }

        // Create shared state
        let shared_state = Arc::new(SharedState {
            file_path: path.clone(),
            backend: Mutex::new(Some(backend)),
            callback: Mutex::new(None),
        });

        // Create async worker
        let (sender, receiver) = unbounded();
        let shared_state_clone = shared_state.clone();
        let worker_handle = thread::spawn(move || {
            async_worker(receiver, shared_state_clone);
        });

        Ok(Self {
            shared_state,
            request_sender: Some(sender),
            _worker_handle: Some(worker_handle),
        })
    }

    /// Load the waveform body if not already loaded
    fn load_body(&mut self) -> PyResult<()> {
        // Release GIL while loading body (heavy I/O operation)
        Python::with_gil(|py| {
            py.allow_threads(|| {
                // Lock backend only for the duration of the I/O operation
                let mut backend_guard = self.shared_state.backend.lock().unwrap();
                let backend = backend_guard
                    .as_mut()
                    .ok_or_else(|| "Backend not initialized".to_string())?;
                backend.load_body()
            })
        })
        .map_err(|err| PyRuntimeError::new_err(err))
    }

    /// Check if the body has been loaded
    fn body_loaded(&self) -> bool {
        // Check backend for body load status
        self.shared_state
            .backend
            .lock()
            .unwrap()
            .as_ref()
            .map_or(false, |b| b.body_loaded())
    }

    /// Check if the header has been loaded (for async API)
    fn header_loaded(&self) -> bool {
        // Check backend for header load status
        self.shared_state
            .backend
            .lock()
            .unwrap()
            .as_ref()
            .map_or(false, |b| b.header_loaded())
    }

    /// Get the hierarchy (returns None if not loaded)
    #[getter]
    fn hierarchy(&self) -> Option<Hierarchy> {
        self.shared_state
            .backend
            .lock()
            .unwrap()
            .as_ref()
            .and_then(|b| b.hierarchy())
            .map(|h| Hierarchy(h))
    }

    /// Set the async callback for receiving events
    #[pyo3(signature = (callback=None))]
    fn set_async_callback(&mut self, callback: Option<PyObject>) -> PyResult<()> {
        *self.shared_state.callback.lock().unwrap() = callback;
        Ok(())
    }

    /// Load header asynchronously
    #[pyo3(signature = (multi_threaded = true, remove_scopes_with_empty_name = false))]
    fn load_header_async(
        &self,
        multi_threaded: bool,
        remove_scopes_with_empty_name: bool,
    ) -> PyResult<()> {
        let opts = LoadOptions {
            multi_thread: multi_threaded,
            remove_scopes_with_empty_name,
        };

        if let Some(sender) = &self.request_sender {
            sender
                .send(AsyncRequest::LoadHeader(opts))
                .map_err(|_| PyRuntimeError::new_err("Failed to send async request"))?;
        } else {
            return Err(PyRuntimeError::new_err("Async worker not initialized"));
        }

        Ok(())
    }

    /// Load body asynchronously
    fn load_body_async(&self) -> PyResult<()> {
        if let Some(sender) = &self.request_sender {
            sender
                .send(AsyncRequest::LoadBody)
                .map_err(|_| PyRuntimeError::new_err("Failed to send async request"))?;
        } else {
            return Err(PyRuntimeError::new_err("Async worker not initialized"));
        }

        Ok(())
    }

    /// Load signals asynchronously
    fn load_signals_async(&self, handles: Vec<SignalHandle>) -> PyResult<()> {
        if let Some(sender) = &self.request_sender {
            sender
                .send(AsyncRequest::LoadSignals(handles))
                .map_err(|_| PyRuntimeError::new_err("Failed to send async request"))?;
        } else {
            return Err(PyRuntimeError::new_err("Async worker not initialized"));
        }

        Ok(())
    }

    /// Get the time table (returns None if body not loaded)
    #[getter]
    fn time_table(&self) -> Option<TimeTable> {
        self.shared_state
            .backend
            .lock()
            .unwrap()
            .as_ref()
            .and_then(|b| b.time_table())
            .map(|tt| TimeTable(tt))
    }

    /// Get signal by hierarchical path (accepts list of path segments).
    /// The path is a list where all elements except the last are scope names,
    /// and the last element is the variable's local name (which may contain dots).
    ///
    /// Args:
    ///     path_segments: List of path segments [scope1, scope2, ..., var_name]
    ///
    /// Returns:
    ///     The Signal if found, error otherwise
    fn get_signal_from_path<'py>(
        &mut self,
        path_segments: Vec<String>,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, Signal>> {
        if path_segments.is_empty() {
            return Err(PyRuntimeError::new_err("Path cannot be empty"));
        }

        // Get hierarchy from backend
        let backend_guard = self.shared_state.backend.lock().unwrap();
        let hier_trait = backend_guard
            .as_ref()
            .and_then(|b| b.hierarchy())
            .ok_or_else(|| PyRuntimeError::new_err("Hierarchy not loaded yet"))?;

        let var_trait = hier_trait
            .find_var_by_path(&path_segments)
            .ok_or(PyRuntimeError::new_err(format!(
                "No var at path {}",
                path_segments.join(".")
            )))?;

        // Use the signal handle from the var to get the signal
        let handle = var_trait.signal_handle();
        drop(backend_guard); // Release lock before calling get_signal_by_handle
        self.get_signal_by_handle(handle, py)
    }

    /// Load multiple signals at once using multiple threads
    fn load_signals<'py>(
        &mut self,
        vars: Vec<PyRef<'py, Var>>,
        py: Python<'py>,
    ) -> PyResult<Vec<Bound<'py, Signal>>> {
        // Convert vars to signal handles (before releasing GIL, as vars are Python objects)
        let handles: Vec<SignalHandle> = vars
            .iter()
            .map(|var| var.0.signal_handle())
            .collect();

        // Backend-agnostic path: release GIL and acquire backend lock only during signal loading
        let signals = py.allow_threads(|| -> Result<Vec<(SignalHandle, Arc<dyn traits::SignalTrait>)>, String> {
            let mut backend_guard = self.shared_state.backend.lock().unwrap();
            let backend = backend_guard
                .as_mut()
                .ok_or_else(|| "Backend not initialized".to_string())?;

            let hier_trait = backend
                .hierarchy()
                .ok_or_else(|| "Hierarchy not loaded yet".to_string())?;

            let wave_source = backend
                .wave_source()
                .ok_or_else(|| "Wave source not available".to_string())?;

            Ok(wave_source.load_signals(&handles, &*hier_trait))
        })
        .map_err(|e| PyRuntimeError::new_err(e))?;

        // Build a map from handle to Signal for quick lookup
        let mut signal_map: std::collections::HashMap<usize, Arc<dyn traits::SignalTrait>> = signals
            .into_iter()
            .collect();

        // Return signals in the same order as the input vars
        let mut result = Vec::new();
        for var in vars.iter() {
            let handle = var.0.signal_handle();
            if let Some(signal_trait) = signal_map.remove(&handle) {
                let signal = Bound::new(
                    py,
                    Signal {
                        backend: signal_trait,
                    },
                )?;
                result.push(signal);
            } else {
                return Err(PyRuntimeError::new_err("Signal not found for variable"));
            }
        }
        Ok(result)
    }




    /// Get a signal by its handle (0-based), always loads fresh
    fn get_signal_by_handle<'py>(
        &mut self,
        handle: SignalHandle,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, Signal>> {
        // Backend-agnostic path: release GIL and acquire backend lock only during signal loading
        let mut signals = py.allow_threads(|| -> Result<Vec<(SignalHandle, Arc<dyn traits::SignalTrait>)>, String> {
            let mut backend_guard = self.shared_state.backend.lock().unwrap();
            let backend = backend_guard
                .as_mut()
                .ok_or_else(|| "Backend not initialized".to_string())?;

            let hier_trait = backend
                .hierarchy()
                .ok_or_else(|| "Hierarchy not loaded yet".to_string())?;

            let wave_source = backend
                .wave_source()
                .ok_or_else(|| "Wave source not available".to_string())?;

            Ok(wave_source.load_signals(&[handle], &*hier_trait))
        })
        .map_err(|e| PyRuntimeError::new_err(e))?;

        if signals.is_empty() {
            return Err(PyRuntimeError::new_err("Failed to load signal"));
        }

        let (_handle, signal_trait) = signals.swap_remove(0);

        Bound::new(
            py,
            Signal {
                backend: signal_trait,
            },
        )
    }
}

#[pyclass]
/// Result of querying a signal at a specific time.
/// Provides information about the current value and next transition.
struct QueryResult {
    /// The value at the requested time
    #[pyo3(get)]
    value: Option<Py<PyAny>>,

    /// The actual time when the value change occurred (at or before query_time)
    #[pyo3(get)]
    actual_time: Option<wellen::Time>,

    /// Time table index of the next signal change, if any
    #[pyo3(get)]
    next_idx: Option<TimeTableIdx>,

    /// Timestamp of the next signal change, if any
    #[pyo3(get)]
    next_time: Option<wellen::Time>,
}

#[pyclass]
#[derive(Clone)]
struct Signal {
    backend: Arc<dyn traits::SignalTrait>,
}

#[pymethods]
impl Signal {
    pub fn value_at_time<'a>(
        &self,
        time: wellen::Time,
        py: Python<'a>,
    ) -> Option<Bound<'a, PyAny>> {
        self.backend.value_at_time(time)
            .and_then(|val| convert_signal_value_to_py(val, py).ok())
            .map(|py_val| py_val.into_bound(py))
    }

    pub fn value_at_idx<'a>(&self, idx: TimeTableIdx, py: Python<'a>) -> Option<Bound<'a, PyAny>> {
        self.backend.value_at_idx(idx)
            .and_then(|val| convert_signal_value_to_py(val, py).ok())
            .map(|py_val| py_val.into_bound(py))
    }

    pub fn all_changes(&self) -> SignalChangeIter {
        SignalChangeIter {
            changes: self.backend.all_changes().collect(),
            index: 0,
        }
    }

    /// Get an iterator over all signal changes after a specific time.
    ///
    /// Args:
    ///     start_time: Time after which to return changes
    ///
    /// Returns:
    ///     Iterator yielding tuples of (time, value) for each signal change after start_time
    pub fn all_changes_after(&self, start_time: wellen::Time) -> SignalChangeIter {
        SignalChangeIter {
            changes: self.backend.all_changes_after(start_time).collect(),
            index: 0,
        }
    }

    /// Query signal value and transition information at a specific time.
    /// This is useful for GUI rendering to detect transitions between pixels.
    ///
    /// Args:
    ///     query_time: Time to query the signal at
    ///
    /// Returns:
    ///     QueryResult containing value and transition information
    pub fn query_signal<'a>(
        &self,
        query_time: wellen::Time,
        py: Python<'a>,
    ) -> PyResult<Bound<'a, QueryResult>> {
        let result = self.backend.query_signal(query_time)
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        let value = convert_signal_value_to_py(result.value, py).ok();

        Bound::new(
            py,
            QueryResult {
                value,
                actual_time: Some(result.actual_time),
                next_idx: result.next_change.map(|_| 0), // Index not used in trait API
                next_time: result.next_change,
            },
        )
    }

    /// Check if two Signal objects reference the same underlying signal
    fn __eq__(&self, other: &Signal) -> bool {
        self.backend.signal_eq(other.backend.as_ref())
    }

    /// Compute hash based on the signal reference
    fn __hash__(&self) -> u64 {
        self.backend.signal_hash()
    }

    /// Compute global min/max range for analog signals across entire waveform.
    ///
    /// This iterates through all actual signal transitions (not sampling) to find
    /// the true min and max values. More accurate and faster than Python-side sampling.
    ///
    /// Args:
    ///     data_format: Format for interpreting integer values (0=unsigned, 1=signed, 2=hex, 3=bin, 4=float)
    ///     bit_width: Bit width of the signal for signed/unsigned conversion
    ///
    /// Returns:
    ///     Tuple of (min_value, max_value) as floats, or (0.0, 1.0) if no valid values found
    pub fn get_global_range(
        &self,
        data_format: u8,
        bit_width: u32,
        _py: Python<'_>,
    ) -> PyResult<(f64, f64)> {
        self.backend.get_global_range(data_format, bit_width)
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))
    }
}

#[pyclass]
/// Iterates across all changes -- the returned object is a tuple of (Time, Value)
struct SignalChangeIter {
    // Pre-collect changes to support len()
    changes: Vec<(traits::Time, traits::SignalValue)>,
    index: usize,
}

#[pymethods]
impl SignalChangeIter {
    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __next__<'a>(
        mut slf: PyRefMut<'_, Self>,
        python: Python<'a>,
    ) -> Option<(wellen::Time, Bound<'a, PyAny>)> {
        if slf.index >= slf.changes.len() {
            return None;
        }

        let (time, value) = slf.changes[slf.index].clone();
        slf.index += 1;

        convert_signal_value_to_py(value, python).ok()
            .map(|py_val| (time, py_val.into_bound(python)))
    }

    fn __len__(&self) -> usize {
        self.changes.len()
    }
}
