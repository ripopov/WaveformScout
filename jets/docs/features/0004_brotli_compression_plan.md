# JETS Feature Plan: Brotli Compression Support

**Feature ID:** 0004
**Feature Name:** Brotli Compression Support for JETS Traces
**Author:** JETS Agentic Coding Feature Architect
**Date:** 2025-10-11
**Target Version:** JETS v0.4.0

---

## 1. Use Cases and Requirements Analysis

### 1.1 Problem Statement

JETS trace files can grow very large, especially for long-running hardware simulations with millions of records and events. Currently, JETS files are stored as uncompressed JSON Lines (`.jets` or `.jsonl` files), which leads to:

1. **Storage Overhead**: Large traces can consume gigabytes of disk space
2. **Transfer Cost**: Moving traces between systems is slow and bandwidth-intensive
3. **Missing Compression**: No built-in compression support in the format

### 1.2 Solution Overview

Add transparent Brotli compression support to the JETS toolchain:

1. **Writer Support** (`writer.rs`): Enable writing Brotli-compressed traces
2. **Parser Support** (`parser.rs`): Enable reading Brotli-compressed traces with automatic detection
3. **Tracegen Support** (`tracegen.rs`): Add `-brotli` command-line option to generate compressed traces
4. **File Extension Convention**: Use `.jets.br` or `.jsonl.br` extensions for compressed traces
5. **Automatic Detection**: Parser automatically detects Brotli compression based on file extension

**Why Brotli?**
- **Superior Compression**: Better compression ratios than gzip for text/JSON data (typically 15-25% smaller)
- **Maintained**: Actively maintained by Google/Dropbox
- **Fast Decompression**: Excellent decompression speed for streaming scenarios
- **Rust Support**: Mature `brotli` crate (version 8.0.2) with PyO3-compatible streaming API

### 1.3 Functional Requirements

#### FR-1: Brotli Compression in TraceWriter
**Priority:** MUST HAVE

**Description:** `TraceWriter` must support writing Brotli-compressed JETS traces.

**Acceptance Criteria:**
- `TraceWriter::new()` detects Brotli compression based on file extension (`.jets.br`, `.jsonl.br`)
- Compression is transparent to the caller (same API as uncompressed writing)
- All existing write methods (`write_header()`, `write_record()`, etc.) work identically
- Compression uses Brotli quality level 6 (balanced speed/ratio) by default
- Proper resource cleanup (flush and close Brotli encoder on drop)

**Design Pattern:**
```rust
// Internal writer enum to support both compressed and uncompressed
enum WriterImpl {
    Uncompressed(BufWriter<File>),
    Brotli(brotli::CompressorWriter<BufWriter<File>>),
}

pub struct TraceWriter {
    writer: WriterImpl,
    // ... existing fields
}
```

---

#### FR-2: Brotli Decompression in Parser
**Priority:** MUST HAVE

**Description:** `parse_trace()` function must automatically detect and decompress Brotli-compressed traces.

**Acceptance Criteria:**
- `parse_trace(path)` detects Brotli compression based on file extension
- Decompression is transparent to the caller (same return type as uncompressed parsing)
- All existing parsing logic works identically with compressed traces
- Error messages distinguish between compression errors and format errors
- Proper resource cleanup (Brotli decompressor closed on scope exit)

**Design Pattern:**
```rust
// Internal reader enum to support both compressed and uncompressed
enum ReaderImpl {
    Uncompressed(BufReader<File>),
    Brotli(brotli::Decompressor<BufReader<File>>),
}

// Helper function to create appropriate reader based on extension
fn create_reader(file_path: &str) -> Result<Box<dyn BufRead>> {
    let file = File::open(file_path)?;
    if file_path.ends_with(".br") {
        Ok(Box::new(BufReader::new(brotli::Decompressor::new(file, 4096))))
    } else {
        Ok(Box::new(BufReader::new(file)))
    }
}
```

---

#### FR-3: Tracegen Command-Line Option
**Priority:** MUST HAVE

**Description:** `jets-tracegen` utility must support a `-brotli` flag to generate compressed traces.

**Acceptance Criteria:**
- New `-brotli` command-line flag added to argument parser
- When `-brotli` is specified, output file extension automatically becomes `.jets.br` (unless `-out` specifies otherwise)
- Help text (`-help`) documents the `-brotli` option
- Compression does not affect trace generation logic (same content, compressed format)
- Default behavior (no `-brotli`) remains unchanged (uncompressed `.jets` file)

**Example Usage:**
```bash
# Generate compressed trace with default output name (trace.jets.br)
./jets-tracegen -num_clt 2 -num_core 4 -brotli

# Generate compressed trace with custom output name
./jets-tracegen -num_clt 2 -num_core 4 -brotli -out my_trace.jets.br

# Generate uncompressed trace (existing behavior)
./jets-tracegen -num_clt 2 -num_core 4 -out trace.jets
```

