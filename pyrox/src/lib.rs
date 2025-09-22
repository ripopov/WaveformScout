mod convert;
// mod design_tree_model;  // Removed - DesignTreeModel no longer used

use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
use std::thread;

use convert::Mappable;
use crossbeam_channel::{unbounded, Receiver, Sender};
use num_bigint::BigUint;
use pyo3::types::PyInt;
use pyo3::{exceptions::PyRuntimeError, prelude::*};
use rustc_hash::FxHashMap;
use tokio::runtime::Runtime;

use wellen::{
    viewers::{self, ReadBodyContinuation},
    LoadOptions, ScopeType, SignalRef, SignalValue, TimeTableIdx,
};

/// Opaque handle exposed to Python for signal lookups (0-based index).
pub type SignalHandle = usize;

/// Events emitted during async operations
#[derive(Debug, Clone)]
enum AsyncEvent {
    HeaderStartLoad,
    HeaderLoaded,
    BodyStartLoad,
    BodyLoaded,
    SignalStartLoad(Vec<SignalHandle>),
    SignalLoaded(Vec<SignalHandle>),
    Error(String),
}

/// Request types for async operations
#[derive(Debug)]
enum AsyncRequest {
    LoadHeader(LoadOptions),
    LoadBody,
    LoadSignals(Vec<SignalHandle>),
    Shutdown,
}

/// Shared state between main thread and worker
struct SharedState {
    file_path: String,
    hierarchy: Mutex<Option<Arc<wellen::Hierarchy>>>,
    wave_source: Mutex<Option<wellen::SignalSource>>,
    time_table: Mutex<Option<Arc<wellen::TimeTable>>>,
    body_continuation: Mutex<Option<Box<ReadBodyContinuation<std::io::BufReader<std::fs::File>>>>>,
    signal_cache: Mutex<FxHashMap<SignalHandle, Arc<wellen::Signal>>>,
    python_signal_cache: Mutex<FxHashMap<SignalHandle, Py<Signal>>>,
    callback: Mutex<Option<PyObject>>,
    header_loaded: AtomicBool,
    body_loaded: AtomicBool,
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
    // m.add_class::<design_tree_model::PyDesignTreeModel>()?;  // Removed - DesignTreeModel no longer used

    // Export SignalHandle as a type alias (using the int type object)
    m.add("SignalHandle", py.get_type::<pyo3::types::PyInt>())?;

    Ok(())
}

#[pyclass]
#[derive(Clone)]
pub(crate) struct Hierarchy(pub(crate) Arc<wellen::Hierarchy>);

#[pymethods]
impl Hierarchy {
    fn all_vars(&self) -> VarIter {
        // Return ALL variables from all scopes, including aliases
        let hier = self.0.clone();
        let mut all_vars = Vec::new();

        // Recursively collect variables from all scopes
        fn collect_vars(
            scope_ref: wellen::ScopeRef,
            hier: &wellen::Hierarchy,
            vars: &mut Vec<wellen::Var>,
        ) {
            // Add variables from this scope
            for var_ref in hier[scope_ref].vars(hier) {
                vars.push(hier[var_ref].clone());
            }
            // Recurse into child scopes
            for child_ref in hier[scope_ref].scopes(hier) {
                collect_vars(child_ref, hier, vars);
            }
        }

        // Start from all top-level scopes
        for scope_ref in hier.scopes() {
            collect_vars(scope_ref, &hier, &mut all_vars);
        }

        VarIter(Box::new(all_vars.into_iter().map(Var)))
    }

    fn top_scopes(&self) -> ScopeIter {
        ScopeIter(Box::new({
            let hier = self.0.clone();
            hier.scopes()
                .map(|val| Scope(hier[val].clone()))
                .collect::<Vec<_>>()
                .into_iter()
        }))
    }

    /// Find a variable by its full hierarchical name
    fn find_var_by_full_name(&self, name: &str) -> Option<Var> {
        // Parse the dotted path
        let parts: Vec<&str> = name.split('.').collect();
        if parts.is_empty() {
            return None;
        }

        // Split into scope path and variable name
        let (path, var_name) = if parts.len() == 1 {
            // Just a variable name at top level
            (&[][..], parts[0])
        } else {
            // Scope path + variable name
            (&parts[0..parts.len() - 1], parts[parts.len() - 1])
        };

        // Use the hierarchy's lookup_var method (expects &str references)
        self.0
            .lookup_var(path, &var_name)
            .map(|var_ref| Var(self.0[var_ref].clone()))
    }

