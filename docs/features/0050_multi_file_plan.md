# Feature Plan: Multi-File Waveform Support

**Feature ID:** 0050
**Feature Name:** Multi-File Waveform Support
**Status:** Planning
**Created:** 2025-09-29

---

## 1. Use Cases and Requirements Analysis

### Core Functionality

Support opening multiple waveform files (VCD/FST) simultaneously and displaying their signals together on the same waveform canvas. Users can add signals from any loaded file to the signal list and view them in a unified timeline.

### Detailed Requirements

#### File Management
- Users can open multiple waveform files through the File → Open menu (opening multiple times)
- Each file maintains its own independent WaveformDB instance
- Files are displayed as separate top-level trees in the DesignTreeView
- If only 1 file is loaded, no changes in UI: top-level scopes come from that file (backward compatibility)

#### Signal Naming and Identification
- In SignalNamesView, signals from different files are distinguished by file prefix in their display name
  - Format: `<filename>:<hierarchical_path>`
  - Example: If `file1.vcd` and `file2.vcd` both have `top.cpu.clk`, they appear as:
    - `file1:top.cpu.clk`
    - `file2:top.cpu.clk`
- **IMPORTANT**: This prefix is only for display purposes. The underlying `SignalNode.name` field should store the original hierarchical path without the prefix. The file ID is stored separately in `SignalNode.file_id`.

#### Timescale Handling
- First loaded file establishes the reference timescale
- Subsequent files must have matching timescale or loading fails with error message
  - Error message format: `"Cannot load <filename>: timescale mismatch. Expected <timescale1>, got <timescale2>"`
- All loaded files share the same time range. If a subsequent file has a longer range, the viewport's `total_duration` is increased to accommodate it

#### Session Persistence
- Sessions save references to all loaded waveform files with unique file IDs
- Use absolute file paths for simplicity in first release
- On load, if any file is missing, show error dialog but load remaining files
- File IDs must be stable across save/load cycles

#### Design Hierarchy Display
- DesignTreeView shows each file as a separate top-level tree node when multiple files are loaded
- Tree node structure for multiple files:
  ```
  DesignTreeView
  ├── file1.vcd (file_id=0)
  │   └── [hierarchy from file1]
  ├── file2.fst (file_id=1)
  │   └── [hierarchy from file2]
  ```
- For single file (backward compatibility):
  ```
  DesignTreeView
  └── [hierarchy from file] (no file node wrapper)
  ```

#### Cross-File Features
- **Markers**: Shared across all files (file-independent, time-based) - No changes needed
- **Analysis**: Measurements and signal analysis work across signals from different files - No changes needed
- **Viewport**: Single unified viewport controls zoom/pan for all files - No changes needed
- **Clock Signal**: Can be any signal from any loaded file
- **Sampling Signal**: Can be any signal from any loaded file

---

## 2. Codebase Research

### Key Architecture Findings

#### Data Model (`wavescout/data_model.py`)
- **WaveformSession** currently has a single `waveform_db` reference (line 345)
- **SignalNode** stores:
  - `name`: Full hierarchical path (e.g., `"top.cpu.clk"`)
  - `handle`: SignalHandle from WaveformDB
  - `var`: Var wrapper around pyrox.Var
  - `signal`: AsyncLoadedSignal for async loading
  - `instance_id`: Unique identifier for this node instance
- **TreeNode** base class provides `instance_id` generation (lines 94-116)
- No existing file_id tracking mechanism

#### WaveformDB (`wavescout/waveform_db.py`)
- Each WaveformDB instance represents one opened waveform file
- Stores `uri` (file path) and `waveform` (pyrox.Waveform instance)
- Handles async signal loading via `AsyncLoadedSignal` and event bus
- Signal handles are specific to each WaveformDB instance
- Has `_timescale` field (line 221) extracted from hierarchy

#### WaveformController (`wavescout/waveform_controller.py`)
- Owns the current `WaveformSession` (line 60)
- Single source of truth for session state
- All state changes flow through controller methods
- Uses EventBus for cross-widget coordination
- No multi-file awareness currently

#### Persistence (`wavescout/persistence.py`)
- **save_session()**: Saves single `db_uri` (line 434)
- **load_session()**: Opens single WaveformDB (lines 501-509)
- Serializes/deserializes SignalNodes with handles
- Uses `_resolve_signal_handles()` to validate handles against current backend (lines 79-131)