---

#### FR-4: Integration Test
**Priority:** MUST HAVE

**Description:** Add integration test to verify round-trip writing and reading of Brotli-compressed traces.

**Acceptance Criteria:**
- Test writes a complete JETS trace with Brotli compression
- Test reads the compressed trace back
- Test verifies all data matches original (header, records, events, annotations, footer)
- Test verifies file size is significantly smaller than uncompressed version
- Test is added to `jets/rjets/tests/integration_test.rs`
- Test passes in CI environment

**Test Structure:**
```rust
#[test]
fn test_brotli_round_trip() -> Result<()> {
    // 1. Write compressed trace
    let compressed_path = "/tmp/test_trace.jets.br";
    // ... write test data ...

    // 2. Read compressed trace
    let trace = parse_trace(compressed_path)?;

    // 3. Verify contents
    assert_eq!(trace.metadata().version(), "2.0");
    // ... verify all records, events, annotations ...

    // 4. Compare file sizes
    let uncompressed_size = write_uncompressed_version();
    let compressed_size = fs::metadata(compressed_path)?.len();
    assert!(compressed_size < uncompressed_size);

    Ok(())
}
```

---

#### FR-5: File Extension Conventions
**Priority:** MUST HAVE

**Description:** Establish and document file extension conventions for compressed traces.

**Acceptance Criteria:**
- `.jets.br` is the primary extension for Brotli-compressed JETS traces
- `.jsonl.br` is also supported (for compatibility with generic JSON Lines tools)
- Both extensions are recognized by parser for automatic decompression
- `TraceWriter::new()` automatically enables compression for paths ending in `.br`
- Documentation updated to reflect extension conventions

---

#### NFR-1: Error Handling
**Priority:** MUST HAVE

**Requirements:**
- Clear error messages for corruption/truncation of compressed files
- Distinguish between compression errors and format errors
- Graceful handling of invalid Brotli streams
- Context propagation using `anyhow::Context` for debugging

**Error Message Examples:**
```
Error: Failed to decompress Brotli stream
Caused by:
    0: Invalid Brotli header
    1: File may be corrupted: trace.jets.br
```

---

## 2. Codebase Research

### 2.1 Current Writer Implementation

**File:** `jets/rjets/src/writer.rs`

**Current Structure (lines 6-24):**
```rust
pub struct TraceWriter {
    writer: BufWriter<File>,  // Direct file writer
    record_count: usize,
    annotation_count: usize,
    event_count: usize,
}

impl TraceWriter {
    pub fn new(file_path: &str) -> Result<Self> {
        let file = File::create(file_path)?;
        Ok(TraceWriter {
            writer: BufWriter::new(file),
            // ...
        })
    }
}
```

**Key Observations:**
- `writer` field is currently `BufWriter<File>` (concrete type, not trait object)
- All write operations go through `write_line()` method (line 133-144)
- `write_line()` serializes to JSON, writes to `writer`, and flushes
- Flush on every line ensures immediate write (important for streaming)

**Required Changes:**
- Replace `BufWriter<File>` with abstraction that supports both compressed and uncompressed
- Detect compression based on file extension in `new()`
- Wrap writer with `brotli::CompressorWriter` when compression is needed

---

### 2.2 Current Parser Implementation

**File:** `jets/rjets/src/parser.rs`

**Current Structure (lines 140-158):**
```rust
pub fn parse_trace(file_path: &str) -> Result<JetsTraceData> {
    let file = File::open(file_path)?;
    let reader = BufReader::new(file);

    for (line_num, line_result) in reader.lines().enumerate() {
        let line = line_result?;
        // ... parse JSON ...
    }
}
```

**Key Observations:**
- Uses `BufReader<File>::lines()` iterator for line-by-line reading
- Does not currently check file extension or detect compression
- Error handling uses `anyhow::Context` for error propagation

**Required Changes:**
- Detect file extension before opening file
- Wrap `BufReader<File>` with `brotli::Decompressor` when `.br` extension detected
- Use trait object `Box<dyn BufRead>` to unify compressed and uncompressed readers
- `.lines()` iterator works identically on both `BufReader` and `Decompressor`

---

### 2.3 Current Tracegen Implementation

**File:** `jets/rjets/src/tracegen.rs`

**Current Argument Parsing (lines 119-185):**
```rust
fn parse_args() -> Result<Config> {
    let args: Vec<String> = env::args().collect();
    let mut config = Config::default();

    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "-num_clt" => { /* ... */ }
            "-num_core" => { /* ... */ }
            "-num_threads" => { /* ... */ }
            "-num_instr" => { /* ... */ }
            "-out" => { /* ... */ }
            "-h" | "-help" | "--help" => { /* ... */ }
            _ => { /* warning */ }
        }
        i += 1;
    }
}
```

