//! Application-level modules for the JETS trace viewer.
//!
//! This module contains the main application coordinator and centralized state management.

mod app_state;
mod application_coordinator;
mod theme_coordinator;
mod settings_coordinator;

pub use app_state::AppState;
pub use application_coordinator::ApplicationCoordinator;
pub use theme_coordinator::ThemeCoordinator;
pub use settings_coordinator::SettingsCoordinator;
