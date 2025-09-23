# SignalNode Signal Reference Implementation Plan

## 1. Use Cases and Requirements Analysis

### Core Requirement
Add a `signal` field to `SignalNode` that holds a reference to the actual `Signal` object from the backend. This will eliminate redundant `waveform_db.get_signal()` calls during rendering and value queries.

### Specific Requirements from User
- Add `signal: Optional[Signal]` field to `SignalNode` dataclass
- Populate this field when SignalNode instances are created in interactive mode (when adding signals from design tree)
- Do NOT persist the Signal reference to JSON (session files should remain backend-agnostic)
- Reload Signal references from `waveform_db` when restoring a session
- Use the cached Signal reference directly in:
  - `WaveformItemModel._value_at_cursor()` - instead of calling `db.get_signal(node.handle)`
  - `signal_renderer.py` functions - instead of calling `waveform_db.get_signal(handle)`

### Performance Benefits
- Eliminates repeated `get_signal()` lookups during rendering (called for every visible signal on every paint)
- Reduces overhead in value queries at cursor position
- Improves responsiveness when scrolling or updating the display

## 2. Codebase Research

### Current SignalNode Structure
The `SignalNode` dataclass in `wavescout/data_model.py` currently has:
- `handle: Optional[SignalHandle]` - backend-specific identifier
- `name: str` - full hierarchical signal name
- `format: DisplayFormat` - rendering configuration
- `instance_id: SignalNodeID` - unique instance identifier
- No Signal reference field

### Signal Loading Patterns

#### WaveformItemModel._value_at_cursor (Line 194-209)
```python
# Current implementation
signal_obj = db.get_signal(node.handle)  # Line 202
if not signal_obj:
    return ""
query = signal_obj.query_signal(max(0, self._session.cursor_time))
```

#### signal_renderer.py (Line 547)
```python
# Current implementation in _get_analog_range
signal_obj = waveform_db.get_signal(handle)  # Line 547
```

### SignalNode Creation Points

#### From Design Tree (design_tree_view.py)
- Line 190-195: Creates SignalNode when adding from hierarchy browser
- Line 504-509: Similar creation in another context
- Currently only sets `name`, `handle`, `format`, and `is_multi_bit`

#### From Persistence (persistence.py)
- Line 123-134: Creates SignalNode when loading from JSON
- Line 266-278: Creates SignalNode for legacy format

#### Handle Resolution (persistence.py)
- Line 54-83: `_resolve_signal_handles()` - Already resolves handles after loading
- This is where we'll add Signal object loading

### Backend Signal Type
From `pyrox/pyrox.pyi`:
- `class Signal` (Line 90) with methods:
  - `value_at_time(time: Time) -> Optional[SignalValue]`
  - `query_signal(query_time: Time) -> QueryResult`
  - `all_changes()` returns iterator

## 3. Implementation Planning

### File-by-File Changes

#### wavescout/data_model.py
**Changes Required:**
- Add import: `from pyrox import Signal` under TYPE_CHECKING block
- Add new field to SignalNode dataclass after `handle` field:
  ```python
  signal: Optional["Signal"] = field(default=None, repr=False, compare=False)
  ```
- Set `repr=False` to keep string representation clean
- Set `compare=False` to exclude from equality checks (signals are runtime objects)

#### wavescout/design_tree_view.py
**Functions to Modify:**
- `_create_signal_node()` (Lines 188-195 and 502-509)
- After creating SignalNode, immediately load Signal object:
  ```python
  # After creating node, load Signal if handle exists
  if node.handle is not None and self.waveform_db:
      node.signal = self.waveform_db.get_signal(node.handle)
  ```

#### wavescout/persistence.py
**Functions to Modify:**
- `_serialize_node()` (Lines 21-51)
  - No changes needed - Signal should NOT be serialized

- `_resolve_signal_handles()` (Lines 54-83)
  - After resolving handle (Line 79-80), also load Signal object:
    ```python
    # After node.handle = handle
    if handle is not None:
        node.signal = waveform_db.get_signal(handle)
    ```

#### wavescout/waveform_item_model.py
**Functions to Modify:**
- `_value_at_cursor()` (Lines 194-209)
  - Replace `signal_obj = db.get_signal(node.handle)` with:
    ```python
    signal_obj = node.signal
    if not signal_obj:
        return ""  # Group nodes have no signal
    ```

#### wavescout/signal_renderer.py
**Functions to Modify:**
- `_get_analog_range()` (Line 547)
  - Accept SignalNode instead of just handle
  - Use `node.signal` directly instead of `waveform_db.get_signal(handle)`

- Update callers of `_get_analog_range()` to pass the full node

#### wavescout/waveform_controller.py
**Functions to Check:**
- Any node creation/cloning operations should NOT copy Signal references
- `deep_copy()` in SignalNode already creates new instance without parent
- Signal field with `field(default=None)` won't be copied by default

### Integration Points

#### Session Loading Flow
1. JSON loaded → SignalNode created without Signal
2. `_resolve_signal_handles()` called → handles resolved AND Signals loaded
3. SignalNodes now have valid Signal references for current backend

#### Interactive Addition Flow
1. User adds signal from design tree
2. `_create_signal_node()` creates node with handle
3. Signal immediately loaded and cached in node
4. Node added to session with Signal already populated

#### Rendering Flow
1. `WaveformCanvas.paintEvent()` triggered
2. Calls renderer with SignalNode (has cached Signal)
3. Renderer uses `node.signal` directly - no DB lookup
4. Same for value queries at cursor

### Performance Considerations
- Signal objects are lightweight references (not data copies)
- Already created by backend when waveform loads
- Caching them eliminates hash lookups in backend's signal map
- No memory overhead - same objects, just cached references

### Signal Field Optionality
- Signal field is Optional because Group nodes have no signal handle/data
- Signal nodes will always have their Signal reference populated when handle exists
- No fallback to `waveform_db.get_signal()` needed - Signal should be loaded at creation/restoration time

### Testing Implications
- Existing tests should continue to work (Signal field defaults to None)
- May need to update tests that create mock SignalNodes
- Persistence tests remain unchanged (Signal not serialized)