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

    fn render_tree_node(&mut self, ui: &mut egui::Ui, record_id: u64, depth: usize) {
        // Extract all needed data from the record first to avoid borrow checker issues
        let (has_children, name, description, clk, end_clk, duration, child_ids) = if let Some(trace) = &self.trace_data {
            if let Some(record) = trace.get_record(record_id) {
                let children = record.children();
                let child_ids: Vec<u64> = children.iter().map(|c| c.id()).collect();
                (
                    !children.is_empty(),
                    record.name().to_string(),
                    record.description().to_string(),
                    record.clk(),
                    record.end_clk(),
                    record.duration(),
                    child_ids
                )
            } else {
                return;
            }
        } else {
            return;
        };

        let indent = depth as f32 * 20.0;

        ui.horizontal(|ui| {
            ui.add_space(indent);

            // Expand/collapse button if has children
            if has_children {
                let is_expanded = self.expanded_nodes.contains(&record_id);
                let symbol = if is_expanded { "▼" } else { "▶" };

                if ui.small_button(symbol).clicked() {
                    if is_expanded {
                        self.expanded_nodes.remove(&record_id);
                    } else {
                        self.expanded_nodes.insert(record_id);
                    }
                }
            } else {
                ui.add_space(20.0);
            }

            // Record info - clickable
            let is_selected = self.selected_record_id == Some(record_id);
            let bg_color = if is_selected {
                Some(Color32::from_rgb(50, 80, 120))
            } else {
                None
            };

            let duration_str = duration
                .map(|d| d.to_string())
                .unwrap_or_else(|| "N/A".to_string());

            let end_str = end_clk
                .map(|e| e.to_string())
                .unwrap_or_else(|| "N/A".to_string());

            let label_text = format!(
                "{} | {} | {} | {} | {} | {}",
                record_id,
                name,
                description,
                clk,
                end_str,
                duration_str
            );

            let response = if let Some(bg) = bg_color {
                ui.colored_label(bg, &label_text)
            } else {
                ui.label(&label_text)
            };

            if response.clicked() {
                self.selected_record_id = Some(record_id);
            }
        });

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
                ui.label(RichText::new(format!("Data & Events for record: {}", selected_id)).strong());
                ui.separator();

                ScrollArea::vertical()
                    .id_salt("details_scroll_area")
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

                    // Show merged data (includes annotations)
                    ui.label(RichText::new("Data (with merged annotations):").strong());
                    let data = record.data();
                    if !data.is_empty() {
                        for (key, value) in data {
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

                    // Show events
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
        egui::TopBottomPanel::top("header").show(ctx, |ui| {
            self.render_header(ui);
        });

        egui::CentralPanel::default().show(ctx, |ui| {
            let available_height = ui.available_height();
            let tree_height = available_height * 0.7;
            let details_height = available_height * 0.3;

            // Tree view (top 70%)
            egui::Frame::default()
                .inner_margin(4.0)
                .show(ui, |ui| {
                    ui.set_height(tree_height);
                    ui.heading("Trace Records");
                    ui.separator();
                    self.render_tree(ui);
                });

            ui.separator();

            // Details panel (bottom 30%)
            egui::Frame::default()
                .inner_margin(4.0)
                .show(ui, |ui| {
                    ui.set_height(details_height);
                    self.render_details(ui);
                });
        });
    }
}