    /// Get the first variable that references this signal (0-based index)
    fn get_var_by_signal_ref(&self, handle: SignalHandle) -> Option<Var> {
        // Convert 0-based handle to wellen SignalRef (which is 1-based internally)
        let wellen_ref = wellen::SignalRef::from_index(handle)?;
        self.0
            .get_var_by_signal_ref(wellen_ref)
            .map(|var_ref| Var(self.0[var_ref].clone()))
    }

    /// Get the date metadata from the waveform file
    fn date(&self) -> String {
        self.0.date().to_string()
    }

    /// Get the version metadata from the waveform file
    fn version(&self) -> String {
        self.0.version().to_string()
    }

    /// Get the timescale metadata from the waveform file
    fn timescale(&self) -> Option<Timescale> {
        self.0.timescale().map(Timescale)
    }

    /// Get the file format of the waveform file
    fn file_format(&self) -> String {
        match self.0.file_format() {
            wellen::FileFormat::Vcd => "VCD".to_string(),
            wellen::FileFormat::Fst => "FST".to_string(),
            wellen::FileFormat::Ghw => "GHW".to_string(),
            wellen::FileFormat::Unknown => "Unknown".to_string(),
        }
    }
}

#[pyclass]
pub(crate) struct Scope(pub(crate) wellen::Scope);

#[pymethods]
impl Scope {
    pub fn name(&self, hier: Bound<'_, Hierarchy>) -> String {
        self.0.name(&hier.borrow().0).to_string()
    }
    pub fn full_name(&self, hier: Bound<'_, Hierarchy>) -> String {
        self.0.full_name(&hier.borrow().0).to_string()
    }

    pub fn scope_type(&self) -> String {
        match self.0.scope_type() {
            ScopeType::Module => "module",
            ScopeType::Task => "task",
            ScopeType::Function => "function",
            ScopeType::Begin => "begin",
            ScopeType::Fork => "fork",
            ScopeType::Generate => "generate",
            ScopeType::Struct => "struct",
            ScopeType::Union => "union",
            ScopeType::Class => "class",
            ScopeType::Interface => "interface",
            ScopeType::Package => "package",
            ScopeType::Program => "program",
            ScopeType::VhdlArchitecture => "vhdl_architecture",
            ScopeType::VhdlProcedure => "vhdl_procedure",
            ScopeType::VhdlFunction => "vhdl_function",
            ScopeType::VhdlRecord => "vhdl_record",
            ScopeType::VhdlProcess => "vhdl_process",
            ScopeType::VhdlBlock => "vhdl_block",
            ScopeType::VhdlForGenerate => "vhdl_for_generate",
            ScopeType::VhdlIfGenerate => "vhdl_if_generate",
            ScopeType::VhdlGenerate => "vhdl_generate",
            ScopeType::VhdlPackage => "vhdl_package",
            ScopeType::GhwGeneric => "ghw_generic",
            ScopeType::VhdlArray => "vhdl_array",
            ScopeType::Unknown => "unknown",
            _ => "unknown", // `ScopeType` is marked as non-exhaustive
        }
        .to_string()
    }

    pub fn vars(&self, hier: Bound<'_, Hierarchy>) -> VarIter {
        let locahier = hier.borrow().clone();
        let scope = self.0.clone();

        //TODO: optimize me! need to rewrite the logic from `HierarchyItemIdIterator` to use
        // Arc<Hierarchy> instead of lifetimes
        //
        // This is because python does not like lifetimes :)
        VarIter(Box::new({
            let hier = locahier.clone();
            scope
                .vars(&hier.0)
                .map(|val| Var(hier.0[val].clone()))
                .collect::<Vec<_>>()
                .into_iter()
        }))
    }

