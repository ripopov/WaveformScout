# JETS Feature Plan: Theme Support with Color Schemes

**Feature ID:** 0003
**Feature Name:** Theme Support with Color Schemes
**Author:** JETS Agentic Coding Feature Architect
**Date:** 2025-10-11
**Target Version:** JETS v0.3.0

---

## 1. Use Cases and Requirements Analysis

### 1.1 Problem Statement

The current JETS GUI (`jets-gui.rs`) implements a simple binary dark/light mode toggle (lines 30, 269-275, 1294-1299). This approach has several limitations:

1. **Limited Customization**: Users cannot choose from popular community themes (Dracula, One Dark Pro) that they use in their IDEs
2. **Poor Extensibility**: Adding new themes requires modifying the main application code
3. **Inconsistent Color Management**: Theme colors are hardcoded throughout the GUI code rather than centralized
4. **No Theme Persistence**: Theme selection is not saved between sessions
5. **Suboptimal UX**: Binary button toggle doesn't scale well for multiple theme options

### 1.2 Solution Overview

Implement a comprehensive theming system with the following components:

1. **Theme Module** (`jets/rjets/src/theme.rs`): Centralized theme definition and management
2. **Built-in Themes**: Support for:
   - Light (existing egui default)
   - Dark (existing egui default)
   - Dracula (Official Dracula theme palette)
   - One Dark Pro (VSCode One Dark Pro palette)
3. **Theme Selector UI**: Replace binary Light/Dark button with dropdown ComboBox
4. **Color Palette Management**: Centralized color definitions for all UI elements
5. **Theme Application**: Consistent theme application across all GUI components

### 1.3 Functional Requirements

#### FR-1: Theme Data Structures
**Priority:** MUST HAVE

**Description:** Define Rust data structures to represent complete theme color palettes.

**Acceptance Criteria:**
- `Theme` struct contains all necessary color definitions
- Support for background, foreground, accent, semantic colors (success/warning/error)
- Support for syntax highlighting colors (used in timeline record colors)
- Each theme includes metadata (name, description, author)
- Themes are cloneable and serializable

**Data Model:**
```rust
pub struct Theme {
    pub name: String,
    pub description: String,
    pub colors: ThemeColors,
}

pub struct ThemeColors {
    // Background colors
    pub background: Color32,
    pub panel_background: Color32,
    pub extreme_background: Color32,

    // Foreground colors
    pub text: Color32,
    pub text_dim: Color32,
    pub text_strong: Color32,

    // Interactive colors
    pub selection: Color32,
    pub hover: Color32,
    pub border: Color32,

    // Syntax/semantic colors (for timeline bars and events)
    pub red: Color32,
    pub orange: Color32,
    pub yellow: Color32,
    pub green: Color32,
    pub cyan: Color32,
    pub blue: Color32,
    pub purple: Color32,
    pub magenta: Color32,
    pub gray: Color32,
}
```

---

#### FR-2: Built-in Theme Definitions
**Priority:** MUST HAVE

**Description:** Implement four built-in themes with exact color palettes from official specifications.

**Acceptance Criteria:**
- **Light Theme**: Uses egui default light visuals as baseline
- **Dark Theme**: Uses egui default dark visuals as baseline
- **Dracula Theme**: Official Dracula color palette (draculatheme.com/spec)
- **One Dark Pro Theme**: Official One Dark Pro palette (Binaryify/OneDark-Pro)
- All color values match official specifications exactly
- Each theme provides complete color coverage (no missing colors)

**Official Color References:**

**Dracula Theme Colors:**
- Background: `#282a36`
- Current Line: `#44475a`
- Foreground: `#f8f8f2`
- Comment: `#6272a4`
- Cyan: `#8be9fd`
- Green: `#50fa7b`
- Orange: `#ffb86c`
- Pink: `#ff79c6`
- Purple: `#bd93f9`
- Red: `#ff5555`
- Yellow: `#f1fa8c`

**One Dark Pro Theme Colors:**
- Background: `#282c34`
- Foreground: `#abb2bf`
- Light Red: `#e06c75`
- Dark Red: `#be5046`
- Green: `#98c379`
- Light Yellow: `#e5c07b`
- Dark Yellow: `#d19a66`
- Blue: `#61afef`
- Magenta: `#c678dd`
- Cyan: `#56b6c2`
- Gutter Grey: `#4b5263`
- Comment Grey: `#5c6370`

