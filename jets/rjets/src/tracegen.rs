use rjets::TraceWriter;
use anyhow::Result;
use std::env;

// RISC-V instruction set (subset) - (mnemonic, assembly, is_memory_op)
const INSTRUCTIONS: &[(&str, &str, bool)] = &[
    ("ADDI", "addi", false),
    ("ADD", "add", false),
    ("SUB", "sub", false),
    ("MV", "mv", false),
    ("LI", "li", false),
    ("LW", "lw", true),   // load
    ("SW", "sw", true),   // store
    ("BEQ", "beq", false),
    ("JAL", "jal", false),
    ("JALR", "jalr", false),
    ("AND", "and", false),
    ("OR", "or", false),
    ("XOR", "xor", false),
    ("SLL", "sll", false),
    ("SRL", "srl", false),
];

// RISC-V registers
const REGISTERS: &[&str] = &[
    "zero", "ra", "sp", "gp", "tp", "t0", "t1", "t2",
    "s0", "s1", "a0", "a1", "a2", "a3", "a4", "a5",
    "a6", "a7", "s2", "s3", "s4", "s5", "s6", "s7",
    "s8", "s9", "s10", "s11", "t3", "t4", "t5", "t6",
];

// Simple PRNG (Linear Congruential Generator)
struct SimpleRng {
    state: u64,
}

impl SimpleRng {
    fn new(seed: u64) -> Self {
        SimpleRng { state: seed }
    }

    fn next_u64(&mut self) -> u64 {
        self.state = self.state.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
        self.state
    }

    fn gen_range(&mut self, min: usize, max: usize) -> usize {
        let range = max - min;
        (self.next_u64() % range as u64) as usize + min
    }

    fn gen_i32_range(&mut self, min: i32, max: i32) -> i32 {
        let range = (max - min) as u64;
        ((self.next_u64() % range) as i32) + min
    }

    fn gen_i64_range(&mut self, min: i64, max: i64) -> i64 {
        let range = (max - min) as u64;
        ((self.next_u64() % range) as i64) + min
    }
}

struct Config {
    num_clusters: usize,
    num_cores: usize,
    num_threads: usize,
    num_instr_min: usize,
    num_instr_max: usize,
    output_file: Option<String>,
    use_brotli: bool,
}

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

// Items to emit, sorted by clock
#[derive(Clone)]
enum TraceItem {
    Record {
        id: u64,
        parent_id: Option<u64>,
        record_type: String,
        clk: i64,
        name: String,
        description: String,
        data: Option<serde_json::Value>,
    },
    Event {
        record_id: u64,
        name: String,
        description: String,
        clk: i64,
    },
    RecordEnd {
        id: u64,
        clk: i64,
    },
}

impl TraceItem {
    fn clk(&self) -> i64 {
        match self {
            TraceItem::Record { clk, .. } => *clk,
            TraceItem::Event { clk, .. } => *clk,
            TraceItem::RecordEnd { clk, .. } => *clk,
        }
    }
}

fn parse_args() -> Result<Config> {
    let args: Vec<String> = env::args().collect();
    let mut config = Config::default();

    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "-num_clt" => {
                i += 1;
                if i >= args.len() {
                    anyhow::bail!("-num_clt requires an argument");
                }
                config.num_clusters = args[i].parse()?;
            }
            "-num_core" => {
                i += 1;
                if i >= args.len() {
                    anyhow::bail!("-num_core requires an argument");
                }
                config.num_cores = args[i].parse()?;
            }
            "-num_threads" => {
                i += 1;
                if i >= args.len() {
                    anyhow::bail!("-num_threads requires an argument");
                }
                config.num_threads = args[i].parse()?;
            }
            "-num_instr" => {
                i += 1;
                if i >= args.len() {
                    anyhow::bail!("-num_instr requires at least one argument");
                }
                config.num_instr_min = args[i].parse()?;
                // Check if there's a second number (range)
                if i + 1 < args.len() && !args[i + 1].starts_with('-') {
                    // Try to parse as number
                    if let Ok(max) = args[i + 1].parse::<usize>() {
                        i += 1;
                        config.num_instr_max = max;
                    } else {
                        config.num_instr_max = config.num_instr_min;
                    }
                } else {
                    config.num_instr_max = config.num_instr_min;
                }
            }
            "-out" => {
                i += 1;
                if i >= args.len() {
                    anyhow::bail!("-out requires a file path argument");
                }
                config.output_file = Some(args[i].clone());
            }
            "-brotli" => {
                config.use_brotli = true;
            }
            "-h" | "-help" | "--help" => {
                print_help();
                std::process::exit(0);
            }
            _ => {
                eprintln!("Warning: Unknown argument: {}", args[i]);
            }
        }
        i += 1;
    }

    Ok(config)
}