    pub fn scopes(&self, hier: Bound<'_, Hierarchy>) -> ScopeIter {
        let locahier = hier.borrow().clone();
        let scope = self.0.clone();

        //TODO: optimize me! need to rewrite the logic from `HierarchyItemIdIterator` to use
        // Arc<Hierarchy> instead of lifetimes
        //
        // This is because python does not like lifetimes :)
        ScopeIter(Box::new({
            let hier = locahier.clone();
            scope
                .scopes(&hier.0)
                .map(|val| Scope(hier.0[val].clone()))
                .collect::<Vec<_>>()
                .into_iter()
        }))
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
struct VarIndex(pub(crate) wellen::VarIndex);

#[pymethods]
impl VarIndex {
    pub fn msb(&self) -> i64 {
        self.0.msb()
    }
    pub fn lsb(&self) -> i64 {
        self.0.lsb()
    }
}

#[pyclass]
pub(crate) struct Var(pub(crate) wellen::Var);

#[pymethods]
impl Var {
    pub fn name(&self, hier: Bound<'_, Hierarchy>) -> String {
        self.0.name(&hier.borrow().0).to_string()
    }
    pub fn full_name(&self, hier: Bound<'_, Hierarchy>) -> String {
        self.0.full_name(&hier.borrow().0).to_string()
    }
    pub fn bitwidth(&self) -> Option<u32> {
        self.0.length()
    }
    pub fn var_type(&self) -> String {
        format!("{:?}", self.0.var_type())
    }
    pub fn enum_type(&self, hier: Bound<'_, Hierarchy>) -> Option<(String, Vec<(String, String)>)> {
        self.0.enum_type(&hier.borrow().0).map(|(name, values)| {
            (
                name.to_string(),
                values
                    .into_iter()
                    .map(|(k, v)| (k.to_string(), v.to_string()))
                    .collect(),
            )
        })
    }
    pub fn vhdl_type_name(&self, hier: Bound<'_, Hierarchy>) -> Option<String> {
        self.0
            .vhdl_type_name(&hier.borrow().0)
            .map(|s| s.to_string())
    }
    pub fn direction(&self) -> String {
        format!("{:?}", self.0.direction())
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
        self.0.signal_ref().index()
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
struct TimeTable(Arc<wellen::TimeTable>);

/// Converts python index to a usize
/// e.g. in python a[-1] is a common way to get an obj from a list
fn convert_py_idx(idx: isize, len: usize) -> usize {
    if idx < 0 {
        (idx + len as isize) as usize
    } else {
        idx as usize
    }
}

/// Convert a signal value to a Python object
fn convert_signal_value_to_py<'a>(signal: SignalValue, py: Python<'a>) -> PyResult<Py<PyAny>> {
    match signal {
        SignalValue::Real(inner) => Ok(inner.into_pyobject(py).unwrap().into()),
        SignalValue::String(str) => Ok(str.into_pyobject(py).unwrap().into()),
        _ => match BigUint::try_from_signal(signal) {
            // If this signal is 2bits, this function will return an int
            Some(number) => Ok(number.into_pyobject(py).unwrap().into()),
            // if this signal is not 2bits (e.g. it contains z,x, etc) then this function
            // will return a string
            None => signal
                .to_bit_string()
                .map(|val| val.into_pyobject(py).unwrap().into())
                .ok_or_else(|| PyRuntimeError::new_err("Failed to convert signal value")),
        },
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
            .cloned()
            .map(|val| val.into_pyobject(py).unwrap()))
    }

    fn __len__(&self) -> usize {
        self.0.len()
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

                AsyncRequest::LoadHeader(opts) => {
                    // Emit start event
                    emit_event(&shared_state, AsyncEvent::HeaderStartLoad);

                    // Get the file path from shared state
                    let path = shared_state.file_path.clone();

                    // Load header
                    match viewers::read_header_from_file(&path, &opts) {
                        Ok(header_result) => {
                            let hier = Arc::new(header_result.hierarchy);

                            // Update shared state
                            *shared_state.hierarchy.lock().unwrap() = Some(hier.clone());
                            *shared_state.body_continuation.lock().unwrap() =
                                Some(Box::new(header_result.body));
                            shared_state.header_loaded.store(true, Ordering::Relaxed);

                            // Emit loaded event
                            emit_event(&shared_state, AsyncEvent::HeaderLoaded);
                        }
                        Err(e) => {
                            emit_event(&shared_state, AsyncEvent::Error(e.to_string()));
                        }
                    }
                }

                AsyncRequest::LoadBody => {
                    // Emit start event
                    emit_event(&shared_state, AsyncEvent::BodyStartLoad);

                    // Get body continuation
                    let body_cont = shared_state.body_continuation.lock().unwrap().take();
                    if let Some(body_cont) = body_cont {
                        let hierarchy = shared_state.hierarchy.lock().unwrap().clone();
                        if let Some(hier) = hierarchy {
                            match viewers::read_body(*body_cont, &hier, None) {
                                Ok(body) => {
                                    // Update shared state
                                    *shared_state.wave_source.lock().unwrap() = Some(body.source);
                                    *shared_state.time_table.lock().unwrap() =
                                        Some(Arc::new(body.time_table));
                                    shared_state.body_loaded.store(true, Ordering::Relaxed);

                                    // Clear signal cache
                                    shared_state.signal_cache.lock().unwrap().clear();
                                    shared_state.python_signal_cache.lock().unwrap().clear();

                                    // Emit loaded event
                                    emit_event(&shared_state, AsyncEvent::BodyLoaded);
                                }
                                Err(e) => {
                                    emit_event(&shared_state, AsyncEvent::Error(e.to_string()));
                                }
                            }
                        } else {
                            emit_event(
                                &shared_state,
                                AsyncEvent::Error("Hierarchy not loaded".to_string()),
                            );
                        }
                    } else {
                        emit_event(
                            &shared_state,
                            AsyncEvent::Error("Body continuation not available".to_string()),
                        );
                    }
                }

                AsyncRequest::LoadSignals(handles) => {
                    // Emit start event
                    emit_event(&shared_state, AsyncEvent::SignalStartLoad(handles.clone()));

                    // Check if wave source and hierarchy are available
                    let has_source = shared_state.wave_source.lock().unwrap().is_some();
                    let hierarchy = shared_state.hierarchy.lock().unwrap().clone();

                    if has_source && hierarchy.is_some() {
                        let mut loaded_handles = Vec::new();

                        // Load signals one by one
                        for handle in handles.iter() {
                            // Check if already cached
                            let is_cached = shared_state
                                .signal_cache
                                .lock()
                                .unwrap()
                                .contains_key(handle);

                            if !is_cached {
                                // Load signal - need to access wave_source for each signal
                                let signal_ref = SignalRef::from_index(*handle).unwrap();

                                // We need to load signals within the lock scope
                                if let Some(source) = &mut *shared_state.wave_source.lock().unwrap()
                                {
                                    if let Some(hier) = &hierarchy {
                                        let signals =
                                            source.load_signals(&[signal_ref], hier, true);
                                        if let Some((_ref, sig)) = signals.into_iter().next() {
                                            shared_state
                                                .signal_cache
                                                .lock()
                                                .unwrap()
                                                .insert(*handle, Arc::new(sig));
                                            loaded_handles.push(*handle);
                                        }
                                    }
                                }
                            }
                        }

                        // Emit loaded event with actual loaded handles
                        if !loaded_handles.is_empty() {
                            emit_event(&shared_state, AsyncEvent::SignalLoaded(loaded_handles));
                        }
                    } else {
                        emit_event(
                            &shared_state,
                            AsyncEvent::Error("Wave source or hierarchy not loaded".to_string()),
                        );
                    }
                }
            }
        }
    });
}