**Current Config Structure (lines 63-83):**
```rust
struct Config {
    num_clusters: usize,
    num_cores: usize,
    num_threads: usize,
    num_instr_min: usize,
    num_instr_max: usize,
    output_file: Option<String>,
}
```

**Current Output File Handling (lines 201-212):**
```rust
fn main() -> Result<()> {
    let config = parse_args()?;

    let output_path = config.output_file.clone()
        .unwrap_or_else(|| "trace.jets".to_string());
    let mut writer = TraceWriter::new(&output_path)?;
    // ...
}
```

**Required Changes:**
- Add `use_brotli: bool` field to `Config` struct
- Add `-brotli` case to argument parser
- Adjust default output filename logic: if `use_brotli && output_file.is_none()`, use `"trace.jets.br"`
- Update help text to document `-brotli` option

---

### 2.4 Brotli Crate API Overview

**Documentation Source:** https://github.com/dropbox/rust-brotli

**Crate:** `brotli = "8.0.2"`

**Key Types:**

**1. Compression:**
```rust
use brotli::enc::BrotliEncoderParams;
use brotli::CompressorWriter;

// Create compressor with default quality (11)
let compressor = CompressorWriter::new(writer, 4096, 11, 22);

// Create compressor with custom quality
let params = BrotliEncoderParams {
    quality: 6,  // 0-11, higher = better compression but slower
    lgwin: 22,   // window size
    // ...
};
let compressor = CompressorWriter::with_params(writer, 4096, &params);
```

**2. Decompression:**
```rust
use brotli::Decompressor;

// Create decompressor
let decompressor = Decompressor::new(reader, 4096);

// Use as BufRead
use std::io::BufRead;
for line in BufReader::new(decompressor).lines() {
    // ...
}
```

**Compression Quality Levels:**
- **0-3**: Fast compression, lower ratio (suitable for real-time streaming)
- **4-6**: Balanced (recommended for JETS traces)
- **7-9**: Slower, better ratio
- **10-11**: Maximum compression, very slow

**Recommendation for JETS:** Quality level **6** provides excellent compression ratio with acceptable encoding speed for trace generation.

---

### 2.5 Integration Test Structure

**File:** `jets/rjets/tests/integration_test.rs`

**Existing Test Pattern (lines 6-144):**
```rust
#[test]
fn test_write_and_read_basic_trace() -> Result<()> {
    let test_file = "/tmp/test_trace.jets";

    // Clean up
    let _ = fs::remove_file(test_file);

    // Write trace
    {
        let mut writer = TraceWriter::new(test_file)?;
        // ... write header, records, events, etc. ...
    }

    // Read trace
    let reader: Box<dyn TraceReader> = Box::new(JetsTraceReader::new());
    let trace = reader.read(test_file)?;

    // Verify contents
    assert_eq!(trace.metadata().version(), "2.0");
    // ... assertions ...

    // Clean up
    fs::remove_file(test_file)?;

    Ok(())
}
```

**Observation:** Clean, self-contained test pattern. New Brotli test should follow same structure.

**Required Test:**
- New test function: `test_brotli_write_and_read()`
- Write compressed trace to `/tmp/test_brotli_trace.jets.br`
- Read back using `parse_trace()` (automatic decompression)
- Verify all data matches
- Compare file sizes (compressed vs. uncompressed)
- Clean up test files

---

## 3. Implementation Planning

### 3.1 File-by-File Changes

#### **File:** `jets/rjets/Cargo.toml`

**Purpose:** Add Brotli dependency.

**Changes:**

**Add dependency (after line 15):**
```toml
brotli = "8.0.2"
```

**Rationale:** Latest stable version with streaming API and PyO3 compatibility.

---

#### **File:** `jets/rjets/src/writer.rs`

**Purpose:** Add Brotli compression support to `TraceWriter`.

**Changes:**

**1. Add imports (after line 3):**
```rust
use brotli::enc::BrotliEncoderParams;
use brotli::CompressorWriter;
```

**2. Replace `writer` field type (line 7):**

**Before:**
```rust
pub struct TraceWriter {
    writer: BufWriter<File>,
    // ...
}
```

**After:**
```rust
pub struct TraceWriter {
    writer: Box<dyn Write>,  // Trait object to support both compressed and uncompressed
    record_count: usize,
    annotation_count: usize,
    event_count: usize,
}
```

**Rationale:** Using `Box<dyn Write>` allows us to abstract over `BufWriter<File>` and `CompressorWriter<BufWriter<File>>`.

**3. Modify `new()` constructor (lines 14-24):**

**Before:**
```rust
pub fn new(file_path: &str) -> Result<Self> {
    let file = File::create(file_path)?;
    Ok(TraceWriter {
        writer: BufWriter::new(file),
        // ...
    })
}
```

