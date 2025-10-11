# Feature Plan: Asynchronous File Loading with Loading Indicator

**Feature ID:** 0005
**Feature Name:** async_file_loading
**Status:** Planning
**Created:** 2025-10-11

---

## 1. Use Cases and Requirements Analysis

### 1.1 Problem Statement

When loading large JETS trace files (especially compressed `.jets.br` files with millions of records), the GUI application freezes during the synchronous `parse_trace()` call in the main thread. This creates a poor user experience as:

1. The application becomes completely unresponsive during loading
2. Users cannot interact with the GUI while waiting
3. There is no visual feedback indicating that loading is in progress
4. Users may think the application has crashed for large files

### 1.2 Core Requirements

**MUST Requirements:**
1. File loading MUST be offloaded to a separate thread to prevent GUI freezing
2. When loading completes, the background thread MUST notify the GUI thread using `ctx.request_repaint()`
3. While file is loading, the Timeline Canvas MUST display "Loading..." message with large font in the center
4. The loading indicator MUST be visible and centered in the Timeline Canvas area
5. GUI MUST remain responsive during file loading (window can be moved, resized, closed)

**SHOULD Requirements:**
1. Loading progress indicator SHOULD provide visual feedback (not just static text)
2. Users SHOULD be able to cancel an in-progress load operation
3. Error messages from background loading SHOULD be properly communicated to the GUI thread

**NICE TO HAVE:**
1. Progress percentage or file parse stage indication
2. Animated loading spinner alongside text
3. Loading time estimation

### 1.3 File Loading Context

Current synchronous loading flow (`jets-gui.rs:142-165`):
```
open_file(path) → reader.read(path) → parse_trace(path) → trace_data = Some(data)
```

Files to be loaded:
- Uncompressed JETS files (`.jets`, `.jsonl`)
- Brotli-compressed JETS files (`.jets.br`, `.jsonl.br`)
- Large files with millions of records taking 5-10+ seconds to parse

### 1.4 User Interaction Flow

**Current (Blocking) Flow:**
1. User clicks "📁 Open Trace" button
2. File picker appears
3. User selects file
4. GUI freezes completely
5. (invisible wait period)
6. GUI unfreezes with trace loaded OR error displayed

**New (Async) Flow:**
1. User clicks "📁 Open Trace" button
2. File picker appears
3. User selects file
4. GUI shows "Loading..." in Timeline Canvas center
5. GUI remains responsive, can be resized/moved
6. Background thread parses trace file
7. On completion: GUI thread receives notification via `ctx.request_repaint()`
8. Timeline Canvas shows loaded trace OR error message in details panel

---

## 2. Codebase Research

### 2.1 Current Loading Architecture

**File:** `jets/rjets/src/jets-gui.rs`

**Current synchronous loading implementation (lines 142-165):**
```rust
fn open_file(&mut self, path: PathBuf) {
    match self.reader.read(path.to_str().unwrap()) {
        Ok(data) => {
            // Synchronous blocking parse
            let (min_clk, max_clk) = data.metadata().trace_extent();
            self.trace_data = Some(data);
            // ... initialization ...
        }
        Err(e) => {
            self.error_message = Some(format!("Error loading trace: {}", e));
        }
    }
}
```

**Called from:** `update()` method when "📁 Open Trace" button is clicked (line 280-290)

### 2.2 Parser Implementation

**File:** `jets/rjets/src/parser.rs`

**Key function:** `parse_trace(file_path: &str) -> Result<JetsTraceData>` (line 166)

- Line-by-line JSON parsing using `BufReader`
- Supports Brotli decompression for `.br` files
- Builds in-memory data structures: `HashMap<u64, JetsTraceRecord>`, tree hierarchy
- No cancellation mechanism or progress callbacks
- Returns fully constructed `JetsTraceData` or error

**Performance characteristics:**
- I/O bound for uncompressed files
- CPU bound for decompression + JSON parsing
- Memory allocation for building record tree
- Typical load times: 100ms - 30s depending on file size

