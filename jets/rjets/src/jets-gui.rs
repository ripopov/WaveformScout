use eframe::egui;
use egui::{Color32, RichText, ScrollArea};
use rjets::{TraceReader, TraceData, JetsTraceReader};
use std::path::PathBuf;

fn main() -> eframe::Result {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([1200.0, 800.0])
            .with_title("JETS Trace Viewer"),
        ..Default::default()
    };

    eframe::run_native(
        "JETS Trace Viewer",
        options,
        Box::new(|_cc| Ok(Box::new(JetsViewerApp::new()))),
    )
}

struct JetsViewerApp {
    reader: Box<dyn TraceReader>,
    trace_data: Option<Box<dyn TraceData>>,
    file_path: Option<PathBuf>,
    selected_record_id: Option<u64>,
    expanded_nodes: std::collections::HashSet<u64>,
    error_message: Option<String>,
    split_ratio: f32,
    dark_mode: bool,
    column_widths: [f32; 5], // Name, ID, Start Clock, End Clock, Description
    // Timeline state
    timeline_split_ratio: f32,
    zoom_level: f32,
    viewport_start_clk: i64,
    viewport_end_clk: i64,
    shared_scroll_y: f32,
    trace_min_clk: i64,
    trace_max_clk: i64,
    // Drag panning state
    is_dragging: bool,
    drag_start_clk: i64,
    // Cursor hover state
    cursor_hover_pos: Option<egui::Pos2>,
    cursor_hover_clk: Option<i64>,
    // Selected event state (record_id, event_clk)
    selected_event: Option<(u64, i64)>,
}

impl Default for JetsViewerApp {
    fn default() -> Self {
        Self::new()
    }
}

impl JetsViewerApp {
    fn new() -> Self {
        Self {
            reader: Box::new(JetsTraceReader::new()),
            trace_data: None,
            file_path: None,
            selected_record_id: None,
            expanded_nodes: std::collections::HashSet::new(),
            error_message: None,
            split_ratio: 0.7,
            dark_mode: true,
            column_widths: [250.0, 80.0, 120.0, 120.0, 300.0], // Default column widths
            timeline_split_ratio: 0.3,
            zoom_level: 1.0,
            viewport_start_clk: 0,
            viewport_end_clk: 0,
            shared_scroll_y: 0.0,
            trace_min_clk: 0,
            trace_max_clk: 0,
            is_dragging: false,
            drag_start_clk: 0,
            cursor_hover_pos: None,
            cursor_hover_clk: None,
            selected_event: None,
        }
    }

    fn open_file(&mut self, path: PathBuf) {
        match self.reader.read(path.to_str().unwrap()) {
            Ok(data) => {
                self.trace_data = Some(data);
                self.file_path = Some(path);
                self.error_message = None;
                self.expanded_nodes.clear();
                self.selected_record_id = None;

                // Calculate trace extent
                let (min_clk, max_clk) = self.calculate_trace_extent();
                self.trace_min_clk = min_clk;
                self.trace_max_clk = max_clk;
                self.viewport_start_clk = min_clk;
                self.viewport_end_clk = max_clk;
                self.zoom_level = 1.0;
                self.shared_scroll_y = 0.0;
            }
            Err(e) => {
                self.error_message = Some(format!("Error loading trace: {}", e));
            }
        }
    }

    fn calculate_trace_extent(&self) -> (i64, i64) {
        if let Some(trace) = &self.trace_data {
            let mut min_clk = i64::MAX;
            let mut max_clk = i64::MIN;

            let root_ids = trace.root_ids();
            for root_id in root_ids {
                self.calculate_extent_recursive(trace.as_ref(), root_id, &mut min_clk, &mut max_clk);
            }

            if min_clk == i64::MAX {
                (0, 1000)
            } else {
                (min_clk, max_clk)
            }
        } else {
            (0, 1000)
        }
    }

    fn calculate_extent_recursive(&self, trace: &dyn TraceData, record_id: u64, min_clk: &mut i64, max_clk: &mut i64) {
        if let Some(record) = trace.get_record(record_id) {
            *min_clk = (*min_clk).min(record.clk());
            if let Some(end_clk) = record.end_clk() {
                *max_clk = (*max_clk).max(end_clk);
            } else {
                *max_clk = (*max_clk).max(record.clk());
            }

            for child in record.children() {
                self.calculate_extent_recursive(trace, child.id(), min_clk, max_clk);
            }
        }
    }

    // Helper: Convert clock value to X-coordinate in timeline canvas
    fn clk_to_x(&self, clk: i64, canvas_rect: egui::Rect) -> f32 {
        if self.viewport_end_clk == self.viewport_start_clk {
            return canvas_rect.left();
        }
        let normalized = (clk - self.viewport_start_clk) as f32 / (self.viewport_end_clk - self.viewport_start_clk) as f32;
        canvas_rect.left() + normalized * canvas_rect.width()
    }

    // Helper: Convert X-coordinate to clock value
    fn x_to_clk(&self, x: f32, canvas_rect: egui::Rect) -> i64 {
        if canvas_rect.width() == 0.0 {
            return self.viewport_start_clk;
        }
        let normalized = (x - canvas_rect.left()) / canvas_rect.width();
        self.viewport_start_clk + (normalized * (self.viewport_end_clk - self.viewport_start_clk) as f32) as i64
    }