#### Design Tree View (`wavescout/design_tree_view.py`)
- Uses `ScopeTreeModel` to display hierarchy
- `_create_signal_node_from_var()` creates SignalNodes from variables (lines 493-547)
- Emits `signals_selected` signal when user adds signals
- Currently assumes single WaveformDB

#### Signal Names View (`wavescout/signal_names_view.py`)
- Displays signal names in tree view
- Context menu for signal operations
- Copy/paste functionality serializes SignalNodes
- No file-aware display logic

#### Main Widget (`wavescout/wave_scout_widget.py`)
- Coordinates three panels (names, values, canvas)
- Uses WaveformItemModel for Qt tree views
- Receives session via `setSession()` (line 180)

### Protocol-Based Abstraction
- The current code imports the concrete `WaveformDB` class directly
- Multiple WaveformDB instances can coexist as long as handles don't collide
- Each WaveformDB has its own signal cache and loading state

---

## 3. Implementation Planning

### Data Model Changes

#### File: `wavescout/data_model.py`

**New DataClass: `WaveformFileReference`**
- Add before WaveformSession definition:
```python
@dataclass
class WaveformFileReference:
    """Reference to a loaded waveform file with unique ID."""
    file_id: int
    file_path: str
    waveform_db: Optional['WaveformDB']
    timescale: Timescale
```

**Modify WaveformSession:**
- **CHANGE**: Replace single `waveform_db` field with `waveform_files: List[WaveformFileReference]` (default empty list)
- **ADD**: `next_file_id: int = 0` for generating unique file IDs
- **KEEP**: All other fields unchanged (root_nodes, viewport, markers, etc.)

**Modify SignalNode:**
- **ADD**: `file_id: int = 0` field to track which file this signal belongs to
- **KEEP**: All existing fields (name stores original path without prefix)

**New Helper Methods:**
Add to WaveformSession (not as dataclass methods, but as module-level functions):
- `get_file_by_id(session, file_id)`: Returns WaveformFileReference or None
- `get_primary_file(session)`: Returns first file (for backward compat)
- `add_waveform_file(session, file_path, waveform_db)`: Adds new file with unique ID

---

### WaveformDB Coordination

#### File: `wavescout/waveform_controller.py`

**New Methods:**
- `open_waveform_file(file_path: str) -> bool`: Opens new waveform file
  - Creates new WaveformDB instance
  - Validates timescale against existing files
  - Adds to session.waveform_files with unique file_id
  - Updates viewport.total_duration if new file is longer
  - Emits session_changed event
  - Returns True on success, False on failure (shows error message)

- `close_waveform_file(file_id: int) -> None`: Closes specific file
  - Removes all signals from that file from root_nodes
  - Removes file from waveform_files list
  - Updates viewport if needed

- `get_waveform_db_for_signal(node: SignalNode) -> Optional[WaveformDB]`: Helper
  - Returns WaveformDB instance for given signal's file_id

**Modify Existing Methods:**
- `set_session()`: No changes needed (works with list of files)
- `set_clock_signal()`: Get WaveformDB via `get_waveform_db_for_signal()`
- `set_sampling_signal()`: Get WaveformDB via `get_waveform_db_for_signal()`

---

### Persistence Changes

#### File: `wavescout/persistence.py`

**Modify `save_session()`:**
- Replace single `db_uri` with `waveform_files` list:
```python
'waveform_files': [
    {
        'file_id': ref.file_id,
        'file_path': ref.file_path,
        'timescale': {'factor': ref.timescale.factor, 'unit': ref.timescale.unit.value}
    }
    for ref in session.waveform_files
]
```
- Add `file_id` to each serialized SignalNode

**Modify `load_session()`:**
- Load all files from `waveform_files` list
- For each file:
  - Open WaveformDB
  - Validate timescale against first file
  - Add to session.waveform_files with original file_id
- If any file is missing:
  - Show warning dialog listing missing files
  - Continue loading with available files
  - Remove SignalNodes referencing missing files
- Restore file_id counter to max loaded file_id + 1

**Modify `_serialize_node()` and `_deserialize_node()`:**
- Include `file_id` in serialization
- Validate file_id exists on deserialization

---