---

#### FR-3: Theme Manager
**Priority:** MUST HAVE

**Description:** Centralized theme management with theme registry and application logic.

**Acceptance Criteria:**
- `ThemeManager` struct provides access to all available themes
- Ability to get theme by name
- Ability to list all available themes
- Ability to convert `Theme` to egui `Visuals`
- Ability to apply custom colors on top of base egui visuals
- Thread-safe access pattern (if needed for future multi-threading)

**API Design:**
```rust
pub struct ThemeManager {
    themes: HashMap<String, Theme>,
    current_theme_name: String,
}

impl ThemeManager {
    pub fn new() -> Self;
    pub fn get_theme(&self, name: &str) -> Option<&Theme>;
    pub fn list_themes(&self) -> Vec<&str>;
    pub fn current_theme(&self) -> &Theme;
    pub fn set_current_theme(&mut self, name: &str) -> Result<(), String>;
    pub fn apply_theme(&self, theme: &Theme, visuals: &mut egui::Visuals);
}
```

---

#### FR-4: Theme Selection UI
**Priority:** MUST HAVE

**Description:** Replace the binary Light/Dark button with a theme selection dropdown menu in the header.

**Acceptance Criteria:**
- Dropdown ComboBox displays all available theme names
- Current theme is highlighted in dropdown
- Selecting a theme immediately applies it to the GUI
- Dropdown is positioned in the top-right corner of header (same location as current theme button)
- Dropdown width adjusts to fit theme names
- Visual feedback when hovering over theme options

**Current Code Location:** `jets-gui.rs` lines 268-275

**Before:**
```rust
let theme_icon = if self.dark_mode { "☀" } else { "🌙" };
let theme_text = if self.dark_mode { "Light" } else { "Dark" };
if ui.button(format!("{} {}", theme_icon, theme_text)).clicked() {
    self.dark_mode = !self.dark_mode;
}
```

**After:**
```rust
egui::ComboBox::from_label("Theme")
    .selected_text(&self.current_theme_name)
    .show_ui(ui, |ui| {
        for theme_name in self.theme_manager.list_themes() {
            ui.selectable_value(&mut self.current_theme_name, theme_name.to_string(), theme_name);
        }
    });
```

---

#### FR-5: Consistent Color Application
**Priority:** MUST HAVE

**Description:** Apply theme colors consistently throughout the GUI, replacing all hardcoded colors.

**Acceptance Criteria:**
- Tree view selection color uses theme selection color
- Timeline record bars use theme syntax colors
- Event markers use theme accent colors
- Grid lines use theme border colors with opacity
- Status panel uses theme text colors
- Details panel JSON display uses theme syntax colors
- All hardcoded `Color32::from_rgb()` calls replaced with theme color references

**Code Locations to Update:**
- `render_tree_node()` line 492-497: Selection highlight
- `render_timeline_row()` line 1094-1104: Timeline bar colors and selection
- `get_record_color()` line 1278-1288: Record type color mapping
- `render_time_axis()` line 1240-1245: Axis colors
- `render_details()` line 640-706: JSON syntax highlighting colors

---

#### FR-6: Theme Customization API (Future Extension Point)
**Priority:** SHOULD HAVE

**Description:** Provide extensibility for future custom theme support.

**Acceptance Criteria:**
- Theme definitions are data structures (not hardcoded logic)
- Clear separation between theme definition and theme application
- Documentation for adding new themes
- Theme data structures are serializable (for future file-based themes)

---

### 1.4 Non-Functional Requirements

#### NFR-1: Zero Performance Impact
**Priority:** MUST HAVE

**Requirements:**
- Theme application occurs once per theme change (not every frame)
- Color lookups are O(1) (direct struct field access)
- No dynamic allocations during rendering
- Theme switching latency <100ms (imperceptible to user)

---

#### NFR-2: Maintainability
**Priority:** MUST HAVE

**Requirements:**
- All theme code isolated in `theme.rs` module
- Clear documentation of color palette sources (official theme URLs)
- Hex color values documented in code comments
- Theme manager is unit testable

