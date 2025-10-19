//! Timeline panel UI rendering
//!
//! Handles the center/right panel with timeline visualization of trace records.
//! Includes pan, zoom, and event selection capabilities.

use crate::app::AppState;
use crate::io::AsyncLoader;
use crate::rendering::{time_axis_renderer, timeline_overlays, timeline_renderer};
use crate::ui::input::timeline_input_handler;
use crate::ui::virtual_scroll_manager::VirtualScrollManager;
use crate::utils::{get_current_memory_mb, format_memory_mb};
use egui::ScrollArea;
use rjets::ThemeColors;

/// Result of timeline panel interactions that need to be handled by the application.
pub enum TimelinePanelInteraction {
    /// A timeline bar was clicked
    BarClicked {
        record_id: u64,
        was_already_selected: bool,
        first_event_clk: Option<i64>,
    },
    /// An event marker was clicked
    EventClicked {
        record_id: u64,
        event_clk: i64,
    },
}

/// Renders the complete timeline panel with time axis, scrollable content, and overlays.
///
/// This function encapsulates all timeline panel rendering logic that was previously
/// in JetsViewerApp::render_timeline().
pub fn render_timeline_panel(
    ui: &mut egui::Ui,
    ctx: &egui::Context,
    state: &mut AppState,
    loader: &AsyncLoader,
    theme_colors: &ThemeColors,
    get_record_color: impl Fn(&str) -> egui::Color32,
) -> Option<TimelinePanelInteraction> {
    // Check if loading is in progress
    if loader.is_loading() {
        render_loading_indicator(ui, theme_colors, loader);
        ctx.request_repaint_after(std::time::Duration::from_secs_f32(0.1));
        return None;
    }

    // Check if we have trace data
    let trace = match state.trace.trace_data() {
        Some(t) => t,
        None => {
            ui.label("No trace loaded - open a JETS trace file to view timeline");
            return None;
        }
    };

    // Render time axis header (fixed at top)
    render_timeline_header(ui, state);
    ui.separator();

    // Handle input (zoom, pan, region selection, cursor tracking)
    let canvas_rect = ui.available_rect_before_wrap();
    let canvas_response = ui.interact(
        canvas_rect,
        ui.id().with("timeline_canvas"),
        egui::Sense::drag().union(egui::Sense::hover()),
    );

    // Get mutable references to state components for input handling
    let trace_min_clk = state.trace.min_clk();
    let trace_max_clk = state.trace.max_clk();
    let (viewport_start_clk, viewport_end_clk, zoom_level) = state.viewport.for_input_handler();
    let (is_dragging, drag_start_clk, is_selecting_region, region_start_pos) = state.interaction.for_input_handler();
    let (cursor_hover_pos, cursor_hover_clk) = state.selection.for_input_handler();

    timeline_input_handler::handle_timeline_input(
        ctx,
        canvas_rect,
        &canvas_response,
        viewport_start_clk,
        viewport_end_clk,
        trace_min_clk,
        trace_max_clk,
        zoom_level,
        is_dragging,
        drag_start_clk,
        is_selecting_region,
        region_start_pos,
        cursor_hover_pos,
        cursor_hover_clk,
    );

    // Track interactions to return
    let mut interaction: Option<TimelinePanelInteraction> = None;

    // Scrollable timeline content (synchronized with tree)
    let scroll_area = ScrollArea::vertical()
        .id_salt("timeline_scroll_area")
        .scroll_bar_visibility(egui::scroll_area::ScrollBarVisibility::AlwaysHidden)
        .vertical_scroll_offset(state.viewport.scroll_y());

    let scroll_output = scroll_area.show(ui, |ui| {
        // Get viewport metrics
        let viewport_height = ui.available_height();
        let scroll_offset = state.viewport.scroll_y();

        // Collect visible nodes (filtered or unfiltered based on viewport filter state)
        let visible_nodes = if state.viewport.viewport_filter_enabled() {
            VirtualScrollManager::collect_filtered_visible_nodes(
                trace,
                state.tree.expanded_nodes_set(),
                &mut state.tree_cache,
                scroll_offset,
                viewport_height,
                state.viewport.viewport_start_clk(),
                state.viewport.viewport_end_clk(),
            )
        } else {
            VirtualScrollManager::collect_visible_nodes(
                trace,
                state.tree.expanded_nodes_set(),
                &mut state.tree_cache,
                scroll_offset,
                viewport_height,
            )
        };

        if visible_nodes.is_empty() {
            return;
        }

        // Calculate padding (use filtered count if filter is enabled)
        let total_visible_nodes = if state.viewport.viewport_filter_enabled() {
            state.tree_cache.filtered_node_count.unwrap_or(0)
        } else {
            VirtualScrollManager::get_total_visible_nodes(
                trace,
                state.tree.expanded_nodes_set(),
                &mut state.tree_cache,
            )
        };

        // Add top padding for skipped rows
        let top_padding = VirtualScrollManager::calculate_top_padding(&visible_nodes);
        if top_padding > 0.0 {
            ui.add_space(top_padding);
        }

        // Render visible timeline rows
        for node in &visible_nodes {
            if let Some(row_interaction) = render_timeline_row(
                ui,
                trace,
                node.record_id,
                state.viewport.viewport_start_clk(),
                state.viewport.viewport_end_clk(),
                state.selection.selected_record_id(),
                state.selection.selected_event(),
                state.interaction.is_dragging(),
                theme_colors,
                &get_record_color,
            ) {
                interaction = Some(row_interaction);
            }
        }

        // Add bottom padding for remaining rows
        let bottom_padding =
            VirtualScrollManager::calculate_bottom_padding(&visible_nodes, total_visible_nodes);
        if bottom_padding > 0.0 {
            ui.add_space(bottom_padding);
        }
    });

    // Draw cursor line overlay if hovering
    if let (Some(hover_pos), Some(hover_clk)) = (state.selection.hover_pos(), state.selection.hover_clk()) {
        timeline_overlays::render_cursor_overlay(
            ctx,
            scroll_output.inner_rect,
            hover_pos,
            hover_clk,
            theme_colors,
        );
    }

    // Draw zoom region selection overlay if active
    if state.interaction.is_selecting_region() {
        if let (Some(start_pos), Some(current_pos)) =
            (state.interaction.region_start_pos(), ctx.input(|i| i.pointer.hover_pos()))
        {
            timeline_overlays::render_region_selection_overlay(
                ctx,
                scroll_output.inner_rect,
                start_pos,
                current_pos,
                theme_colors,
            );
        }
    }

    interaction
}