**After:**
```rust
pub fn new(file_path: &str) -> Result<Self> {
    let file = File::create(file_path)
        .with_context(|| format!("Failed to create file: {}", file_path))?;

    let writer: Box<dyn Write> = if file_path.ends_with(".br") {
        // Brotli compression enabled
        let buf_writer = BufWriter::new(file);
        let params = BrotliEncoderParams {
            quality: 6,  // Balanced compression
            lgwin: 22,   // Window size
            ..Default::default()
        };
        Box::new(CompressorWriter::with_params(buf_writer, 4096, &params))
    } else {
        // No compression
        Box::new(BufWriter::new(file))
    };

    Ok(TraceWriter {
        writer,
        record_count: 0,
        annotation_count: 0,
        event_count: 0,
    })
}
```

**Integration Points:**
- Automatic detection based on file extension
- No API changes for callers
- Compression is transparent

**4. No changes needed to other methods:**
- `write_header()`, `write_record()`, `write_event()`, etc. remain unchanged
- `write_line()` uses `writeln!(self.writer, ...)` which works with trait object
- `Drop` implementation continues to flush (works with trait object)

---

#### **File:** `jets/rjets/src/parser.rs`

**Purpose:** Add Brotli decompression support to `parse_trace()`.

**Changes:**

**1. Add imports (after line 5):**
```rust
use brotli::Decompressor;
```

**2. Modify `parse_trace()` function (lines 140-158):**

**Before:**
```rust
pub fn parse_trace(file_path: &str) -> Result<JetsTraceData> {
    let file = File::open(file_path)
        .with_context(|| format!("Failed to open file: {}", file_path))?;
    let reader = BufReader::new(file);

    for (line_num, line_result) in reader.lines().enumerate() {
        // ... parsing logic ...
    }
}
```

**After:**
```rust
pub fn parse_trace(file_path: &str) -> Result<JetsTraceData> {
    let file = File::open(file_path)
        .with_context(|| format!("Failed to open file: {}", file_path))?;

    let reader: Box<dyn BufRead> = if file_path.ends_with(".br") {
        // Brotli decompression enabled
        let decompressor = Decompressor::new(file, 4096);
        Box::new(BufReader::new(decompressor))
    } else {
        // No decompression
        Box::new(BufReader::new(file))
    };

    for (line_num, line_result) in reader.lines().enumerate() {
        // ... existing parsing logic unchanged ...
    }
}
```

**Integration Points:**
- Automatic detection based on file extension
- `BufRead::lines()` works identically for both compressed and uncompressed
- No changes to parsing logic
- Error context includes file path for debugging

**3. Add decompression error context:**

**After file opening (before line iteration):**
```rust
let reader: Box<dyn BufRead> = if file_path.ends_with(".br") {
    let decompressor = Decompressor::new(file, 4096);
    Box::new(BufReader::new(decompressor))
} else {
    Box::new(BufReader::new(file))
}.with_context(|| format!("Failed to initialize reader for: {}", file_path))?;
```

**Note:** If `Decompressor::new()` returns `Result`, we need error handling. Based on the crate docs, it does NOT return `Result`, so no additional error handling needed at construction.

---

#### **File:** `jets/rjets/src/tracegen.rs`

**Purpose:** Add `-brotli` command-line option.

**Changes:**

**1. Add field to `Config` struct (line 69):**

**Before:**
```rust
struct Config {
    num_clusters: usize,
    num_cores: usize,
    num_threads: usize,
    num_instr_min: usize,
    num_instr_max: usize,
    output_file: Option<String>,
}
```

**After:**
```rust
struct Config {
    num_clusters: usize,
    num_cores: usize,
    num_threads: usize,
    num_instr_min: usize,
    num_instr_max: usize,
    output_file: Option<String>,
    use_brotli: bool,
}
```

**2. Update `Default` implementation (lines 72-82):**

**Before:**
```rust
impl Default for Config {
    fn default() -> Self {
        Config {
            num_clusters: 1,
            num_cores: 1,
            num_threads: 1,
            num_instr_min: 100,
            num_instr_max: 100,
            output_file: None,
        }
    }
}
```

**After:**
```rust
impl Default for Config {
    fn default() -> Self {
        Config {
            num_clusters: 1,
            num_cores: 1,
            num_threads: 1,
            num_instr_min: 100,
            num_instr_max: 100,
            output_file: None,
            use_brotli: false,
        }
    }
}
```

**3. Add `-brotli` argument handling in `parse_args()` (after line 172):**

**Add case:**
```rust
"-brotli" => {
    config.use_brotli = true;
}
```

**4. Update `print_help()` function (lines 187-199):**

**Add help text after `-out` description:**
```rust
println!("  -brotli                Write compressed trace using Brotli (output: *.jets.br)");
```

**5. Update output file logic in `main()` (lines 201-212):**