---

#### NFR-3: Visual Consistency
**Priority:** SHOULD HAVE

**Requirements:**
- Dracula theme matches official specification appearance
- One Dark Pro theme matches VSCode appearance
- Timeline record colors provide sufficient contrast for readability
- Selection highlights are clearly visible in all themes

---

## 2. Codebase Research

### 2.1 Current Theme Implementation

**File:** `jets/rjets/src/jets-gui.rs`

**Current State Variables (line 30):**
- `dark_mode: bool` — Binary flag for dark/light mode

**Current Theme Application (lines 1294-1299):**
```rust
if self.dark_mode {
    ctx.set_visuals(egui::Visuals::dark());
} else {
    ctx.set_visuals(egui::Visuals::light());
}
```

**Observation:** Theme application is extremely simple but not extensible. The entire theme state is a single boolean, and themes are directly applied using egui's built-in visuals.

---

### 2.2 Color Usage Throughout GUI

**Hardcoded Colors Inventory:**

1. **Tree View Selection (line 492-497):**
   ```rust
   Color32::from_rgb(50, 80, 120)
   ```

2. **Timeline Bar Colors (lines 1094-1098, 1278-1288):**
   ```rust
   Color32::from_rgb(52, 152, 219)  // Blue (selected)
   // get_record_color() method:
   Color32::from_rgb(52, 152, 219)  // HostProgram (blue)
   Color32::from_rgb(155, 89, 182)  // GpuContext (purple)
   Color32::from_rgb(46, 204, 113)  // Dispatch (green)
   Color32::from_rgb(243, 156, 18)  // ThreadBlock (orange)
   Color32::from_rgb(231, 76, 60)   // Warp (red)
   Color32::from_rgb(149, 165, 166) // Instruction (gray)
   Color32::from_rgb(52, 73, 94)    // Default (dark gray)
   ```

3. **Timeline Selection Stroke (line 1103):**
   ```rust
   Color32::from_rgb(100, 180, 255)
   ```

4. **Event Markers (lines 1173-1178):**
   ```rust
   Color32::from_rgb(255, 100, 80)  // Selected event (bright)
   Color32::from_rgb(231, 76, 60)   // Normal event (red)
   ```

5. **Event Selection Ring (lines 1184-1186):**
   ```rust
   Color32::from_rgb(255, 200, 100)
   ```

6. **Details Panel Colors (lines 640-706):**
   ```rust
   Color32::from_rgb(100, 150, 255) // Record JSON (blue)
   Color32::from_rgb(100, 200, 100) // Annotations (green)
   Color32::GRAY                     // "(no data)"
   Color32::from_rgb(255, 165, 0)   // Events (orange)
   Color32::from_rgb(255, 200, 100) // Selected event text (yellow)
   Color32::from_rgb(60, 40, 20)    // Selected event background (brown)
   ```

7. **Cursor Line (line 974):**
   ```rust
   Color32::from_rgb(255, 255, 100) // Yellow
   ```

8. **Zoom Region Selection (lines 1032-1042):**
   ```rust
   Color32::from_rgba_premultiplied(100, 150, 255, 80) // Overlay
   Color32::from_rgb(100, 150, 255)                     // Border
   ```

9. **Error Messages (line 279):**
   ```rust
   Color32::RED
   ```

**Observation:** 20+ hardcoded color locations throughout the codebase. All of these need to be replaced with theme color references.

---

### 2.3 egui Visuals System

**File:** egui crate (external dependency)

**Key Structures:**
- `egui::Visuals` — Complete visual theme specification
- `egui::Visuals::dark()` — Built-in dark theme
- `egui::Visuals::light()` — Built-in light theme
- `egui::style::WidgetVisuals` — Widget-specific colors
- `egui::Color32` — RGBA color type (8-bit per channel)

**Key Fields in `egui::Visuals`:**
- `dark_mode: bool`
- `override_text_color: Option<Color32>`
- `widgets: Widgets` (normal, hovered, active, inactive, open)
- `selection: Selection` (background, stroke colors)
- `hyperlink_color: Color32`
- `faint_bg_color: Color32`
- `extreme_bg_color: Color32`
- `code_bg_color: Color32`
- `warn_fg_color: Color32`
- `error_fg_color: Color32`

