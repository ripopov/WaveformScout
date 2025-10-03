# Codex Bugfix Plan – Support VCD Variables With Dotted Names

## Problem Recap
VCD variables may legally contain dots (`.`) inside their local identifier (e.g. `inner.pready`), but the current WaveformScout stack assumes every dot separates hierarchy levels. As soon as we see a full path like `apb_testbench.inner.pready`, the code splits on every dot and mis-classifies the segments (`apb_testbench` as scope, `inner` as scope, `pready` as the variable). That breaks lookups and downstream features across Python and Rust layers:

- PyO3 bindings (`Hierarchy.find_var_by_full_name`, `Waveform.get_signal_from_path`) split dotted strings.
- Python-side database, models, and widgets convert names with `split('.')` for navigation, selection, persistence, and snippets.
- Data model stores `TreeNode.name` as the flattened full path, so we lose information about original scope/local identifier boundaries.

## Goals / Acceptance Criteria
- Accurately represent hierarchy scopes and variable local names even when locals contain dots.
- End-to-end abilities must work with dotted variables: add to waveform, search by full path, navigate to scope, save/load sessions, snippet workflows.
- Refactor `TreeNode` so it stores the local name and exposes `full_name()` + `path()` helpers instead of persisting the flattened string.
- All public APIs that accept hierarchical locations should take an explicit list (scope segments + local identifier) rather than inferring from dotted strings.
- Keep mypy (`--strict`) and the test suite green.

## Architectural Strategy
1. **Adopt explicit path segments** throughout the stack. Represent hierarchical locations as `tuple[str, ...]` in Python and `Vec<String>` in Rust bindings. The final element is always the local identifier; preceding elements are scopes.
2. **Store local identifiers in the data model.** `TreeNode` will keep `local_name` and derive its full path from its ancestry. `SignalNode` tracks scope segments (immutable tuple) sourced from pyrox metadata.
3. **Extend pyrox/Wellen bindings** so callers can request scope segments without relying on string parsing. Replace dotted-string lookups with path-based APIs.
4. **Update all consumers** (WaveformDB, models, widgets, persistence) to use the new helpers. Anything that previously did `name.split('.')` must now operate on `TreeNode.path()` or the explicit segment list carried by domain objects.
5. **Add regression coverage** to lock the behaviour for dotted names at the Python layer and across the rust binding surface.

## Detailed Work Plan
### 1. Data Model Restructuring (Python)
- Introduce `NodePath = tuple[str, ...]` (or similar) in `wavescout/core/data_model.py` along with helpers to join/split while preserving immutability.
- Refactor `TreeNode` dataclass:
  - Replace `name: str` with `local_name: str` and `scope_path: NodePath` (empty tuple for root-level nodes, optional for ad-hoc UI groups).
  - Provide `def full_name(self) -> str` that joins `(*self.scope_path, self.local_name)` with `'.'` when applicable.
  - Provide `def path(self) -> list[str]` returning list(scope segments + [local_name]) for convenience.
  - Update `__repr__`, `_comparison_state`, `deep_copy`, and equality helpers to account for the new fields.
- Adjust `SignalNode` / `GroupNode` construction to pass the new parameters and ensure `deep_copy` duplicates `scope_path` correctly.

### 2. Signal Node Creation & Session Assembly
- Update `wavescout/core/waveform_loader.py:create_signal_node_from_var` to:
  - Pull scope segments from pyrox (`Var`) rather than inferring from `full_name`.
  - Populate `scope_path` with the hierarchy segments (excluding the var local name) and `local_name` with the raw identifier (which may contain dots).
- Audit other call sites that instantiate `SignalNode` or `GroupNode` directly (`waveform_controller`, `design_tree_view`, tests) and ensure they provide the correct scope/local breakdown instead of a flattened string.
- Provide small helper(s) (e.g. `compose_scope_path(var: Var, hierarchy: pyrox.Hierarchy) -> NodePath`) to keep scope derivation consistent.

### 3. Pyrox / Rust Binding Changes
- Extend `Var` in `pyrox/src/lib.rs` with a new `fn scope_path(&self, hier: Bound<Hierarchy>) -> Vec<String>` that walks `Var::parent()` to collect scope names in order.
- Replace `Hierarchy.find_var_by_full_name` with `find_var_by_path(path: Vec<String>)`, validating that `path.len() >= 1` and splitting scopes vs local name without string parsing.
- Update Python exposure accordingly (new method signature, rename call sites).
- Adjust `Waveform.get_signal_from_path` to accept a `Vec<String>` path instead of a dotted `String`; keep a Python shim to accept list input and join only when logging.
- Remove remaining uses of `.split('.')` in Rust (including `pywellen` helper) and migrate to the new path-based behaviour. If pywellen must still accept dotted strings from other entry points, gate them behind a minimal shim that delegates to the new API instead of splitting blindly.
- Update associated unit tests in `pyrox`/`wellen` if they exist or add new ones to exercise dotted local names.