fn print_help() {
    println!("RISC-V SoC Trace Generator");
    println!("Usage: jets-tracegen [OPTIONS]");
    println!();
    println!("OPTIONS:");
    println!("  -num_clt <N>           Number of clusters (default: 1)");
    println!("  -num_core <N>          Number of cores per cluster (default: 1)");
    println!("  -num_threads <N>       Number of threads per core (default: 1)");
    println!("  -num_instr <N> [M]     Number of instructions (default: 100)");
    println!("                         If two numbers provided, generates random count in range [N, M]");
    println!("  -out <FILE>            Output file path (default: trace.jets)");
    println!("  -brotli                Write compressed trace using Brotli (output: *.jets.br)");
    println!("  -h, -help, --help      Show this help message");
}

fn main() -> Result<()> {
    let config = parse_args()?;

    // Create trace writer
    let output_path = config.output_file.clone()
        .unwrap_or_else(|| {
            if config.use_brotli {
                "trace.jets.br".to_string()
            } else {
                "trace.jets".to_string()
            }
        });
    let mut writer = TraceWriter::new(&output_path)?;

    generate_trace(&mut writer, &config)?;

    if output_path == "trace.jets" || output_path == "trace.jets.br" {
        println!("Trace written to: {}", output_path);
    }

    Ok(())
}