**Before:**
```rust
fn main() -> Result<()> {
    let config = parse_args()?;

    let output_path = config.output_file.clone()
        .unwrap_or_else(|| "trace.jets".to_string());
    let mut writer = TraceWriter::new(&output_path)?;
    // ...
}
```

**After:**
```rust
fn main() -> Result<()> {
    let config = parse_args()?;

    let output_path = config.output_file.clone()
        .unwrap_or_else(|| {
            if config.use_brotli {
                "trace.jets.br".to_string()
            } else {
                "trace.jets".to_string()
            }
        });

    let mut writer = TraceWriter::new(&output_path)?;
    // ...
}
```

**Integration Points:**
- Default output filename changes to `.jets.br` when `-brotli` is specified
- `-out` flag overrides this behavior (user can specify any filename)
- `TraceWriter::new()` automatically detects compression based on extension

---

#### **File:** `jets/rjets/tests/integration_test.rs`

**Purpose:** Add integration test for Brotli compression round-trip.

**Changes:**

**Add new test function (after line 343):**

```rust
#[test]
fn test_brotli_write_and_read() -> Result<()> {
    let compressed_file = "/tmp/test_brotli_trace.jets.br";
    let uncompressed_file = "/tmp/test_brotli_trace_uncompressed.jets";

    // Clean up any existing files
    let _ = fs::remove_file(compressed_file);
    let _ = fs::remove_file(uncompressed_file);

    // Write compressed trace
    {
        let mut writer = TraceWriter::new(compressed_file)?;

        // Write header
        writer.write_header(
            "2.0",
            serde_json::json!({
                "test": "brotli_compression",
                "expected": "transparent_decompression"
            })
        )?;

        // Write root record
        writer.write_record(
            1,
            None,
            "TestRoot",
            1000,
            "root_record",
            "Root record for Brotli test",
            Some(serde_json::json!({"test_field": "test_value"}))
        )?;

        // Write child record
        writer.write_record(
            2,
            Some(1),
            "TestChild",
            1100,
            "child_record",
            "Child record for Brotli test",
            None
        )?;

        // Write annotation
        writer.write_annotation(
            2,
            "test_annotation",
            "Test annotation for Brotli",
            serde_json::json!({"annotation_key": "annotation_value"})
        )?;

        // Write event
        writer.write_event(
            2,
            "TestEvent",
            "Test event for Brotli",
            1150,
            Some(serde_json::json!({"event_key": "event_value"}))
        )?;

        // End records
        writer.write_record_end(2, 1200)?;
        writer.write_record_end(1, 1300)?;

        // Write footer
        writer.write_footer(Some(1300))?;
    }

    // Also write uncompressed version for size comparison
    {
        let mut writer = TraceWriter::new(uncompressed_file)?;
        writer.write_header(
            "2.0",
            serde_json::json!({"test": "brotli_compression"})
        )?;
        writer.write_record(1, None, "TestRoot", 1000, "root_record", "Root record for Brotli test", Some(serde_json::json!({"test_field": "test_value"})))?;
        writer.write_record(2, Some(1), "TestChild", 1100, "child_record", "Child record for Brotli test", None)?;
        writer.write_annotation(2, "test_annotation", "Test annotation for Brotli", serde_json::json!({"annotation_key": "annotation_value"}))?;
        writer.write_event(2, "TestEvent", "Test event for Brotli", 1150, Some(serde_json::json!({"event_key": "event_value"})))?;
        writer.write_record_end(2, 1200)?;
        writer.write_record_end(1, 1300)?;
        writer.write_footer(Some(1300))?;
    }

    // Read compressed trace back using parse_trace (automatic decompression)
    let trace = parse_trace(compressed_file)?;

    // Verify metadata
    assert_eq!(trace.metadata().version(), "2.0");
    assert_eq!(trace.metadata().header_data()["test"], "brotli_compression");

    // Verify root record
    let root_ids = trace.root_ids();
    assert_eq!(root_ids.len(), 1);

    let root = trace.get_record(root_ids[0]).unwrap();
    assert_eq!(root.id(), 1);
    assert_eq!(root.name(), "root_record");
    assert_eq!(root.description(), "Root record for Brotli test");
    assert_eq!(root.clk(), 1000);
    assert_eq!(root.end_clk(), Some(1300));

    // Verify child record
    let children = root.children();
    assert_eq!(children.len(), 1);
    let child = children[0];
    assert_eq!(child.id(), 2);
    assert_eq!(child.name(), "child_record");
    assert_eq!(child.parent_id(), Some(1));
    assert_eq!(child.clk(), 1100);
    assert_eq!(child.end_clk(), Some(1200));

    // Verify annotation (merged into data)
    let child_data = child.data();
    assert!(child_data.contains_key("test_annotation"));
    assert_eq!(child_data["test_annotation"]["annotation_key"], "annotation_value");

    // Verify event
    let events = child.events();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].name(), "TestEvent");
    assert_eq!(events[0].description(), "Test event for Brotli");
    assert_eq!(events[0].clk(), 1150);

    // Verify footer
    assert_eq!(trace.metadata().capture_end_clk(), Some(1300));
    assert_eq!(trace.metadata().total_records(), Some(2));
    assert_eq!(trace.metadata().total_annotations(), Some(1));
    assert_eq!(trace.metadata().total_events(), Some(1));

    // Compare file sizes (compressed should be smaller)
    let compressed_size = fs::metadata(compressed_file)?.len();
    let uncompressed_size = fs::metadata(uncompressed_file)?.len();

    println!("Uncompressed size: {} bytes", uncompressed_size);
    println!("Compressed size: {} bytes", compressed_size);
    println!("Compression ratio: {:.1}%", 100.0 * (compressed_size as f64) / (uncompressed_size as f64));

    // For this small trace, compressed might actually be larger due to overhead
    // But verify that compression doesn't break functionality
    assert!(compressed_size > 0, "Compressed file should not be empty");

    // Clean up
    fs::remove_file(compressed_file)?;
    fs::remove_file(uncompressed_file)?;

    Ok(())
}
```

