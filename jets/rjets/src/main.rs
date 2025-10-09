use eframe::egui;
use egui::{Color32, RichText, ScrollArea};
use rjets::{parse_trace, TraceData, TraceRecord};
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
        Box::new(|_cc| Ok(Box::new(JetsViewerApp::default()))),
    )
}

#[derive(Default)]
struct JetsViewerApp {
    trace_data: Option<TraceData>,
    file_path: Option<PathBuf>,
    selected_record_id: Option<u64>,
    expanded_nodes: std::collections::HashSet<u64>,
    error_message: Option<String>,
}

impl JetsViewerApp {
    fn open_file(&mut self, path: PathBuf) {
        match parse_trace(path.to_str().unwrap()) {
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
                let metadata = &trace.header.metadata;
                let gpu_model = metadata
                    .get("gpu_model")
                    .and_then(|v| v.as_str())
                    .unwrap_or("Unknown");
                let clock_freq = metadata
                    .get("clock_frequency_mhz")
                    .or_else(|| metadata.get("clock_frequency_ghz"))
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

        // Clone the roots to avoid borrow checker issues
        let roots = self.trace_data.as_ref().unwrap().roots.clone();

        ScrollArea::vertical()
            .id_salt("tree_scroll_area")
            .show(ui, |ui| {
                for root in &roots {
                    self.render_record_tree(ui, root, 0);
                }
            });
    }

    fn render_record_tree(&mut self, ui: &mut egui::Ui, record: &TraceRecord, depth: usize) {
        let indent = depth as f32 * 20.0;

        ui.horizontal(|ui| {
            ui.add_space(indent);

            // Expand/collapse button if has children
            if !record.children.is_empty() {
                let is_expanded = self.expanded_nodes.contains(&record.id);
                let symbol = if is_expanded { "▼" } else { "▶" };

                if ui.small_button(symbol).clicked() {
                    if is_expanded {
                        self.expanded_nodes.remove(&record.id);
                    } else {
                        self.expanded_nodes.insert(record.id);
                    }
                }
            } else {
                ui.add_space(20.0);
            }

            // Record info - clickable
            let is_selected = self.selected_record_id == Some(record.id);
            let bg_color = if is_selected {
                Some(Color32::from_rgb(50, 80, 120))
            } else {
                None
            };

            let duration_str = record.duration
                .map(|d| d.to_string())
                .unwrap_or_else(|| "N/A".to_string());

            let end_str = record.end_clk
                .map(|e| e.to_string())
                .unwrap_or_else(|| "N/A".to_string());

            let label_text = format!(
                "{} | {} | {} | {} | {} | {} | {}",
                record.id,
                record.name,
                record.description,
                record.record_type,
                record.clk,
                end_str,
                duration_str
            );

            let response = if let Some(bg) = bg_color {
                ui.colored_label(bg, &label_text)
            } else {
                ui.label(&label_text)
            };

            if response.clicked() {
                self.selected_record_id = Some(record.id);
            }
        });

        // Render children if expanded
        if self.expanded_nodes.contains(&record.id) {
            for child in &record.children {
                self.render_record_tree(ui, child, depth + 1);
            }
        }
    }

    fn render_details(&mut self, ui: &mut egui::Ui) {
        if let (Some(trace), Some(selected_id)) = (&self.trace_data, self.selected_record_id) {
            if let Some(record) = self.find_record(&trace.roots, selected_id) {
                ui.label(RichText::new(format!("Annotations & Events for record: {}", selected_id)).strong());
                ui.separator();

                ScrollArea::vertical()
                    .id_salt("details_scroll_area")
                    .show(ui, |ui| {
                    // Show record itself
                    let record_json = format!(
                        r#"{{"clk":{},"record_type":"{}","name":"{}","description":"{}","id":"{}","parent_id":{}}}"#,
                        record.clk,
                        record.record_type,
                        record.name,
                        record.description,
                        record.id,
                        record.parent_id.map(|id| id.to_string()).unwrap_or_else(|| "null".to_string())
                    );
                    ui.colored_label(Color32::from_rgb(100, 150, 255), &record_json);

                    // Show annotations
                    for annotation in &record.annotations {
                        let ann_json = serde_json::json!({
                            "type": "annotation",
                            "name": annotation.name,
                            "description": annotation.description,
                            "record_id": annotation.record_id,
                            "data": annotation.data
                        });
                        ui.colored_label(
                            Color32::from_rgb(100, 200, 100),
                            serde_json::to_string(&ann_json).unwrap()
                        );
                    }

                    // Show events
                    for event in &record.events {
                        let evt_json = if let Some(data) = &event.data {
                            serde_json::json!({
                                "clk": event.clk,
                                "type": "event",
                                "name": event.name,
                                "description": event.description,
                                "record_id": event.record_id,
                                "data": data
                            })
                        } else {
                            serde_json::json!({
                                "clk": event.clk,
                                "type": "event",
                                "name": event.name,
                                "description": event.description,
                                "record_id": event.record_id
                            })
                        };
                        ui.colored_label(
                            Color32::from_rgb(255, 165, 0),
                            serde_json::to_string(&evt_json).unwrap()
                        );
                    }

                    if record.annotations.is_empty() && record.events.is_empty() {
                        ui.colored_label(Color32::GRAY, "(no annotations or events for this record)");
                    }
                });
            }
        } else {
            ui.label("Annotations & Events (select a record to view)");
        }
    }

    fn find_record<'a>(&self, records: &'a [TraceRecord], id: u64) -> Option<&'a TraceRecord> {
        for record in records {
            if record.id == id {
                return Some(record);
            }
            if let Some(found) = self.find_record(&record.children, id) {
                return Some(found);
            }
        }
        None
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