/// Helper to emit events to Python callback
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
                AsyncEvent::SignalLoaded(handles) => {
                    let dict = pyo3::types::PyDict::new(py);
                    dict.set_item("type", "SignalLoaded").ok();
                    dict.set_item("handles", handles.clone()).ok();
                    dict
                }
                AsyncEvent::Error(msg) => {
                    let dict = pyo3::types::PyDict::new(py);
                    dict.set_item("type", "Error").ok();
                    dict.set_item("message", msg.clone()).ok();
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

        // Create shared state based on what we're loading
        let shared_state = if load_header {
            let header_result = viewers::read_header_from_file(path.as_str(), &opts).toerr()?;
            let hier = Arc::new(header_result.hierarchy);

            if load_body {
                let body = viewers::read_body(header_result.body, &hier, None)
                    .map_err(|err| PyRuntimeError::new_err(err.to_string()))?;

                // Create shared state with loaded header and body
                Arc::new(SharedState {
                    file_path: path.clone(),
                    hierarchy: Mutex::new(Some(hier)),
                    wave_source: Mutex::new(Some(body.source)),
                    time_table: Mutex::new(Some(Arc::new(body.time_table))),
                    body_continuation: Mutex::new(None),
                    signal_cache: Mutex::new(FxHashMap::default()),
                    python_signal_cache: Mutex::new(FxHashMap::default()),
                    callback: Mutex::new(None),
                    header_loaded: AtomicBool::new(true),
                    body_loaded: AtomicBool::new(true),
                })
            } else {
                // Create shared state with header only
                Arc::new(SharedState {
                    file_path: path.clone(),
                    hierarchy: Mutex::new(Some(hier)),
                    wave_source: Mutex::new(None),
                    time_table: Mutex::new(None),
                    body_continuation: Mutex::new(Some(Box::new(header_result.body))),
                    signal_cache: Mutex::new(FxHashMap::default()),
                    python_signal_cache: Mutex::new(FxHashMap::default()),
                    callback: Mutex::new(None),
                    header_loaded: AtomicBool::new(true),
                    body_loaded: AtomicBool::new(false),
                })
            }
        } else {
            // Nothing loaded - store path for later async loading
            Arc::new(SharedState {
                file_path: path,
                hierarchy: Mutex::new(None),
                wave_source: Mutex::new(None),
                time_table: Mutex::new(None),
                body_continuation: Mutex::new(None),
                signal_cache: Mutex::new(FxHashMap::default()),
                python_signal_cache: Mutex::new(FxHashMap::default()),
                callback: Mutex::new(None),
                header_loaded: AtomicBool::new(false),
                body_loaded: AtomicBool::new(false),
            })
        };

        // Create channel for async requests
        let (sender, receiver) = unbounded();

        // Spawn worker thread
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
        // Check if body is already loaded
        if self.shared_state.body_loaded.load(Ordering::Relaxed) {
            return Ok(());
        }

        // Get body continuation from shared state
        let body_continuation = self
            .shared_state
            .body_continuation
            .lock()
            .unwrap()
            .take()
            .ok_or_else(|| {
                PyRuntimeError::new_err("Body continuation already consumed or not available")
            })?;

        // Release GIL while reading body (heavy I/O operation)
        let hierarchy = self.get_hierarchy_internal()?;
        let body = Python::with_gil(|py| {
            py.allow_threads(|| viewers::read_body(*body_continuation, &hierarchy, None))
        })
        .map_err(|err| PyRuntimeError::new_err(err.to_string()))?;

        // Update shared state
        *self.shared_state.wave_source.lock().unwrap() = Some(body.source);
        *self.shared_state.time_table.lock().unwrap() = Some(Arc::new(body.time_table));
        self.shared_state.body_loaded.store(true, Ordering::Relaxed);

        // Clear signal cache when body is loaded
        self.shared_state.signal_cache.lock().unwrap().clear();
        self.shared_state
            .python_signal_cache
            .lock()
            .unwrap()
            .clear();

        Ok(())
    }

    /// Check if the body has been loaded
    fn body_loaded(&self) -> bool {
        // Check the shared state for async operations
        self.shared_state.body_loaded.load(Ordering::Relaxed)
    }

    /// Check if the header has been loaded (for async API)
    fn header_loaded(&self) -> bool {
        self.shared_state.header_loaded.load(Ordering::Relaxed)
    }

    /// Get the hierarchy (returns None if not loaded)
    #[getter]
    fn hierarchy(&self) -> Option<Hierarchy> {
        self.shared_state
            .hierarchy
            .lock()
            .unwrap()
            .as_ref()
            .map(|h| Hierarchy(h.clone()))
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
        let shared_tt = self.shared_state.time_table.lock().unwrap();
        shared_tt.as_ref().map(|tt| TimeTable(tt.clone()))
    }

    /// Assumes a dotted signal
    fn get_signal_from_path<'py>(
        &mut self,
        abs_hierarchy_path: String,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, Signal>> {
        let path: Vec<&str> = abs_hierarchy_path.split('.').collect();

        let (path, names) = (
            &path[0..path.len() - 1],
            path.last()
                .ok_or(PyRuntimeError::new_err("Path could not be parsed!")),
        );
        let hierarchy = self.get_hierarchy_internal()?;
        let maybe_var = hierarchy
            .lookup_var(path, names?)
            .ok_or(PyRuntimeError::new_err(format!(
                "No var at path {abs_hierarchy_path}"
            )))?;
        let var = &hierarchy[maybe_var];
        // Use the signal handle from the var to get the signal
        let handle = Var(var.clone()).signal_handle();
        self.get_signal_by_handle(handle, py)
    }

    /// Helper function to load signals and preserve input order
    fn load_signals_impl<'py>(
        &mut self,
        vars: Vec<PyRef<'py, Var>>,
        py: Python<'py>,
        multithreaded: bool,
    ) -> PyResult<Vec<Bound<'py, Signal>>> {
        // Ensure body is loaded
        self.load_body()?;

        // Get wave_source and time_table from shared state
        let mut wave_source_guard = self.shared_state.wave_source.lock().unwrap();
        let wave_source = wave_source_guard
            .as_mut()
            .ok_or_else(|| PyRuntimeError::new_err("Wave source not available"))?;

        let shared_tt = self.shared_state.time_table.lock().unwrap();
        let time_table = shared_tt
            .as_ref()
            .map(|tt| TimeTable(tt.clone()))
            .ok_or_else(|| PyRuntimeError::new_err("Time table not available"))?;

        let signal_refs: Vec<SignalRef> = vars.iter().map(|var| var.0.signal_ref()).collect(); // These are Wellen SignalRefs

        // Release GIL while loading signals (heavy I/O operation)
        let hierarchy = self.get_hierarchy_internal()?;
        let signals =
            py.allow_threads(|| wave_source.load_signals(&signal_refs, &hierarchy, multithreaded));

        // Build a map from SignalRef to Signal for quick lookup
        // This ensures we return signals in the same order as requested
        let mut signal_map: std::collections::HashMap<SignalRef, _> = signals.into_iter().collect();

        // Return signals in the same order as the input vars
        let mut result = Vec::new();
        for var in vars.iter() {
            let signal_ref = var.0.signal_ref(); // This is the actual Wellen SignalRef
            if let Some(sig) = signal_map.remove(&signal_ref) {
                let signal = Bound::new(
                    py,
                    Signal {
                        signal: Arc::new(sig),
                        all_times: time_table.clone(),
                    },
                )?;
                result.push(signal);
            } else {
                // If signal not found, return an error
                return Err(PyRuntimeError::new_err("Signal not found for variable"));
            }
        }
        Ok(result)
    }

    /// Load multiple signals at once
    fn load_signals<'py>(
        &mut self,
        vars: Vec<PyRef<'py, Var>>,
        py: Python<'py>,
    ) -> PyResult<Vec<Bound<'py, Signal>>> {
        self.load_signals_impl(vars, py, false)
    }

    /// Load multiple signals at once using multiple threads
    fn load_signals_multithreaded<'py>(
        &mut self,
        vars: Vec<PyRef<'py, Var>>,
        py: Python<'py>,
    ) -> PyResult<Vec<Bound<'py, Signal>>> {
        self.load_signals_impl(vars, py, true)
    }

    /// Load and cache signals by their 0-based handles
    fn preload_signals_by_handles(
        &mut self,
        handles: Vec<SignalHandle>,
        py: Python,
    ) -> PyResult<usize> {
        // Ensure body is loaded
        self.load_body()?;

        // Get wave_source from shared state
        let mut wave_source_guard = self.shared_state.wave_source.lock().unwrap();
        let wave_source = wave_source_guard
            .as_mut()
            .ok_or_else(|| PyRuntimeError::new_err("Wave source not available"))?;

        // Collect wellen signal refs and their corresponding 0-based handles
        let mut signal_refs_to_load = Vec::new();
        let mut handle_map = std::collections::HashMap::new();

        let signal_cache = self.shared_state.signal_cache.lock().unwrap();
        for handle in handles {
            // Skip if already cached
            if signal_cache.contains_key(&handle) {
                continue;
            }

            // Convert 0-based handle to wellen SignalRef and check if var exists
            if let Some(wellen_ref) = wellen::SignalRef::from_index(handle) {
                if let Ok(hierarchy) = self.get_hierarchy_internal() {
                    if let Some(_var_ref) = hierarchy.get_var_by_signal_ref(wellen_ref) {
                        signal_refs_to_load.push(wellen_ref);
                        handle_map.insert(wellen_ref, handle);
                    }
                }
            }
        }
        drop(signal_cache); // Release lock before loading

        if signal_refs_to_load.is_empty() {
            return Ok(0); // Nothing to load
        }

        // Load signals in batch
        let hierarchy = self.get_hierarchy_internal()?;
        let loaded_signals =
            py.allow_threads(|| wave_source.load_signals(&signal_refs_to_load, &hierarchy, false));

        // Cache the loaded signals with their 0-based handles
        let mut loaded_count = 0;
        let mut signal_cache = self.shared_state.signal_cache.lock().unwrap();
        for (wellen_ref, signal) in loaded_signals {
            if let Some(&handle) = handle_map.get(&wellen_ref) {
                signal_cache.insert(handle, Arc::new(signal));
                loaded_count += 1;
            }
        }

        Ok(loaded_count)
    }

    /// Check if a signal is cached by its 0-based handle
    fn is_signal_cached(&self, handle: SignalHandle) -> bool {
        self.shared_state
            .signal_cache
            .lock()
            .unwrap()
            .contains_key(&handle)
    }

    /// Clear the signal cache (for testing)
    fn clear_signal_cache(&mut self) {
        self.shared_state.signal_cache.lock().unwrap().clear();
        self.shared_state
            .python_signal_cache
            .lock()
            .unwrap()
            .clear();
    }

    /// Get a signal by its handle (0-based), using cache
    fn get_signal_by_handle<'py>(
        &mut self,
        handle: SignalHandle,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, Signal>> {
        // Check Python signal cache first for object identity
        let python_cache = self.shared_state.python_signal_cache.lock().unwrap();
        if let Some(cached_py_signal) = python_cache.get(&handle) {
            // Return cached Python Signal object
            return Ok(cached_py_signal.bind(py).clone());
        }
        drop(python_cache);

        // Check Rust signal cache
        let signal_cache = self.shared_state.signal_cache.lock().unwrap();
        if let Some(cached_signal) = signal_cache.get(&handle) {
            let cached_signal = cached_signal.clone();
            drop(signal_cache);

            // Get time table
            let shared_tt = self.shared_state.time_table.lock().unwrap();
            let time_table = shared_tt
                .as_ref()
                .map(|tt| TimeTable(tt.clone()))
                .ok_or_else(|| PyRuntimeError::new_err("Time table not available"))?;

            // Create new Python Signal object and cache it
            let py_signal = Bound::new(
                py,
                Signal {
                    signal: cached_signal,
                    all_times: time_table,
                },
            )?;

            // Cache the Python object for future calls
            self.shared_state
                .python_signal_cache
                .lock()
                .unwrap()
                .insert(handle, py_signal.clone().unbind());
            return Ok(py_signal);
        }
        drop(signal_cache);

        // Ensure body is loaded
        self.load_body()?;

        // Convert 0-based handle to wellen SignalRef and get the var
        let wellen_ref = wellen::SignalRef::from_index(handle)
            .ok_or_else(|| PyRuntimeError::new_err(format!("Invalid handle {}", handle)))?;
        let hierarchy = self.get_hierarchy_internal()?;
        let _var_ref = hierarchy.get_var_by_signal_ref(wellen_ref).ok_or_else(|| {
            PyRuntimeError::new_err(format!("No variable found for handle {}", handle))
        })?;

        // Load the signal
        let mut wave_source_guard = self.shared_state.wave_source.lock().unwrap();
        let wave_source = wave_source_guard
            .as_mut()
            .ok_or_else(|| PyRuntimeError::new_err("Wave source not available"))?;

        // Get time table
        let shared_tt = self.shared_state.time_table.lock().unwrap();
        let time_table = shared_tt
            .as_ref()
            .map(|tt| TimeTable(tt.clone()))
            .ok_or_else(|| PyRuntimeError::new_err("Time table not available"))?;

        // Release GIL while loading signal (heavy I/O operation)
        let hierarchy = self.get_hierarchy_internal()?;
        let mut signals =
            py.allow_threads(|| wave_source.load_signals(&[wellen_ref], &hierarchy, true));

        let (_sr, sig) = signals.swap_remove(0);
        let signal_arc = Arc::new(sig);

        // Cache the loaded signal
        self.shared_state
            .signal_cache
            .lock()
            .unwrap()
            .insert(handle, signal_arc.clone());

        // Create and cache the Python signal object
        let py_signal = Bound::new(
            py,
            Signal {
                signal: signal_arc,
                all_times: time_table,
            },
        )?;

        // Cache the Python object for future calls
        self.shared_state
            .python_signal_cache
            .lock()
            .unwrap()
            .insert(handle, py_signal.clone().unbind());

        Ok(py_signal)
    }
}