### Design Tree View Changes

#### File: Need to create/modify scope tree model

**New Class: `MultiFileTreeModel` (or modify existing ScopeTreeModel)**
Currently using `ScopeTreeModel` from `wavescout/scope_tree_model.py` (line 119).

**Approach 1: Wrapper Model (Recommended)**
- Create `MultiFileScopeTreeModel` that wraps multiple ScopeTreeModel instances
- Root nodes are file wrappers when multiple files loaded
- Single file mode delegates directly to ScopeTreeModel (backward compat)

**Approach 2: Modify ScopeTreeModel**
- Add multi-file awareness to ScopeTreeModel
- Conditional root node structure based on file count

#### File: `wavescout/design_tree_view.py`

**Modify `set_waveform_db()` → `set_waveform_files()`:**
- Signature: `set_waveform_files(waveform_files: List[WaveformFileReference])`
- Create appropriate model based on file count:
  - Single file: Use ScopeTreeModel directly (backward compat)
  - Multiple files: Use MultiFileScopeTreeModel with file nodes

**Modify `_create_signal_node_from_var()`:**
- Extract file_id from current context (selected file node)
- Set `file_id` field when creating SignalNode
- Keep `name` as original hierarchical path (no prefix)

**New Method: `_get_current_file_id()`:**
- Determines which file context user is in
- Used when creating SignalNodes from tree selection

---

### Signal Names View Changes

#### File: `wavescout/signal_names_view.py`

**No direct changes to data structures** - this view displays SignalNodes from the model.

**Display Logic Changes (in Qt ItemDelegate or Model):**
Need to modify display to show file prefix for signals from non-primary files.

#### File: `wavescout/waveform_item_model.py` (Qt model)

**Modify `data()` method for display role:**
- When returning signal name for display:
  - If multiple files in session AND signal.file_id != primary_file_id:
    - Return formatted name: `"{filename}:{signal.name}"`
  - Else:
    - Return `signal.name` (backward compat)

**Helper Method:**
- `_get_display_name(node: SignalNode) -> str`: Formats name with file prefix if needed
- Uses session.waveform_files to lookup filename by file_id

---

### UI Integration Points

#### File: `wavescout/wave_scout_widget.py`

**No structural changes needed** - the widget displays whatever session it receives.

#### Main Application File (scout.py or main.py)

**Modify File → Open Handler:**
- Allow calling open multiple times without closing previous file
- Each open adds to session.waveform_files via controller
- Show error dialog if timescale mismatch
- Update window title to show multiple files (e.g., "WaveformScout - 3 files loaded")

**New File → Close File Menu:**
- Submenu listing all open files by name
- Allows closing individual files
- Grayed out if only one file open

---

### Backward Compatibility Strategy

**Single File Mode (Implicit):**
- When only one file is loaded:
  - No file prefix in signal names
  - DesignTreeView shows hierarchy directly (no file wrapper node)
  - Session serialization includes `waveform_files` list with one entry
  - Old sessions (with `db_uri` field) are auto-upgraded on load

**Legacy Session Loading:**
- Detect old format (has `db_uri` instead of `waveform_files`)
- Convert to new format:
  - Create single WaveformFileReference with file_id=0
  - Set all existing SignalNodes to file_id=0
  - Save in new format on next save

---

### Error Handling

