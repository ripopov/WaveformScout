//! Panel orchestration and layout management.
//!
//! Coordinates all UI panels (header, tree, timeline, details, status) and manages
//! their layout, resizing, and interaction coordination.

use crate::app::AppState;
use crate::io::AsyncLoader;
use crate::ui::{details_panel, header, status_bar, timeline_panel, tree_panel};
use crate::presentation::color_mapping;
use egui::Color32;

/// Result of panel interactions that need to be handled by the application coordinator.
pub enum PanelInteraction {
    /// User requested to open a file
    OpenFileRequested(std::path::PathBuf),
    /// User requested to open a virtual trace
    OpenVirtualTraceRequested,
    /// A tree node was selected
    TreeNodeSelected {
        record_id: u64,
        was_already_selected: bool,
        first_event_clk: Option<i64>,
    },
    /// A tree node's expansion state was toggled
    TreeNodeExpandToggled {
        record_id: u64,
        was_expanded: bool,
    },
    /// A timeline bar was clicked
    TimelineBarClicked {
        record_id: u64,
        was_already_selected: bool,
        first_event_clk: Option<i64>,
    },
    /// A timeline event was clicked
    TimelineEventClicked {
        record_id: u64,
        event_clk: i64,
    },
}

/// Manages the layout and rendering of all UI panels.
pub struct PanelManager;

impl PanelManager {
    /// Renders all panels in the application window.
    ///
    /// This is the main entry point for rendering the entire UI, called from
    /// the eframe::App::update() implementation.
    pub fn render_all_panels(
        ctx: &egui::Context,
        state: &mut AppState,
        loader: &AsyncLoader,
    ) -> Option<PanelInteraction> {
        let mut interaction: Option<PanelInteraction> = None;

        // Get theme colors for rendering
        let theme_colors = color_mapping::theme_colors(state.theme.theme_manager(), state.theme.current_theme_name()).clone();

        // Header panel at the top
        egui::TopBottomPanel::top("header").show(ctx, |ui| {
            if let Some(header_interaction) = header::render_header(ui, state) {
                interaction = Some(match header_interaction {
                    header::HeaderInteraction::OpenFileRequested(path) => {
                        PanelInteraction::OpenFileRequested(path)
                    }
                    header::HeaderInteraction::OpenVirtualTraceRequested => {
                        PanelInteraction::OpenVirtualTraceRequested
                    }
                });
            }
        });

        // Status panel at the very bottom
        egui::TopBottomPanel::bottom("status_panel").show(ctx, |ui| {
            status_bar::render_status_bar(ui, state);
        });

        // Details panel above status panel
        egui::TopBottomPanel::bottom("details_panel")
            .default_height(ctx.content_rect().height() * (1.0 - state.layout.split_ratio()))
            .resizable(true)
            .show(ctx, |ui| {
                egui::Frame::default().inner_margin(4.0).show(ui, |ui| {
                    details_panel::render_details_panel(ui, state, &theme_colors);
                });
            });

        // Left panel: Tree
        let tree_frame = egui::Frame::default()
            .inner_margin(egui::Margin::same(4))
            .fill(ctx.style().visuals.panel_fill);

        egui::SidePanel::left("tree_panel")
            .default_width(ctx.content_rect().width() * state.layout.timeline_split_ratio())
            .resizable(true)
            .frame(tree_frame)
            .show(ctx, |ui| {
                ui.heading("Trace Records");
                ui.separator();

                if let Some(tree_interaction) = tree_panel::render_tree_panel(ui, state, &theme_colors) {
                    interaction = Some(match tree_interaction {
                        tree_panel::TreePanelInteraction::NodeSelected {
                            record_id,
                            was_already_selected,
                            first_event_clk,
                        } => PanelInteraction::TreeNodeSelected {
                            record_id,
                            was_already_selected,
                            first_event_clk,
                        },
                        tree_panel::TreePanelInteraction::NodeExpandToggled {
                            record_id,
                            was_expanded,
                        } => PanelInteraction::TreeNodeExpandToggled {
                            record_id,
                            was_expanded,
                        },
                    });
                }
            });

        // Right panel: Timeline
        let timeline_frame = egui::Frame::default()
            .inner_margin(egui::Margin::same(4))
            .fill(ctx.style().visuals.panel_fill);

        egui::CentralPanel::default()
            .frame(timeline_frame)
            .show(ctx, |ui| {
                ui.heading("Timeline View");
                ui.separator();

                // Create color mapping closure
                let get_record_color = |name: &str| -> Color32 {
                    color_mapping::get_record_color(name, &theme_colors)
                };

                if let Some(timeline_interaction) = timeline_panel::render_timeline_panel(
                    ui,
                    ctx,
                    state,
                    loader,
                    &theme_colors,
                    get_record_color,
                ) {
                    interaction = Some(match timeline_interaction {
                        timeline_panel::TimelinePanelInteraction::BarClicked {
                            record_id,
                            was_already_selected,
                            first_event_clk,
                        } => PanelInteraction::TimelineBarClicked {
                            record_id,
                            was_already_selected,
                            first_event_clk,
                        },
                        timeline_panel::TimelinePanelInteraction::EventClicked {
                            record_id,
                            event_clk,
                        } => PanelInteraction::TimelineEventClicked {
                            record_id,
                            event_clk,
                        },
                    });
                }
            });

        interaction
    }
}