impl Waveform {
    /// Internal helper to get hierarchy - returns error if not loaded
    fn get_hierarchy_internal(&self) -> PyResult<Arc<wellen::Hierarchy>> {
        self.shared_state
            .hierarchy
            .lock()
            .unwrap()
            .clone()
            .ok_or_else(|| PyRuntimeError::new_err("Hierarchy not loaded yet"))
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
    signal: Arc<wellen::Signal>,
    all_times: TimeTable,
}

#[pymethods]
impl Signal {
    pub fn value_at_time<'a>(
        &self,
        time: wellen::Time,
        py: Python<'a>,
    ) -> Option<Bound<'a, PyAny>> {
        let val = self
            .all_times
            .0
            .as_ref()
            .binary_search(&time)
            .unwrap_or_else(|val| val);
        self.value_at_idx(val as TimeTableIdx, py)
    }

    pub fn value_at_idx<'a>(&self, idx: TimeTableIdx, py: Python<'a>) -> Option<Bound<'a, PyAny>> {
        let maybe_signal = self
            .signal
            .get_offset(idx)
            .map(|data_offset| self.signal.get_value_at(&data_offset, 0));
        if let Some(signal) = maybe_signal {
            convert_signal_value_to_py(signal, py)
                .ok()
                .map(|py_val| py_val.into_bound(py))
        } else {
            None
        }
    }

    pub fn all_changes(&self) -> SignalChangeIter {
        SignalChangeIter {
            signal: self.clone(),
            offset: 0,
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
        // Find the first change after start_time
        let time_indices = &self.signal.time_indices();

        // Binary search in the time table to find where to start
        let start_idx = match self.all_times.0.binary_search(&start_time) {
            Ok(idx) => {
                // Exact match - start from the next change
                // Find the corresponding offset in time_indices
                let time_table_idx = idx as TimeTableIdx;
                time_indices
                    .iter()
                    .position(|&t| t > time_table_idx)
                    .unwrap_or(time_indices.len())
            }
            Err(idx) => {
                // Not exact match - idx is the insertion point
                let time_table_idx = idx as TimeTableIdx;
                time_indices
                    .iter()
                    .position(|&t| t >= time_table_idx)
                    .unwrap_or(time_indices.len())
            }
        };

        SignalChangeIter {
            signal: self.clone(),
            offset: start_idx,
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
        // Binary search to find the time index
        let time_idx = match self.all_times.0.as_ref().binary_search(&query_time) {
            Ok(idx) => idx as TimeTableIdx, // Exact match
            Err(idx) => {
                if idx == 0 {
                    // Query time is before first timestamp
                    0
                } else {
                    (idx - 1) as TimeTableIdx // Get the index before
                }
            }
        };

        // Get the signal offset at this time index (for value at or before query time)
        let offset = self.signal.get_offset(time_idx);

        let (value, actual_time) = if let Some(ref data_offset) = offset {
            // Get the time when this value was actually set
            let offset_time_idx = self.signal.get_time_idx_at(data_offset);
            let actual_time = self.all_times.0.get(offset_time_idx as usize).cloned();

            // Get the signal value (last value in the time step)
            let signal_value = self
                .signal
                .get_value_at(data_offset, data_offset.elements - 1);
            let value = convert_signal_value_to_py(signal_value, py)?;

            (Some(value), actual_time)
        } else {
            // No change at or before the requested time
            (None, None)
        };

        // Find the next transition
        let (next_idx, next_time) = if let Some(offset) = offset {
            // Check if there's a next index from this offset
            if let Some(next_index) = offset.next_index {
                let next_idx = next_index.get() as TimeTableIdx;
                let next_time = self.all_times.0.get(next_idx as usize).cloned();
                (Some(next_idx), next_time)
            } else {
                (None, None)
            }
        } else {
            // If no offset at time_idx, check if there's a first change after this time
            if let Some(first_idx) = self.signal.get_first_time_idx() {
                if first_idx > time_idx {
                    let next_time = self.all_times.0.get(first_idx as usize).cloned();
                    (Some(first_idx), next_time)
                } else {
                    (None, None)
                }
            } else {
                (None, None)
            }
        };

        Bound::new(
            py,
            QueryResult {
                value,
                actual_time,
                next_idx,
                next_time,
            },
        )
    }

    /// Check if two Signal objects reference the same underlying wellen::Signal
    fn __eq__(&self, other: &Signal) -> bool {
        // Two signals are equal if they have the same signal reference
        self.signal.signal_ref() == other.signal.signal_ref()
    }

    /// Compute hash based on the signal reference
    fn __hash__(&self) -> u64 {
        // Use the signal reference index as hash
        let signal_ref = self.signal.signal_ref();
        signal_ref.index() as u64
    }
}

#[pyclass]
/// Iterates across all changes -- the returned object is a tuple of (Time, Value)
struct SignalChangeIter {
    signal: Signal,
    offset: usize,
}

#[pymethods]
impl SignalChangeIter {
    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __len__(&self) -> usize {
        let total_changes = self.signal.signal.time_indices().len();
        total_changes.saturating_sub(self.offset)
    }

    fn __next__<'a>(
        mut slf: PyRefMut<'_, Self>,
        python: Python<'a>,
    ) -> Option<(wellen::Time, Bound<'a, PyAny>)> {
        if let Some(time_idx) = slf.signal.signal.time_indices().get(slf.offset) {
            let data = slf.signal.value_at_idx(*time_idx, python);
            let time = slf.signal.all_times.0.get(*time_idx as usize).cloned()?;
            slf.offset += 1;
            data.map(|val| (time, val))
        } else {
            None
        }
    }
}
