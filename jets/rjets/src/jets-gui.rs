//! JETS Trace Viewer GUI Application
//!
//! This module provides an interactive graphical viewer for JETS trace files using the egui framework.
//! The viewer features:
//! - Hierarchical tree view of trace records with virtual scrolling for performance
//! - Timeline visualization with zoom, pan, and event markers

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
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
use std::path::PathBuf;

mod utils;
mod cache;
mod domain;
mod presentation;
mod io;
mod app;
mod rendering;
mod ui;
mod state;

use app::{AppState, ApplicationCoordinator, ThemeCoordinator, SettingsCoordinator};
use io::AsyncLoader;
use ui::panel_manager::PanelManager;

const COLUMN_WIDTHS_KEY: &str = "column_widths";
const EXPAND_WIDTH_KEY: &str = "expand_width";

/// Main application entry point that initializes and launches the JETS trace viewer GUI.
fn main() -> eframe::Result {
    // Parse command-line arguments to check for initial file to load
    let initial_file = std::env::args()
        .nth(1)
        .map(PathBuf::from);

    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([1200.0, 800.0])
            .with_title("JETS Trace Viewer"),
        ..Default::default()
    };

    eframe::run_native(
        "JETS Trace Viewer",
        options,
        Box::new(move |cc| Ok(Box::new(JetsViewerApp::new(cc, initial_file)))),
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
    /// Optional file to load on first frame
    pending_file_load: Option<PathBuf>,
}

impl Default for JetsViewerApp {
    fn default() -> Self {
        Self {
            state: AppState::new(),
            loader: AsyncLoader::new(),
            pending_file_load: None,
        }
    }
}

impl JetsViewerApp {
    /// Creates a new viewer instance with theme and layout settings loaded from persistent storage.
    /// Optionally accepts an initial file path to load on startup.
    fn new(cc: &eframe::CreationContext, initial_file: Option<PathBuf>) -> Self {
        let current_theme_name = ThemeCoordinator::load_theme_from_storage(cc.storage);

        // Load column widths with proper defaults (not [0.0, 0.0, 0.0, 0.0, 0.0])
        // Default widths: [Name, Description, Start Clock, End Clock, ID]
        let default_widths = [100.0, 300.0, 120.0, 120.0, 80.0];
        let column_widths: [f32; 5] = SettingsCoordinator::load_setting_or(
            cc.storage,
            COLUMN_WIDTHS_KEY,
            default_widths
        );

        // Load expand width with proper default
        let default_expand_width = 100.0;
        let expand_width: f32 = SettingsCoordinator::load_setting_or(
            cc.storage,
            EXPAND_WIDTH_KEY,
            default_expand_width
        );

        Self {
            state: AppState::with_theme_and_layout(current_theme_name, column_widths, expand_width),
            loader: AsyncLoader::new(),
            pending_file_load: initial_file,
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

impl eframe::App for JetsViewerApp {
    /// Called when the app is being shut down - ensures preferences are saved.
    fn save(&mut self, storage: &mut dyn eframe::Storage) {
        ThemeCoordinator::save_theme_to_storage(storage, self.state.theme.current_theme_name());
        SettingsCoordinator::save_setting(storage, COLUMN_WIDTHS_KEY, self.state.layout.column_widths());
        SettingsCoordinator::save_setting(storage, EXPAND_WIDTH_KEY, &self.state.layout.expand_width());
    }

    /// Main update loop that renders all UI panels and handles application state.
    ///
    /// This method is now very simple - it delegates to coordinators:
    /// 1. Check for async loading completion
    /// 2. Apply theme
    /// 3. Load initial file if specified via command line
    /// 4. Render all panels via PanelManager
    /// 5. Handle panel interactions
    fn update(&mut self, ctx: &egui::Context, frame: &mut eframe::Frame) {
        // Check for async loading completion
        ApplicationCoordinator::check_loading_completion(&mut self.state, &mut self.loader);

        // Apply current theme
        ThemeCoordinator::apply_current_theme(ctx, &self.state);

        // Persist preferences during frame (for crash resilience)
        if let Some(storage) = frame.storage_mut() {
            storage.set_string("theme_preference", self.state.theme.current_theme_name().to_string());
            SettingsCoordinator::save_setting(storage, COLUMN_WIDTHS_KEY, self.state.layout.column_widths());
            SettingsCoordinator::save_setting(storage, EXPAND_WIDTH_KEY, &self.state.layout.expand_width());
        }

        // Load initial file if specified via command line (only on first frame)
        if let Some(path) = self.pending_file_load.take() {
            ApplicationCoordinator::open_file(&mut self.state, &mut self.loader, path, ctx);
        }

        // Render all panels and get interaction result
        if let Some(interaction) = PanelManager::render_all_panels(ctx, &mut self.state, &self.loader) {
            self.handle_panel_interaction(interaction, ctx);
        }
    }
}