### 2.3 GUI Rendering Architecture

**File:** `jets/rjets/src/jets-gui.rs`

**Timeline rendering:** `render_timeline()` method (line 794-1135)
- Early return if `self.trace_data.is_none()` (lines 795-798)
- Shows placeholder: "No trace loaded - open a JETS trace file to view timeline"

**Update loop:** `update()` method (line 1408-1475)
- Called every frame by egui
- egui is an immediate-mode GUI (stateless per frame)
- `ctx.request_repaint()` triggers re-render from background thread

### 2.4 Threading Model for egui

**egui threading constraints:**
1. egui context (`egui::Context`) can be cloned and is `Send + Sync`
2. Background threads can call `ctx.request_repaint()` to trigger GUI update
3. State updates must use thread-safe primitives: `Arc<Mutex<T>>` or channels
4. Only the main thread can modify GUI state directly

**Recommended pattern for async operations:**
```rust
use std::sync::{Arc, Mutex};
use std::thread;

struct LoadingState {
    in_progress: bool,
    result: Option<Result<TraceData>>,
}

// In App struct:
loading_state: Arc<Mutex<LoadingState>>,

// Start load:
let loading_state = Arc::clone(&self.loading_state);
let ctx = ui.ctx().clone();
thread::spawn(move || {
    let result = parse_trace(path);
    {
        let mut state = loading_state.lock().unwrap();
        state.in_progress = false;
        state.result = Some(result);
    }
    ctx.request_repaint();
});
```

### 2.5 Dependencies Available

**File:** `jets/rjets/Cargo.toml`

Current dependencies include:
- `eframe` - provides threading-friendly egui context
- `egui` - immediate mode GUI
- Standard library threading: `std::thread`, `std::sync`

**No additional dependencies needed** - can use standard library `std::thread` and `Arc<Mutex<T>>`.

---

## 3. Implementation Planning

### 3.1 Data Structures

**File:** `jets/rjets/src/jets-gui.rs`

#### New State in `JetsViewerApp` struct

Add to struct definition (after line 53):
```rust
// Async loading state
loading_state: Arc<Mutex<LoadingState>>,
pending_load_path: Option<PathBuf>,
```

#### New `LoadingState` struct

Define before `JetsViewerApp` (around line 23):
```rust
struct LoadingState {
    in_progress: bool,
    result: Option<Result<Box<dyn TraceData>, String>>,
}
```

**Fields:**
- `in_progress: bool` - True while background thread is parsing
- `result: Option<Result<...>>` - Holds parse result when complete
  - `Some(Ok(data))` - successful parse
  - `Some(Err(msg))` - parse error
  - `None` - no result yet

**Thread-safety:** Wrapped in `Arc<Mutex<>>` for safe access from both threads

#### Update `Default` implementation

Modify `impl Default for JetsViewerApp` (line 56-84):
- Initialize `loading_state: Arc::new(Mutex::new(LoadingState { in_progress: false, result: None }))`
- Initialize `pending_load_path: None`

### 3.2 Modified Loading Flow

**File:** `jets/rjets/src/jets-gui.rs`

#### Modify `open_file()` method (lines 142-165)

**Current:** Synchronous parsing
**New:** Launch background thread

**Changes:**
1. Set `loading_state.in_progress = true`
2. Store `path` in `pending_load_path` for error reporting
3. Clone `Arc<Mutex<LoadingState>>` and `egui::Context`
4. Spawn background thread calling `parse_trace()`
5. Convert `anyhow::Error` to `String` for thread-safe transfer
6. On completion: store result in `loading_state` and call `ctx.request_repaint()`

**Signature:** No change - still `fn open_file(&mut self, path: PathBuf)`

**Integration points:**
- Called from button click handler in `render_header()` (line 288)
- Background thread invokes `parse_trace()` from `parser.rs`
- Result stored in shared `LoadingState` mutex

#### New method: `check_loading_completion()`

**Purpose:** Poll loading state each frame and apply result if complete