**Timescale Mismatch:**
- Show error dialog with clear message
- Dialog options: [Cancel] (don't open file)
- Do not add file to session

**Missing File on Load:**
- Show warning dialog listing all missing files
- Dialog options: [Continue] [Cancel]
- If Continue:
  - Load available files
  - Remove signals referencing missing files
  - Log removed signal count to status bar

**File Load Errors:**
- Wrap WaveformDB.open() in try/except
- Show error dialog with file path and error message
- Continue with other files

---

### Implementation Sequence

**Phase 1: Data Model Foundation**
1. Add WaveformFileReference dataclass to data_model.py
2. Modify WaveformSession to use waveform_files list
3. Add file_id field to SignalNode
4. Add helper functions for file management

**Phase 2: Controller Logic**
1. Add open_waveform_file() to WaveformController
2. Add close_waveform_file() to WaveformController
3. Add get_waveform_db_for_signal() helper
4. Modify clock/sampling signal methods to use helper

**Phase 3: Persistence**
1. Modify save_session() for multi-file format
2. Modify load_session() for multi-file format
3. Add legacy format detection and upgrade
4. Add file_id to node serialization

**Phase 4: Design Tree Model**
1. Create MultiFileScopeTreeModel wrapper
2. Implement file node layer for multiple files
3. Add single-file bypass for backward compat
4. Modify design_tree_view.py to use new model

**Phase 5: Display Logic**
1. Modify waveform_item_model.py data() for file prefix display
2. Add _get_display_name() helper
3. Test with multiple files with same signal names

**Phase 6: UI Integration**
1. Modify main application File → Open to support multiple calls
2. Add File → Close File submenu
3. Update window title for multiple files
4. Add error dialogs for timescale/missing files

**Phase 7: Testing & Polish**
1. Test single file mode (backward compat)
2. Test multiple files with different hierarchies
3. Test save/load with multiple files
4. Test missing file on load
5. Test timescale validation
6. Test clock/sampling signals across files

---

### Algorithm Descriptions

**Opening Multiple Files:**
```
1. User selects File → Open
2. Controller.open_waveform_file(path):
   a. Check if already open → show warning, return
   b. Create new WaveformDB instance
   c. Call waveform_db.open(path)
   d. Extract timescale from waveform_db
   e. If not first file:
      - Compare timescale with session.waveform_files[0].timescale
      - If mismatch:
        * Show error dialog
        * Close waveform_db
        * Return False
   f. Create WaveformFileReference:
      - file_id = session.next_file_id
      - file_path = path
      - waveform_db = waveform_db
      - timescale = extracted timescale
   g. Add to session.waveform_files
   h. Increment session.next_file_id
   i. Update viewport.total_duration if new file is longer
   j. Emit session_changed event
   k. Return True
```

**Display Name Resolution:**
```
For each SignalNode in tree view:
1. Get session.waveform_files list
2. If len(waveform_files) == 1:
   - Display: node.name (original path)
3. Else (multiple files):
   - Get file_ref = get_file_by_id(session, node.file_id)
   - Get filename = basename(file_ref.file_path)
   - If node.file_id == 0 (primary file):
     * Display: node.name (no prefix for first file)
   - Else:
     * Display: f"{filename}:{node.name}"
```

**Session Save with Multiple Files:**
```
1. Create waveform_files list in JSON:
   [
     {file_id: 0, file_path: "/path/to/file1.vcd", timescale: {...}},
     {file_id: 1, file_path: "/path/to/file2.fst", timescale: {...}}
   ]
2. For each SignalNode:
   - Include file_id in serialization
3. Save next_file_id to ensure stable IDs on reload
```

**Session Load with Multiple Files:**
```
1. Read waveform_files list from JSON
2. For each file entry:
   a. Check if file exists
   b. If exists:
      - Create WaveformDB, open file
      - Validate timescale matches first file
      - Add to session.waveform_files with original file_id
   c. If missing:
      - Add to missing_files list
3. If missing_files not empty:
   - Show warning dialog
   - If user clicks Continue:
     * Remove SignalNodes with file_id in missing set
     * Update next_file_id
4. Restore next_file_id from max(loaded file_ids) + 1
5. Continue normal session loading
```

---

### Performance Considerations

**Signal Loading:**
- Each WaveformDB manages its own signal cache
- Async loading works independently per file
- No cross-file signal cache coordination needed

**Memory Usage:**
- Multiple WaveformDB instances in memory
- Each has its own hierarchy and time table
- Acceptable for typical use (2-4 files)

**Handle Disambiguation:**
- Handles are file-scoped (no global handle space)
- file_id + handle uniquely identifies a signal
- No handle collision possible

---

### Open Questions for User

1. **File Prefix Display Policy**: Should the first/primary file also show a prefix, or only subsequent files?
   - **Proposed**: First file has no prefix (cleaner for single-file workflows)

2. **Window Title Format**: When multiple files are open, what should the title show?
   - **Proposed**: "WaveformScout - file1.vcd, file2.fst" (comma-separated)

3. **File Order**: Should there be a way to reorder files in the list?
   - **Proposed**: Not in first release (can add later if needed)

4. **Relative Paths**: Should we support relative paths in session files?
   - **Proposed**: Not in first release (absolute paths only for simplicity)
