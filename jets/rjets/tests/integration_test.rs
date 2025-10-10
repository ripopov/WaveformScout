use rjets::{TraceWriter, TraceReader, JetsTraceReader, VirtualTraceReader};
use anyhow::Result;
use std::fs;

#[test]
fn test_write_and_read_basic_trace() -> Result<()> {
    let test_file = "/tmp/test_trace.jets";

    // Clean up any existing file
    let _ = fs::remove_file(test_file);

    // Write a trace
    {
        let mut writer = TraceWriter::new(test_file)?;

        // Write header
        writer.write_header(
            "2.0",
            serde_json::json!({
                "gpu_model": "Test GPU",
                "clock_frequency_hz": 1_000_000_000
            })
        )?;

        // Write root record
        writer.write_record(
            1,
            None,
            "HostProgram",
            1000,
            "TestProgram",
            "Main test program entry point",
            Some(serde_json::json!({"language": "CUDA"}))
        )?;

        // Write annotation
        writer.write_annotation(
            1,
            "compiler",
            "Compiler information",
            serde_json::json!({"name": "nvcc", "version": "12.0"})
        )?;

        // Write event
        writer.write_event(
            1,
            "ProgramStart",
            "Program execution start",
            1001,
            None
        )?;

        // Write child record
        writer.write_record(
            2,
            Some(1),
            "Dispatch",
            1100,
            "kernel_launch",
            "Kernel dispatch to hardware",
            None
        )?;

        // Write event for child
        writer.write_event(
            2,
            "DispatchStart",
            "Dispatch execution start",
            1105,
            Some(serde_json::json!({"grid_size": [1, 1, 1]}))
        )?;

        // End child record
        writer.write_record_end(2, 1200)?;

        // End root record
        writer.write_record_end(1, 1500)?;

        // Write footer
        writer.write_footer(Some(1500))?;
    }

    // Read the trace back using trait API
    let reader: Box<dyn TraceReader> = Box::new(JetsTraceReader::new());
    let trace = reader.read(test_file)?;

    // Verify metadata
    assert_eq!(trace.metadata().version(), "2.0");
    assert_eq!(trace.metadata().header_data()["gpu_model"], "Test GPU");

    // Verify roots
    let root_ids = trace.root_ids();
    assert_eq!(root_ids.len(), 1);

    let root = trace.get_record(root_ids[0]).unwrap();
    assert_eq!(root.id(), 1);
    assert_eq!(root.name(), "TestProgram");
    assert_eq!(root.description(), "Main test program entry point");
    assert_eq!(root.clk(), 1000);
    assert_eq!(root.end_clk(), Some(1500));
    assert_eq!(root.duration(), Some(500));

    // Verify merged data (includes annotations)
    let data = root.data();
    assert!(data.contains_key("language"));
    assert!(data.contains_key("compiler"));  // Annotation merged into data
    assert_eq!(data["compiler"]["name"], "nvcc");

    // Verify events
    let events = root.events();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].name(), "ProgramStart");
    assert_eq!(events[0].description(), "Program execution start");
    assert_eq!(events[0].clk(), 1001);

    // Verify children
    let children = root.children();
    assert_eq!(children.len(), 1);
    let child = children[0];
    assert_eq!(child.id(), 2);
    assert_eq!(child.parent_id(), Some(1));
    assert_eq!(child.name(), "kernel_launch");
    assert_eq!(child.description(), "Kernel dispatch to hardware");
    assert_eq!(child.clk(), 1100);
    assert_eq!(child.end_clk(), Some(1200));
    assert_eq!(child.duration(), Some(100));

    // Verify child events
    let child_events = child.events();
    assert_eq!(child_events.len(), 1);
    assert_eq!(child_events[0].name(), "DispatchStart");
    assert_eq!(child_events[0].description(), "Dispatch execution start");

    // Verify footer metadata
    assert_eq!(trace.metadata().capture_end_clk(), Some(1500));
    assert_eq!(trace.metadata().total_records(), Some(2));
    assert_eq!(trace.metadata().total_annotations(), Some(1));
    assert_eq!(trace.metadata().total_events(), Some(2));

    // Clean up
    fs::remove_file(test_file)?;

    Ok(())
}

