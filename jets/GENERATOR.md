# RISC-V SoC Trace Generator

## Overview

The RISC-V SoC Trace Generator (`jets-tracegen`) is a synthetic trace generation tool that produces realistic hardware execution traces in JETS (JSON Event Trace Streaming) format. 
It simulates a pipelined RISC-V processor architecture with configurable hierarchy (clusters, cores, threads) and generates instruction-level execution traces with pipeline stage events.

## Purpose

The generator serves multiple purposes:

1. **Testing and Development**: Validate JETS parsers, viewers, and analysis tools with realistic trace data
2. **Benchmarking**: Generate traces of varying sizes and complexity for performance testing
3. **Demonstration**: Provide example traces that showcase JETS format capabilities
4. **Reference Implementation**: Serve as a canonical example of JETS 2.0 compliant trace generation

## Requirements

### Functional Requirements

#### FR1: Hierarchical SoC Structure
- **FR1.1**: Generate multi-cluster SoC topologies
- **FR1.2**: Generate multi-core configurations per cluster
- **FR1.3**: Generate multi-thread execution per core
- **FR1.4**: Support arbitrary hierarchy depth (Cluster → Core → Thread → Instruction)

#### FR2: RISC-V Instruction Set
- **FR2.1**: Generate instructions from RISC-V base integer instruction set
- **FR2.2**: Support computational instructions (ADD, SUB, ADDI, AND, OR, XOR, SLL, SRL)
- **FR2.3**: Support memory instructions (LW, SW) with distinct memory pipeline stage
- **FR2.4**: Support control flow instructions (BEQ, JAL, JALR)
- **FR2.5**: Support pseudo-instructions (MV, LI)
- **FR2.6**: Generate valid RISC-V assembly syntax with register names and immediates

#### FR3: Pipeline Simulation
- **FR3.1**: Model realistic 11-stage pipeline:
  - F1: Fetch 1 (Instruction fetch request, PC generation)
  - F2: Fetch 2 (Instruction cache access and retrieval)
  - D: Decode (Instruction decode and branch prediction)
  - RN: Rename (Register renaming)
  - DS: Dispatch (Dispatch to reservation stations)
  - IS: Issue (Issue to execution units)
  - RR: Register Read (Read physical registers)
  - EX: Execute (ALU/FPU execution)
  - M: Memory (Memory access for load/store only)
  - WB: Writeback (Write results to register file)
  - C: Commit/Retire (Commit in program order)
- **FR3.2**: Generate overlapping instruction execution (pipelined)
- **FR3.3**: Model variable execution latencies (execute: 1-2 cycles, memory: 2-6 cycles)
- **FR3.4**: Model random pipeline stalls (20% probability at Issue stage, 1-3 cycle stall)

#### FR4: JETS Format Compliance
- **FR4.1**: Generate JETS 2.0 compliant output
- **FR4.2**: Emit header with metadata (version, hardware model, tool info)
- **FR4.3**: Emit records with start times (type: "record")
- **FR4.4**: Emit record_end markers with completion times
- **FR4.5**: Emit events with precise clock timestamps
- **FR4.6**: Emit footer with summary statistics
- **FR4.7**: Use JSON Lines format (one JSON object per line)

#### FR5: Clock Monotonicity
- **FR5.1**: Ensure clock values never decrease in output file
- **FR5.2**: Buffer and sort trace items by clock time before emission
- **FR5.3**: Maintain pipelined execution while preserving monotonicity

#### FR6: Configurability
- **FR6.1**: Configurable number of clusters (default: 1)
- **FR6.2**: Configurable cores per cluster (default: 1)
- **FR6.3**: Configurable threads per core (default: 1)
- **FR6.4**: Configurable instruction count per thread (default: 100)
- **FR6.5**: Support instruction count ranges for randomization
- **FR6.6**: Configurable output file path (default: trace.jets)

### Non-Functional Requirements

#### NFR1: Performance
- **NFR1.1**: Generate 1000 instructions in < 100ms
- **NFR1.2**: Memory efficient buffering (buffer per-thread, not entire trace)
- **NFR1.3**: Streaming output (flush after each thread)

#### NFR2: Correctness
- **NFR2.1**: 100% JETS format compliance (validated against spec)
- **NFR2.2**: Valid parent-child relationships (no orphaned records)
- **NFR2.3**: Valid clock timestamps (events within record duration)
- **NFR2.4**: Proper record_end for all records with duration

#### NFR3: Determinism
- **NFR3.1**: Deterministic PRNG seeded by configuration
- **NFR3.2**: Reproducible traces given same configuration
- **NFR3.3**: Seed based on: num_clusters × 1000 + num_cores × 100 + num_threads × 10 + num_instr

#### NFR4: Usability
- **NFR4.1**: Command-line interface with clear options
- **NFR4.2**: Help message documenting all options
- **NFR4.3**: Reasonable defaults for quick testing
- **NFR4.4**: Clear error messages for invalid inputs