**Customization Pattern:**
```rust
let mut visuals = egui::Visuals::dark();
visuals.widgets.noninteractive.bg_fill = Color32::from_rgb(40, 42, 54); // Custom background
visuals.selection.bg_fill = Color32::from_rgb(68, 71, 90); // Custom selection
ctx.set_visuals(visuals);
```

**Observation:** egui provides a rich customization API. We can start with base visuals (dark/light) and override specific colors to match Dracula/OneDarkPro themes.

---

### 2.4 Module Organization

**Current Structure:**
```
jets/rjets/src/
├── lib.rs (exports)
├── jets-gui.rs (main GUI application)
├── parser.rs (JETS format parsing)
├── traits.rs (core trait definitions)
├── virtual_reader.rs (virtual trace generation)
└── writer.rs (JETS format writing)
```

**Proposed Addition:**
```
jets/rjets/src/
├── lib.rs (exports, add theme module)
├── jets-gui.rs (main GUI application, use theme module)
├── theme.rs (NEW: theme definitions and management)
├── parser.rs
├── traits.rs
├── virtual_reader.rs
└── writer.rs
```

---

## 3. Implementation Planning

### 3.1 File-by-File Changes

#### **File:** `jets/rjets/src/theme.rs` (NEW)

**Purpose:** Centralized theme definitions, color palettes, and theme management logic.

**Content:**

**1. Color Palette Structures:**
- `ThemeColors` struct with all color fields
- Helper methods for color conversion (hex string to `Color32`)
- Documentation of color sources (official theme URLs)

**2. Theme Structure:**
- `Theme` struct with name, description, colors
- Builder pattern for theme construction (optional)
- Serialization support via `#[derive(serde::Serialize, serde::Deserialize)]`

**3. Built-in Theme Definitions:**
- `fn light_theme() -> Theme`
- `fn dark_theme() -> Theme`
- `fn dracula_theme() -> Theme`
- `fn one_dark_pro_theme() -> Theme`

**4. Theme Manager:**
- `ThemeManager` struct with theme registry
- `new()` — Initialize with built-in themes
- `get_theme(name)` — Retrieve theme by name
- `list_themes()` — Get all available theme names
- `apply_theme(theme, visuals)` — Apply theme colors to egui visuals

**5. Helper Functions:**
- `fn hex_to_color32(hex: &str) -> Color32` — Parse hex colors like "#282a36"
- `fn adjust_brightness(color: Color32, factor: f32) -> Color32` — Lighten/darken colors
- `fn with_alpha(color: Color32, alpha: u8) -> Color32` — Set alpha channel

**Integration Points:**
- Exported publicly via `lib.rs`
- Used by `JetsViewerApp` to manage current theme
- No dependencies on GUI code (purely data structures)

---

#### **File:** `jets/rjets/src/lib.rs`

**Modifications:**

**1. Add Theme Module Declaration (after line 4):**
```rust
pub mod theme;
```

**2. Re-export Theme Types (after line 10):**
```rust
// Export theme support
pub use theme::{Theme, ThemeColors, ThemeManager};
```

**Rationale:** Makes theme types available to both the GUI binary and external users (if they want to extend themes).

---

#### **File:** `jets/rjets/src/jets-gui.rs`

**Modifications:**

**1. Add Theme Import (after line 2):**
```rust
use rjets::{Theme, ThemeColors, ThemeManager};
```

**2. App State Extension (`JetsViewerApp` struct, lines 22-51):**

**Replace:**
```rust
dark_mode: bool,
```

**With:**
```rust
theme_manager: ThemeManager,
current_theme_name: String,
```

**3. Initialization Method (`new()`, lines 59-87):**

**Replace:**
```rust
dark_mode: true,
```

**With:**
```rust
theme_manager: ThemeManager::new(),
current_theme_name: "Dark".to_string(),
```

**4. Header Rendering (`render_header()`, lines 216-281):**