#[test]
fn test_write_and_read_hierarchical_trace() -> Result<()> {
    let test_file = "/tmp/test_hierarchical_trace.jets";

    // Clean up any existing file
    let _ = fs::remove_file(test_file);

    // Write a more complex hierarchical trace
    {
        let mut writer = TraceWriter::new(test_file)?;

        writer.write_header("2.0", serde_json::json!({"gpu": "H100"}))?;

        // Level 0: HostProgram
        writer.write_record(1, None, "HostProgram", 0, "main", "Main program", None)?;

        // Level 1: Dispatch
        writer.write_record(2, Some(1), "Dispatch", 100, "kernel", "Kernel dispatch", None)?;

        // Level 2: ThreadBlock
        writer.write_record(3, Some(2), "ThreadBlock", 200, "block_0", "Thread block 0", None)?;

        // Level 3: Warp
        writer.write_record(4, Some(3), "Warp", 300, "warp_0", "Warp 0 execution", None)?;

        // Level 4: Instruction
        writer.write_record(5, Some(4), "SASS_Instruction", 400, "HMMA", "HMMA instruction", None)?;
        writer.write_event(5, "Execute", "Instruction execution", 405, None)?;
        writer.write_record_end(5, 410)?;

        // End warp
        writer.write_record_end(4, 420)?;

        // End thread block
        writer.write_record_end(3, 500)?;

        // End dispatch
        writer.write_record_end(2, 600)?;

        // End program
        writer.write_record_end(1, 700)?;

        writer.write_footer(Some(700))?;
    }

    // Parse and verify using trait API
    let reader: Box<dyn TraceReader> = Box::new(JetsTraceReader::new());
    let trace = reader.read(test_file)?;

    let root_ids = trace.root_ids();
    assert_eq!(root_ids.len(), 1);

    let prog = trace.get_record(root_ids[0]).unwrap();
    assert_eq!(prog.id(), 1);
    assert_eq!(prog.name(), "main");
    assert_eq!(prog.description(), "Main program");
    let prog_children = prog.children();
    assert_eq!(prog_children.len(), 1);

    let disp = prog_children[0];
    assert_eq!(disp.id(), 2);
    assert_eq!(disp.name(), "kernel");
    assert_eq!(disp.description(), "Kernel dispatch");
    let disp_children = disp.children();
    assert_eq!(disp_children.len(), 1);

    let tb = disp_children[0];
    assert_eq!(tb.id(), 3);
    assert_eq!(tb.name(), "block_0");
    assert_eq!(tb.description(), "Thread block 0");
    let tb_children = tb.children();
    assert_eq!(tb_children.len(), 1);

    let warp = tb_children[0];
    assert_eq!(warp.id(), 4);
    assert_eq!(warp.name(), "warp_0");
    assert_eq!(warp.description(), "Warp 0 execution");
    let warp_children = warp.children();
    assert_eq!(warp_children.len(), 1);

    let inst = warp_children[0];
    assert_eq!(inst.id(), 5);
    assert_eq!(inst.name(), "HMMA");
    assert_eq!(inst.description(), "HMMA instruction");
    let inst_events = inst.events();
    assert_eq!(inst_events.len(), 1);
    assert_eq!(inst_events[0].description(), "Instruction execution");
    assert_eq!(inst.duration(), Some(10));

    // Clean up
    fs::remove_file(test_file)?;

    Ok(())
}

#[test]
fn test_virtual_reader() -> Result<()> {
    let reader: Box<dyn TraceReader> = Box::new(VirtualTraceReader::new());
    let trace = reader.read("")?; // Path is ignored for virtual reader

    // Verify metadata
    assert_eq!(trace.metadata().version(), "virtual-1.0");
    assert_eq!(trace.metadata().header_data()["generator"], "VirtualTraceReader");

    // Verify we have roots
    let root_ids = trace.root_ids();
    assert!(root_ids.len() > 0);

    // Verify records
    for root_id in root_ids {
        let record = trace.get_record(root_id).unwrap();
        assert_eq!(record.id(), root_id);
        assert!(record.name().starts_with("Record_"));
        assert!(record.clk() >= 0);

        // Verify children generation works
        let _children = record.children();
        // Children may or may not exist depending on depth and random generation

        // Verify data exists
        let data = record.data();
        assert!(data.len() >= 3); // Should have 3-7 fields

        // Verify events
        let events = record.events();
        assert!(events.len() <= 5); // Should have 0-5 events
    }

    Ok(())
}

#[test]
fn test_trait_polymorphism() -> Result<()> {
    // Create test file for JETS reader
    let test_file = "/tmp/test_polymorphism.jets";
    let _ = fs::remove_file(test_file);

    {
        let mut writer = TraceWriter::new(test_file)?;
        writer.write_header("2.0", serde_json::json!({"test": "polymorphism"}))?;
        writer.write_record(1, None, "Test", 0, "test", "test record", None)?;
        writer.write_record_end(1, 100)?;
        writer.write_footer(Some(100))?;
    }

    // Test polymorphism: both readers should work through the same interface
    let readers: Vec<Box<dyn TraceReader>> = vec![
        Box::new(JetsTraceReader::new()),
        Box::new(VirtualTraceReader::new()),
    ];

    for (i, reader) in readers.iter().enumerate() {
        let path = if i == 0 { test_file } else { "" }; // Virtual reader ignores path
        let trace = reader.read(path)?;

        // Both should provide valid traces through the same interface
        assert!(trace.metadata().version().len() > 0);
        assert!(trace.root_ids().len() > 0);

        // Test record access
        for root_id in trace.root_ids() {
            let record = trace.get_record(root_id).unwrap();
            assert!(record.id() > 0);
            assert!(record.name().len() > 0);
        }
    }

    // Clean up
    fs::remove_file(test_file)?;

    Ok(())
}

#[test]
fn test_read_real_trace_file() -> Result<()> {
    // Try to read the trace.jets file if it exists
    let trace_file = "../trace.jets";
    if !std::path::Path::new(trace_file).exists() {
        // Skip test if file doesn't exist
        return Ok(());
    }

    let reader: Box<dyn TraceReader> = Box::new(JetsTraceReader::new());
    let trace = reader.read(trace_file)?;
    
    // Just verify we can read it
    assert!(trace.metadata().version().len() > 0);
    assert!(trace.root_ids().len() > 0);
    
    for root_id in trace.root_ids() {
        if let Some(record) = trace.get_record(root_id) {
            assert!(record.id() > 0);
            assert!(record.name().len() > 0);
        }
    }
    
    Ok(())
}