### 4. WaveformDB & Controller Updates (Python)
- Change `WaveformDB.find_handle_by_path` to accept `Sequence[str]` (scope + local) and update all call sites to supply structured paths directly.
- Use the new pyrox `find_var_by_path` and `Var.scope_path` to look up handles with explicit segments; remove any `split('.')` logic inside the database or controller.
- Ensure async loading queues, cache keys, and event payloads continue to use handles; no additional work expected.
- Update anywhere `Var.name(hierarchy)` was assumed to be the unpacked leaf (e.g. analysis code) so that comparisons use `SignalNode.local_name` / `full_name()` appropriately.

### 5. UI Models & Widgets
- `WaveformItemModel`: stop splitting `node.name`; call `node.full_name()` and `node.path()` helpers. When trimming hierarchy levels for display, slice `node.path()` instead of `split('.')`.
- `SignalNamesView`, `SignalValuesView`, and delegates: swap usage of string splits with the new helper. Update drag/drop payloads so they transmit structured paths (serialize both `local_name` and `scope_path`).
- `DesignTreeView` and `VarsView`: maintain the `DesignTreeNode` API but ensure lookups use explicit scope lists. When constructing a `SignalNode`, pass `scope_path` (list of scope names from the tree) and `local_name` (node name, even if dotted). Update navigation routines (`navigate_to_scope`, `_find_scope_by_path`) to consume lists provided by `TreeNode.path()` instead of raw strings.
- Event bus payloads that currently emit dotted strings (e.g. `navigate_to_scope_requested: Signal(str, str)`) may need companion structured payloads or inline conversion using the stored path; when a string is required, build it with `TreeNode.full_name()` instead of manual splitting.

### 6. Persistence, Sessions & Snippets
- Update `_serialize_node` / `_deserialize_node` in `wavescout/core/persistence.py`:
  - Persist `scope_path` (list) and `local_name` (string).
- Adjust snippet serialisation helpers to store relative scope lists plus local names. Update snippet JSON schema version if necessary to reflect the structural change.
- Ensure `Var.placeholder()` and other placeholder constructs can provide scope/local information (likely empty tuple/local name) so tests keep functioning.

### 7. Tests & Fixtures
- Add regression tests to guard dotted-name behaviour:
  - WaveformDB integration test loading `test_inputs/apb_sim_2scope.vcd` verifying `find_handle_by_path` works when the local name contains dots and when both scope + local names have dots.
  - UI model/unit tests ensuring `TreeNode.full_name()` reconstructs the correct string and that selection/hierarchy trimming respects dotted locals.
  - Persistence round-trip test saving a session/snippet containing dotted names and reloading it.
  - Rust-side test (unit or integration) covering `Hierarchy::find_var_by_path` with dotted locals.
- Update existing tests that rely on `split('.')[-1]` (e.g. `tests/test_snippet_integration.py`, `tests/test_analysis_window.py`) to use the new helpers or supply `scope_path` explicitly.
- Maintain or enhance fixtures that mock `Var`; ensure mocks expose `scope_path` to match the new protocol expectations.

### 8. Validation & Tooling
- Run `QT_QPA_PLATFORM=offscreen make test` to cover Python-side regressions.
- Execute relevant targeted tests if runtime is large (e.g. waveform DB, snippets, persistence modules).
- Run `make typecheck` to confirm strict typing compliance after signature changes.
- Rebuild pyrox via `poetry run build-pyrox` (or `make install` as appropriate) to ensure Rust changes compile.

## Risks & Mitigations
- **Large touch surface.** Mitigate by staging changes: update data model first, then pyrox, then consumers, running tests between steps.
- **Performance hit from path scans.** Cache mappings (`full_name` → `NodePath`) in `WaveformDB` to avoid repeated tree walks when handling user strings.
- **Session format change.** Document that previously saved sessions/snippets need regeneration after the upgrade.
- **Rust/Python interface mismatch.** Update PyO3 signatures and regenerate bindings carefully; add type hints and mypy stubs if needed.

## Follow-Ups (Nice-to-Haves)
- Update developer documentation (docs/features, README) to describe the new path semantics and helper APIs.
- Publish release notes covering the new session/snippet format so users can recreate saved setups if needed.
- Consider introducing a small `Path` value object shared across modules to further reduce ad-hoc handling.

