//! JETS Trace Viewer GUI Application
//!
//! This module provides an interactive graphical viewer for JETS trace files using the egui framework.
//! The viewer features:
//! - Hierarchical tree view of trace records with virtual scrolling for performance
//! - Timeline visualization with zoom, pan, and event markers
//! - Asynchronous file loading with loading indicators
//! - Multiple theme support with persistent preferences
//! - Details panel for viewing record annotations and events
//!
//! The application is built with a modular architecture:
//! - `app/` - Application state management and coordination
//! - `domain/` - Core business logic (tree operations, viewport calculations)
//! - `presentation/` - Visual styling and color mapping (separated from domain logic)
//! - `cache/` - Performance caching for tree computations
//! - `io/` - File loading and virtual trace generation
//! - `utils/` - Utility functions for formatting and geometry
//! - `ui/` - UI panel rendering, interaction, and input handling
//! - `rendering/` - Low-level rendering for tree nodes and timelines
//! - `state/` - State management for viewport and selection

use eframe::egui;

mod utils;
mod cache;
mod domain;
mod presentation;
mod io;
mod app;
mod rendering;
mod ui;
mod state;

use app::{AppState, ApplicationCoordinator, ThemeCoordinator};
use io::AsyncLoader;
use ui::panel_manager::PanelManager;

/// Main application entry point that initializes and launches the JETS trace viewer GUI.
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
        Box::new(|cc| Ok(Box::new(JetsViewerApp::new(cc)))),
    )
}

/// The main JETS Trace Viewer application.
///
/// This struct is now much simpler, delegating most functionality to coordinators:
/// - `ApplicationCoordinator` handles file loading, error handling, and interaction logic
/// - `ThemeCoordinator` handles theme persistence and application
/// - `PanelManager` handles UI panel layout and rendering
struct JetsViewerApp {
    /// Centralized application state
    state: AppState,
    /// Asynchronous file loader
    loader: AsyncLoader,
}

impl Default for JetsViewerApp {
    fn default() -> Self {
        Self {
            state: AppState::new(),
            loader: AsyncLoader::new(),
        }
    }
}

impl JetsViewerApp {
    /// Creates a new viewer instance with theme loaded from persistent storage.
    fn new(cc: &eframe::CreationContext) -> Self {
        let current_theme_name = ThemeCoordinator::load_theme_from_storage(cc.storage);

        Self {
            state: AppState::with_theme(current_theme_name),
            loader: AsyncLoader::new(),
        }
    }

    /// Handles panel interactions by delegating to ApplicationCoordinator.
    fn handle_panel_interaction(&mut self, interaction: ui::panel_manager::PanelInteraction, ctx: &egui::Context) {
        match interaction {
            ui::panel_manager::PanelInteraction::OpenFileRequested(path) => {
                ApplicationCoordinator::open_file(&mut self.state, &mut self.loader, path, ctx);
            }
            ui::panel_manager::PanelInteraction::OpenVirtualTraceRequested => {
                ApplicationCoordinator::open_virtual_trace(&mut self.state, &mut self.loader);
            }
            ui::panel_manager::PanelInteraction::TreeNodeSelected {
                record_id,
                was_already_selected,
                first_event_clk,
            } => {
                ApplicationCoordinator::handle_node_selection(
                    &mut self.state,
                    record_id,
                    was_already_selected,
                    first_event_clk,
                );
            }
            ui::panel_manager::PanelInteraction::TreeNodeExpandToggled {
                record_id,
                was_expanded,
            } => {
                ApplicationCoordinator::handle_node_expand_toggle(
                    &mut self.state,
                    record_id,
                    was_expanded,
                );
            }
            ui::panel_manager::PanelInteraction::TimelineBarClicked {
                record_id,
                was_already_selected,
                first_event_clk,
            } => {
                ApplicationCoordinator::handle_timeline_bar_click(
                    &mut self.state,
                    record_id,
                    was_already_selected,
                    first_event_clk,
                );
            }
            ui::panel_manager::PanelInteraction::TimelineEventClicked {
                record_id,
                event_clk,
            } => {
                ApplicationCoordinator::handle_timeline_event_click(
                    &mut self.state,
                    record_id,
                    event_clk,
                );
            }
        }
    }
}

impl Drop for JetsViewerApp {
    fn drop(&mut self) {
        eprintln!(
            "DEBUG [drop]: Application shutting down with theme: '{}'",
            self.state.theme.current_theme_name()
        );
    }
}

impl eframe::App for JetsViewerApp {
    /// Called when the app is being shut down - ensures preferences are saved.
    fn save(&mut self, storage: &mut dyn eframe::Storage) {
        ThemeCoordinator::save_theme_to_storage(storage, self.state.theme.current_theme_name());
    }

    /// Main update loop that renders all UI panels and handles application state.
    ///
    /// This method is now very simple - it delegates to coordinators:
    /// 1. Check for async loading completion
    /// 2. Apply theme
    /// 3. Render all panels via PanelManager
    /// 4. Handle panel interactions
    fn update(&mut self, ctx: &egui::Context, frame: &mut eframe::Frame) {
        // Check for async loading completion
        ApplicationCoordinator::check_loading_completion(&mut self.state, &mut self.loader);

        // Apply current theme
        ThemeCoordinator::apply_current_theme(ctx, &self.state);

        // Persist theme preference during frame (for crash resilience)
        if let Some(storage) = frame.storage_mut() {
            storage.set_string("theme_preference", self.state.theme.current_theme_name().to_string());
        }

        // Render all panels and get interaction result
        if let Some(interaction) = PanelManager::render_all_panels(ctx, &mut self.state, &self.loader) {
            self.handle_panel_interaction(interaction, ctx);
        }
    }
}