## Architecture

### High-Level Design

```
┌─────────────────────────────────────────────────────────────────┐
│                    jets-tracegen Binary                         │
│                                                                 │
│  ┌──────────────┐      ┌──────────────┐      ┌──────────────┐   │
│  │   CLI Args   │─────▶│  Generator   │─────▶│ TraceWriter  │   │
│  │   Parser     │      │   Engine     │      │   (JETS)     │   │
│  └──────────────┘      └──────────────┘      └──────────────┘   │
│                               │                      │          │
│                               ▼                      ▼          │
│                        ┌──────────────┐      ┌──────────────┐   │
│                        │ Trace Buffer │      │  Output File │   │
│                        │  (per thread)│      │  (JSON Lines)│   │
│                        └──────────────┘      └──────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### Component Architecture

#### 1. CLI Argument Parser (`parse_args`)

**Responsibility**: Parse and validate command-line arguments

**Input**: Command-line arguments (argv)

**Output**: `Config` struct with validated parameters

**Implementation**:
```rust
struct Config {
    num_clusters: usize,      // Number of clusters
    num_cores: usize,         // Cores per cluster
    num_threads: usize,       // Threads per core
    num_instr_min: usize,     // Min instructions per thread
    num_instr_max: usize,     // Max instructions per thread
    output_file: Option<String>, // Output path
}
```

**Supported Arguments**:
- `-num_clt <N>`: Number of clusters
- `-num_core <N>`: Number of cores per cluster
- `-num_threads <N>`: Number of threads per core
- `-num_instr <N> [M]`: Instruction count (or range)
- `-out <FILE>`: Output file path
- `-h, -help, --help`: Show help message


#### 2. Generation Engine (`generate_trace`)

**Responsibility**: Orchestrate trace generation

**Algorithm**:

```
1. Initialize RNG with deterministic seed
2. Write header with metadata
3. For each cluster:
   3.1. Write cluster record
   3.2. For each core:
      3.2.1. Write core record
      3.2.2. For each thread:
         3.2.2.1. Buffer thread record
         3.2.2.2. For each instruction:
            3.2.2.2.1. Generate random instruction
            3.2.2.2.2. Buffer instruction record
            3.2.2.2.3. Generate pipeline events (F1, F2, D, RN, DS, IS, RR, EX, [M], WB, C)
            3.2.2.2.4. Buffer all events
            3.2.2.2.5. Buffer record_end
            3.2.2.2.6. Advance instruction start time (pipeline overlap)
         3.2.2.3. Buffer thread record_end
         3.2.2.4. Sort all buffered items by clock
         3.2.2.5. Emit all items in chronological order
      3.2.3. Write core record_end
   3.3. Write cluster record_end
4. Write footer with statistics
```

### Monotonicity Preservation

**Problem**: Pipelined execution causes instruction N+1 to start before instruction N completes, creating backward clock jumps when written sequentially.

**Solution**: Buffer-and-sort approach

```
Generation Phase (unbuffered):
  Instr 1: start=1000, end=1009
  Instr 2: start=1002, end=1011  ← starts during Instr 1
  Instr 3: start=1004, end=1013  ← starts during Instr 1, 2

Buffering Phase:
  items = [
    Record(instr1, clk=1000),
    Event(instr1_F1, clk=1000),
    Event(instr1_F2, clk=1001),
    ...
    RecordEnd(instr1, clk=1009),
    Record(instr2, clk=1002),    ← out of order!
    Event(instr2_F1, clk=1002),
    ...
  ]

Sorting Phase:
  items.sort_by_key(|item| item.clk())

Emission Phase (monotonic):
  clk=1000: Record(instr1)
  clk=1000: Event(instr1_F1)
  clk=1001: Event(instr1_F2)
  clk=1002: Record(instr2)       ← now in order!
  clk=1002: Event(instr2_F1)
  ...
```

### Pipeline Stage Timing Model

```
Instruction Lifecycle:
Clock  Stage  Description
─────────────────────────────────────────────────────────────
T+0    F1     Fetch 1 (PC gen, I-cache request)
T+1    F2     Fetch 2 (I-cache access)
T+2    D      Decode (instruction decode, branch prediction)
T+3    RN     Rename (register renaming, RAW dependency resolution)
T+4    DS     Dispatch (dispatch to reservation stations)
T+5    IS     Issue (issue to execution unit when ready)
              ↓ [possible stall: 20% prob, 1-3 cycles]
T+6    RR     Register Read (read operands from PRF)
T+7    EX     Execute (ALU/FPU operation)
              ↓ [variable latency: 1-2 cycles]
