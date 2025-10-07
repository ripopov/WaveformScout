mod convert;
mod jets_loader;
// mod design_tree_model;  // Removed - DesignTreeModel no longer used

use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
use std::thread;

use convert::Mappable;
use crossbeam_channel::{unbounded, Receiver, Sender};
use num_bigint::BigUint;
use pyo3::types::{PyInt, PyString};
use pyo3::{exceptions::PyRuntimeError, prelude::*};
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
    SignalLoaded(Vec<(SignalHandle, Arc<wellen::Signal>)>),
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
    callback: Mutex<Option<PyObject>>,
    header_loaded: AtomicBool,
    body_loaded: AtomicBool,
    // JETS-specific state
    jets_hierarchy: Mutex<Option<Arc<jets_loader::JetsHierarchy>>>,
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
    // m.add_class::<design_tree_model::PyDesignTreeModel>()?;  // Removed - DesignTreeModel no longer used

    // Export SignalHandle as a type alias (using the int type object)
    m.add("SignalHandle", py.get_type::<pyo3::types::PyInt>())?;

    Ok(())
}

/// Backend enum to support both Wellen and JETS hierarchies
#[derive(Clone)]
pub(crate) enum HierarchyBackend {
    Wellen(Arc<wellen::Hierarchy>),
    Jets(Arc<jets_loader::JetsHierarchy>),
}

#[pyclass]
#[derive(Clone)]
pub(crate) struct Hierarchy(pub(crate) HierarchyBackend);

#[pymethods]
impl Hierarchy {
    fn all_vars(&self) -> VarIter {
        match &self.0 {
            HierarchyBackend::Wellen(hier) => {
                // Return ALL variables from all scopes, including aliases
                let hier = hier.clone();
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

                VarIter(Box::new(all_vars.into_iter().map(|v| Var(VarBackend::Wellen(v)))))
            }
            HierarchyBackend::Jets(jets) => {
                // Collect all records as vars
                let mut all_vars = Vec::new();
                let freq = jets.clock_freq_mhz();

                fn collect_record_vars(
                    record: &rjets::TraceRecord,
                    jets: &jets_loader::JetsHierarchy,
                    freq: f64,
                    vars: &mut Vec<Var>,
                ) {
                    // Add this record as a var
                    if let Some(handle) = jets.get_handle_by_id(&record.id) {
                        vars.push(Var(VarBackend::Jets {
                            record: Arc::new(record.clone()),
                            signal_handle: handle,
                            clock_freq_mhz: freq,
                        }));
                    }
                    // Recurse into children
                    for child in &record.children {
                        collect_record_vars(child, jets, freq, vars);
                    }
                }

                for root in jets.top_records() {
                    collect_record_vars(root, jets, freq, &mut all_vars);
                }

                VarIter(Box::new(all_vars.into_iter()))
            }
        }
    }

    fn top_scopes(&self) -> ScopeIter {
        match &self.0 {
            HierarchyBackend::Wellen(hier) => {
                ScopeIter(Box::new({
                    let hier = hier.clone();
                    hier.scopes()
                        .map(|val| Scope(ScopeBackend::Wellen(hier[val].clone())))
                        .collect::<Vec<_>>()
                        .into_iter()
                }))
            }
            HierarchyBackend::Jets(jets) => {
                let freq = jets.clock_freq_mhz();
                let scopes: Vec<Scope> = jets
                    .top_records()
                    .iter()
                    .map(|record| {
                        Scope(ScopeBackend::Jets {
                            record: Arc::new(record.clone()),
                            clock_freq_mhz: freq,
                        })
                    })
                    .collect();
                ScopeIter(Box::new(scopes.into_iter()))
            }
        }
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
        if path.is_empty() {
            return None;
        }

        match &self.0 {
            HierarchyBackend::Wellen(hier) => {
                // Split into scope path and variable name
                let (scope_path, var_name) = if path.len() == 1 {
                    // Just a variable name at top level
                    (vec![], &path[0])
                } else {
                    // Scope path + variable name
                    (path[0..path.len() - 1].to_vec(), &path[path.len() - 1])
                };

                // Use the hierarchy's lookup_var method
                hier.lookup_var(&scope_path, var_name)
                    .map(|var_ref| Var(VarBackend::Wellen(hier[var_ref].clone())))
            }
            HierarchyBackend::Jets(_jets) => {
                // For JETS, path lookup is not yet supported
                // TODO: Implement path lookup for JETS if needed
                None
            }
        }
    }