**Replace Theme Toggle Section (lines 268-275):**
```rust
// OLD: Binary button toggle
let theme_icon = if self.dark_mode { "☀" } else { "🌙" };
let theme_text = if self.dark_mode { "Light" } else { "Dark" };
if ui.button(format!("{} {}", theme_icon, theme_text)).clicked() {
    self.dark_mode = !self.dark_mode;
}
```

**With Theme Dropdown:**
```rust
// NEW: Theme selection dropdown
ui.label("Theme:");
egui::ComboBox::from_id_salt("theme_selector")
    .selected_text(&self.current_theme_name)
    .show_ui(ui, |ui| {
        for theme_name in self.theme_manager.list_themes() {
            ui.selectable_value(
                &mut self.current_theme_name,
                theme_name.to_string(),
                theme_name
            );
        }
    });
```

**5. Theme Application (`update()` method, lines 1291-1351):**

**Replace Theme Application Logic (lines 1294-1299):**
```rust
// OLD:
if self.dark_mode {
    ctx.set_visuals(egui::Visuals::dark());
} else {
    ctx.set_visuals(egui::Visuals::light());
}
```

**With Theme Manager Application:**
```rust
// NEW:
if let Some(theme) = self.theme_manager.get_theme(&self.current_theme_name) {
    let mut visuals = if theme.name == "Light" {
        egui::Visuals::light()
    } else {
        egui::Visuals::dark()
    };

    self.theme_manager.apply_theme(theme, &mut visuals);
    ctx.set_visuals(visuals);
}
```

**6. Replace Hardcoded Colors with Theme Colors:**

**Add Helper Method to Get Current Theme Colors:**
```rust
impl JetsViewerApp {
    fn theme_colors(&self) -> &ThemeColors {
        self.theme_manager
            .get_theme(&self.current_theme_name)
            .map(|t| &t.colors)
            .unwrap_or_else(|| {
                // Fallback to dark theme colors
                &self.theme_manager.get_theme("Dark").unwrap().colors
            })
    }
}
```

**Replace Hardcoded Colors:**

- **Line 495** (tree selection background):
  ```rust
  // OLD: Color32::from_rgb(50, 80, 120)
  // NEW:
  self.theme_colors().selection
  ```

- **Line 640** (record JSON color):
  ```rust
  // OLD: Color32::from_rgb(100, 150, 255)
  // NEW:
  self.theme_colors().blue
  ```

- **Line 657** (annotation color):
  ```rust
  // OLD: Color32::from_rgb(100, 200, 100)
  // NEW:
  self.theme_colors().green
  ```

- **Line 699** (event color):
  ```rust
  // OLD: Color32::from_rgb(255, 165, 0)
  // NEW:
  self.theme_colors().orange
  ```

- **Line 974** (cursor line color):
  ```rust
  // OLD: Color32::from_rgb(255, 255, 100)
  // NEW:
  self.theme_colors().yellow
  ```

- **Line 1035** (zoom selection overlay):
  ```rust
  // OLD: Color32::from_rgba_premultiplied(100, 150, 255, 80)
  // NEW:
  rjets::theme::with_alpha(self.theme_colors().blue, 80)
  ```

- **Line 1094** (timeline bar selected):
  ```rust
  // OLD: Color32::from_rgb(52, 152, 219)
  // NEW:
  self.theme_colors().blue
  ```

- **Line 1103** (selection stroke):
  ```rust
  // OLD: Color32::from_rgb(100, 180, 255)
  // NEW:
  rjets::theme::adjust_brightness(self.theme_colors().blue, 1.2)
  ```

- **Lines 1173-1178** (event markers):
  ```rust
  // OLD: Color32::from_rgb(255, 100, 80) / Color32::from_rgb(231, 76, 60)
  // NEW:
  let event_color = if is_event_selected {
      rjets::theme::adjust_brightness(self.theme_colors().red, 1.2)
  } else {
      self.theme_colors().red
  };
  ```

- **Line 1185** (event selection ring):
  ```rust
  // OLD: Color32::from_rgb(255, 200, 100)
  // NEW:
  self.theme_colors().yellow
  ```

**7. Update `get_record_color()` Method (lines 1277-1288):**