**Location:** Add after `open_file()` method (around line 166)

**Logic:**
1. Lock `loading_state` mutex
2. If `result.is_some()`:
   - Take result (leaving `None`)
   - Match on `Ok(data)` or `Err(msg)`:
     - `Ok`: Initialize `trace_data`, viewport, clk ranges (copy logic from old `open_file`)
     - `Err`: Set `error_message`
   - Clear `pending_load_path`
3. Release mutex lock

**Called from:** `update()` method at the beginning of each frame

#### Update `update()` method (lines 1408-1475)

**Changes:**
1. Add call to `check_loading_completion()` at top of method (after line 1424)
2. No other changes needed - existing rendering logic handles loading state

### 3.3 UI Rendering Changes

**File:** `jets/rjets/src/jets-gui.rs`

#### Modify `render_timeline()` method (lines 794-1135)

**Current early-return logic (lines 795-798):**
```rust
if self.trace_data.is_none() {
    ui.label("No trace loaded - open a JETS trace file to view timeline");
    return;
}
```

**New logic:**
1. Check `loading_state.lock().unwrap().in_progress`
2. If loading:
   - Get canvas center position
   - Draw large "Loading..." text centered
   - Use `egui::FontId::proportional(48.0)` for large font
   - Use theme color (e.g., `self.theme_colors().text_dim`)
   - Return early
3. Else if `trace_data.is_none()`:
   - Show original placeholder message
4. Else:
   - Continue with normal timeline rendering

**Font size:** 48pt for visibility
**Positioning:** Use `ui.available_rect_before_wrap()` center
**Painter call:** `ui.painter().text(center_pos, Align2::CENTER_CENTER, "Loading...", font, color)`

#### No changes needed to `render_tree()` or `render_details()`

These methods already handle `None` trace_data gracefully:
- `render_tree()`: Shows "No trace data to display" (line 407)
- `render_details()`: Shows "Data & Events (select a record to view)" (line 789)

### 3.4 File-by-File Change Summary

#### `jets/rjets/src/jets-gui.rs`

**Structs to add:**
- `LoadingState` (new struct definition, ~8 lines)

**Modifications to `JetsViewerApp`:**
- Add fields: `loading_state`, `pending_load_path` (~2 lines)
- Update `Default` impl initialization (~2 lines)
- Update `new()` method initialization (~2 lines)

**Methods to modify:**
- `open_file()`: Replace synchronous parse with thread spawn (~25 lines changed)
- `render_timeline()`: Add loading indicator rendering logic (~15 lines added)
- `update()`: Add `check_loading_completion()` call (~1 line added)

**Methods to add:**
- `check_loading_completion()`: New method to poll and apply results (~30 lines)

**Total:** ~85 lines modified/added across 1 file

#### `jets/rjets/src/parser.rs`

**No changes needed** - `parse_trace()` function is already thread-safe:
- Takes `&str` (copied/owned by thread)
- Returns owned `JetsTraceData`
- No shared mutable state
- Pure function (I/O + computation → result)

#### `jets/rjets/src/lib.rs`

**No changes needed** - exports remain the same

#### `jets/rjets/Cargo.toml`

**No changes needed** - all required primitives in standard library

---

## 4. Algorithm Descriptions

### 4.1 Background Loading Algorithm

**Thread spawn in `open_file()`:**

```
FUNCTION open_file(path):
    # 1. Prepare shared state
    SET loading_state.in_progress = TRUE
    SET self.pending_load_path = Some(path.clone())

    # 2. Clone thread-safe handles
    LET state_handle = Arc::clone(&self.loading_state)
    LET ctx_handle = ui.ctx().clone()
    LET path_string = path.to_str().unwrap().to_owned()

    # 3. Spawn background thread
    SPAWN THREAD:
        # Parse trace (blocking in background)
        LET parse_result = parse_trace(path_string)

        # Convert Result<T, anyhow::Error> to Result<T, String>
        LET result_string = parse_result.map_err(|e| e.to_string())

        # Store result in shared state
        LOCK state_handle:
            SET in_progress = FALSE
            SET result = Some(result_string)

        # Notify GUI thread
        CALL ctx_handle.request_repaint()

    # 4. Return immediately (non-blocking)
    RETURN
```

