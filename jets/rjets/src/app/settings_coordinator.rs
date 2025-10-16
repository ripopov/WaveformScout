//! Generic settings persistence coordination.
//!
//! Provides a reusable API for persisting application settings to storage.
//! This module follows the same pattern as ThemeCoordinator but is designed
//! to be generic and extensible for any serializable settings.

use serde::{Deserialize, Serialize};

/// Coordinates generic settings persistence.
///
/// This coordinator provides type-safe loading and saving of any serializable
/// settings to eframe's persistent storage. Settings are stored as JSON strings.
pub struct SettingsCoordinator;

impl SettingsCoordinator {
    /// Loads a setting from persistent storage with a default fallback.
    ///
    /// # Type Parameters
    /// * `T` - The type to deserialize, must implement Deserialize and Default
    ///
    /// # Arguments
    /// * `storage` - The eframe storage interface
    /// * `key` - The storage key for this setting
    ///
    /// # Returns
    /// The deserialized value if found and valid, otherwise the default value for type T
    ///
    /// # Examples
    /// ```ignore
    /// let column_widths: [f32; 5] = SettingsCoordinator::load_setting(
    ///     storage,
    ///     "column_widths"
    /// );
    /// ```
    pub fn load_setting<T>(storage: Option<&dyn eframe::Storage>, key: &str) -> T
    where
        T: for<'de> Deserialize<'de> + Default,
    {
        if let Some(storage) = storage {
            if let Some(json_str) = storage.get_string(key) {
                if let Ok(value) = serde_json::from_str(&json_str) {
                    return value;
                }
            }
        }
        T::default()
    }

    /// Saves a setting to persistent storage.
    ///
    /// # Type Parameters
    /// * `T` - The type to serialize, must implement Serialize
    ///
    /// # Arguments
    /// * `storage` - The eframe storage interface (mutable)
    /// * `key` - The storage key for this setting
    /// * `value` - The value to serialize and save
    ///
    /// # Examples
    /// ```ignore
    /// SettingsCoordinator::save_setting(
    ///     storage,
    ///     "column_widths",
    ///     &[250.0, 300.0, 120.0, 120.0, 80.0]
    /// );
    /// ```
    pub fn save_setting<T>(storage: &mut dyn eframe::Storage, key: &str, value: &T)
    where
        T: Serialize,
    {
        if let Ok(json_str) = serde_json::to_string(value) {
            storage.set_string(key, json_str);
            storage.flush();
        }
    }

    /// Loads a setting from persistent storage with a custom default.
    ///
    /// # Type Parameters
    /// * `T` - The type to deserialize, must implement Deserialize
    ///
    /// # Arguments
    /// * `storage` - The eframe storage interface
    /// * `key` - The storage key for this setting
    /// * `default` - The default value to use if loading fails
    ///
    /// # Returns
    /// The deserialized value if found and valid, otherwise the provided default
    pub fn load_setting_or<T>(storage: Option<&dyn eframe::Storage>, key: &str, default: T) -> T
    where
        T: for<'de> Deserialize<'de>,
    {
        if let Some(storage) = storage {
            if let Some(json_str) = storage.get_string(key) {
                if let Ok(value) = serde_json::from_str(&json_str) {
                    return value;
                }
            }
        }
        default
    }

    /// Attempts to load a setting, returning None if not found or invalid.
    ///
    /// # Type Parameters
    /// * `T` - The type to deserialize, must implement Deserialize
    ///
    /// # Arguments
    /// * `storage` - The eframe storage interface
    /// * `key` - The storage key for this setting
    ///
    /// # Returns
    /// Some(value) if found and valid, None otherwise
    pub fn try_load_setting<T>(storage: Option<&dyn eframe::Storage>, key: &str) -> Option<T>
    where
        T: for<'de> Deserialize<'de>,
    {
        let storage = storage?;
        let json_str = storage.get_string(key)?;
        serde_json::from_str(&json_str).ok()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    /// Simple mock storage for testing
    struct MockStorage {
        data: HashMap<String, String>,
    }

    impl MockStorage {
        fn new() -> Self {
            Self {
                data: HashMap::new(),
            }
        }
    }

    impl eframe::Storage for MockStorage {
        fn get_string(&self, key: &str) -> Option<String> {
            self.data.get(key).cloned()
        }

        fn set_string(&mut self, key: &str, value: String) {
            self.data.insert(key.to_string(), value);
        }

        fn flush(&mut self) {}
    }

    #[test]
    fn test_save_and_load_simple() {
        let mut storage = MockStorage::new();

        // Save a value
        SettingsCoordinator::save_setting(&mut storage, "test_key", &42i32);

        // Load it back
        let loaded: i32 = SettingsCoordinator::load_setting(Some(&storage), "test_key");
        assert_eq!(loaded, 42);
    }

    #[test]
    fn test_load_with_default() {
        let storage = MockStorage::new();

        // Try to load non-existent key, should return default
        let loaded: i32 = SettingsCoordinator::load_setting(Some(&storage), "missing_key");
        assert_eq!(loaded, 0); // i32::default()
    }

    #[test]
    fn test_save_and_load_array() {
        let mut storage = MockStorage::new();
        let widths = [250.0, 300.0, 120.0, 120.0, 80.0];

        // Save array
        SettingsCoordinator::save_setting(&mut storage, "widths", &widths);

        // Load it back
        let loaded: [f32; 5] = SettingsCoordinator::load_setting(Some(&storage), "widths");
        assert_eq!(loaded, widths);
    }

    #[test]
    fn test_try_load_setting() {
        let mut storage = MockStorage::new();

        // Non-existent key
        let result: Option<i32> = SettingsCoordinator::try_load_setting(Some(&storage), "missing");
        assert_eq!(result, None);

        // Save and load
        SettingsCoordinator::save_setting(&mut storage, "test", &123i32);
        let result: Option<i32> = SettingsCoordinator::try_load_setting(Some(&storage), "test");
        assert_eq!(result, Some(123));
    }
}
