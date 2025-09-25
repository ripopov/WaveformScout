# Add Var Member to SignalNodeSignal and Fix VariableData Type

## Use Cases and Requirements Analysis

The primary goal is to add a `var: Var` member to the `SignalNodeSignal` dataclass to provide direct access to the underlying pyrox.Var object. Additionally, fix the `VariableData` TypedDict to use proper typing for its `var` field instead of `Any`.

### Core Requirements
- Add **non-optional** `var: Var` field to `SignalNodeSignal` dataclass
- Fix `VariableData.var` type from `Any` to `Var` for proper type safety
- Mark field with `compare=False` and `repr=False` (similar to the existing `signal` field)
- Ensure the field is excluded from deep copy and comparison operations
- Maintain backward compatibility with persistence layer (var won't be serialized)
- Populate var field at all construction sites using available waveform_db context
- All production code paths MUST provide a valid Var object

### Benefits
- Direct access to bit width via `node.var.bitwidth()` without lookups
- Eliminate expensive hierarchy searches like iterating through `waveform_db.hierarchy.all_vars()`
- Simplify code in multiple locations that currently call `waveform_db.get_var(handle)` or `waveform_db.var_from_handle(handle)`
- Consistent with existing pattern of having both `handle` and `signal` members
- Type safety: guaranteed var availability eliminates need for None checks
- Proper typing for VariableData eliminates Any usage

## Codebase Research

### Current SignalNodeSignal Structure
Located in `wavescout/data_model.py:127-165`:
- Extends `SignalNode` base class
- Contains: `handle`, `signal`, `format`, `is_multi_bit` fields
- `signal` field already follows the pattern we want (optional, compare=False, repr=False)
- Methods: `_comparison_state()` and `deep_copy()`

### Current VariableData Structure
Located in `wavescout/vars_view.py:19-24`:
- TypedDict with fields: `name`, `full_path`, `var_type`, `bit_range`, `var`
- The `var` field is currently typed as `Any` (should be `Var`)
- Used in `scope_tree_model.py` and `design_tree_view.py` for passing variable information

### SignalNodeSignal Construction Sites

1. **waveform_loader.py:68-76**
   - Has direct access to `var` object (passed as parameter)
   - Currently only uses var to determine bit width and format

2. **design_tree_view.py:1025-1030 and 1165-1170**
   - Two locations creating SignalNodeSignal
   - Both locations already call `self.waveform_db.get_var(handle)` immediately after construction
   - Can pass var directly during construction

3. **persistence.py:185-194 and 231-240**
   - Two deserialization paths
   - After loading, needs to populate var using `waveform_db.get_var(handle)`
   - Similar to how `signal` field is populated post-deserialization

4. **data_model.py:157-164**
   - `deep_copy()` method creates new SignalNodeSignal
   - Should exclude var from copy (like signal field)

### Code Locations That Will Be Simplified

1. **signal_renderer.py:1037-1049**
   - Currently iterates through all vars to find matching handle
   - Can be replaced with: `bit_width = node.var.bitwidth() if node.var else 32`

2. **waveform_item_model.py:329**
   - Calls `db.get_var_bitwidth(signal_node.handle)`
   - Can use: `signal_node.var.bitwidth()`

3. **signal_sampling.py:296**
   - Calls `waveform_db.get_var_bitwidth(signal.handle)`
   - Can use: `signal.var.bitwidth()`

4. **waveform_canvas.py:2227**
   - Calls `db.get_var_bitwidth(signal_node.handle)`
   - Can use: `signal_node.var.bitwidth()`

5. **waveform_controller.py:1339**
   - Calls `db.var_from_handle(node.handle)`
   - Can use: `node.var`

6. **signal_names_view.py:642**
   - Calls `db.var_from_handle(node.handle)`
   - Can use: `node.var`

7. **analysis_engine.py (multiple locations)**
   - Lines 504, 604, 683: Call `waveform_db.var_from_handle(signal_node.handle)`
   - Can use: `signal_node.var`

## Implementation Planning

### File-by-File Changes

#### 1. wavescout/vars_view.py
- **VariableData TypedDict (line ~19)**
  - Change: `var: Any` to `var: "Var"`
  - Add import: `from pyrox import Var` (or add to TYPE_CHECKING block if not runtime needed)
  - This fixes the type safety issue and eliminates Any usage

#### 2. wavescout/data_model.py
- **SignalNodeSignal class (line ~130)**
  - Add field: `var: "Var" = field(repr=False, compare=False)`  # Non-optional!
  - Import Var type: Add `from pyrox import Var` to TYPE_CHECKING block
  - Update `_comparison_state()`: Ensure var is not included (already excludes signal)
  - Update `deep_copy()`: Pass the same var reference to the copy (like we do with handle):
    ```python
    return SignalNodeSignal(
        name=self.name,
        nickname=self.nickname,
        height_scaling=self.height_scaling,
        handle=self.handle,
        var=self.var,  # Pass the same var reference
        format=format_copy,
        is_multi_bit=self.is_multi_bit,
    )
    ```

#### 3. wavescout/waveform_loader.py
- **create_signal_node function (line ~68)**
  - Add `var` parameter to SignalNodeSignal constructor
  - Pass the var object that's already available as function parameter

#### 4. wavescout/design_tree_view.py
- **_create_signal_node_from_var (line ~468)**
  - This method receives VariableData which now has properly typed `var: Var`
  - The var is already in var_data['var'], just pass it to SignalNodeSignal constructor
  - Remove redundant var lookup after construction
- **_create_signal_node_from_var (line ~1025)**
  - Get var before construction: `var = self.waveform_db.get_var(handle)`
  - Add assertion: `assert var is not None, f"Failed to get var for handle {handle}"`
  - Pass var to SignalNodeSignal constructor
  - Remove redundant var lookup after construction
- **_drop_signals_from_scope_tree (line ~1165)**
  - Same changes as above

#### 5. wavescout/persistence.py
- **_node_from_dict function (line ~185)**
  - Get var before construction: `var = waveform_db.get_var(handle) if waveform_db and handle else None`
  - Add assertion: `assert var is not None, f"Cannot deserialize signal without var for handle {handle}"`
  - Pass var to SignalNodeSignal constructor
- **_load_session_v3 function (line ~231)**
  - Same changes as above

#### 6. wavescout/signal_renderer.py
- **_calculate_analog_range function (line ~1037)**
  - Replace entire hierarchy search loop with: `bit_width = node.var.bitwidth() or 32`

#### 7. wavescout/waveform_item_model.py
- **_get_value_at_cursor function (line ~329)**
  - Replace `db.get_var_bitwidth(signal_node.handle)` with: `signal_node.var.bitwidth() or 32`

#### 8. wavescout/signal_sampling.py
- **sample_bus_signal function (line ~296)**
  - Replace `waveform_db.get_var_bitwidth(signal.handle)` with: `signal.var.bitwidth() or 32`

#### 9. wavescout/waveform_canvas.py
- **_show_value_tooltip function (line ~2227)**
  - Replace `db.get_var_bitwidth(signal_node.handle)` with: `signal_node.var.bitwidth() or 32`

#### 10. wavescout/waveform_controller.py
- **set_clock_signal function (line ~1339)**
  - Replace `var = db.var_from_handle(node.handle)` with: `var = node.var`
  - Remove the `if not var` check - var is guaranteed to exist

#### 11. wavescout/signal_names_view.py
- **_show_context_menu function (line ~642)**
  - Replace `var = db.var_from_handle(node.handle)` with: `var = node.var`
  - Update condition to just: `if is_valid_clock_signal(node.var):`

#### 12. wavescout/analysis_engine.py
- **analyze_edges function (line ~504)**
  - Replace `var = waveform_db.var_from_handle(signal_node.handle)` with: `var = signal_node.var`
  - Remove `if var:` check - var is guaranteed
- **get_sampling_times function (line ~604)**
  - Replace `var = waveform_db.var_from_handle(sampling_signal.handle)` with: `var = sampling_signal.var`
  - Remove `if not var: return []` check - var is guaranteed
- **analyze_statistics function (line ~683)**
  - Replace `var = waveform_db.var_from_handle(signal_node.handle)` with: `var = signal_node.var`
  - Remove `if var:` check - var is guaranteed

### Test Fixture Handling

For test files that create SignalNodeSignal without a real waveform_db:
- **Option 1: Create a MockVar class**
  - Implement a minimal MockVar with required methods (bitwidth, var_type, etc.)
  - Use in tests that don't have a real waveform_db

#### MockVar Implementation
Create `tests/test_utils.py` with:
```python
class MockVar:
    """Mock Var object for tests that don't have a real waveform_db."""

    def __init__(self, name: str = "test_signal", bitwidth: int = 1, var_type: str = "Wire"):
        self._name = name
        self._bitwidth = bitwidth
        self._var_type = var_type

    def name(self, hier=None) -> str:
        return self._name

    def full_name(self, hier=None) -> str:
        return self._name

    def bitwidth(self) -> int:
        return self._bitwidth

    def var_type(self) -> str:
        return self._var_type

    def is_1bit(self) -> bool:
        return self._bitwidth == 1

    def signal_handle(self) -> int:
        return -1  # Invalid handle for test purposes
```

### Implementation Order

1. **Phase 1: Add var field and update production code**
   - Add non-optional var field to SignalNodeSignal
   - Update all production construction sites to pass var
   - Add assertions to ensure var is never None in production

2. **Phase 2: Update usage sites**
   - Replace all var lookups with direct access
   - Remove unnecessary None checks since var is guaranteed

3. **Phase 3: Handle test fixtures**
   - Create MockVar class for tests
   - Update test files to provide MockVar instances

4. **Phase 4: Cleanup**
   - Remove now-unused get_var_bitwidth helper methods
   - Verify all tests pass
   - Performance testing to confirm improvements

### Performance Considerations

This change will improve performance by:
- Eliminating O(n) searches through all hierarchy variables
- Reducing repeated var lookups for the same signal
- Caching var reference at construction time

Memory impact is minimal as we're only storing an additional reference to an already-loaded object.