    // Helper: Format clock value with thousands separators
    fn format_clock(clk: i64) -> String {
        let s = clk.to_string();
        let mut result = String::new();
        let chars: Vec<char> = s.chars().collect();
        for (i, ch) in chars.iter().enumerate() {
            if i > 0 && (chars.len() - i) % 3 == 0 {
                result.push(',');
            }
            result.push(*ch);
        }
        result
    }

    // Helper: Calculate next power of 10
    fn next_power_of_10(value: f32) -> i64 {
        if value <= 0.0 {
            return 1;
        }
        let exponent = value.log10().ceil() as i32;
        10_i64.pow(exponent as u32)
    }

    fn render_header(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            if ui.button("📁 Open Trace").clicked() {
                let mut dialog = rfd::FileDialog::new()
                    .add_filter("JETS Traces", &["jets", "jsonl"]);

                if let Ok(cwd) = std::env::current_dir() {
                    dialog = dialog.set_directory(cwd);
                }

                if let Some(path) = dialog.pick_file() {
                    self.open_file(path);
                }
            }

            ui.separator();

            if let Some(trace) = &self.trace_data {
                let header_data = trace.metadata().header_data();
                let gpu_model = header_data
                    .get("gpu_model")
                    .and_then(|v| v.as_str())
                    .unwrap_or("Unknown");
                let clock_freq = header_data
                    .get("clock_frequency_mhz")
                    .or_else(|| header_data.get("clock_frequency_ghz"))
                    .and_then(|v| v.as_f64())
                    .map(|f| format!("{:.2}", f))
                    .unwrap_or_else(|| "Unknown".to_string());

                ui.label(RichText::new(format!("GPU: {} | Clock: {} MHz", gpu_model, clock_freq)).strong());

                ui.separator();

                // Zoom controls
                if ui.button("🔍+").clicked() {
                    self.zoom_level = (self.zoom_level * 1.5).min(10000.0);
                    let new_range = (self.trace_max_clk - self.trace_min_clk) as f32 / self.zoom_level;
                    let center = (self.viewport_start_clk + self.viewport_end_clk) / 2;
                    self.viewport_start_clk = center - (new_range / 2.0) as i64;
                    self.viewport_end_clk = center + (new_range / 2.0) as i64;
                    self.viewport_start_clk = self.viewport_start_clk.max(self.trace_min_clk);
                    self.viewport_end_clk = self.viewport_end_clk.min(self.trace_max_clk);
                }

                if ui.button("🔍-").clicked() {
                    self.zoom_level = (self.zoom_level / 1.5).max(1.0);
                    let new_range = (self.trace_max_clk - self.trace_min_clk) as f32 / self.zoom_level;
                    let center = (self.viewport_start_clk + self.viewport_end_clk) / 2;
                    self.viewport_start_clk = center - (new_range / 2.0) as i64;
                    self.viewport_end_clk = center + (new_range / 2.0) as i64;
                    self.viewport_start_clk = self.viewport_start_clk.max(self.trace_min_clk);
                    self.viewport_end_clk = self.viewport_end_clk.min(self.trace_max_clk);
                }

                if ui.button("⛶ Fit").clicked() {
                    self.zoom_level = 1.0;
                    self.viewport_start_clk = self.trace_min_clk;
                    self.viewport_end_clk = self.trace_max_clk;
                }

                ui.label(format!("Zoom: {:.1}x", self.zoom_level));
            } else {
                ui.label("No trace loaded");
            }

            // Push theme toggle button to the right
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                let theme_icon = if self.dark_mode { "☀" } else { "🌙" };
                let theme_text = if self.dark_mode { "Light" } else { "Dark" };
                if ui.button(format!("{} {}", theme_icon, theme_text)).clicked() {
                    self.dark_mode = !self.dark_mode;
                }
            });
        });

        if let Some(err) = &self.error_message {
            ui.colored_label(Color32::RED, err);
        }
    }

    fn render_tree(&mut self, ui: &mut egui::Ui) {
        let has_trace = self.trace_data.is_some();
        if !has_trace {
            ui.label("No trace data to display");
            return;
        }

        // Render table header
        self.render_table_header(ui);

        ui.separator();

        // Get root IDs
        let root_ids: Vec<u64> = if let Some(trace) = &self.trace_data {
            trace.root_ids()
        } else {
            Vec::new()
        };

        // Clone IDs and render them
        let ids_to_render = root_ids.clone();

        let scroll_area = ScrollArea::vertical()
            .id_salt("tree_scroll_area")
            .show(ui, |ui| {
                for root_id in ids_to_render {
                    self.render_tree_node(ui, root_id, 0);
                }
            });

        // Update shared scroll position
        self.shared_scroll_y = scroll_area.state.offset.y;
    }

    fn render_table_header(&mut self, ui: &mut egui::Ui) {
        let column_names = ["Name", "ID", "Start Clock", "End Clock", "Description"];

        let mut x_offset = 0.0;
        let header_height = 24.0;
        let start_pos = ui.cursor().min;

        // Reserve space for the entire header row
        let (_header_rect, _) = ui.allocate_exact_size(
            egui::vec2(ui.available_width(), header_height),
            egui::Sense::hover()
        );

        // Space for expand/collapse buttons
        x_offset += 40.0;

        for (i, name) in column_names.iter().enumerate() {
            let width = self.column_widths[i];

            // Draw column header label
            let label_rect = egui::Rect::from_min_size(
                egui::pos2(start_pos.x + x_offset, start_pos.y),
                egui::vec2(width, header_height),
            );

            ui.painter().text(
                label_rect.left_center() + egui::vec2(4.0, 0.0),
                egui::Align2::LEFT_CENTER,
                name,
                egui::FontId::proportional(14.0),
                ui.visuals().strong_text_color(),
            );

            x_offset += width;

            // Column resize handle
            if i < column_names.len() - 1 {
                let handle_width = 8.0;
                let handle_rect = egui::Rect::from_center_size(
                    egui::pos2(start_pos.x + x_offset, start_pos.y + header_height / 2.0),
                    egui::vec2(handle_width, header_height),
                );

                let handle_id = ui.id().with(format!("header_resize_{}", i));
                let handle_response = ui.interact(handle_rect, handle_id, egui::Sense::drag());

                // Handle dragging
                if handle_response.dragged() {
                    let delta = handle_response.drag_delta().x;
                    self.column_widths[i] = (self.column_widths[i] + delta).max(50.0);
                }

                // Visual feedback
                let color = if handle_response.hovered() || handle_response.dragged() {
                    ui.ctx().set_cursor_icon(egui::CursorIcon::ResizeHorizontal);
                    Color32::from_rgb(100, 150, 255)
                } else {
                    ui.visuals().widgets.noninteractive.bg_stroke.color.gamma_multiply(0.5)
                };

                ui.painter().rect_filled(handle_rect.shrink(2.0), 0.0, color);
            }
        }
    }

    fn render_tree_node(&mut self, ui: &mut egui::Ui, record_id: u64, depth: usize) {
        // Extract all needed data from the record first to avoid borrow checker issues
        let (has_children, name, description, clk, end_clk, child_ids, first_event_clk) = if let Some(trace) = &self.trace_data {
            if let Some(record) = trace.get_record(record_id) {
                let children = record.children();
                let child_ids: Vec<u64> = children.iter().map(|c| c.id()).collect();
                let events = record.events();
                let first_event_clk = if !events.is_empty() {
                    Some(events[0].clk())
                } else {
                    None
                };
                (
                    !children.is_empty(),
                    record.name().to_string(),
                    record.description().to_string(),
                    record.clk(),
                    record.end_clk(),
                    child_ids,
                    first_event_clk
                )
            } else {
                return;
            }
        } else {
            return;
        };

        let indent = depth as f32 * 20.0;
        let is_selected = self.selected_record_id == Some(record_id);
        let row_height = 22.0;

        let mut x_offset = 0.0;
        let start_pos = ui.cursor().min;

        // Reserve space for the entire row
        let (row_rect, row_response) = ui.allocate_exact_size(
            egui::vec2(ui.available_width(), row_height),
            egui::Sense::click()
        );

        if row_response.clicked() {
            // Check if this is a new selection
            let was_already_selected = self.selected_record_id == Some(record_id);
            self.selected_record_id = Some(record_id);

            // Auto-select first event if this is a new record selection
            if !was_already_selected {
                if let Some(event_clk) = first_event_clk {
                    self.selected_event = Some((record_id, event_clk));
                    println!("DEBUG: Auto-selected first event at clk {}", event_clk);
                } else {
                    // Clear event selection if no events
                    self.selected_event = None;
                }
            }
        }

        // Draw background for selected row
        if is_selected {
            ui.painter().rect_filled(
                row_rect,
                0.0,
                Color32::from_rgb(50, 80, 120),
            );
        }

        // Tree expansion control (40px area)
        let expand_width = 40.0;
        let expand_rect = egui::Rect::from_min_size(
            egui::pos2(start_pos.x + indent, start_pos.y),
            egui::vec2(expand_width - indent, row_height),
        );

        if has_children {
            let is_expanded = self.expanded_nodes.contains(&record_id);
            let symbol = if is_expanded { "▼" } else { "▶" };

            let button_id = ui.id().with(format!("expand_{}", record_id));
            let button_rect = egui::Rect::from_center_size(
                expand_rect.center(),
                egui::vec2(16.0, 16.0),
            );
            let button_response = ui.interact(button_rect, button_id, egui::Sense::click());

            if button_response.clicked() {
                if is_expanded {
                    self.expanded_nodes.remove(&record_id);
                } else {
                    self.expanded_nodes.insert(record_id);
                }
            }

            ui.painter().text(
                button_rect.center(),
                egui::Align2::CENTER_CENTER,
                symbol,
                egui::FontId::proportional(12.0),
                ui.visuals().text_color(),
            );
        }

        x_offset += expand_width;

        // Column 0: Name
        let name_rect = egui::Rect::from_min_size(
            egui::pos2(start_pos.x + x_offset, start_pos.y),
            egui::vec2(self.column_widths[0], row_height),
        );
        ui.painter().text(
            name_rect.left_center() + egui::vec2(4.0, 0.0),
            egui::Align2::LEFT_CENTER,
            &name,
            egui::FontId::proportional(13.0),
            ui.visuals().text_color(),
        );
        x_offset += self.column_widths[0];

        // Column 1: ID
        let id_rect = egui::Rect::from_min_size(
            egui::pos2(start_pos.x + x_offset, start_pos.y),
            egui::vec2(self.column_widths[1], row_height),
        );
        ui.painter().text(
            id_rect.left_center() + egui::vec2(4.0, 0.0),
            egui::Align2::LEFT_CENTER,
            &record_id.to_string(),
            egui::FontId::proportional(13.0),
            ui.visuals().text_color(),
        );
        x_offset += self.column_widths[1];

        // Column 2: Start Clock
        let start_rect = egui::Rect::from_min_size(
            egui::pos2(start_pos.x + x_offset, start_pos.y),
            egui::vec2(self.column_widths[2], row_height),
        );
        ui.painter().text(
            start_rect.left_center() + egui::vec2(4.0, 0.0),
            egui::Align2::LEFT_CENTER,
            &clk.to_string(),
            egui::FontId::proportional(13.0),
            ui.visuals().text_color(),
        );
        x_offset += self.column_widths[2];

        // Column 3: End Clock
        let end_str = end_clk
            .map(|e| e.to_string())
            .unwrap_or_else(|| "N/A".to_string());

        let end_rect = egui::Rect::from_min_size(
            egui::pos2(start_pos.x + x_offset, start_pos.y),
            egui::vec2(self.column_widths[3], row_height),
        );
        ui.painter().text(
            end_rect.left_center() + egui::vec2(4.0, 0.0),
            egui::Align2::LEFT_CENTER,
            &end_str,
            egui::FontId::proportional(13.0),
            ui.visuals().text_color(),
        );
        x_offset += self.column_widths[3];

        // Column 4: Description
        let desc_rect = egui::Rect::from_min_size(
            egui::pos2(start_pos.x + x_offset, start_pos.y),
            egui::vec2(self.column_widths[4], row_height),
        );
        ui.painter().text(
            desc_rect.left_center() + egui::vec2(4.0, 0.0),
            egui::Align2::LEFT_CENTER,
            &description,
            egui::FontId::proportional(13.0),
            ui.visuals().text_color(),
        );

        // Render children if expanded
        if self.expanded_nodes.contains(&record_id) {
            for child_id in child_ids {
                self.render_tree_node(ui, child_id, depth + 1);
            }
        }
    }

    fn render_details(&mut self, ui: &mut egui::Ui) {
        if let (Some(trace), Some(selected_id)) = (&self.trace_data, self.selected_record_id) {
            if let Some(record) = trace.get_record(selected_id) {
                ui.label(RichText::new(format!("Details for record: {}", selected_id)).strong());
                ui.separator();

                let available_height = ui.available_height();

                ScrollArea::vertical()
                    .id_salt("details_scroll_area")
                    .max_height(available_height)
                    .auto_shrink([false, false])
                    .show(ui, |ui| {
                    // Show record itself
                    let record_json = serde_json::json!({
                        "clk": record.clk(),
                        "name": record.name(),
                        "description": record.description(),
                        "id": record.id(),
                        "parent_id": record.parent_id()
                    });
                    ui.colored_label(Color32::from_rgb(100, 150, 255),
                        serde_json::to_string(&record_json).unwrap());

                    ui.add_space(10.0);

                    // Show merged data (includes annotations) - ALL of them, sorted by key
                    ui.label(RichText::new("Annotations & Data:").strong());
                    let data = record.data();
                    if !data.is_empty() {
                        let mut sorted_data: Vec<_> = data.iter().collect();
                        sorted_data.sort_by_key(|(key, _)| *key);

                        for (key, value) in sorted_data {
                            let data_json = serde_json::json!({
                                key: value
                            });
                            ui.colored_label(
                                Color32::from_rgb(100, 200, 100),
                                serde_json::to_string(&data_json).unwrap()
                            );
                        }
                    } else {
                        ui.colored_label(Color32::GRAY, "(no data)");
                    }

                    ui.add_space(10.0);

                    // Show events - ALL of them
                    ui.label(RichText::new("Events:").strong());
                    let events = record.events();
                    if !events.is_empty() {
                        for event in events {
                            let evt_json = serde_json::json!({
                                "clk": event.clk(),
                                "name": event.name(),
                                "description": event.description(),
                                "record_id": event.record_id(),
                                "data": event.data()
                            });
                            let event_text = serde_json::to_string(&evt_json).unwrap();

                            // Check if this event is selected
                            let is_event_selected = self.selected_event == Some((event.record_id(), event.clk()));

                            if is_event_selected {
                                // Draw with highlighted background
                                let text_color = Color32::from_rgb(255, 200, 100);
                                let bg_color = Color32::from_rgb(60, 40, 20);

                                // Use a frame with background color
                                egui::Frame::none()
                                    .fill(bg_color)
                                    .inner_margin(4.0)
                                    .rounding(2.0)
                                    .show(ui, |ui| {
                                        ui.colored_label(text_color, event_text);
                                    });
                            } else {
                                ui.colored_label(
                                    Color32::from_rgb(255, 165, 0),
                                    event_text
                                );
                            }
                        }
                    } else {
                        ui.colored_label(Color32::GRAY, "(no events)");
                    }
                });
            }
        } else {
            ui.label("Data & Events (select a record to view)");
        }
    }

    fn render_timeline(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
        if self.trace_data.is_none() {
            ui.label("No trace loaded - open a JETS trace file to view timeline");
            return;
        }

        // Render time axis (fixed at top) - matching tree's table header height exactly
        self.render_timeline_header(ui);

        ui.separator();  // Match the separator in tree view

        // Handle zoom and horizontal pan input
        let canvas_rect = ui.available_rect_before_wrap();

        // Handle drag panning with left mouse button AND hover for cursor tracking
        let canvas_response = ui.interact(canvas_rect, ui.id().with("timeline_canvas"), egui::Sense::drag().union(egui::Sense::hover()));

        if canvas_response.dragged() {
            let drag_delta = canvas_response.drag_delta();

            if !self.is_dragging {
                // Starting drag
                self.is_dragging = true;
                if let Some(pos) = ctx.input(|i| i.pointer.press_origin()) {
                    self.drag_start_clk = self.x_to_clk(pos.x, canvas_rect);
                }
                println!("DEBUG: Drag started at clk: {}", self.drag_start_clk);
            }

            // Calculate how much clock time the drag represents
            let viewport_range = (self.viewport_end_clk - self.viewport_start_clk) as f32;
            let pixels_to_clk_ratio = viewport_range / canvas_rect.width();
            let clk_delta = (-drag_delta.x * pixels_to_clk_ratio) as i64;

            println!("DEBUG: Dragging - delta.x: {}, clk_delta: {}", drag_delta.x, clk_delta);

            // Apply the pan
            self.viewport_start_clk += clk_delta;
            self.viewport_end_clk += clk_delta;

            // Clamp to trace bounds
            if self.viewport_start_clk < self.trace_min_clk {
                let diff = self.trace_min_clk - self.viewport_start_clk;
                self.viewport_start_clk = self.trace_min_clk;
                self.viewport_end_clk += diff;
            }
            if self.viewport_end_clk > self.trace_max_clk {
                let diff = self.viewport_end_clk - self.trace_max_clk;
                self.viewport_end_clk = self.trace_max_clk;
                self.viewport_start_clk -= diff;
            }

            println!("DEBUG: Viewport after drag: {}..{}", self.viewport_start_clk, self.viewport_end_clk);
        } else if self.is_dragging {
            // Drag ended
            self.is_dragging = false;
            println!("DEBUG: Drag ended");
        }

        // Track cursor hover position for vertical cursor line
        // Don't rely on canvas_response.hovered() as it's blocked by child widgets
        // Instead, directly check if pointer is in the canvas rect
        if let Some(hover_pos) = ctx.input(|i| i.pointer.hover_pos()) {
            if canvas_rect.contains(hover_pos) {
                self.cursor_hover_pos = Some(hover_pos);
                self.cursor_hover_clk = Some(self.x_to_clk(hover_pos.x, canvas_rect));
            } else {
                self.cursor_hover_pos = None;
                self.cursor_hover_clk = None;
            }
        } else {
            self.cursor_hover_pos = None;
            self.cursor_hover_clk = None;
        }

        if ui.rect_contains_pointer(canvas_rect) {
            ctx.input(|i| {
                // DEBUG: Print all scroll-related inputs
                if i.raw_scroll_delta != egui::Vec2::ZERO || i.smooth_scroll_delta != egui::Vec2::ZERO {
                    println!("DEBUG: raw_scroll_delta: {:?}, smooth_scroll_delta: {:?}, modifiers.ctrl: {}",
                        i.raw_scroll_delta, i.smooth_scroll_delta, i.modifiers.ctrl);
                }

                // Handle zoom (Ctrl + Mouse Wheel)
                // Try both raw_scroll_delta and smooth_scroll_delta for compatibility
                let scroll_y = if i.raw_scroll_delta.y != 0.0 {
                    i.raw_scroll_delta.y
                } else {
                    i.smooth_scroll_delta.y
                };

                if i.modifiers.ctrl && scroll_y != 0.0 {
                    println!("DEBUG: Zoom triggered! scroll_y: {}, current zoom_level: {}", scroll_y, self.zoom_level);

                    let zoom_factor = 1.0 + scroll_y * 0.002;
                    let mouse_pos = i.pointer.hover_pos().unwrap_or(canvas_rect.center());
                    let mouse_clk = self.x_to_clk(mouse_pos.x, canvas_rect);

                    println!("DEBUG: zoom_factor: {}, mouse_clk: {}", zoom_factor, mouse_clk);

                    self.zoom_level = (self.zoom_level * zoom_factor).clamp(1.0, 10000.0);

                    let new_range = (self.trace_max_clk - self.trace_min_clk) as f32 / self.zoom_level;
                    let old_range = (self.viewport_end_clk - self.viewport_start_clk) as f32;
                    let left_ratio = if old_range > 0.0 {
                        (mouse_clk - self.viewport_start_clk) as f32 / old_range
                    } else {
                        0.5
                    };

                    self.viewport_start_clk = mouse_clk - (left_ratio * new_range) as i64;
                    self.viewport_end_clk = self.viewport_start_clk + new_range as i64;
                    self.viewport_start_clk = self.viewport_start_clk.max(self.trace_min_clk);
                    self.viewport_end_clk = self.viewport_end_clk.min(self.trace_max_clk);

                    println!("DEBUG: New zoom_level: {}, viewport: {}..{}",
                        self.zoom_level, self.viewport_start_clk, self.viewport_end_clk);
                }

                // Handle pan (mouse wheel without Ctrl or middle-mouse drag)
                // Mouse wheel Y-axis pans horizontally in the timeline
                let scroll_y_for_pan = if i.raw_scroll_delta.y != 0.0 {
                    i.raw_scroll_delta.y
                } else {
                    i.smooth_scroll_delta.y
                };

                if !i.modifiers.ctrl && scroll_y_for_pan != 0.0 {
                    println!("DEBUG: Pan triggered! scroll_y_for_pan: {}", scroll_y_for_pan);

                    // Negative scroll_y means scroll down/right, positive means scroll up/left
                    // Invert the sign so scrolling down moves the timeline left (showing later times)
                    let viewport_range = (self.viewport_end_clk - self.viewport_start_clk) as f32;

                    // Calculate pan amount with minimum threshold to ensure movement at high zoom
                    let pan_amount = (-scroll_y_for_pan / 100.0) * viewport_range * 0.1;

                    // At high zoom levels (small viewport_range), ensure we always move at least 1 clock
                    // Use a minimum of 1 clock or 2% of viewport range, whichever is larger
                    let min_pan = (viewport_range * 0.02).max(1.0);
                    let pan_clk = if pan_amount.abs() < min_pan {
                        if pan_amount >= 0.0 {
                            min_pan
                        } else {
                            -min_pan
                        }
                    } else {
                        pan_amount
                    };

                    println!("DEBUG: viewport_range: {}, pan_amount: {}, pan_clk: {}", viewport_range, pan_amount, pan_clk);

                    self.viewport_start_clk += pan_clk as i64;
                    self.viewport_end_clk += pan_clk as i64;

                    // Clamp to trace bounds
                    if self.viewport_start_clk < self.trace_min_clk {
                        let diff = self.trace_min_clk - self.viewport_start_clk;
                        self.viewport_start_clk = self.trace_min_clk;
                        self.viewport_end_clk += diff;
                    }
                    if self.viewport_end_clk > self.trace_max_clk {
                        let diff = self.viewport_end_clk - self.trace_max_clk;
                        self.viewport_end_clk = self.trace_max_clk;
                        self.viewport_start_clk -= diff;
                    }

                    println!("DEBUG: New viewport after pan: {}..{}", self.viewport_start_clk, self.viewport_end_clk);
                }
            });
        }

        // Scrollable timeline content (synchronized with tree)
        let mut scroll_area = ScrollArea::vertical()
            .id_salt("timeline_scroll_area")
            .scroll_bar_visibility(egui::scroll_area::ScrollBarVisibility::AlwaysHidden);

        scroll_area = scroll_area.vertical_scroll_offset(self.shared_scroll_y);

        let scroll_output = scroll_area.show(ui, |ui| {
            // Render timeline rows matching tree structure
            if let Some(trace) = &self.trace_data {
                let root_ids = trace.root_ids();
                for root_id in root_ids {
                    self.render_timeline_row(ui, root_id, 0, ctx);
                }
            }
        });

        // Draw cursor line on top of everything if hovering
        // Use a dedicated layer ID to ensure it draws on top of all content
        if let (Some(hover_pos), Some(hover_clk)) = (self.cursor_hover_pos, self.cursor_hover_clk) {
            let line_x = hover_pos.x;

            // Use the scroll area's outer rect for proper clipping
            let scroll_rect = scroll_output.inner_rect;
            let content_top = scroll_rect.top();
            let content_bottom = scroll_rect.bottom();

            // Create a dedicated foreground layer that's guaranteed to be on top
            // Use debug_painter which draws on top of everything
            let painter = ui.ctx().debug_painter();

            // Draw the vertical cursor line
            painter.line_segment(
                [
                    egui::pos2(line_x, content_top),
                    egui::pos2(line_x, content_bottom),
                ],
                egui::Stroke::new(1.5, Color32::from_rgb(255, 255, 100)),
            );

            // Draw timestamp label at the bottom of the line
            let label_text = Self::format_clock(hover_clk);
            let font_id = egui::FontId::proportional(12.0);
            let label_color = Color32::from_rgb(255, 255, 100);
            let bg_color = Color32::from_rgba_premultiplied(0, 0, 0, 200);

            // Measure text size to create background box
            let galley = painter.layout_no_wrap(
                label_text.clone(),
                font_id.clone(),
                label_color,
            );

            let text_size = galley.size();
            let padding = egui::vec2(4.0, 2.0);
            let label_pos = egui::pos2(line_x, content_bottom - text_size.y - padding.y * 2.0 - 4.0);

            // Draw background box
            let bg_rect = egui::Rect::from_min_size(
                egui::pos2(label_pos.x - padding.x, label_pos.y - padding.y),
                egui::vec2(text_size.x + padding.x * 2.0, text_size.y + padding.y * 2.0),
            );
            painter.rect_filled(bg_rect, 2.0, bg_color);
            painter.rect_stroke(bg_rect, 2.0, egui::Stroke::new(1.0, label_color));

            // Draw text
            painter.text(
                egui::pos2(label_pos.x + padding.x, label_pos.y + padding.y),
                egui::Align2::LEFT_TOP,
                label_text,
                font_id,
                label_color,
            );
        }
    }

    fn render_timeline_row(&mut self, ui: &mut egui::Ui, record_id: u64, _depth: usize, ctx: &egui::Context) {
        let trace = match &self.trace_data {
            Some(t) => t.as_ref(),
            None => return,
        };

        let record = match trace.get_record(record_id) {
            Some(r) => r,
            None => return,
        };

        let row_height = 22.0;
        let start_y = ui.cursor().min.y;

        // Allocate space for this row (matching tree's allocation)
        // Use hover sense instead of click to avoid interfering with canvas drag
        let (_row_rect, _row_response) = ui.allocate_exact_size(
            egui::vec2(ui.available_width(), row_height),
            egui::Sense::hover()
        );

        // Get canvas rect for horizontal positioning
        let canvas_rect = ui.available_rect_before_wrap();

        // Draw the timeline bar for this record
        let start_clk = record.clk();
        let end_clk = record.end_clk().unwrap_or(self.viewport_end_clk);

        let x_start = self.clk_to_x(start_clk, egui::Rect::from_min_max(
            egui::pos2(canvas_rect.min.x, start_y),
            egui::pos2(canvas_rect.max.x, start_y + row_height)
        ));
        let x_end = self.clk_to_x(end_clk, egui::Rect::from_min_max(
            egui::pos2(canvas_rect.min.x, start_y),
            egui::pos2(canvas_rect.max.x, start_y + row_height)
        ));
        let width = (x_end - x_start).max(2.0);

        if width >= 0.5 {
            let bar_rect = egui::Rect::from_min_size(
                egui::pos2(x_start, start_y),
                egui::vec2(width, row_height),
            );

            let is_selected = self.selected_record_id == Some(record_id);
            let bar_color = if is_selected {
                Color32::from_rgb(52, 152, 219)
            } else {
                self.get_record_color(record.name())
            };

            ui.painter().rect_filled(bar_rect, 2.0, bar_color);

            if is_selected {
                ui.painter().rect_stroke(bar_rect, 2.0, egui::Stroke::new(2.0, Color32::from_rgb(100, 180, 255)));
            }

            // Handle click on bar for selection (only when not dragging)
            let bar_id = ui.id().with(format!("bar_select_{}", record_id));
            let bar_response = ui.interact(bar_rect, bar_id, egui::Sense::click());

            if bar_response.clicked() && !self.is_dragging {
                // Check if this is a new selection
                let was_already_selected = self.selected_record_id == Some(record_id);
                self.selected_record_id = Some(record_id);
                println!("DEBUG: Selected record {}", record_id);

                // Auto-select first event if this is a new record selection
                if !was_already_selected {
                    let events = record.events();
                    if !events.is_empty() {
                        let first_event = &events[0];
                        self.selected_event = Some((record_id, first_event.clk()));
                        println!("DEBUG: Auto-selected first event at clk {}", first_event.clk());
                    } else {
                        // Clear event selection if no events
                        self.selected_event = None;
                    }
                }
            }

            // Handle hover tooltip (only when not dragging)
            if bar_response.hovered() && !self.is_dragging {
                bar_response.on_hover_ui(|ui| {
                    ui.label(format!("{}", record.name()));
                    ui.label(format!("Start: {}", Self::format_clock(start_clk)));
                    if let Some(end) = record.end_clk() {
                        ui.label(format!("End: {}", Self::format_clock(end)));
                        ui.label(format!("Duration: {}", Self::format_clock(end - start_clk)));
                    }
                });
            }

            // Draw event markers
            for event in record.events() {
                let event_clk = event.clk();
                if event_clk >= self.viewport_start_clk && event_clk <= self.viewport_end_clk {
                    let x = self.clk_to_x(event_clk, egui::Rect::from_min_max(
                        egui::pos2(canvas_rect.min.x, start_y),
                        egui::pos2(canvas_rect.max.x, start_y + row_height)
                    ));
                    let marker_pos = egui::pos2(x, start_y + 11.0);

                    // Check if this event is selected
                    let is_event_selected = self.selected_event == Some((record_id, event_clk));
                    let marker_radius = if is_event_selected { 6.0 } else { 4.0 };

                    // Create interaction rect for the event marker
                    let marker_rect = egui::Rect::from_center_size(
                        marker_pos,
                        egui::vec2(marker_radius * 2.0, marker_radius * 2.0)
                    );

                    let marker_id = ui.id().with(format!("event_marker_{}_{}", record_id, event_clk));
                    let marker_response = ui.interact(marker_rect, marker_id, egui::Sense::click());

                    // Handle click to select event (only when not dragging)
                    if marker_response.clicked() && !self.is_dragging {
                        self.selected_event = Some((record_id, event_clk));
                        println!("DEBUG: Selected event at clk {} for record {}", event_clk, record_id);
                    }

                    // Draw the event circle
                    let event_color = if is_event_selected {
                        Color32::from_rgb(255, 100, 80) // Brighter color when selected
                    } else {
                        Color32::from_rgb(231, 76, 60)
                    };
                    ui.painter().circle_filled(marker_pos, marker_radius, event_color);

                    // Draw selection ring for selected events
                    if is_event_selected {
                        ui.painter().circle_stroke(
                            marker_pos,
                            marker_radius + 1.0,
                            egui::Stroke::new(1.5, Color32::from_rgb(255, 200, 100))
                        );
                    }
                }
            }
        }

        // Render children if expanded (matching tree logic)
        if self.expanded_nodes.contains(&record_id) {
            let child_ids: Vec<u64> = record.children().iter().map(|c| c.id()).collect();
            for child_id in child_ids {
                self.render_timeline_row(ui, child_id, _depth + 1, ctx);
            }
        }
    }

    fn render_timeline_header(&mut self, ui: &mut egui::Ui) {
        // Match tree header height EXACTLY (24px from render_table_header)
        let header_height = 24.0;

        // Reserve space for the header
        let (header_rect, _) = ui.allocate_exact_size(
            egui::vec2(ui.available_width(), header_height),
            egui::Sense::hover()
        );

        // Draw time axis in this header space
        self.render_time_axis(ui, header_rect);
    }

    fn render_time_axis(&self, ui: &mut egui::Ui, canvas_rect: egui::Rect) {
        // Use the exact rect provided (24px from header allocation)
        let axis_rect = canvas_rect;

        ui.painter().rect_filled(
            axis_rect,
            0.0,
            ui.visuals().extreme_bg_color,
        );

        let visible_range = (self.viewport_end_clk - self.viewport_start_clk) as f32;
        if visible_range <= 0.0 {
            return;
        }

        let tick_interval = Self::next_power_of_10(visible_range / 10.0);
        let first_tick = (self.viewport_start_clk / tick_interval) * tick_interval;

        let mut tick_clk = first_tick;
        while tick_clk <= self.viewport_end_clk {
            let x = self.clk_to_x(tick_clk, canvas_rect);

            // Draw major tick line (scaled to fit 24px height)
            ui.painter().line_segment(
                [
                    egui::pos2(x, axis_rect.top()),
                    egui::pos2(x, axis_rect.top() + 8.0),
                ],
                egui::Stroke::new(2.0, ui.visuals().text_color()),
            );

            // Draw label (centered vertically in available space)
            ui.painter().text(
                egui::pos2(x, axis_rect.top() + 12.0),
                egui::Align2::CENTER_TOP,
                Self::format_clock(tick_clk),
                egui::FontId::proportional(10.0),
                ui.visuals().text_color(),
            );

            // Draw minor ticks (scaled to fit)
            for i in 1..5 {
                let minor_clk = tick_clk + (tick_interval * i) / 5;
                if minor_clk > self.viewport_end_clk {
                    break;
                }
                let minor_x = self.clk_to_x(minor_clk, canvas_rect);
                ui.painter().line_segment(
                    [
                        egui::pos2(minor_x, axis_rect.top()),
                        egui::pos2(minor_x, axis_rect.top() + 4.0),
                    ],
                    egui::Stroke::new(1.0, ui.visuals().text_color().gamma_multiply(0.5)),
                );
            }

            tick_clk += tick_interval;
        }
    }

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
}

