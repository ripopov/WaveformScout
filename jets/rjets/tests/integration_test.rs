use rjets::{TraceWriter, parse_trace};
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

    // Read the trace back
    let trace = parse_trace(test_file)?;

    // Verify header
    assert_eq!(trace.header.version, "2.0");
    assert_eq!(trace.header.metadata["gpu_model"], "Test GPU");

    // Verify roots
    assert_eq!(trace.roots.len(), 1);
    let root = &trace.roots[0];
    assert_eq!(root.id, 1);
    assert_eq!(root.record_type, "HostProgram");
    assert_eq!(root.name, "TestProgram");
    assert_eq!(root.description, "Main test program entry point");
    assert_eq!(root.clk, 1000);
    assert_eq!(root.end_clk, Some(1500));
    assert_eq!(root.duration, Some(500));

    // Verify annotations
    assert_eq!(root.annotations.len(), 1);
    assert_eq!(root.annotations[0].name, "compiler");
    assert_eq!(root.annotations[0].description, "Compiler information");

    // Verify events
    assert_eq!(root.events.len(), 1);
    assert_eq!(root.events[0].name, "ProgramStart");
    assert_eq!(root.events[0].description, "Program execution start");
    assert_eq!(root.events[0].clk, 1001);

    // Verify children
    assert_eq!(root.children.len(), 1);
    let child = &root.children[0];
    assert_eq!(child.id, 2);
    assert_eq!(child.parent_id, Some(1));
    assert_eq!(child.record_type, "Dispatch");
    assert_eq!(child.name, "kernel_launch");
    assert_eq!(child.description, "Kernel dispatch to hardware");
    assert_eq!(child.clk, 1100);
    assert_eq!(child.end_clk, Some(1200));
    assert_eq!(child.duration, Some(100));

    // Verify child events
    assert_eq!(child.events.len(), 1);
    assert_eq!(child.events[0].name, "DispatchStart");
    assert_eq!(child.events[0].description, "Dispatch execution start");

    // Verify footer
    assert!(trace.footer.is_some());
    let footer = trace.footer.unwrap();
    assert_eq!(footer.capture_end_clk, Some(1500));
    assert_eq!(footer.total_records, Some(2));
    assert_eq!(footer.total_annotations, Some(1));
    assert_eq!(footer.total_events, Some(2));

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

    // Parse and verify
    let trace = parse_trace(test_file)?;

    assert_eq!(trace.roots.len(), 1);

    let prog = &trace.roots[0];
    assert_eq!(prog.id, 1);
    assert_eq!(prog.name, "main");
    assert_eq!(prog.description, "Main program");
    assert_eq!(prog.children.len(), 1);

    let disp = &prog.children[0];
    assert_eq!(disp.id, 2);
    assert_eq!(disp.name, "kernel");
    assert_eq!(disp.description, "Kernel dispatch");
    assert_eq!(disp.children.len(), 1);

    let tb = &disp.children[0];
    assert_eq!(tb.id, 3);
    assert_eq!(tb.name, "block_0");
    assert_eq!(tb.description, "Thread block 0");
    assert_eq!(tb.children.len(), 1);

    let warp = &tb.children[0];
    assert_eq!(warp.id, 4);
    assert_eq!(warp.name, "warp_0");
    assert_eq!(warp.description, "Warp 0 execution");
    assert_eq!(warp.children.len(), 1);

    let inst = &warp.children[0];
    assert_eq!(inst.id, 5);
    assert_eq!(inst.name, "HMMA");
    assert_eq!(inst.description, "HMMA instruction");
    assert_eq!(inst.record_type, "SASS_Instruction");
    assert_eq!(inst.events.len(), 1);
    assert_eq!(inst.events[0].description, "Instruction execution");
    assert_eq!(inst.duration, Some(10));

    // Clean up
    fs::remove_file(test_file)?;

    Ok(())
}
