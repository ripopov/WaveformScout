use std::sync::Arc;
use std::collections::HashMap;

/// String interning pool for reducing memory usage by deduplicating strings.
///
/// When parsing large trace files with millions of records, many strings
/// (like record names, types, and descriptions) are repeated frequently.
/// String interning stores each unique string once and returns shared references,
/// dramatically reducing memory usage.
///
/// # Examples
///
/// ```
/// use rjets::StringInterner;
/// use std::sync::Arc;
///
/// let mut interner = StringInterner::new();
/// let s1 = interner.intern("hello");
/// let s2 = interner.intern("hello");
/// assert!(Arc::ptr_eq(&s1, &s2)); // Same underlying memory
/// ```
pub struct StringInterner {
    pool: HashMap<String, Arc<str>>,
}

impl StringInterner {
    /// Creates a new empty string interner.
    pub fn new() -> Self {
        Self::with_capacity(1024)
    }

    /// Creates a new string interner with the specified capacity.
    ///
    /// Pre-allocating capacity can improve performance when you know
    /// approximately how many unique strings to expect.
    pub fn with_capacity(capacity: usize) -> Self {
        StringInterner {
            pool: HashMap::with_capacity(capacity),
        }
    }

    /// Interns a string, returning a shared reference.
    ///
    /// If the string has been interned before, returns the existing Arc.
    /// Otherwise, creates a new Arc and stores it in the pool.
    pub fn intern(&mut self, s: &str) -> Arc<str> {
        if let Some(interned) = self.pool.get(s) {
            Arc::clone(interned)
        } else {
            let arc: Arc<str> = Arc::from(s);
            self.pool.insert(s.to_string(), Arc::clone(&arc));
            arc
        }
    }

    /// Returns the number of unique strings interned.
    pub fn len(&self) -> usize {
        self.pool.len()
    }

    /// Returns true if no strings have been interned.
    pub fn is_empty(&self) -> bool {
        self.pool.is_empty()
    }

    /// Clears the interner, removing all interned strings.
    pub fn clear(&mut self) {
        self.pool.clear();
    }
}

impl Default for StringInterner {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_basic_interning() {
        let mut interner = StringInterner::new();
        let s1 = interner.intern("hello");
        let s2 = interner.intern("hello");

        // Should return the same Arc
        assert!(Arc::ptr_eq(&s1, &s2));
        assert_eq!(interner.len(), 1);
    }

    #[test]
    fn test_multiple_strings() {
        let mut interner = StringInterner::new();
        let s1 = interner.intern("foo");
        let s2 = interner.intern("bar");
        let s3 = interner.intern("foo");

        assert!(Arc::ptr_eq(&s1, &s3));
        assert!(!Arc::ptr_eq(&s1, &s2));
        assert_eq!(interner.len(), 2);
    }

    #[test]
    fn test_empty_string() {
        let mut interner = StringInterner::new();
        let s1 = interner.intern("");
        let s2 = interner.intern("");

        assert!(Arc::ptr_eq(&s1, &s2));
        assert_eq!(interner.len(), 1);
    }

    #[test]
    fn test_clear() {
        let mut interner = StringInterner::new();
        interner.intern("test");
        assert_eq!(interner.len(), 1);

        interner.clear();
        assert_eq!(interner.len(), 0);
        assert!(interner.is_empty());
    }
}