T+8-9  M      Memory (only for LW/SW: 2-6 cycles)
T+10   WB     Writeback (write result to PRF)
T+11   C      Commit (retire in-order, update arch state)
```

**Latency Characteristics**:
- Fixed stages: 1 cycle each (F1, F2, D, RN, DS, RR, WB, C)
- Variable stages:
  - EX: 1-2 cycles (random)
  - M: 2-6 cycles (memory ops only, random)
  - IS: +0-3 cycles stall (20% probability)

**Pipeline Overlap**:
- New instruction starts every 1-2 cycles (random)
- Achieves ~100% pipeline utilization
- Multiple instructions in flight simultaneously

### Data Model

#### Record Hierarchy

```
Cluster (id=1, parent=null)
  ├─ Core (id=2, parent=1)
  │   ├─ Thread (id=3, parent=2)
  │   │   ├─ Instruction (id=4, parent=3)
  │   │   │   ├─ Event: F1 (clk=1000)
  │   │   │   ├─ Event: F2 (clk=1001)
  │   │   │   ├─ Event: D  (clk=1002)
  │   │   │   ├─ Event: RN (clk=1003)
  │   │   │   ├─ Event: DS (clk=1004)
  │   │   │   ├─ Event: IS (clk=1005)
  │   │   │   ├─ Event: RR (clk=1006)
  │   │   │   ├─ Event: EX (clk=1007)
  │   │   │   ├─ Event: M  (clk=1009) [if memory op]
  │   │   │   ├─ Event: WB (clk=1010)
  │   │   │   └─ Event: C  (clk=1011)
  │   │   └─ Instruction (id=5, parent=3)
  │   └─ Thread (id=6, parent=2)
  └─ Core (id=7, parent=1)
```

#### Instruction Format

**Name**: `0x<PC>-<MNEMONIC>`
- Example: `0xFFFFFFFF00000000-ADDI`

**Description**: Full assembly instruction
- Example: `addi  s1, a1, -1`

**Data Field** (JSON):
```json
{
  "pc": "0xFFFFFFFF00000000",
  "opcode": "ADDI",
  "disassembly": "addi  s1, a1, -1"
}
```

**PC Address Scheme**:
```
Base: 0xFFFFFFFF00000000
Offset: cluster_idx * 0x100000 + core_idx * 0x10000 + thread_idx * 0x1000
PC increments by 4 per instruction
```

### Instruction Generation

#### Instruction Set Coverage

| Category | Instructions |
|----------|--------------|
| Arithmetic | ADD, SUB, ADDI |
| Logical | AND, OR, XOR |
| Shift | SLL, SRL |
| Memory | LW (load word), SW (store word) |
| Branch | BEQ (branch equal) |
| Jump | JAL (jump and link), JALR (jump and link register) |
| Pseudo | MV (move), LI (load immediate) |

#### Assembly Syntax Generation

**Register Operands**:
- 32 RISC-V registers: zero, ra, sp, gp, tp, t0-t6, s0-s11, a0-a7
- Randomly selected from register pool

**Immediate Operands**:
- Small immediates: -100 to 100 (typical)
- Large immediates: -2048 to 2048 (for LI)
- Branch offsets: -50 to 50 × 4 (word-aligned)
- Jump offsets: -100 to 100 × 4 (word-aligned)

**Memory Operands**:
- Format: `offset(base_reg)`
- Offset: -100 to 100
- Example: `lw s1, 15(tp)`

#### Instruction Templates

```rust
ADDI:  "addi  rd, rs1, imm"        → "addi  s1, a1, -1"
ADD:   "add   rd, rs1, rs2"        → "add   t0, t1, t2"
LW:    "lw    rd, offset(rs1)"     → "lw    s1, 15(tp)"
SW:    "sw    rs2, offset(rs1)"    → "sw    a0, -8(sp)"
BEQ:   "beq   rs1, rs2, offset"    → "beq   t0, t1, 16"
JAL:   "jal   rd, offset"          → "jal   ra, 100"
MV:    "mv    rd, rs1"             → "mv    a0, s0"
LI:    "li    rd, imm"             → "li    t0, 1024"
```

## Implementation Details

### File Structure

```
jets/rjets/src/tracegen.rs    (550 lines)
├─ Constants
│  ├─ INSTRUCTIONS: &[(&str, &str, bool)]
│  └─ REGISTERS: &[&str]
├─ Data Structures
│  ├─ struct SimpleRng
│  ├─ struct Config
│  └─ enum TraceItem
├─ Functions
│  ├─ fn parse_args() -> Result<Config>
│  ├─ fn print_help()
│  ├─ fn main() -> Result<()>
│  └─ fn generate_trace(writer, config) -> Result<()>
└─ Implementation Details
   ├─ SimpleRng impl (PRNG)
   ├─ TraceItem impl (clock extraction)
   └─ Config impl (defaults)
```

### Build and Run

```bash
# Development build
cargo build --bin jets-tracegen

# Release build (optimized)
cargo build --release --bin jets-tracegen

# Run
cargo run --bin jets-tracegen -- [OPTIONS]

# Or directly
./target/release/jets-tracegen [OPTIONS]
```