/// Renders the timeline header area with time axis.
fn render_timeline_header(ui: &mut egui::Ui, state: &AppState) {
    // Match tree header height EXACTLY (24px from render_table_header)
    let header_height = 24.0;

    // Reserve space for the header
    let (header_rect, _) =
        ui.allocate_exact_size(egui::vec2(ui.available_width(), header_height), egui::Sense::hover());

    // Draw time axis in this header space
    time_axis_renderer::render_time_axis(
        ui,
        header_rect,
        state.viewport.viewport_start_clk(),
        state.viewport.viewport_end_clk(),
    );
}

/// Renders a loading indicator when trace is being loaded.
fn render_loading_indicator(ui: &mut egui::Ui, theme_colors: &ThemeColors, _loader: &AsyncLoader) {
    let canvas_rect = ui.available_rect_before_wrap();
    let center_pos = canvas_rect.center();

    let font = egui::FontId::proportional(48.0);
    let memory_font = egui::FontId::proportional(24.0);
    let color = theme_colors.text_dim;

    // Display "Loading..." text
    ui.painter().text(
        center_pos,
        egui::Align2::CENTER_CENTER,
        "Loading...",
        font,
        color,
    );

    // Display memory usage below using centralized utility
    let memory_text = format_memory_mb(get_current_memory_mb());

    let memory_pos = egui::pos2(center_pos.x, center_pos.y + 60.0);
    ui.painter().text(
        memory_pos,
        egui::Align2::CENTER_CENTER,
        memory_text,
        memory_font,
        color,
    );
}

/// Renders a single timeline row (delegates to timeline_renderer).
fn render_timeline_row(
    ui: &mut egui::Ui,
    trace: &rjets::DynTraceData,
    record_id: u64,
    viewport_start_clk: i64,
    viewport_end_clk: i64,
    selected_record_id: Option<u64>,
    selected_event: Option<(u64, i64)>,
    is_dragging: bool,
    theme_colors: &ThemeColors,
    get_record_color: &impl Fn(&str) -> egui::Color32,
) -> Option<TimelinePanelInteraction> {
    timeline_renderer::render_timeline_row(
        ui,
        trace,
        record_id,
        viewport_start_clk,
        viewport_end_clk,
        selected_record_id,
        selected_event,
        is_dragging,
        theme_colors,
        get_record_color,
    )
    .map(|timeline_interaction| match timeline_interaction {
        timeline_renderer::TimelineRowInteraction::BarClicked {
            record_id,
            was_already_selected,
            first_event_clk,
        } => TimelinePanelInteraction::BarClicked {
            record_id,
            was_already_selected,
            first_event_clk,
        },
        timeline_renderer::TimelineRowInteraction::EventClicked {
            record_id,
            event_clk,
        } => TimelinePanelInteraction::EventClicked {
            record_id,
            event_clk,
        },
    })
}
