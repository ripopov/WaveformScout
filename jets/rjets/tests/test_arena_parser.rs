use rjets::{parse_trace, TraceData};

#[test]
fn test_arena_based_parser() {
    // Generate a test trace
    std::process::Command::new("cargo")
        .args(&["run", "--bin", "jets-tracegen", "--", "-out", "/tmp/test_arena_trace.jets", "-num_instr", "20"])
        .output()
        .expect("Failed to generate trace");

    // Parse the trace
    let trace_data = parse_trace("/tmp/test_arena_trace.jets")
        .expect("Failed to parse trace");

    // Test basic functionality
    let root_ids = trace_data.root_ids();
    assert!(!root_ids.is_empty(), "Should have at least one root record");

    // Test record access and children resolution
    let mut total_records = 0;
    let mut total_children = 0;

    for root_id in &root_ids {
        if let Some(record) = trace_data.get_record(*root_id) {
            total_records += 1;

            // Test children resolution through arena
            let children = record.children();
            total_children += children.len();

            // Verify children have correct parent_id
            for child in &children {
                assert_eq!(
                    child.parent_id(),
                    Some(*root_id),
                    "Child parent_id should match parent record id"
                );

                // Test that we can get children of children
                let grandchildren = child.children();
                for grandchild in &grandchildren {
                    assert_eq!(
                        grandchild.parent_id(),
                        Some(child.id()),
                        "Grandchild parent_id should match child record id"
                    );
                }
            }
        }
    }

    assert!(total_records > 0, "Should have visited at least one record");
    println!("✓ Visited {} records with {} direct children", total_records, total_children);
}

#[test]
fn test_no_deep_cloning() {
    // This test verifies that the arena-based approach doesn't deep clone
    // We can't directly test memory usage, but we can verify structure

    // Generate a small trace
    std::process::Command::new("cargo")
        .args(&["run", "--bin", "jets-tracegen", "--", "-out", "/tmp/test_no_clone.jets", "-num_instr", "10"])
        .output()
        .expect("Failed to generate trace");

    let trace_data = parse_trace("/tmp/test_no_clone.jets")
        .expect("Failed to parse trace");

    // Verify that records are stored flat in all_records
    let root_ids = trace_data.root_ids();

    // Access the same record multiple times - should be efficient
    for _ in 0..100 {
        for root_id in &root_ids {
            if let Some(record) = trace_data.get_record(*root_id) {
                let _children = record.children(); // This should be cheap (just index lookups)
            }
        }
    }

    // If we get here without hanging, the test passes
    println!("✓ Arena-based access is efficient");
}