    /// Get the first variable that references this signal (0-based index)
    fn get_var_by_signal_ref(&self, handle: SignalHandle) -> Option<Var> {
        match &self.0 {
            HierarchyBackend::Wellen(hier) => {
                // Convert 0-based handle to wellen SignalRef (which is 1-based internally)
                let wellen_ref = wellen::SignalRef::from_index(handle)?;
                hier.get_var_by_signal_ref(wellen_ref)
                    .map(|var_ref| Var(VarBackend::Wellen(hier[var_ref].clone())))
            }
            HierarchyBackend::Jets(jets) => {
                // For JETS, get the record by handle
                jets.get_record_by_handle(handle).map(|record| {
                    Var(VarBackend::Jets {
                        record,
                        signal_handle: handle,
                        clock_freq_mhz: jets.clock_freq_mhz(),
                    })
                })
            }
        }
    }

    /// Get the date metadata from the waveform file
    fn date(&self) -> String {
        match &self.0 {
            HierarchyBackend::Wellen(hier) => hier.date().to_string(),
            HierarchyBackend::Jets(jets) => jets.date(),
        }
    }

    /// Get the version metadata from the waveform file
    fn version(&self) -> String {
        match &self.0 {
            HierarchyBackend::Wellen(hier) => hier.version().to_string(),
            HierarchyBackend::Jets(jets) => jets.version(),
        }
    }

    /// Get the timescale metadata from the waveform file
    fn timescale(&self) -> Option<Timescale> {
        match &self.0 {
            HierarchyBackend::Wellen(hier) => hier.timescale().map(Timescale),
            HierarchyBackend::Jets(jets) => {
                // JETS uses microseconds
                Some(Timescale(wellen::Timescale::new(1, wellen::TimescaleUnit::MicroSeconds)))
            }
        }
    }

    /// Get the file format of the waveform file
    fn file_format(&self) -> String {
        match &self.0 {
            HierarchyBackend::Wellen(hier) => match hier.file_format() {
                wellen::FileFormat::Vcd => "VCD".to_string(),
                wellen::FileFormat::Fst => "FST".to_string(),
                wellen::FileFormat::Ghw => "GHW".to_string(),
                wellen::FileFormat::Unknown => "Unknown".to_string(),
            },
            HierarchyBackend::Jets(_) => "JETS".to_string(),
        }
    }
}

/// Backend enum to support both Wellen and JETS scopes
#[derive(Clone)]
pub(crate) enum ScopeBackend {
    Wellen(wellen::Scope),
    Jets {
        record: Arc<rjets::TraceRecord>,
        clock_freq_mhz: f64,
    },
}

#[pyclass]
pub(crate) struct Scope(pub(crate) ScopeBackend);

#[pymethods]
impl Scope {
    pub fn name(&self, hier: Bound<'_, Hierarchy>) -> String {
        match &self.0 {
            ScopeBackend::Wellen(scope) => {
                match &hier.borrow().0 {
                    HierarchyBackend::Wellen(h) => scope.name(h).to_string(),
                    HierarchyBackend::Jets(_) => unreachable!("Wellen scope with JETS hierarchy"),
                }
            }
            ScopeBackend::Jets { record, .. } => record.name.clone(),
        }
    }

    pub fn full_name(&self, hier: Bound<'_, Hierarchy>) -> String {
        match &self.0 {
            ScopeBackend::Wellen(scope) => {
                match &hier.borrow().0 {
                    HierarchyBackend::Wellen(h) => scope.full_name(h).to_string(),
                    HierarchyBackend::Jets(_) => unreachable!("Wellen scope with JETS hierarchy"),
                }
            }
            ScopeBackend::Jets { record, .. } => {
                // Build full name from parent chain
                let mut names = vec![record.name.clone()];
                let mut current_id = record.parent_id.clone();

                // Get JETS hierarchy to look up parents
                if let HierarchyBackend::Jets(jets) = &hier.borrow().0 {
                    while let Some(parent_id) = current_id {
                        if let Some(handle) = jets.get_handle_by_id(&parent_id) {
                            if let Some(parent_rec) = jets.get_record_by_handle(handle) {
                                names.insert(0, parent_rec.name.clone());
                                current_id = parent_rec.parent_id.clone();
                            } else {
                                break;
                            }
                        } else {
                            break;
                        }
                    }
                }
                names.join(".")
            }
        }
    }