**Integration Points:**
- Uses same test pattern as existing tests
- Verifies all JETS features (header, records, events, annotations, footer)
- Compares file sizes (informational, not a strict assertion for small traces)
- Cleans up test files

**Additional Test (Bonus):**

```rust
#[test]
fn test_brotli_detection_by_extension() -> Result<()> {
    // Test that .jets.br triggers compression
    let br_file = "/tmp/test.jets.br";
    let _ = fs::remove_file(br_file);

    {
        let mut writer = TraceWriter::new(br_file)?;
        writer.write_header("2.0", serde_json::json!({}))?;
        writer.write_footer(None)?;
    }

    // Verify file is actually compressed (not just renamed)
    let content = fs::read(br_file)?;
    // Brotli magic bytes are not standardized, but we can check it's not JSON
    assert!(!content.starts_with(b"{\"type\":\"header\""));

    // Verify we can read it back
    let trace = parse_trace(br_file)?;
    assert_eq!(trace.metadata().version(), "2.0");

    fs::remove_file(br_file)?;
    Ok(())
}
```

---

### 3.2 Algorithm: Compression Detection and Application

**Purpose:** Transparent compression/decompression based on file extension.

**Writer Side (Compression):**

1. **Entry Point:** `TraceWriter::new(file_path: &str)`
2. **Check Extension:** `file_path.ends_with(".br")`
3. **If .br detected:**
   - Create `File` → wrap in `BufWriter` → wrap in `CompressorWriter` → box as `Box<dyn Write>`
4. **If .br not detected:**
   - Create `File` → wrap in `BufWriter` → box as `Box<dyn Write>`
5. **Store:** Box in `writer` field
6. **Usage:** All write methods use trait object transparently

**Parser Side (Decompression):**

1. **Entry Point:** `parse_trace(file_path: &str)`
2. **Check Extension:** `file_path.ends_with(".br")`
3. **If .br detected:**
   - Open `File` → wrap in `Decompressor` → wrap in `BufReader` → box as `Box<dyn BufRead>`
4. **If .br not detected:**
   - Open `File` → wrap in `BufReader` → box as `Box<dyn BufRead>`
5. **Store:** Box in local variable
6. **Usage:** `.lines()` iterator works identically on both

**Performance Characteristics:**
- Extension check: O(1) string suffix comparison
- Compression initialization: One-time cost at writer creation
- Per-line compression: Buffered, amortized cost
- Decompression initialization: One-time cost at parse start
- Per-line decompression: Streaming, no memory overhead

---

### 3.3 Compression Quality Trade-offs

**Brotli Quality Levels:**

| Quality | Encoding Speed | Compression Ratio | Use Case |
|---------|---------------|-------------------|----------|
| 0-3     | Very Fast     | Moderate (70-80%) | Real-time streaming |
| 4-6     | Fast          | Good (60-70%)     | **Recommended for JETS** |
| 7-9     | Moderate      | Better (50-60%)   | Archival, offline processing |
| 10-11   | Slow          | Best (40-50%)     | Maximum compression, rarely used |

**Recommendation for JETS:** Quality **6**
- Provides 60-70% size reduction for typical JSON data
- Encoding speed is acceptable for trace generation (~2-3x slower than uncompressed)
- Decoding speed is excellent (often faster than disk I/O)

**Alternative:** Make quality level configurable via environment variable `JETS_BROTLI_QUALITY` (future enhancement).

---

### 3.4 Error Handling Strategy