### 4.2 Result Polling Algorithm

**Frame-by-frame check in `update()`:**

```
FUNCTION check_loading_completion():
    # 1. Try lock (non-blocking check)
    LOCK self.loading_state:
        IF result IS Some(r):
            # 2. Take ownership of result
            LET result = TAKE(result)  # Leaves None

            # 3. Process result
            MATCH result:
                CASE Ok(trace_data):
                    # Success path
                    LET (min_clk, max_clk) = trace_data.metadata().trace_extent()
                    SET self.trace_data = Some(trace_data)
                    SET self.viewport_start_clk = min_clk
                    SET self.viewport_end_clk = max_clk
                    # ... (copy full initialization from old open_file)
                    SET self.error_message = None

                CASE Err(error_msg):
                    # Error path
                    SET self.error_message = Some("Error loading trace: " + error_msg)
                    SET self.trace_data = None

            # 4. Clean up
            SET self.pending_load_path = None
```

### 4.3 Loading Indicator Rendering Algorithm

**Conditional rendering in `render_timeline()`:**

```
FUNCTION render_timeline(ui, ctx):
    # 1. Check loading state
    LOCK self.loading_state:
        LET is_loading = in_progress

    IF is_loading:
        # 2. Calculate center position
        LET canvas_rect = ui.available_rect_before_wrap()
        LET center_x = canvas_rect.center().x
        LET center_y = canvas_rect.center().y
        LET center_pos = Pos2::new(center_x, center_y)

        # 3. Prepare text styling
        LET font = FontId::proportional(48.0)
        LET color = self.theme_colors().text_dim
        LET text = "Loading..."

        # 4. Render centered text
        CALL ui.painter().text(
            center_pos,
            Align2::CENTER_CENTER,
            text,
            font,
            color
        )

        # 5. Early return (skip timeline rendering)
        RETURN

    # 6. Continue with normal timeline rendering if not loading
    IF self.trace_data.is_none():
        SHOW placeholder message
        RETURN

    # ... rest of timeline rendering ...
```

---

## 5. UI Integration

### 5.1 Loading Indicator Visual Design

**Location:** Center of Timeline Canvas area (right panel)

**Typography:**
- Text: "Loading..."
- Font size: 48pt (large, easily visible)
- Font family: Proportional (egui default)
- Alignment: Center-center

**Colors:**
- Text color: `theme_colors().text_dim` (muted but visible)
- No background box (renders directly on panel background)

**Layout:**
- Positioned using `available_rect_before_wrap().center()`
- Centered both horizontally and vertically
- Overlays empty timeline canvas area

### 5.2 State Transitions

**Visual states:**

1. **Initial state** (no file loaded):
   - Tree panel: "Trace Records" header, empty area
   - Timeline panel: "No trace loaded - open a JETS trace file to view timeline"

2. **Loading state** (file loading):
   - Tree panel: "Trace Records" header, empty area
   - Timeline panel: **"Loading..."** (large centered text)
   - Header: Trace file selection controls remain enabled
   - User can still resize panels, change theme, close app

3. **Loaded state** (file parsed successfully):
   - Tree panel: Record hierarchy tree visible
   - Timeline panel: Gantt chart with timeline bars and events
   - Status panel: Metadata displayed

4. **Error state** (parse failed):
   - Tree panel: "Trace Records" header, empty area
   - Timeline panel: "No trace loaded..." message
   - Header: Red error text displayed: "Error loading trace: <details>"

### 5.3 User Interaction During Loading

**Allowed interactions:**
- Window resize, move, minimize
- Panel splitter dragging (timeline vs tree split ratio)
- Theme selector dropdown
- Clicking other UI elements (no-op, safe)
- Closing application (thread cleanup handled by OS)