impl eframe::App for JetsViewerApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        // Apply theme based on dark_mode state
        if self.dark_mode {
            ctx.set_visuals(egui::Visuals::dark());
        } else {
            ctx.set_visuals(egui::Visuals::light());
        }

        egui::TopBottomPanel::top("header").show(ctx, |ui| {
            self.render_header(ui);
        });

        // Bottom panel: Details
        egui::TopBottomPanel::bottom("details_panel")
            .default_height(ctx.screen_rect().height() * (1.0 - self.split_ratio))
            .resizable(true)
            .show(ctx, |ui| {
                egui::Frame::default()
                    .inner_margin(4.0)
                    .show(ui, |ui| {
                        self.render_details(ui);
                    });
            });

        // Left panel: Tree
        egui::SidePanel::left("tree_panel")
            .default_width(ctx.screen_rect().width() * self.timeline_split_ratio)
            .resizable(true)
            .show(ctx, |ui| {
                egui::Frame::default()
                    .inner_margin(4.0)
                    .show(ui, |ui| {
                        ui.heading("Trace Records");
                        ui.separator();
                        self.render_tree(ui);
                    });
            });

        // Right panel: Timeline
        egui::CentralPanel::default().show(ctx, |ui| {
            ui.heading("Timeline View");
            ui.separator();
            self.render_timeline(ui, ctx);
        });
    }
}