**Compression Errors (Writer Side):**
- `File::create()` failure → propagate with context
- `CompressorWriter` initialization → should not fail (no validation at construction)
- Write operations → propagate I/O errors with context
- Flush on drop → ignore errors (already logged)

**Decompression Errors (Parser Side):**
- `File::open()` failure → propagate with context
- `Decompressor` initialization → should not fail
- Reading lines → propagate I/O errors with context
- Corrupt Brotli stream → I/O error from decompressor, add context

**Example Error Message:**
```
Error: Failed to parse JETS trace
Caused by:
    0: Failed to read line 42
    1: I/O error during decompression
    2: Invalid Brotli stream
    3: File: trace.jets.br
```

**Implementation:** Use `anyhow::Context` to add contextual information at each layer.

---

## 4. Testing Strategy

### 4.1 Unit Testing

**Test Cases:**

**1. Extension Detection:**
```rust
#[test]
fn test_extension_detection() {
    assert!(is_brotli_file("trace.jets.br"));
    assert!(is_brotli_file("trace.jsonl.br"));
    assert!(!is_brotli_file("trace.jets"));
    assert!(!is_brotli_file("trace.jsonl"));
}
```

**2. Writer Mode Selection:**
- Create `TraceWriter` with `.jets.br` path → verify compression enabled
- Create `TraceWriter` with `.jets` path → verify compression disabled

**3. Parser Mode Selection:**
- Create reader with `.jets.br` path → verify decompression enabled
- Create reader with `.jets` path → verify decompression disabled

---

### 4.2 Integration Testing

**Test Cases (in `integration_test.rs`):**

**1. Brotli Round-Trip (FR-4):**
- Write compressed trace with full JETS data
- Read back and verify all data matches
- Verify file size comparison (informational)

**2. Mixed File Types:**
- Write both compressed and uncompressed traces
- Read both using same `parse_trace()` function
- Verify contents are identical

**3. Large Trace Compression:**
- Generate large trace (10,000+ records) with compression
- Verify decompression succeeds
- Measure compression ratio (should be >50% reduction)

**4. Error Handling:**
- Attempt to read truncated `.jets.br` file → verify error message
- Attempt to read non-Brotli file with `.br` extension → verify error message

---

### 4.3 Performance Benchmarking

**Benchmarks to Add (Future Enhancement):**

**1. Writer Benchmark:**
```rust
#[bench]
fn bench_write_uncompressed(b: &mut Bencher) {
    // Write 1000-record trace without compression
}

#[bench]
fn bench_write_brotli(b: &mut Bencher) {
    // Write 1000-record trace with Brotli compression
}
```

**Expected Results:**
- Brotli compression: ~2-3x slower than uncompressed
- Acceptable for trace generation use case

**2. Parser Benchmark:**
```rust
#[bench]
fn bench_parse_uncompressed(b: &mut Bencher) {
    // Parse 1000-record trace without decompression
}

#[bench]
fn bench_parse_brotli(b: &mut Bencher) {
    // Parse 1000-record trace with Brotli decompression
}
```

**Expected Results:**
- Brotli decompression: ~1.2-1.5x slower than uncompressed
- Often hidden by disk I/O latency

---

### 4.4 Real-World Testing

**Test Scenarios:**

**1. Small Trace (100 records):**
- Generate with `-brotli` flag
- Verify file size (may not see compression benefit due to overhead)
- Verify functionality

**2. Medium Trace (10,000 records):**
- Generate with `-brotli` flag
- Verify file size (expect 60-70% size reduction)
- Verify reading in jets-gui

**3. Large Trace (1,000,000 records):**
- Generate with `-brotli` flag
- Verify file size (expect 60-70% size reduction, ~100s of MB → ~30-40MB)
- Verify parsing performance is acceptable
- Verify jets-gui can load and display

**4. Tracegen Integration:**
```bash
# Generate compressed trace
./jets-tracegen -num_clt 4 -num_core 8 -num_threads 2 -num_instr 1000 -brotli

# Verify output file
ls -lh trace.jets.br

# Load in GUI
./jets-gui trace.jets.br
```

---

## 5. Documentation Updates

### 5.1 Code Documentation