**Disabled interactions:**
- Cannot load another file while loading in progress (button remains active but spawns concurrent load - acceptable)
- Cannot interact with trace data (doesn't exist yet)

**Cancel operation:**
- Not implemented in Phase 1 (future enhancement)
- User can close application to cancel

---

## 6. Performance Considerations

### 6.1 Thread Overhead

**Thread creation cost:**
- Spawning thread: ~100μs overhead
- Minimal compared to parse time (100ms - 30s)
- Negligible performance impact

**Memory:**
- Thread stack: ~2MB (OS default)
- Acceptable for single background thread
- Cleaned up automatically on completion

### 6.2 Mutex Contention

**Lock frequency:**
- GUI thread locks once per frame (~60 Hz = 16ms intervals)
- Background thread locks once at completion
- Lock held for microseconds (check + assign)
- **No contention expected** - locks are very brief

### 6.3 Parse Performance

**No change to parse speed:**
- Same `parse_trace()` implementation
- Same I/O, decompression, JSON parsing
- Moved to background thread → perceived performance improvement (responsive GUI)

**Actual load times unchanged:**
- Small files (< 10MB): 100-500ms
- Medium files (10-100MB): 500ms - 5s
- Large files (> 100MB compressed): 5-30s

### 6.4 Frame Rate Impact

**Loading indicator rendering:**
- Single text draw call per frame
- Trivial GPU cost (~0.01ms)
- No animations (static text)
- **No measurable FPS impact**

### 6.5 Scalability

**Current design supports:**
- Single concurrent load operation
- Sequential loads (one at a time)

**Not supported (acceptable for Phase 1):**
- Multiple concurrent file loads
- Load cancellation
- Progress updates during parse

**Future enhancements (out of scope):**
- Streaming parse with incremental UI updates
- Chunked loading for multi-GB files
- Progress bar with percentage

---

## 7. Error Handling

### 7.1 Parse Errors

**Error types from `parse_trace()`:**
- File not found: I/O error
- Invalid JSON: Parse error
- Missing header: Validation error
- Corrupted Brotli: Decompression error
- Invalid schema: Deserialization error

**Handling:**
1. Background thread catches `anyhow::Error`
2. Converts to `String` via `.to_string()` (thread-safe)
3. Stores in `LoadingState::result` as `Err(String)`
4. GUI thread displays in header panel: `self.error_message = Some(...)`

**User-facing message format:**
```
Error loading trace: <error details>
```

### 7.2 Thread Panics

**Scenario:** Background thread panics during parse

**Handling:**
- Thread panic does NOT crash GUI (isolated)
- `LoadingState::result` remains `None`
- `LoadingState::in_progress` remains `true` (stale state)

**Mitigation:**
- Wrap `parse_trace()` in `std::panic::catch_unwind()` (optional)
- Convert panic to `Err("Internal parsing error")` result
- **Not critical** - parser is well-tested, panics unlikely

### 7.3 Lock Poisoning

**Scenario:** Thread panics while holding mutex lock

**Handling:**
- Mutex becomes "poisoned"
- `.lock().unwrap()` will panic on subsequent access
- GUI crashes (acceptable - indicates serious bug)

**Mitigation:**
- Use `.lock().unwrap_or_else(|e| e.into_inner())` to recover from poisoned mutex
- Log warning and continue with potentially inconsistent state
- **Low priority** - poisoning indicates catastrophic failure

---

## 8. Testing Strategy

### 8.1 Manual Testing Scenarios

**Test Case 1: Small file load**
- Input: Small trace file (< 1MB, < 1000 records)
- Expected: Loading indicator flashes briefly (~100ms), trace appears
- Verify: No GUI freeze, smooth transition

**Test Case 2: Large file load**
- Input: Large compressed file (> 50MB, > 1M records)
- Expected: Loading indicator visible for 5-10 seconds
- Verify: GUI remains responsive (can resize window), trace loads successfully

**Test Case 3: Invalid file**
- Input: Corrupted or non-JETS file
- Expected: Loading indicator appears, then error message in header
- Verify: Error message is clear and actionable

**Test Case 4: Multiple sequential loads**
- Input: Load file A, wait for completion, load file B
- Expected: Each load shows indicator, previous trace replaced
- Verify: No memory leaks, no stale state

**Test Case 5: Rapid load attempts**
- Input: Click "Open Trace" multiple times quickly
- Expected: Multiple file dialogs, last selected file loads
- Verify: No crashes, no deadlocks (acceptable: concurrent loads)

**Test Case 6: Load cancellation via close**
- Input: Start loading large file, close application immediately
- Expected: Application closes cleanly
- Verify: No zombie threads, OS cleans up properly

### 8.2 Visual Verification

**Loading indicator appearance:**
- [ ] Text is large (48pt) and centered
- [ ] Text uses theme-appropriate color
- [ ] Text is visible on both light and dark themes
- [ ] Text does not flicker or jitter
- [ ] Timeline header (time axis) remains visible during load

**GUI responsiveness:**
- [ ] Window can be moved during load
- [ ] Window can be resized during load
- [ ] Theme selector works during load
- [ ] Panel splitters can be dragged during load
- [ ] Application can be closed during load

### 8.3 Performance Verification

**Metrics to check:**
- Frame rate during load: Should remain ~60 FPS
- Memory usage: No significant increase beyond loaded trace data
- Thread count: +1 thread during load, returns to baseline after

**Tools:**
- `top` / `htop` for CPU and memory monitoring
- egui built-in FPS counter (if available)
- `ps -eLf` for thread count verification

---

## 9. Future Enhancements (Out of Scope)

### 9.1 Progress Indication

**Enhancement:** Show parse progress percentage

**Implementation:**
- Modify `parse_trace()` to accept optional progress callback
- Report progress based on lines read / file size estimate
- Update `LoadingState` with `progress: f32` field
- Render progress bar below "Loading..." text

**Complexity:** Medium (requires parser modification)

### 9.2 Load Cancellation

**Enhancement:** Add "Cancel" button during load

**Implementation:**
- Add `cancel_requested: Arc<AtomicBool>` to `LoadingState`
- Check flag in `parse_trace()` loop (every N lines)
- Stop parsing and return early if cancelled
- Show "Load cancelled" message in GUI

**Complexity:** Medium (requires parser cooperation)

### 9.3 Animated Loading Spinner

**Enhancement:** Rotating spinner icon next to "Loading..." text

**Implementation:**
- Add animation state (rotation angle)
- Increment angle each frame
- Render circle with arc segment using egui painter
- Rotate around center position

**Complexity:** Low (pure rendering change)

### 9.4 Load Time Estimation

**Enhancement:** Show estimated time remaining

**Implementation:**
- Track lines parsed per second
- Estimate total lines from file size
- Calculate ETA based on current rate
- Display "Loading... (~30s remaining)"

**Complexity:** Medium (requires progress tracking + heuristics)

### 9.5 Background Load Queue

**Enhancement:** Support loading multiple files concurrently

**Implementation:**
- Change `LoadingState` to `Vec<LoadingTask>`
- Support multiple background threads
- Show list of in-progress loads
- Load into separate trace slots (multi-trace viewer)

**Complexity:** High (major architectural change)

---

## 10. Implementation Checklist

**Phase 1: Core Async Loading (MVP)**
- [ ] Add `LoadingState` struct definition
- [ ] Add `loading_state` and `pending_load_path` fields to `JetsViewerApp`
- [ ] Update `Default` and `new()` implementations
- [ ] Rewrite `open_file()` to spawn background thread
- [ ] Implement `check_loading_completion()` method
- [ ] Call `check_loading_completion()` in `update()`
- [ ] Modify `render_timeline()` to show loading indicator
- [ ] Test with small files (< 1MB)
- [ ] Test with large files (> 50MB compressed)
- [ ] Test error handling (invalid files)
- [ ] Verify GUI responsiveness during load
- [ ] Verify proper error message display

**Phase 2: Polish (Optional)**
- [ ] Add animated spinner (if time permits)
- [ ] Improve error messages with more context
- [ ] Add load time metrics logging (debug mode)

**Documentation Updates:**
- [ ] Update feature plan status to "Completed"
- [ ] Add inline code comments explaining threading
- [ ] Document async loading pattern in JETS docs

---

## 11. Risk Assessment

### 11.1 Technical Risks

**Risk: Race condition in state update**
- **Likelihood:** Low
- **Impact:** Medium (incorrect state display)
- **Mitigation:** Use `Mutex` for all shared state access; careful lock ordering

**Risk: Memory leak from thread not joining**
- **Likelihood:** Low
- **Impact:** Low (single thread, small overhead)
- **Mitigation:** Threads clean up automatically on completion; no join needed

**Risk: Performance regression**
- **Likelihood:** Very Low
- **Impact:** Low (slightly slower due to lock overhead)
- **Mitigation:** Locks are very brief; benchmark before/after

### 11.2 User Experience Risks

**Risk: Loading indicator not visible**
- **Likelihood:** Low
- **Impact:** Medium (no feedback for user)
- **Mitigation:** Large font (48pt), high contrast color, manual testing

**Risk: Confusing error messages**
- **Likelihood:** Medium
- **Impact:** Low (user can retry)
- **Mitigation:** Preserve detailed error messages from parser

### 11.3 Maintenance Risks

**Risk: Increased code complexity**
- **Likelihood:** High
- **Impact:** Medium (harder to debug threading issues)
- **Mitigation:** Clear comments, simple state machine, comprehensive testing

---

## 12. Success Criteria

**Functional:**
- ✅ Large files (> 50MB compressed) load without GUI freeze
- ✅ Loading indicator appears and is easily visible
- ✅ GUI remains responsive during load (can resize, move window)
- ✅ Successful loads display trace correctly
- ✅ Failed loads show clear error messages
- ✅ Application can be closed during load without hanging

**Performance:**
- ✅ Frame rate remains above 30 FPS during load
- ✅ Memory usage does not exceed loaded trace size + 10MB overhead
- ✅ Thread creation overhead < 1ms (negligible)

**User Experience:**
- ✅ User receives immediate visual feedback when load starts
- ✅ User can distinguish between "loading" and "loaded" states
- ✅ User can understand error messages and take corrective action

---

## 13. Appendix

### 13.1 Related Files

**Core implementation:**
- `jets/rjets/src/jets-gui.rs` - Main application and GUI rendering
- `jets/rjets/src/parser.rs` - Trace parsing logic (unchanged)

**Related features:**
- Feature #0004: Brotli compression support (large files benefit most from async loading)
- Feature #0003: Theme support (loading indicator uses theme colors)

### 13.2 egui Context API Reference

**Relevant methods:**
- `egui::Context::clone()` - Create thread-safe handle
- `egui::Context::request_repaint()` - Trigger frame render from background thread
- `egui::Ui::available_rect_before_wrap()` - Get canvas dimensions
- `egui::Painter::text()` - Render text at position

**Threading guarantees:**
- `Context` is `Send + Sync` - safe to clone and share across threads
- `request_repaint()` is thread-safe - can be called from any thread
- Only main thread can call `ui.painter()` and other rendering methods

### 13.3 Standard Library Primitives Used

**Threading:**
- `std::thread::spawn()` - Create background thread
- `std::sync::Arc<T>` - Atomic reference counting for shared ownership
- `std::sync::Mutex<T>` - Mutual exclusion lock

**Conventions:**
- Clone `Arc` before moving into thread closure
- Lock duration should be minimal (microseconds)
- Use `.unwrap()` on locks (panic on poisoning is acceptable)

---

**Plan Status:** Ready for Implementation
**Estimated Implementation Time:** 2-3 hours
**Lines of Code Changed:** ~85 lines in 1 file