    pub fn scope_type(&self) -> String {
        match &self.0 {
            ScopeBackend::Wellen(scope) => {
                match scope.scope_type() {
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
            ScopeBackend::Jets { .. } => "record".to_string(),
        }
    }

    pub fn vars(&self, hier: Bound<'_, Hierarchy>) -> VarIter {
        match &self.0 {
            ScopeBackend::Wellen(scope) => {
                let locahier = hier.borrow().clone();
                let scope = scope.clone();

                //TODO: optimize me! need to rewrite the logic from `HierarchyItemIdIterator` to use
                // Arc<Hierarchy> instead of lifetimes
                //
                // This is because python does not like lifetimes :)
                VarIter(Box::new({
                    match &locahier.0 {
                        HierarchyBackend::Wellen(h) => {
                            scope
                                .vars(h)
                                .map(|val| Var(VarBackend::Wellen(h[val].clone())))
                                .collect::<Vec<_>>()
                                .into_iter()
                        }
                        HierarchyBackend::Jets(_) => unreachable!("Wellen scope with JETS hierarchy"),
                    }
                }))
            }
            ScopeBackend::Jets { record, clock_freq_mhz } => {
                // JETS: Each record exposes itself as a single Var (string signal)
                let record_clone = record.clone();
                let freq = *clock_freq_mhz;

                // Get the signal handle from JETS hierarchy
                let handle = match &hier.borrow().0 {
                    HierarchyBackend::Jets(jets) => {
                        jets.get_handle_by_id(&record.id).unwrap_or(0)
                    }
                    HierarchyBackend::Wellen(_) => unreachable!("JETS scope with Wellen hierarchy"),
                };

                VarIter(Box::new(std::iter::once(Var(VarBackend::Jets {
                    record: record_clone,
                    signal_handle: handle,
                    clock_freq_mhz: freq,
                }))))
            }
        }
    }

    pub fn scopes(&self, hier: Bound<'_, Hierarchy>) -> ScopeIter {
        match &self.0 {
            ScopeBackend::Wellen(scope) => {
                let locahier = hier.borrow().clone();
                let scope = scope.clone();

                //TODO: optimize me! need to rewrite the logic from `HierarchyItemIdIterator` to use
                // Arc<Hierarchy> instead of lifetimes
                //
                // This is because python does not like lifetimes :)
                ScopeIter(Box::new({
                    match &locahier.0 {
                        HierarchyBackend::Wellen(h) => {
                            scope
                                .scopes(h)
                                .map(|val| Scope(ScopeBackend::Wellen(h[val].clone())))
                                .collect::<Vec<_>>()
                                .into_iter()
                        }
                        HierarchyBackend::Jets(_) => unreachable!("Wellen scope with JETS hierarchy"),
                    }
                }))
            }
            ScopeBackend::Jets { record, clock_freq_mhz } => {
                // JETS: Return child records as child scopes
                let children: Vec<Scope> = record
                    .children
                    .iter()
                    .map(|child| {
                        Scope(ScopeBackend::Jets {
                            record: Arc::new(child.clone()),
                            clock_freq_mhz: *clock_freq_mhz,
                        })
                    })
                    .collect();

                ScopeIter(Box::new(children.into_iter()))
            }
        }
    }

    /// Check if this scope is a JETS record
    /// For non-JETS waveforms, always returns false
    pub fn is_record(&self) -> bool {
        matches!(&self.0, ScopeBackend::Jets { .. })
    }

    /// Get the Record object if this scope is a JETS record
    /// For non-JETS waveforms, always returns None
    pub fn record(&self) -> Option<jets_loader::Record> {
        match &self.0 {
            ScopeBackend::Wellen(_) => None,
            ScopeBackend::Jets { record, clock_freq_mhz } => {
                Some(jets_loader::Record {
                    inner: record.clone(),
                    clock_freq_mhz: *clock_freq_mhz,
                })
            }
        }
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

/// Backend enum to support both Wellen and JETS vars
#[derive(Clone)]
pub(crate) enum VarBackend {
    Wellen(wellen::Var),
    Jets {
        record: Arc<rjets::TraceRecord>,
        signal_handle: usize,
        clock_freq_mhz: f64,
    },
}

#[pyclass]
pub(crate) struct Var(pub(crate) VarBackend);

#[pymethods]
impl Var {
    pub fn name(&self, hier: Bound<'_, Hierarchy>) -> String {
        match &self.0 {
            VarBackend::Wellen(var) => {
                match &hier.borrow().0 {
                    HierarchyBackend::Wellen(h) => var.name(h).to_string(),
                    HierarchyBackend::Jets(_) => unreachable!("Wellen var with JETS hierarchy"),
                }
            }
            VarBackend::Jets { record, .. } => record.name.clone(),
        }
    }
    pub fn full_name(&self, hier: Bound<'_, Hierarchy>) -> String {
        match &self.0 {
            VarBackend::Wellen(var) => {
                match &hier.borrow().0 {
                    HierarchyBackend::Wellen(h) => var.full_name(h).to_string(),
                    HierarchyBackend::Jets(_) => unreachable!("Wellen var with JETS hierarchy"),
                }
            }
            VarBackend::Jets { record, .. } => {
                // Build full name from parent chain - same as Scope.full_name()
                let mut names = vec![record.name.clone()];
                let mut current_id = record.parent_id.clone();

                if let HierarchyBackend::Jets(jets) = &hier.borrow().0 {
                    while let Some(parent_id) = current_id {
                        if let Some(handle) = jets.get_handle_by_id(&parent_id) {
                            if let Some(parent_rec) = jets.get_record_by_handle(handle) {
                                names.insert(0, parent_rec.name.clone());
                                current_id = parent_rec.parent_id.clone();
                            } else {
                                break;
                            }
                        } else {
                            break;
                        }
                    }
                }
                names.join(".")
            }
        }
    }
    pub fn bitwidth(&self) -> Option<u32> {
        match &self.0 {
            VarBackend::Wellen(var) => var.length(),
            VarBackend::Jets { .. } => None, // JETS records are string signals, no bitwidth
        }
    }
    pub fn var_type(&self) -> String {
        match &self.0 {
            VarBackend::Wellen(var) => format!("{:?}", var.var_type()),
            VarBackend::Jets { .. } => "String".to_string(), // JETS records are string signals
        }
    }
    pub fn enum_type(&self, hier: Bound<'_, Hierarchy>) -> Option<(String, Vec<(String, String)>)> {
        match &self.0 {
            VarBackend::Wellen(var) => {
                match &hier.borrow().0 {
                    HierarchyBackend::Wellen(h) => var.enum_type(h).map(|(name, values)| {
                        (
                            name.to_string(),
                            values
                                .into_iter()
                                .map(|(k, v)| (k.to_string(), v.to_string()))
                                .collect(),
                        )
                    }),
                    HierarchyBackend::Jets(_) => unreachable!("Wellen var with JETS hierarchy"),
                }
            }
            VarBackend::Jets { .. } => None,
        }
    }
    pub fn vhdl_type_name(&self, hier: Bound<'_, Hierarchy>) -> Option<String> {
        match &self.0 {
            VarBackend::Wellen(var) => {
                match &hier.borrow().0 {
                    HierarchyBackend::Wellen(h) => var.vhdl_type_name(h).map(|s| s.to_string()),
                    HierarchyBackend::Jets(_) => unreachable!("Wellen var with JETS hierarchy"),
                }
            }
            VarBackend::Jets { .. } => None,
        }
    }
    pub fn direction(&self) -> String {
        match &self.0 {
            VarBackend::Wellen(var) => format!("{:?}", var.direction()),
            VarBackend::Jets { .. } => "None".to_string(),
        }
    }
    pub fn length(&self) -> Option<u32> {
        match &self.0 {
            VarBackend::Wellen(var) => var.length(),
            VarBackend::Jets { .. } => None,
        }
    }
    pub fn is_real(&self) -> bool {
        match &self.0 {
            VarBackend::Wellen(var) => var.is_real(),
            VarBackend::Jets { .. } => false,
        }
    }
    pub fn is_string(&self) -> bool {
        match &self.0 {
            VarBackend::Wellen(var) => var.is_string(),
            VarBackend::Jets { .. } => true, // JETS records are string signals
        }
    }
    pub fn is_bit_vector(&self) -> bool {
        match &self.0 {
            VarBackend::Wellen(var) => var.is_bit_vector(),
            VarBackend::Jets { .. } => false,
        }
    }
    pub fn is_1bit(&self) -> bool {
        match &self.0 {
            VarBackend::Wellen(var) => var.is_1bit(),
            VarBackend::Jets { .. } => false,
        }
    }

    pub fn index(&self) -> Option<VarIndex> {
        match &self.0 {
            VarBackend::Wellen(var) => var.index().map(VarIndex),
            VarBackend::Jets { .. } => None,
        }
    }

    /// Get the signal reference as an integer for internal use.
    /// Two vars with the same `signal_handle()` are aliases.
    /// Returns a 0-based `SignalHandle` for Python code.
    pub fn signal_handle(&self) -> SignalHandle {
        match &self.0 {
            VarBackend::Wellen(var) => var.signal_ref().index(),
            VarBackend::Jets { signal_handle, .. } => *signal_handle,
        }
    }

    /// Get the scope path for this variable as a list of scope names.
    /// The returned list contains scope names from root to immediate parent (excluding the variable name itself).
    /// Returns an empty list for top-level variables.
    pub fn scope_path(&self, hier: Bound<'_, Hierarchy>) -> Vec<String> {
        match &self.0 {
            VarBackend::Wellen(var) => {
                match &hier.borrow().0 {
                    HierarchyBackend::Wellen(h) => {
                        let mut scopes = Vec::new();
                        // Walk up the parent chain collecting scope names
                        if let Some(parent_scope) = var.parent(h) {
                            let scope = &h[parent_scope];
                            collect_scope_path(scope, h, &mut scopes);
                        }
                        scopes
                    }
                    HierarchyBackend::Jets(_) => unreachable!("Wellen var with JETS hierarchy"),
                }
            }
            VarBackend::Jets { record, .. } => {
                // Build scope path from parent chain
                let mut scopes = Vec::new();
                let mut current_id = record.parent_id.clone();

                if let HierarchyBackend::Jets(jets) = &hier.borrow().0 {
                    while let Some(parent_id) = current_id {
                        if let Some(handle) = jets.get_handle_by_id(&parent_id) {
                            if let Some(parent_rec) = jets.get_record_by_handle(handle) {
                                scopes.insert(0, parent_rec.name.clone());
                                current_id = parent_rec.parent_id.clone();
                            } else {
                                break;
                            }
                        } else {
                            break;
                        }
                    }
                }
                scopes
            }
        }
    }
}

/// Helper function to collect scope names from a scope up to the root
fn collect_scope_path(scope: &wellen::Scope, hier: &wellen::Hierarchy, scopes: &mut Vec<String>) {
    // Recursively walk up to the root
    if let Some(parent_ref) = scope.parent(hier) {
        collect_scope_path(&hier[parent_ref], hier, scopes);
    }
    // Add this scope's name
    scopes.push(scope.name(hier).to_string());
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

/// Convert a signal value to a float based on data format
/// Returns None for undefined/high-impedance values
///
/// Data format codes: 0=unsigned, 1=signed, 2=hex, 3=bin, 4=float
fn convert_signal_value_to_float(signal: SignalValue, data_format: u8, bit_width: u32) -> Option<f64> {
    match signal {
        SignalValue::Real(val) => Some(val),
        SignalValue::String(_) => None, // Strings can't be converted to numeric values
        _ => {
            // Try to convert to integer
            if let Some(biguint) = BigUint::try_from_signal(signal.clone()) {
                // Convert BigUint to u64 (or return None if too large)
                let bytes = biguint.to_bytes_le();
                if bytes.len() > 8 {
                    // Value too large to fit in u64, skip
                    return None;
                }

                let mut value_u64 = 0u64;
                for (i, &byte) in bytes.iter().enumerate() {
                    value_u64 |= (byte as u64) << (i * 8);
                }

                // Apply data format conversion
                match data_format {
                    0 | 2 | 3 => {
                        // UNSIGNED (0), HEX (2), BIN (3) - all treated as unsigned
                        Some(value_u64 as f64)
                    }
                    1 => {
                        // SIGNED (1) - 2's complement conversion
                        let max_val = 1u64 << (bit_width.saturating_sub(1));
                        if value_u64 >= max_val {
                            let signed_value = (value_u64 as i64) - (1i64 << bit_width);
                            Some(signed_value as f64)
                        } else {
                            Some(value_u64 as f64)
                        }
                    }
                    4 => {
                        // FLOAT (4) - IEEE 754 float conversion
                        if bit_width == 32 && bytes.len() <= 4 {
                            let bits = value_u64 as u32;
                            Some(f32::from_bits(bits) as f64)
                        } else if bit_width == 64 && bytes.len() <= 8 {
                            Some(f64::from_bits(value_u64))
                        } else {
                            // Unsupported float width
                            Some(value_u64 as f64)
                        }
                    }
                    _ => Some(value_u64 as f64), // Default to unsigned
                }
            } else {
                // Value contains X/Z - undefined or high impedance
                None
            }
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
                        let mut loaded_signals = Vec::new();

                        // Load signals one by one
                        for handle in handles.iter() {
                            // Always load signals fresh - no caching in Rust
                            // Load signal - need to access wave_source for each signal
                            let signal_ref = SignalRef::from_index(*handle).unwrap();

                            // We need to load signals within the lock scope
                            if let Some(source) = &mut *shared_state.wave_source.lock().unwrap()
                            {
                                if let Some(hier) = &hierarchy {
                                    let signals =
                                        source.load_signals(&[signal_ref], hier, true);
                                    if let Some((_ref, sig)) = signals.into_iter().next() {
                                        // Store both handle and signal
                                        loaded_signals.push((*handle, Arc::new(sig)));
                                    }
                                }
                            }
                        }

                        // Emit loaded event with actual loaded signals
                        if !loaded_signals.is_empty() {
                            emit_event(&shared_state, AsyncEvent::SignalLoaded(loaded_signals));
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
                AsyncEvent::SignalLoaded(signals) => {
                    let dict = pyo3::types::PyDict::new(py);
                    dict.set_item("type", "SignalLoaded").ok();

                    // Get the time table from shared state
                    let time_table = shared_state.time_table.lock().unwrap().clone();

                    // Always return signals list matching pyi spec
                    let py_list = pyo3::types::PyList::empty(py);
                    if let Some(tt) = time_table {
                        for (handle, signal_arc) in signals.iter() {
                            // Create Python Signal object
                            if let Ok(py_signal) = Bound::new(
                                py,
                                Signal {
                                    backend: SignalBackend::Wellen {
                                        signal: signal_arc.clone(),
                                        all_times: TimeTable(tt.clone()),
                                    },
                                },
                            ) {
                                let tuple = pyo3::types::PyTuple::new(py, &[handle.to_object(py), py_signal.to_object(py)]).unwrap();
                                py_list.append(tuple).ok();
                            }
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
        // Check if this is a JETS file
        let is_jets_file = path.ends_with(".jets") || path.ends_with(".jsonl");

        if is_jets_file {
            // Load JETS file
            let jets_hier = jets_loader::load_jets_file(&path)
                .map_err(|e| PyRuntimeError::new_err(format!("Failed to load JETS file: {}", e)))?;

            let shared_state = Arc::new(SharedState {
                file_path: path.clone(),
                hierarchy: Mutex::new(None),
                wave_source: Mutex::new(None),
                time_table: Mutex::new(None),
                body_continuation: Mutex::new(None),
                callback: Mutex::new(None),
                header_loaded: AtomicBool::new(true),
                body_loaded: AtomicBool::new(true),
                jets_hierarchy: Mutex::new(Some(Arc::new(jets_hier))),
            });

            return Ok(Self {
                shared_state,
                request_sender: None,
                _worker_handle: None,
            });
        }

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
                    callback: Mutex::new(None),
                    header_loaded: AtomicBool::new(true),
                    body_loaded: AtomicBool::new(true),
                    jets_hierarchy: Mutex::new(None),
                })
            } else {
                // Create shared state with header only
                Arc::new(SharedState {
                    file_path: path.clone(),
                    hierarchy: Mutex::new(Some(hier)),
                    wave_source: Mutex::new(None),
                    time_table: Mutex::new(None),
                    body_continuation: Mutex::new(Some(Box::new(header_result.body))),
                    callback: Mutex::new(None),
                    header_loaded: AtomicBool::new(true),
                    body_loaded: AtomicBool::new(false),
                    jets_hierarchy: Mutex::new(None),
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
                callback: Mutex::new(None),
                header_loaded: AtomicBool::new(false),
                body_loaded: AtomicBool::new(false),
                jets_hierarchy: Mutex::new(None),
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
        // Check if this is a JETS file first
        if let Some(jets_hier) = self.shared_state.jets_hierarchy.lock().unwrap().as_ref() {
            return Some(Hierarchy(HierarchyBackend::Jets(jets_hier.clone())));
        }

        // Otherwise, return Wellen hierarchy
        self.shared_state
            .hierarchy
            .lock()
            .unwrap()
            .as_ref()
            .map(|h| Hierarchy(HierarchyBackend::Wellen(h.clone())))
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

        // Split into scope path and variable name
        let (scope_path, var_name) = if path_segments.len() == 1 {
            (vec![], &path_segments[0])
        } else {
            (path_segments[0..path_segments.len() - 1].to_vec(), &path_segments[path_segments.len() - 1])
        };

        let hierarchy = self.get_hierarchy_internal()?;
        let maybe_var = hierarchy
            .lookup_var(&scope_path, var_name)
            .ok_or(PyRuntimeError::new_err(format!(
                "No var at path {}",
                path_segments.join(".")
            )))?;
        let var = &hierarchy[maybe_var];
        // Use the signal handle from the var to get the signal
        let handle = Var(VarBackend::Wellen(var.clone())).signal_handle();
        self.get_signal_by_handle(handle, py)
    }

    /// Load multiple signals at once using multiple threads
    fn load_signals_multithreaded<'py>(
        &mut self,
        vars: Vec<PyRef<'py, Var>>,
        py: Python<'py>,
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

        let signal_refs: Vec<SignalRef> = vars
            .iter()
            .filter_map(|var| match &var.0 {
                VarBackend::Wellen(w) => Some(w.signal_ref()),
                VarBackend::Jets { .. } => None, // JETS vars not supported in multithreaded loading
            })
            .collect();

        // Release GIL while loading signals (heavy I/O operation)
        // Always use multithreaded loading
        let hierarchy = self.get_hierarchy_internal()?;
        let signals =
            py.allow_threads(|| wave_source.load_signals(&signal_refs, &hierarchy, true));

        // Build a map from SignalRef to Signal for quick lookup
        // This ensures we return signals in the same order as requested
        let mut signal_map: std::collections::HashMap<SignalRef, _> = signals.into_iter().collect();

        // Return signals in the same order as the input vars
        let mut result = Vec::new();
        for var in vars.iter() {
            match &var.0 {
                VarBackend::Wellen(w) => {
                    let signal_ref = w.signal_ref(); // This is the actual Wellen SignalRef
                    if let Some(sig) = signal_map.remove(&signal_ref) {
                        let signal = Bound::new(
                            py,
                            Signal {
                                backend: SignalBackend::Wellen {
                                    signal: Arc::new(sig),
                                    all_times: time_table.clone(),
                                },
                            },
                        )?;
                        result.push(signal);
                    } else {
                        // If signal not found, return an error
                        return Err(PyRuntimeError::new_err("Signal not found for variable"));
                    }
                }
                VarBackend::Jets { .. } => {
                    // JETS vars not supported in multithreaded loading yet
                    return Err(PyRuntimeError::new_err(
                        "JETS signals not supported in multithreaded loading",
                    ));
                }
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
        // Check if this is a JETS file
        if let Some(jets_hier) = self.shared_state.jets_hierarchy.lock().unwrap().as_ref() {
            // Generate JETS signal
            let record = jets_hier
                .get_record_by_handle(handle)
                .ok_or_else(|| PyRuntimeError::new_err(format!("No record found for handle {}", handle)))?;

            let changes = jets_hier.generate_signal_changes(&record);

            // Create JETS signal
            return create_jets_signal(changes, py);
        }

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

        // Create the Python signal object (no caching)
        let py_signal = Bound::new(
            py,
            Signal {
                backend: SignalBackend::Wellen {
                    signal: signal_arc,
                    all_times: time_table,
                },
            },
        )?;

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

/// Helper function to create a JETS signal from changes
fn create_jets_signal<'py>(
    changes: Vec<(i64, String)>,
    py: Python<'py>,
) -> PyResult<Bound<'py, Signal>> {
    Bound::new(
        py,
        Signal {
            backend: SignalBackend::Jets {
                changes: Arc::new(changes),
            },
        },
    )
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

/// Backend enum for Signal to support both Wellen and JETS
#[derive(Clone)]
enum SignalBackend {
    Wellen {
        signal: Arc<wellen::Signal>,
        all_times: TimeTable,
    },
    Jets {
        changes: Arc<Vec<(i64, String)>>,
    },
}

#[pyclass]
#[derive(Clone)]
struct Signal {
    backend: SignalBackend,
}

#[pymethods]
impl Signal {
    pub fn value_at_time<'a>(
        &self,
        time: wellen::Time,
        py: Python<'a>,
    ) -> Option<Bound<'a, PyAny>> {
        match &self.backend {
            SignalBackend::Wellen { all_times, .. } => {
                let val = all_times
                    .0
                    .as_ref()
                    .binary_search(&time)
                    .unwrap_or_else(|val| val);
                self.value_at_idx(val as TimeTableIdx, py)
            }
            SignalBackend::Jets { .. } => {
                // JETS signals don't support indexed access
                None
            }
        }
    }

    pub fn value_at_idx<'a>(&self, idx: TimeTableIdx, py: Python<'a>) -> Option<Bound<'a, PyAny>> {
        match &self.backend {
            SignalBackend::Wellen { signal, .. } => {
                let maybe_signal = signal
                    .get_offset(idx)
                    .map(|data_offset| signal.get_value_at(&data_offset, 0));
                if let Some(signal_val) = maybe_signal {
                    convert_signal_value_to_py(signal_val, py)
                        .ok()
                        .map(|py_val| py_val.into_bound(py))
                } else {
                    None
                }
            }
            SignalBackend::Jets { .. } => {
                // JETS signals don't support indexed access
                None
            }
        }
    }

    pub fn all_changes(&self) -> SignalChangeIter {
        match &self.backend {
            SignalBackend::Wellen { .. } => {
                SignalChangeIter {
                    signal: self.clone(),
                    offset: 0,
                }
            }
            SignalBackend::Jets { .. } => {
                SignalChangeIter {
                    signal: self.clone(),
                    offset: 0,
                }
            }
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
        match &self.backend {
            SignalBackend::Wellen { signal, all_times } => {
                // Find the first change after start_time
                let time_indices = signal.time_indices();

                // Binary search in the time table to find where to start
                let start_idx = match all_times.0.binary_search(&start_time) {
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
            SignalBackend::Jets { changes } => {
                // Find first change after start_time
                // JETS uses i64 for time (microseconds), convert from Wellen u64
                let start_time_i64 = start_time as i64;
                let start_idx = changes
                    .iter()
                    .position(|(time, _)| *time > start_time_i64)
                    .unwrap_or(changes.len());

                SignalChangeIter {
                    signal: self.clone(),
                    offset: start_idx,
                }
            }
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
        match &self.backend {
            SignalBackend::Wellen { signal, all_times } => {
                // Binary search to find the time index
                let time_idx = match all_times.0.as_ref().binary_search(&query_time) {
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
                let offset = signal.get_offset(time_idx);

                let (value, actual_time) = if let Some(ref data_offset) = offset {
                    // Get the time when this value was actually set
                    let offset_time_idx = signal.get_time_idx_at(data_offset);
                    let actual_time = all_times.0.get(offset_time_idx as usize).cloned();

                    // Get the signal value (last value in the time step)
                    let signal_value = signal
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
                        let next_time = all_times.0.get(next_idx as usize).cloned();
                        (Some(next_idx), next_time)
                    } else {
                        (None, None)
                    }
                } else {
                    // If no offset at time_idx, check if there's a first change after this time
                    if let Some(first_idx) = signal.get_first_time_idx() {
                        if first_idx > time_idx {
                            let next_time = all_times.0.get(first_idx as usize).cloned();
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
            SignalBackend::Jets { .. } => {
                // JETS signals don't support query_signal
                Bound::new(
                    py,
                    QueryResult {
                        value: None,
                        actual_time: None,
                        next_idx: None,
                        next_time: None,
                    },
                )
            }
        }
    }

    /// Check if two Signal objects reference the same underlying signal
    fn __eq__(&self, other: &Signal) -> bool {
        match (&self.backend, &other.backend) {
            (SignalBackend::Wellen { signal: s1, .. }, SignalBackend::Wellen { signal: s2, .. }) => {
                s1.signal_ref() == s2.signal_ref()
            }
            (SignalBackend::Jets { changes: c1 }, SignalBackend::Jets { changes: c2 }) => {
                Arc::ptr_eq(c1, c2)
            }
            _ => false,
        }
    }

    /// Compute hash based on the signal reference
    fn __hash__(&self) -> u64 {
        match &self.backend {
            SignalBackend::Wellen { signal, .. } => {
                signal.signal_ref().index() as u64
            }
            SignalBackend::Jets { changes } => {
                // Use Arc pointer address as hash
                Arc::as_ptr(changes) as u64
            }
        }
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
        match &self.backend {
            SignalBackend::Wellen { signal, .. } => {
                let mut min_val = f64::INFINITY;
                let mut max_val = f64::NEG_INFINITY;

                // Iterate through all signal changes
                let time_indices = signal.time_indices();
                for time_idx in time_indices {
                    // Get the signal value at this time index
                    if let Some(data_offset) = signal.get_offset(*time_idx) {
                        // Get the last value in the time step
                        let signal_value = signal
                            .get_value_at(&data_offset, data_offset.elements - 1);

                        // Convert to float based on data format
                        if let Some(value_float) = convert_signal_value_to_float(signal_value, data_format, bit_width) {
                            if !value_float.is_nan() && value_float.is_finite() {
                                min_val = min_val.min(value_float);
                                max_val = max_val.max(value_float);
                            }
                        }
                    }
                }

                // Handle case where no valid values found
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
            SignalBackend::Jets { .. } => {
                // JETS signals are strings, not analog - return default range
                Ok((0.0, 1.0))
            }
        }
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
        match &self.signal.backend {
            SignalBackend::Wellen { signal, .. } => {
                let total_changes = signal.time_indices().len();
                total_changes.saturating_sub(self.offset)
            }
            SignalBackend::Jets { changes } => {
                changes.len().saturating_sub(self.offset)
            }
        }
    }

    fn __next__<'a>(
        mut slf: PyRefMut<'_, Self>,
        python: Python<'a>,
    ) -> Option<(wellen::Time, Bound<'a, PyAny>)> {
        match &slf.signal.backend {
            SignalBackend::Wellen { signal, all_times } => {
                if let Some(time_idx) = signal.time_indices().get(slf.offset) {
                    let data = slf.signal.value_at_idx(*time_idx, python);
                    let time = all_times.0.get(*time_idx as usize).cloned()?;
                    slf.offset += 1;
                    data.map(|val| (time, val))
                } else {
                    None
                }
            }
            SignalBackend::Jets { changes } => {
                if let Some((time, value)) = changes.get(slf.offset) {
                    // Clone values before mutating slf
                    let time_val = *time as wellen::Time;
                    let value_str = value.clone();
                    slf.offset += 1;
                    let py_value = PyString::new(python, &value_str).into_any();
                    Some((time_val, py_value))
                } else {
                    None
                }
            }
        }
    }
}