**Add to `writer.rs`:**
```rust
/// Creates a new TraceWriter for the specified file path.
///
/// Automatically enables Brotli compression if the file path ends with `.br`
/// (e.g., `trace.jets.br` or `trace.jsonl.br`).
///
/// # Compression
///
/// Brotli compression uses quality level 6 (balanced speed/ratio).
/// Typical compression ratios: 60-70% size reduction for JSON traces.
///
/// # Examples
///
/// ```
/// // Uncompressed trace
/// let mut writer = TraceWriter::new("trace.jets")?;
///
/// // Compressed trace
/// let mut writer = TraceWriter::new("trace.jets.br")?;
/// ```
pub fn new(file_path: &str) -> Result<Self> { ... }
```

**Add to `parser.rs`:**
```rust
/// Parses a JETS trace file from disk.
///
/// Automatically detects and decompresses Brotli-compressed traces
/// based on file extension (`.br`).
///
/// # Supported Formats
///
/// - `.jets` — Uncompressed JSON Lines
/// - `.jsonl` — Uncompressed JSON Lines
/// - `.jets.br` — Brotli-compressed JETS
/// - `.jsonl.br` — Brotli-compressed JSON Lines
///
/// # Examples
///
/// ```
/// // Parse uncompressed trace
/// let trace = parse_trace("trace.jets")?;
///
/// // Parse compressed trace (automatic decompression)
/// let trace = parse_trace("trace.jets.br")?;
/// ```
pub fn parse_trace(file_path: &str) -> Result<JetsTraceData> { ... }
```

---

### 5.2 User Documentation

**Update JETS.md (Format Specification):**

Add new section:

```markdown
## File Compression

JETS traces can be compressed using Brotli compression for storage efficiency.

### Compression Support

**File Extensions:**
- `.jets` — Uncompressed JETS trace
- `.jsonl` — Uncompressed JSON Lines
- `.jets.br` — Brotli-compressed JETS trace
- `.jsonl.br` — Brotli-compressed JSON Lines

**Compression Detection:**
The JETS toolchain automatically detects compression based on file extension.
No special flags or configuration needed when reading compressed traces.

**Compression Ratios:**
Typical Brotli compression ratios for JETS traces: 60-70% size reduction.
Example: 100MB uncompressed → 30-40MB compressed.

### Generating Compressed Traces

Use `jets-tracegen` with the `-brotli` flag:

```bash
# Generate compressed trace
./jets-tracegen -num_clt 2 -num_core 4 -brotli

# Output: trace.jets.br (compressed)
```

### Reading Compressed Traces

All JETS tools automatically decompress `.br` files:

```bash
# Load compressed trace in GUI
./jets-gui trace.jets.br

# Parse compressed trace programmatically
let trace = parse_trace("trace.jets.br")?;
```

### Performance Considerations

- **Compression:** ~2-3x slower than uncompressed writing
- **Decompression:** ~1.2-1.5x slower than uncompressed reading
- **Recommendation:** Use compression for archival, large traces, or storage-constrained environments
```

---

### 5.3 GENERATOR.md Updates

**Add to GENERATOR.md:**

```markdown
## Brotli Compression

The `jets-tracegen` utility supports Brotli compression via the `-brotli` flag.

### Usage

```bash
# Generate compressed trace with default name (trace.jets.br)
./jets-tracegen -brotli

# Generate compressed trace with custom name
./jets-tracegen -brotli -out my_trace.jets.br

# Generate uncompressed trace (default behavior)
./jets-tracegen -out trace.jets
```

### Compression Benefits

- **Storage:** 60-70% size reduction for typical traces
- **Transfer:** Faster upload/download of large traces
- **Archival:** Efficient long-term storage

### Compression Settings

- **Algorithm:** Brotli (quality level 6)
- **Speed:** ~2-3x slower than uncompressed generation
- **Compatibility:** All JETS tools automatically decompress `.br` files
```

---

## 6. Future Enhancements (Out of Scope)

### 6.1 Configurable Compression Quality

**Description:** Allow users to specify Brotli quality level.

**Implementation:**
- Add `JETS_BROTLI_QUALITY` environment variable (0-11)
- Add `-brotli-quality <N>` flag to tracegen
- Update `TraceWriter::new()` to read configuration

**Use Cases:**
- Real-time streaming: Use quality 3 (faster)
- Archival: Use quality 9 (better compression)

---

### 6.2 Alternative Compression Formats

**Description:** Support additional compression formats (gzip, zstd).

**Implementation:**
- Add `flate2` crate for gzip
- Add `zstd` crate for zstd
- Detect format by extension: `.jets.gz`, `.jets.zst`
- Update `TraceWriter` and `parse_trace()` to support multiple formats

**Use Cases:**
- Compatibility with existing gzip-compressed traces
- Zstd for maximum compression speed

---

### 6.3 Compression Statistics

**Description:** Report compression statistics after writing.

**Implementation:**
- Track uncompressed bytes written
- Track compressed bytes written
- Report ratio in `TraceWriter::drop()` or explicit method

**Output Example:**
```
Trace written to: trace.jets.br
Uncompressed size: 125.6 MB
Compressed size: 38.2 MB
Compression ratio: 69.6%
```

## 10. Dependencies

**New Dependency:**
- **`brotli`** version **8.0.2**
  - Purpose: Brotli compression/decompression
  - License: MIT/Apache-2.0
  - Maturity: Stable, widely used
  - Maintenance: Actively maintained by Dropbox

**No other dependencies required.**

---

**End of Plan**