**Replace:**
```rust
fn get_record_color(&self, name: &str) -> Color32 {
    match name {
        n if n.contains("HostProgram") => Color32::from_rgb(52, 152, 219),
        n if n.contains("GpuContext") => Color32::from_rgb(155, 89, 182),
        n if n.contains("Dispatch") => Color32::from_rgb(46, 204, 113),
        n if n.contains("ThreadBlock") => Color32::from_rgb(243, 156, 18),
        n if n.contains("Warp") => Color32::from_rgb(231, 76, 60),
        n if n.contains("Instruction") => Color32::from_rgb(149, 165, 166),
        _ => Color32::from_rgb(52, 73, 94),
    }
}
```

**With:**
```rust
fn get_record_color(&self, name: &str) -> Color32 {
    let colors = self.theme_colors();
    match name {
        n if n.contains("HostProgram") => colors.blue,
        n if n.contains("GpuContext") => colors.purple,
        n if n.contains("Dispatch") => colors.green,
        n if n.contains("ThreadBlock") => colors.orange,
        n if n.contains("Warp") => colors.red,
        n if n.contains("Instruction") => colors.gray,
        _ => colors.text_dim,
    }
}
```

---

### 3.2 Theme Color Mappings

#### Dracula Theme Color Mapping

**Background Colors:**
- `background`: `#282a36` (main background)
- `panel_background`: `#282a36` (same as background)
- `extreme_background`: `#21222c` (darker, for contrast)

**Foreground Colors:**
- `text`: `#f8f8f2` (primary text)
- `text_dim`: `#6272a4` (comments, secondary text)
- `text_strong`: `#f8f8f2` (emphasized text, same as primary)

**Interactive Colors:**
- `selection`: `#44475a` (selection background)
- `hover`: `#44475a` (hover state, same as selection)
- `border`: `#6272a4` (borders and separators)

**Syntax Colors:**
- `red`: `#ff5555`
- `orange`: `#ffb86c`
- `yellow`: `#f1fa8c`
- `green`: `#50fa7b`
- `cyan`: `#8be9fd`
- `blue`: `#bd93f9` (using purple as blue)
- `purple`: `#bd93f9`
- `magenta`: `#ff79c6` (pink)
- `gray`: `#6272a4` (comment color)

---

#### One Dark Pro Theme Color Mapping

**Background Colors:**
- `background`: `#282c34` (main background)
- `panel_background`: `#282c34` (same as background)
- `extreme_background`: `#21252b` (slightly darker)

**Foreground Colors:**
- `text`: `#abb2bf` (primary foreground)
- `text_dim`: `#5c6370` (comment grey)
- `text_strong`: `#abb2bf` (same as text)

**Interactive Colors:**
- `selection`: `#4b5263` (gutter grey)
- `hover`: `#4b5263` (same as selection)
- `border`: `#5c6370` (comment grey)

**Syntax Colors:**
- `red`: `#e06c75` (light red)
- `orange`: `#d19a66` (dark yellow)
- `yellow`: `#e5c07b` (light yellow)
- `green`: `#98c379`
- `cyan`: `#56b6c2`
- `blue`: `#61afef`
- `purple`: `#c678dd` (magenta)
- `magenta`: `#c678dd`
- `gray`: `#5c6370` (comment grey)

---

### 3.3 egui Visuals Customization Strategy

**Approach:** Start with base egui visuals (dark/light) and override specific fields.

**For Dracula Theme:**
```rust
let mut visuals = egui::Visuals::dark();

// Override background colors
visuals.panel_fill = hex_to_color32("#282a36");
visuals.extreme_bg_color = hex_to_color32("#21222c");
visuals.faint_bg_color = hex_to_color32("#44475a");

// Override text colors
visuals.override_text_color = Some(hex_to_color32("#f8f8f2"));

// Override selection
visuals.selection.bg_fill = hex_to_color32("#44475a");
visuals.selection.stroke.color = hex_to_color32("#bd93f9");

// Override widget colors
visuals.widgets.noninteractive.bg_fill = hex_to_color32("#282a36");
visuals.widgets.inactive.bg_fill = hex_to_color32("#44475a");
visuals.widgets.hovered.bg_fill = hex_to_color32("#44475a");
visuals.widgets.active.bg_fill = hex_to_color32("#6272a4");

// Override hyperlink
visuals.hyperlink_color = hex_to_color32("#8be9fd");
```