fn generate_trace(writer: &mut TraceWriter, config: &Config) -> Result<()> {
    // Use a deterministic seed based on config for reproducibility
    let seed = (config.num_clusters as u64) * 1000
              + (config.num_cores as u64) * 100
              + (config.num_threads as u64) * 10
              + (config.num_instr_min as u64);
    let mut rng = SimpleRng::new(seed);

    let mut next_id = 1u64;

    // Write header
    writer.write_header(
        "2.0",
        serde_json::json!({
            "hardware_model": "RISC-V SoC",
            "architecture": "RISC-V Pipeline",
            "clock_frequency_mhz": 1000,
            "tool": "jets-tracegen v0.1",
            "num_clusters": config.num_clusters,
            "num_cores": config.num_cores,
            "num_threads": config.num_threads,
        })
    )?;

    let mut clk = 1000i64;

    // Track all IDs for proper record_end writing
    let mut cluster_ids = Vec::new();
    let mut core_ids = Vec::new();

    for cluster_idx in 0..config.num_clusters {
        let cluster_id = next_id;
        next_id += 1;
        cluster_ids.push(cluster_id);

        writer.write_record(
            cluster_id,
            None,
            "Cluster",
            0,
            &format!("cluster_{}", cluster_idx),
            &format!("Cluster {}", cluster_idx),
            None,
        )?;

        for core_idx in 0..config.num_cores {
            let core_id = next_id;
            next_id += 1;
            core_ids.push((core_id, cluster_id));

            writer.write_record(
                core_id,
                Some(cluster_id),
                "Core",
                0,
                &format!("core_{}", core_idx),
                &format!("Core {}", core_idx),
                None,
            )?;

            for thread_idx in 0..config.num_threads {
                let thread_id = next_id;
                next_id += 1;

                let num_instructions = if config.num_instr_min == config.num_instr_max {
                    config.num_instr_min
                } else {
                    rng.gen_range(config.num_instr_min, config.num_instr_max + 1)
                };

                let thread_start_clk = 0;

                // Buffer all items for this thread to emit in sorted order
                let mut items = Vec::new();

                // Add thread record
                items.push(TraceItem::Record {
                    id: thread_id,
                    parent_id: Some(core_id),
                    record_type: "Thread".to_string(),
                    clk: thread_start_clk,
                    name: format!("thread_{}", thread_idx),
                    description: format!("Thread {}", thread_idx),
                    data: None,
                });

                let mut pc = 0xFFFFFFFF00000000u64 + (cluster_idx * 0x100000 + core_idx * 0x10000 + thread_idx * 0x1000) as u64;
                let mut instr_start_clk = clk;

                for _ in 0..num_instructions {
                    let instr_id = next_id;
                    next_id += 1;

                    // Select random instruction
                    let instr_info = INSTRUCTIONS[rng.gen_range(0, INSTRUCTIONS.len())];
                    let (mnemonic, asm, is_mem) = instr_info;

                    // Generate instruction operands
                    let rd = REGISTERS[rng.gen_range(0, REGISTERS.len())];
                    let rs1 = REGISTERS[rng.gen_range(0, REGISTERS.len())];

                    let disassembly = match mnemonic {
                        "MV" => {
                            format!("{}  {}, {}", asm, rd, rs1)
                        }
                        "LI" => {
                            let imm = rng.gen_i32_range(-2048, 2048);
                            format!("{}  {}, {}", asm, rd, imm)
                        }
                        "LW" | "SW" => {
                            let offset = rng.gen_i32_range(-100, 100);
                            format!("{}  {}, {}({})", asm, rd, offset, rs1)
                        }
                        "BEQ" => {
                            let rs2 = REGISTERS[rng.gen_range(0, REGISTERS.len())];
                            let offset = rng.gen_i32_range(-50, 50) * 4;
                            format!("{}  {}, {}, {}", asm, rd, rs2, offset)
                        }
                        "JAL" => {
                            let offset = rng.gen_i32_range(-100, 100) * 4;
                            format!("{}  {}, {}", asm, rd, offset)
                        }
                        "JALR" => {
                            let offset = rng.gen_i32_range(-100, 100);
                            format!("{}  {}, {}({})", asm, rd, offset, rs1)
                        }
                        "ADDI" => {
                            let imm = rng.gen_i32_range(-100, 100);
                            format!("{}  {}, {}, {}", asm, rd, rs1, imm)
                        }
                        _ => {
                            let rs2 = REGISTERS[rng.gen_range(0, REGISTERS.len())];
                            format!("{}  {}, {}, {}", asm, rd, rs1, rs2)
                        }
                    };

                    let instr_name = format!("0x{:016X}-{}", pc, mnemonic);

                    // Add instruction record
                    items.push(TraceItem::Record {
                        id: instr_id,
                        parent_id: Some(thread_id),
                        record_type: "Instruction".to_string(),
                        clk: instr_start_clk,
                        name: instr_name,
                        description: disassembly.clone(),
                        data: Some(serde_json::json!({
                            "pc": format!("0x{:016X}", pc),
                            "opcode": mnemonic,
                            "disassembly": disassembly
                        })),
                    });

                    // Generate pipeline events
                    let mut event_clk = instr_start_clk;

                    // F1 - Fetch 1
                    items.push(TraceItem::Event {
                        record_id: instr_id,
                        name: "F1".to_string(),
                        description: "Fetch 1. Instruction fetch request, PC generation".to_string(),
                        clk: event_clk,
                    });
                    event_clk += 1;

                    // F2 - Fetch 2
                    items.push(TraceItem::Event {
                        record_id: instr_id,
                        name: "F2".to_string(),
                        description: "Fetch 2. Instruction cache access and retrieval".to_string(),
                        clk: event_clk,
                    });
                    event_clk += 1;

                    // D - Decode
                    items.push(TraceItem::Event {
                        record_id: instr_id,
                        name: "D".to_string(),
                        description: "Decode. Instruction decode and branch prediction".to_string(),
                        clk: event_clk,
                    });
                    event_clk += 1;

                    // RN - Rename
                    items.push(TraceItem::Event {
                        record_id: instr_id,
                        name: "RN".to_string(),
                        description: "Rename. Register renaming to eliminate false dependencies".to_string(),
                        clk: event_clk,
                    });
                    event_clk += 1;

                    // DS - Dispatch
                    items.push(TraceItem::Event {
                        record_id: instr_id,
                        name: "DS".to_string(),
                        description: "Dispatch. Dispatch instructions to reservation stations/issue queues".to_string(),
                        clk: event_clk,
                    });
                    event_clk += 1;

                    // IS - Issue (might stall)
                    if rng.gen_range(0, 10) < 2 {
                        event_clk += rng.gen_i64_range(1, 4); // Random stall
                    }
                    items.push(TraceItem::Event {
                        record_id: instr_id,
                        name: "IS".to_string(),
                        description: "Issue. Issue instructions to execution units when operands are ready".to_string(),
                        clk: event_clk,
                    });
                    event_clk += 1;

                    // RR - Register Read
                    items.push(TraceItem::Event {
                        record_id: instr_id,
                        name: "RR".to_string(),
                        description: "Register Read. Read physical registers from register file".to_string(),
                        clk: event_clk,
                    });
                    event_clk += 1;

                    // EX - Execute
                    items.push(TraceItem::Event {
                        record_id: instr_id,
                        name: "EX".to_string(),
                        description: "Execute. Execute operation in ALU/FPU/other functional units".to_string(),
                        clk: event_clk,
                    });
                    event_clk += rng.gen_i64_range(1, 3); // Execution can take 1-2 cycles

                    // M - Memory (only for load/store)
                    if is_mem {
                        items.push(TraceItem::Event {
                            record_id: instr_id,
                            name: "M".to_string(),
                            description: "Memory. Memory access for load/store instructions".to_string(),
                            clk: event_clk,
                        });
                        event_clk += rng.gen_i64_range(2, 6); // Memory can take longer
                    }

                    // WB - Writeback
                    items.push(TraceItem::Event {
                        record_id: instr_id,
                        name: "WB".to_string(),
                        description: "Writeback. Write results back to physical register file".to_string(),
                        clk: event_clk,
                    });
                    event_clk += 1;

                    // C - Commit
                    items.push(TraceItem::Event {
                        record_id: instr_id,
                        name: "C".to_string(),
                        description: "Commit/Retire. Commit instructions in program order and update architectural state".to_string(),
                        clk: event_clk,
                    });

                    // Instruction ends
                    items.push(TraceItem::RecordEnd {
                        id: instr_id,
                        clk: event_clk,
                    });

                    // Update PC
                    pc += 4;

                    // Advance clock for next instruction (pipelined, so small increment)
                    // This creates overlapping instructions
                    instr_start_clk += rng.gen_i64_range(1, 3);
                }

                // Find max clock time for thread end
                let thread_end_clk = items.iter()
                    .map(|item| item.clk())
                    .max()
                    .unwrap_or(thread_start_clk) + 1;

                items.push(TraceItem::RecordEnd {
                    id: thread_id,
                    clk: thread_end_clk,
                });

                // Sort all items by clock time to ensure monotonicity
                items.sort_by_key(|item| item.clk());

                // Emit all items in sorted order
                for item in items {
                    match item {
                        TraceItem::Record { id, parent_id, record_type, clk, name, description, data } => {
                            writer.write_record(id, parent_id, &record_type, clk, &name, &description, data)?;
                        }
                        TraceItem::Event { record_id, name, description, clk } => {
                            writer.write_event(record_id, &name, &description, clk, None)?;
                        }
                        TraceItem::RecordEnd { id, clk } => {
                            writer.write_record_end(id, clk)?;
                        }
                    }
                }

                // Update global clock to be past this thread
                clk = thread_end_clk;
            }
        }
    }

    // End all cores and clusters at the end of the trace
    let trace_end_clk = clk;

    // End cores
    for (core_id, _) in core_ids.iter().rev() {
        writer.write_record_end(*core_id, trace_end_clk)?;
    }

    // End clusters
    for cluster_id in cluster_ids.iter().rev() {
        writer.write_record_end(*cluster_id, trace_end_clk)?;
    }

    // Write footer
    writer.write_footer(Some(trace_end_clk))?;

    Ok(())
}
