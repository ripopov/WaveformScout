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
            }
            Err(e) => {
                self.error_message = Some(format!("Error loading trace: {}", e));
            }
        }
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

        ScrollArea::vertical()
            .id_salt("tree_scroll_area")
            .show(ui, |ui| {
                for root_id in ids_to_render {
                    self.render_tree_node(ui, root_id, 0);
                }
            });
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
        let (has_children, name, description, clk, end_clk, child_ids) = if let Some(trace) = &self.trace_data {
            if let Some(record) = trace.get_record(record_id) {
                let children = record.children();
                let child_ids: Vec<u64> = children.iter().map(|c| c.id()).collect();
                (
                    !children.is_empty(),
                    record.name().to_string(),
                    record.description().to_string(),
                    record.clk(),
                    record.end_clk(),
                    child_ids
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
            self.selected_record_id = Some(record_id);
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
                            ui.colored_label(
                                Color32::from_rgb(255, 165, 0),
                                serde_json::to_string(&evt_json).unwrap()
                            );
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

        egui::CentralPanel::default().show(ctx, |ui| {
            let available_height = ui.available_height();
            let tree_height = available_height * self.split_ratio;
            let details_height = available_height * (1.0 - self.split_ratio);

            // Tree view (top panel)
            egui::Frame::default()
                .inner_margin(4.0)
                .show(ui, |ui| {
                    ui.set_height(tree_height);
                    ui.heading("Trace Records");
                    ui.separator();
                    self.render_tree(ui);
                });

            // Draggable separator
            let separator_rect = egui::Rect::from_min_size(
                egui::pos2(ui.min_rect().left(), ui.min_rect().top() + tree_height),
                egui::vec2(ui.available_width(), 8.0),
            );

            let separator_response = ui.allocate_rect(separator_rect, egui::Sense::click_and_drag());

            if separator_response.dragged() {
                if let Some(pointer_pos) = ui.ctx().pointer_interact_pos() {
                    let new_ratio = (pointer_pos.y - ui.min_rect().top()) / available_height;
                    self.split_ratio = new_ratio.clamp(0.1, 0.9);
                }
            }

            let is_active = separator_response.hovered() || separator_response.dragged();

            if is_active {
                ui.ctx().set_cursor_icon(egui::CursorIcon::ResizeVertical);
            }

            // Draw the separator line with different style when active
            let (stroke_width, stroke_color) = if is_active {
                (3.0, Color32::from_rgb(100, 150, 255))  // Brighter blue and thicker when active
            } else {
                (1.0, ui.visuals().widgets.noninteractive.bg_stroke.color)  // Normal style
            };

            ui.painter().line_segment(
                [
                    egui::pos2(separator_rect.left(), separator_rect.center().y),
                    egui::pos2(separator_rect.right(), separator_rect.center().y),
                ],
                egui::Stroke::new(stroke_width, stroke_color),
            );

            // Details panel (bottom panel)
            egui::Frame::default()
                .inner_margin(4.0)
                .show(ui, |ui| {
                    ui.set_height(details_height);
                    self.render_details(ui);
                });
        });
    }
}