**Similar customization for One Dark Pro theme using its color palette.**

---

### 3.4 Algorithm: Theme Application Flow

**Purpose:** Efficiently apply theme changes without performance impact.

**Steps:**
1. **User Action:** User selects theme from dropdown
2. **State Update:** `current_theme_name` is updated via egui `selectable_value()`
3. **Next Frame:** In `update()` method:
   - Retrieve theme from `ThemeManager` by name
   - Start with base egui visuals (dark or light)
   - Call `theme_manager.apply_theme()` to override colors
   - Call `ctx.set_visuals()` to apply
4. **Rendering:** All subsequent widget rendering uses new visuals
5. **Custom Colors:** Hardcoded colors replaced with `theme_colors()` lookups

**Performance Characteristics:**
- Theme application: Once per frame after change (negligible cost)
- Color lookups: O(1) struct field access
- Zero allocations during rendering
- Theme change latency: <16ms (one frame)

---

## 4. Testing Strategy

### 4.1 Visual Verification

**Test Cases:**
1. **Light Theme:**
   - Verify tree view has light background
   - Verify timeline bars use appropriate light-mode colors
   - Verify text is readable

2. **Dark Theme:**
   - Verify current behavior is maintained
   - Verify no visual regressions

3. **Dracula Theme:**
   - Compare background color to official Dracula specification (#282a36)
   - Verify selection color matches (#44475a)
   - Verify syntax colors match official palette
   - Compare with Dracula theme in VSCode side-by-side

4. **One Dark Pro Theme:**
   - Compare background color to official One Dark Pro (#282c34)
   - Verify foreground text color (#abb2bf)
   - Verify syntax colors match VSCode One Dark Pro
   - Compare with One Dark Pro in VSCode side-by-side

### 4.2 Functionality Testing

**Test Scenarios:**
1. **Theme Switching:**
   - Start application (defaults to Dark theme)
   - Switch to Light theme → verify immediate update
   - Switch to Dracula → verify immediate update
   - Switch to One Dark Pro → verify immediate update
   - Switch back to Dark → verify no corruption

2. **UI Element Coverage:**
   - Verify tree view selection uses theme selection color
   - Verify timeline record bars use theme syntax colors
   - Verify event markers use theme colors
   - Verify cursor line uses theme color
   - Verify details panel JSON uses theme colors
   - Verify status panel text uses theme text color

3. **Edge Cases:**
   - Invalid theme name → fallback to Dark theme
   - Theme manager initialization failure → graceful degradation

### 4.3 Code Quality Testing

**Checks:**
1. **No Hardcoded Colors:**
   - Run regex search for `Color32::from_rgb\(` in jets-gui.rs
   - Verify all results are either removed or documented as intentional

2. **Theme Module Tests:**
   - Unit test `hex_to_color32()` with various inputs
   - Unit test theme retrieval from ThemeManager
   - Unit test theme list functionality

---

## 5. Future Enhancements (Out of Scope for v0.3.0)

### 5.1 User-Defined Themes
- Load themes from JSON/TOML configuration files
- User theme directory (`~/.jets/themes/`)
- Theme editor UI for live customization

### 5.2 Theme Persistence
- Save selected theme to application settings
- Restore theme on application restart
- Per-trace theme preferences

### 5.3 Additional Built-in Themes
- Solarized Dark/Light
- Monokai Pro
- Nord
- Gruvbox

### 5.4 Theme Variants
- Dracula Pro (official paid variant)
- One Dark Pro variants (darker, flat, vivid)

### 5.5 Accessibility Features
- High contrast themes
- Colorblind-friendly palettes
- Configurable text size scaling

---

## 6. Dependencies

**No new crate dependencies required.** All features can be implemented using existing dependencies:
- `egui` 0.29: Already provides `Color32` and `Visuals` customization
- `serde` 1.0: Already included for serialization (future theme loading)

**Estimated Implementation Effort:** 1-2 days for experienced Rust + egui developer.

---

## 7. Implementation Checklist

**Phase 1: Theme Module Foundation**
- [ ] Create `jets/rjets/src/theme.rs` file
- [ ] Define `ThemeColors` struct with all color fields
- [ ] Define `Theme` struct with name, description, colors
- [ ] Implement `hex_to_color32()` helper function
- [ ] Implement `adjust_brightness()` helper function
- [ ] Implement `with_alpha()` helper function

**Phase 2: Built-in Theme Definitions**
- [ ] Implement `light_theme()` function
- [ ] Implement `dark_theme()` function
- [ ] Implement `dracula_theme()` function with official colors
- [ ] Implement `one_dark_pro_theme()` function with official colors
- [ ] Document color sources (URLs) in code comments

**Phase 3: Theme Manager**
- [ ] Define `ThemeManager` struct
- [ ] Implement `new()` — initialize with built-in themes
- [ ] Implement `get_theme()` — retrieve by name
- [ ] Implement `list_themes()` — get all theme names
- [ ] Implement `apply_theme()` — apply to egui visuals

**Phase 4: GUI Integration**
- [ ] Add theme module export to `lib.rs`
- [ ] Replace `dark_mode: bool` with `ThemeManager` in `JetsViewerApp`
- [ ] Add `current_theme_name: String` field
- [ ] Replace Light/Dark button with ComboBox dropdown
- [ ] Update `update()` method to apply theme via ThemeManager
- [ ] Add `theme_colors()` helper method

**Phase 5: Color Replacement**
- [ ] Replace tree view selection color (line 495)
- [ ] Replace details panel JSON colors (lines 640-706)
- [ ] Replace cursor line color (line 974)
- [ ] Replace zoom selection colors (lines 1032-1042)
- [ ] Replace timeline bar colors in `get_record_color()` (lines 1278-1288)
- [ ] Replace timeline selection colors (lines 1094-1103)
- [ ] Replace event marker colors (lines 1173-1186)

**Phase 6: Testing & Validation**
- [ ] Visual test: Light theme appearance
- [ ] Visual test: Dark theme appearance (no regression)
- [ ] Visual test: Dracula theme matches specification
- [ ] Visual test: One Dark Pro theme matches specification
- [ ] Functional test: Theme switching works immediately
- [ ] Code quality: No hardcoded colors remain (except intentional)

---

## 8. Documentation Updates

### 8.1 Code Documentation

**Add to `theme.rs`:**
- Module-level doc comment explaining purpose
- Doc comments for all public structs and methods
- Examples showing how to add a new theme
- References to official theme specifications (URLs)

### 8.2 User-Facing Documentation

**Future additions to README or user guide:**
- List of available themes
- Instructions for switching themes
- Screenshots of each theme
- Explanation of theme color mappings

---

## 9. Risk Assessment

### 9.1 Technical Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Color contrast issues in custom themes | Medium | Test all themes for readability; provide high-contrast fallbacks |
| egui visuals customization limitations | Low | Work within egui's visual system; avoid hacky workarounds |
| Performance regression from color lookups | Low | Use direct struct field access; profile after implementation |
| Missing color mappings (incomplete theme coverage) | Medium | Define complete ThemeColors struct; ensure all UI elements covered |

### 9.2 UX Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Users expect theme to persist across sessions | Medium | Document as future enhancement; implement in v0.4.0 |
| Dropdown may be less discoverable than button | Low | Use clear label "Theme:" next to dropdown |
| Dracula/One Dark Pro colors don't match user expectations | Low | Use exact official color palettes; document sources |

---

## 10. Success Metrics

### 10.1 Functional Completeness
- [ ] All FR-1 through FR-5 acceptance criteria pass
- [ ] Four themes (Light, Dark, Dracula, One Dark Pro) implemented
- [ ] Dropdown theme selector works correctly
- [ ] All hardcoded colors replaced with theme colors

### 10.2 Visual Quality
- [ ] Dracula theme visually matches official specification
- [ ] One Dark Pro theme visually matches VSCode appearance
- [ ] All themes provide sufficient text/background contrast
- [ ] Timeline record colors distinguishable in all themes

### 10.3 Code Quality
- [ ] Theme code isolated in separate module
- [ ] Zero hardcoded colors in jets-gui.rs (except documented exceptions)
- [ ] Theme manager is unit testable
- [ ] Official color sources documented

---

**End of Plan**
