#!/usr/bin/env python3
"""GPU Simulator - Flash Attention Kernel Trace Generator

Generates realistic JETS format traces simulating Flash Attention kernel execution
on NVIDIA Hopper H100 GPU architecture.

This is a fake simulator for prototyping trace analysis tools - it generates
realistic hierarchical traces with proper GPU pipeline stages, memory hierarchy,
and instruction-level parallelism.

Usage:
    python gpu_sim_trace.py [options]

Options:
    -o, --output FILE       Output filename (default: gpu_sim.jets)
    -b, --blocks N          Number of thread blocks to simulate (default: 8)
    -s, --seed N            Random seed for reproducibility (default: 42)
    -v, --verbose           Verbose output
    --validate              Validate trace after generation
    --help                  Show this help message
"""

import argparse
import random
import sys
from dataclasses import dataclass
from typing import List, Tuple
from pyjets import TraceWriter, validate_trace


@dataclass
class SimConfig:
    """Simulation configuration parameters."""
    # GPU Architecture
    gpu_model: str = "NVIDIA H100"
    architecture: str = "Hopper"
    clock_freq_mhz: int = 1830
    num_sms: int = 132

    # Flash Attention Kernel Parameters
    batch_size: int = 4
    num_heads: int = 8
    seq_len: int = 1024
    head_dim: int = 64
    tile_size: int = 128  # Tile size for tiling algorithm

    # Simulation Parameters
    num_thread_blocks: int = 8  # Simulate subset of thread blocks
    threads_per_block: int = 256
    warps_per_block: int = 8  # 256 / 32
    instructions_per_warp: int = 500  # Target instruction count

    # Timing (in GPU cycles)
    base_clk: int = 1000

    # Output options
    output_file: str = 'gpu_sim.jets'
    verbose: bool = False
    validate: bool = False


class InstructionGenerator:
    """Generates realistic Flash Attention instruction sequences."""

    def __init__(self, config: SimConfig):
        self.config = config
        self.pc = 0

    def next_pc(self, increment: int = 0x10) -> str:
        """Get next program counter."""
        pc_str = f"0x{self.pc:04x}"
        self.pc += increment
        return pc_str

    def reset_pc(self):
        """Reset program counter for new warp."""
        self.pc = 0

    def generate_instruction_sequence(self) -> List[Tuple[str, str, str]]:
        """Generate Flash Attention instruction sequence.

        Returns: List of (pc, opcode, disassembly) tuples
        """
        instructions = []

        # Prologue: Initialize registers
        pc = self.next_pc()
        instructions.append((pc, "MOV", "MOV R0, c[0x0][0x20]"))
        pc = self.next_pc()
        instructions.append((pc, "IMAD", "IMAD R1, R0, c[0x0][0x24], RZ"))

        # Phase 1: Load tile of Q from global memory to shared memory
        for i in range(4):
            pc = self.next_pc()
            instructions.append((pc, "LDGSTS", f"LDGSTS.E.128 [shm_q+{i*128}], [gmem_q+{i*128}]"))

        # Async barrier - wait for Q loads
        pc = self.next_pc()
        instructions.append((pc, "CP.ASYNC.WAIT_GROUP", "CP.ASYNC.WAIT_GROUP 0"))

        # Phase 2: Load tile of K from global memory to shared memory
        for i in range(4):
            pc = self.next_pc()
            instructions.append((pc, "LDGSTS", f"LDGSTS.E.128 [shm_k+{i*128}], [gmem_k+{i*128}]"))

        # Barrier synchronization
        pc = self.next_pc()
        instructions.append((pc, "BAR.SYNC", "BAR.SYNC 0"))

        # Phase 3: Compute Q @ K^T using Tensor Cores (multiple iterations)
        for i in range(8):
            # Load Q tile from shared to registers
            pc = self.next_pc()
            instructions.append((pc, "LDS", f"LDS.128 R{i*4}, [shm_q+{i*16}]"))

            # Load K tile from shared to registers
            pc = self.next_pc()
            instructions.append((pc, "LDS", f"LDS.128 R{32+i*4}, [shm_k+{i*16}]"))

            # Tensor Core matrix multiply (WGMMA on Hopper)
            pc = self.next_pc()
            instructions.append((pc, "HMMA.16816", f"HMMA.16816.F16.F16 R{64+i*8}, R{i*4}, R{32+i*4}, R{64+i*8}"))

        # Phase 4: Compute max for numerical stability (softmax)
        pc = self.next_pc()
        instructions.append((pc, "FMAX", "FMAX.F32 R100, R64, R65"))
        for i in range(6):
            pc = self.next_pc()
            instructions.append((pc, "FMAX", f"FMAX.F32 R100, R100, R{66+i}"))

        # Broadcast max across warp
        pc = self.next_pc()
        instructions.append((pc, "SHFL.BFLY", "SHFL.BFLY.F32 R100, R100, 0x10, 0x1f"))

        # Phase 5: Compute exp(x - max)
        for i in range(8):
            # Subtract max
            pc = self.next_pc()
            instructions.append((pc, "FADD", f"FADD.F32 R{64+i}, R{64+i}, -R100"))

            # Compute exp using EX2 approximation
            pc = self.next_pc()
            instructions.append((pc, "FMUL", f"FMUL.F32 R{64+i}, R{64+i}, 1.44269504"))  # log2(e)
            pc = self.next_pc()
            instructions.append((pc, "EX2", f"EX2.F32.APPROX R{64+i}, R{64+i}"))

        # Phase 6: Compute sum for normalization
        pc = self.next_pc()
        instructions.append((pc, "FADD", "FADD.F32 R101, R64, R65"))
        for i in range(6):
            pc = self.next_pc()
            instructions.append((pc, "FADD", f"FADD.F32 R101, R101, R{66+i}"))

        # Reduce sum across warp
        pc = self.next_pc()
        instructions.append((pc, "SHFL.BFLY", "SHFL.BFLY.F32 R101, R101, 0x10, 0x1f"))

        # Phase 7: Divide by sum (softmax normalization)
        for i in range(8):
            pc = self.next_pc()
            instructions.append((pc, "FMUL", f"FMUL.F32 R{64+i}, R{64+i}, RCP(R101)"))

        # Store softmax scores to shared memory
        for i in range(4):
            pc = self.next_pc()
            instructions.append((pc, "STS", f"STS.128 [shm_scores+{i*16}], R{64+i*4}"))

        # Barrier before next phase
        pc = self.next_pc()
        instructions.append((pc, "BAR.SYNC", "BAR.SYNC 0"))

        # Phase 8: Load V tile from global memory
        for i in range(4):
            pc = self.next_pc()
            instructions.append((pc, "LDGSTS", f"LDGSTS.E.128 [shm_v+{i*128}], [gmem_v+{i*128}]"))

        # Wait for async loads
        pc = self.next_pc()
        instructions.append((pc, "CP.ASYNC.WAIT_GROUP", "CP.ASYNC.WAIT_GROUP 0"))

        # Phase 9: Compute scores @ V using Tensor Cores
        for i in range(8):
            # Load scores from shared memory
            pc = self.next_pc()
            instructions.append((pc, "LDS", f"LDS.128 R{i*4}, [shm_scores+{i*16}]"))

            # Load V from shared memory
            pc = self.next_pc()
            instructions.append((pc, "LDS", f"LDS.128 R{32+i*4}, [shm_v+{i*16}]"))

            # Tensor Core matrix multiply
            pc = self.next_pc()
            instructions.append((pc, "HMMA.16816", f"HMMA.16816.F16.F16 R{128+i*8}, R{i*4}, R{32+i*4}, R{128+i*8}"))

        # Phase 10: Accumulate partial results
        for i in range(16):
            pc = self.next_pc()
            instructions.append((pc, "FFMA", f"FFMA.F32 R{200+i}, R{128+i}, c[0x0][{i*4}], R{200+i}"))

        # Phase 11: Store output to global memory
        for i in range(4):
            pc = self.next_pc()
            instructions.append((pc, "STG", f"STG.E.128 [gmem_out+{i*128}], R{200+i*4}"))

        # Conditional branch for tile loop
        pc = self.next_pc()
        instructions.append((pc, "ISETP", "ISETP.GT.AND P0, PT, R250, RZ, PT"))
        pc = self.next_pc()
        instructions.append((pc, "BRA", "BRA P0, loop_tiles"))

        # Exit instruction
        pc = self.next_pc()
        instructions.append((pc, "EXIT", "EXIT"))

        return instructions


class GPUSimulator:
    """Main GPU simulator class."""

    def __init__(self, config: SimConfig):
        self.config = config
        self.writer = TraceWriter(config.output_file)
        self.clk = config.base_clk
        self.record_ids = []

    def log(self, message: str):
        """Print log message if verbose mode enabled."""
        if self.config.verbose:
            print(message)

    def advance_clk(self, cycles: int = 1) -> int:
        """Advance clock and return current time."""
        self.clk += cycles
        return self.clk

    def get_mem_latency(self, cache_level: str) -> int:
        """Get realistic memory latency."""
        latencies = {
            'L1_hit': 28,
            'L1_miss': 80,
            'L2_hit': 80,
            'L2_miss': 380,
            'shared_mem': 20,
            'dram': 380
        }
        return latencies.get(cache_level, 1)

    def simulate_instruction(self, warp_id: str, pc: str, opcode: str,
                            disasm: str, is_first_in_warp: bool = False):
        """Simulate a single instruction with full pipeline."""
        inst_id = f"inst_{warp_id}_{pc}"

        # Record instruction
        inst_start = self.clk
        self.writer.write_record(
            inst_id, warp_id, 'SASS_Instruction',
            clk=inst_start,
            name=f"{opcode} {pc}",
            data={
                'pc': pc,
                'opcode': opcode,
                'disassembly': disasm
            }
        )

        # Pipeline Stage 1: Decode
        decode_clk = self.advance_clk(1)
        self.writer.write_event(inst_id, 'DecodeStage', decode_clk)

        # Pipeline Stage 2: Scoreboard check
        scoreboard_clk = self.advance_clk(1)
        # Add realistic stalls occasionally
        if random.random() < 0.1 and not is_first_in_warp:
            self.writer.write_event(inst_id, 'Stall_RAW', scoreboard_clk,
                                  data={'reason': 'Register dependency'})
            self.advance_clk(random.randint(2, 8))
            scoreboard_clk = self.clk

        self.writer.write_event(inst_id, 'ScoreboardCheck', scoreboard_clk,
                              data={'status': 'ready'})

        # Pipeline Stage 3: Operand collect
        operand_clk = self.advance_clk(1)
        self.writer.write_event(inst_id, 'OperandCollect', operand_clk)

        # Pipeline Stage 4: Execute (depends on opcode)
        exec_unit, exec_latency = self.get_exec_unit_and_latency(opcode)

        if opcode == "LDGSTS":
            # Async copy - issue and continue
            exec_clk = self.advance_clk(1)
            self.writer.write_event(inst_id, 'TMA_Issue', exec_clk,
                                  data={'unit': 'Tensor Memory Accelerator'})
            # Async operation - record async completion later
            async_complete_clk = exec_clk + 100
            self.writer.write_event(inst_id, 'TMA_Complete', async_complete_clk)

        elif opcode in ["LDS", "STS"]:
            # Shared memory access
            exec_clk = self.advance_clk(1)
            addr_calc_clk = self.clk
            self.writer.write_event(inst_id, 'SharedMem_AddressCalc', addr_calc_clk)

            # Bank conflict check
            has_conflict = random.random() < 0.05
            if has_conflict:
                self.advance_clk(4)
                self.writer.write_event(inst_id, 'SharedMem_BankConflict', self.clk)

            mem_clk = self.advance_clk(self.get_mem_latency('shared_mem'))
            self.writer.write_event(inst_id,
                                  'SharedMem_Read' if opcode == 'LDS' else 'SharedMem_Write',
                                  mem_clk)

        elif opcode == "HMMA.16816":
            # Tensor Core operation
            exec_clk = self.advance_clk(1)
            self.writer.write_event(inst_id, 'TensorCore_WGMMA_Issue', exec_clk,
                                  data={'matrix_shape': '16x8x16'})

            # Tensor core latency
            tc_latency = 8
            self.advance_clk(tc_latency)
            self.writer.write_event(inst_id, 'TensorCore_WGMMA_Complete', self.clk)

        elif opcode in ["LDGDEPBAR", "LDG", "STG"]:
            # Global memory access
            exec_clk = self.advance_clk(1)
            self.writer.write_event(inst_id, 'LD_Unit_AddressCalc', exec_clk)

            coalesce_clk = self.advance_clk(2)
            self.writer.write_event(inst_id, 'LD_Unit_Coalescing', coalesce_clk)

            # L1 cache lookup
            l1_clk = self.advance_clk(3)
            self.writer.write_event(inst_id, 'L1_Cache_Lookup', l1_clk)

            # L1 miss occasionally
            if random.random() < 0.3:
                self.writer.write_event(inst_id, 'L1_Cache_Miss', self.clk,
                                      data={'tag': f'0x{random.randint(0x1000, 0xFFFF):08x}'})

                # L2 lookup
                l2_clk = self.advance_clk(20)
                self.writer.write_event(inst_id, 'L2_Lookup', l2_clk)

                # L2 miss occasionally
                if random.random() < 0.2:
                    self.writer.write_event(inst_id, 'L2_Miss', self.clk)

                    # DRAM access
                    dram_clk = self.advance_clk(200)
                    self.writer.write_event(inst_id, 'DRAM_Activate', dram_clk,
                                          data={'bank': random.randint(0, 15)})
                    self.advance_clk(10)
                    self.writer.write_event(inst_id,
                                          'DRAM_Read' if 'LD' in opcode else 'DRAM_Write',
                                          self.clk)
                else:
                    self.writer.write_event(inst_id, 'L2_Hit', self.clk)
                    self.advance_clk(self.get_mem_latency('L2_hit'))
            else:
                self.writer.write_event(inst_id, 'L1_Cache_Hit', self.clk)
                self.advance_clk(self.get_mem_latency('L1_hit'))

        elif opcode in ["BAR.SYNC"]:
            # Barrier synchronization
            exec_clk = self.advance_clk(1)
            self.writer.write_event(inst_id, 'Barrier_Arrive', exec_clk,
                                  data={'barrier_id': 0})
            # Wait for all warps
            self.advance_clk(random.randint(10, 50))
            self.writer.write_event(inst_id, 'Barrier_Release', self.clk)

        elif opcode == "CP.ASYNC.WAIT_GROUP":
            # Wait for async copies
            exec_clk = self.advance_clk(1)
            self.writer.write_event(inst_id, 'AsyncCopy_Wait', exec_clk)
            self.advance_clk(random.randint(5, 30))
            self.writer.write_event(inst_id, 'AsyncCopy_Complete', self.clk)

        else:
            # Generic execution unit
            exec_clk = self.advance_clk(1)
            self.writer.write_event(inst_id, f'Execute_{exec_unit}', exec_clk)
            self.advance_clk(exec_latency - 1)

        # Pipeline Stage 5: Writeback
        if opcode not in ["STG", "STS", "BAR.SYNC", "BRA", "EXIT"]:
            wb_clk = self.advance_clk(1)
            self.writer.write_event(inst_id, 'Writeback', wb_clk)

        # End instruction
        inst_end = self.clk
        self.writer.write_record_end(inst_id, inst_end)

        # Small gap before next instruction (ILP simulation)
        self.advance_clk(random.randint(0, 2))

    def get_exec_unit_and_latency(self, opcode: str) -> Tuple[str, int]:
        """Get execution unit and latency for opcode."""
        if opcode.startswith('HMMA'):
            return 'TensorCore', 8
        elif opcode in ['FFMA', 'FADD', 'FMUL', 'FMAX']:
            return 'FP32_Unit', 4
        elif opcode in ['IMAD', 'IADD', 'ISETP']:
            return 'INT32_Unit', 4
        elif opcode in ['EX2', 'RCP', 'RSQRT']:
            return 'SFU', 8
        elif opcode in ['LDS', 'STS']:
            return 'LD_ST_Unit', 1
        elif opcode in ['LDG', 'STG', 'LDGSTS']:
            return 'LD_ST_Unit', 1
        elif opcode == 'SHFL.BFLY':
            return 'Warp_Shuffle', 1
        elif opcode == 'MOV':
            return 'ALU', 1
        else:
            return 'CUDA_Core', 4

    def simulate_warp(self, warp_id: str, thread_block_id: str,
                     warp_idx: int, sm_id: int):
        """Simulate a single warp execution."""
        warp_start = self.clk

        self.log(f"    Warp {warp_idx}: threads {warp_idx*32}-{(warp_idx+1)*32-1}")

        self.writer.write_record(
            warp_id, thread_block_id, 'Warp',
            clk=warp_start,
            name=f"Warp_{warp_idx}",
            data={
                'warp_id': warp_idx,
                'thread_range': [warp_idx * 32, (warp_idx + 1) * 32 - 1],
                'sm_id': sm_id
            }
        )

        # Add warp metadata
        self.writer.write_annotation(
            warp_id, 'WarpScheduler',
            {'scheduler_id': warp_idx % 4, 'slot': warp_idx}
        )
        self.writer.write_annotation(
            warp_id, 'RegisterAllocation',
            {'registers': 'R0-R255', 'per_thread': 255}
        )

        # Generate instruction sequence
        inst_gen = InstructionGenerator(self.config)
        instructions = inst_gen.generate_instruction_sequence()

        self.log(f"      Executing {len(instructions)} instructions...")

        # Simulate instructions
        for i, (pc, opcode, disasm) in enumerate(instructions):
            self.simulate_instruction(warp_id, pc, opcode, disasm, i == 0)

        # End warp
        warp_end = self.clk
        duration = warp_end - warp_start
        self.writer.write_record_end(warp_id, warp_end)
        self.log(f"      Warp {warp_idx} complete: {duration} cycles")

    def simulate_thread_block(self, block_id: str, dispatch_id: str,
                             block_idx: Tuple[int, int, int], sm_id: int):
        """Simulate a thread block (CTA)."""
        block_start = self.clk

        self.log(f"  ThreadBlock[{block_idx[0]},{block_idx[1]},{block_idx[2]}] on SM_{sm_id}")

        self.writer.write_record(
            block_id, dispatch_id, 'ThreadBlock',
            clk=block_start,
            name=f"TB[{block_idx[0]},{block_idx[1]},{block_idx[2]}]",
            data={
                'block_idx': list(block_idx),
                'sm_id': sm_id,
                'gpc_id': sm_id // 16  # Assume 16 SMs per GPC
            }
        )

        # Thread block metadata
        self.writer.write_annotation(
            block_id, 'ThreadCount',
            {'total': self.config.threads_per_block}
        )
        self.writer.write_annotation(
            block_id, 'SharedMemAlloc',
            {'size_bytes': 48 * 1024, 'range': '0x0000-0xBFFF'}
        )

        # Dispatch event
        self.writer.write_event(block_id, 'ThreadBlock_Dispatch', block_start,
                              data={'scheduler': f'SM_{sm_id}_Scheduler'})

        # Simulate warps (with some parallelism)
        warp_start_clks = []
        for w in range(self.config.warps_per_block):
            warp_id = f"warp_{block_id}_{w}"
            # Warps start with small offsets (parallel execution)
            warp_offset = random.randint(0, 20)
            warp_start_clks.append((self.clk + warp_offset, warp_id, w))

        # Sort by start time and simulate
        for warp_clk, warp_id, w_idx in sorted(warp_start_clks):
            self.clk = warp_clk
            self.simulate_warp(warp_id, block_id, w_idx, sm_id)

        # End thread block
        block_end = self.clk
        duration = block_end - block_start
        self.writer.write_event(block_id, 'ThreadBlock_Complete', block_end)
        self.writer.write_record_end(block_id, block_end)
        self.log(f"  ThreadBlock complete: {duration} cycles")

    def run(self):
        """Run the complete simulation."""
        print("Starting Flash Attention GPU simulation...")

        # Write header
        self.writer.write_header({
            'gpu_model': self.config.gpu_model,
            'architecture': self.config.architecture,
            'clock_frequency_mhz': self.config.clock_freq_mhz,
            'num_sms': self.config.num_sms,
            'tool': 'gpu_sim_trace.py',
            'kernel': 'FlashAttention-2',
            'kernel_params': {
                'batch_size': self.config.batch_size,
                'num_heads': self.config.num_heads,
                'seq_len': self.config.seq_len,
                'head_dim': self.config.head_dim,
                'tile_size': self.config.tile_size
            }
        })

        # Host program
        host_id = "host_prog"
        self.writer.write_record(host_id, None, 'HostProgram',
                                clk=self.clk, name='flash_attention_fwd')
        self.advance_clk(10)

        # GPU context submission
        ctx_id = "gpu_ctx"
        self.writer.write_record(ctx_id, host_id, 'GpuContextSubmission',
                                clk=self.clk, name='GPU_Context_0')
        self.advance_clk(10)

        # Dispatch compute
        dispatch_id = "dispatch"
        grid_dim = [
            (self.config.seq_len + self.config.tile_size - 1) // self.config.tile_size,
            self.config.batch_size * self.config.num_heads,
            1
        ]
        block_dim = [256, 1, 1]

        self.writer.write_record(
            dispatch_id, ctx_id, 'DispatchCompute',
            clk=self.clk,
            name='FlashAttention_Dispatch',
            data={'grid_dim': grid_dim, 'block_dim': block_dim}
        )
        self.advance_clk(10)

        # GigaThread Engine
        gte_id = "gte"
        self.writer.write_record(gte_id, dispatch_id, 'GigaThreadEngine',
                                clk=self.clk, name='GTE_Engine')
        self.advance_clk(10)

        # GTE annotations
        self.writer.write_annotation(gte_id, 'GridDimensions',
                                    {'x': grid_dim[0], 'y': grid_dim[1], 'z': grid_dim[2]})
        self.writer.write_annotation(gte_id, 'BlockDimensions',
                                    {'x': block_dim[0], 'y': block_dim[1], 'z': block_dim[2]})
        self.writer.write_annotation(gte_id, 'TotalThreadBlocks',
                                    {'count': grid_dim[0] * grid_dim[1] * grid_dim[2]})

        # Simulate subset of thread blocks across different SMs
        print(f"Simulating {self.config.num_thread_blocks} thread blocks across SMs...")

        for i in range(self.config.num_thread_blocks):
            block_id = f"tb_{i:03d}"
            sm_id = i % 8  # Distribute across 8 SMs
            block_idx = (i % grid_dim[0], i // grid_dim[0], 0)

            # Thread blocks can start in parallel on different SMs
            if i < 4:
                tb_offset = random.randint(0, 100)
            else:
                # Later blocks wait for SM availability
                tb_offset = random.randint(1000, 2000)

            tb_clk = self.config.base_clk + 1100 + tb_offset
            self.clk = tb_clk

            print(f"  Thread Block {i}: SM_{sm_id}, Block[{block_idx[0]},{block_idx[1]},{block_idx[2]}]")
            self.simulate_thread_block(block_id, gte_id, block_idx, sm_id)

        # End GTE
        gte_end = self.clk + 100
        self.writer.write_record_end(gte_id, gte_end)

        # End dispatch
        dispatch_end = gte_end + 10
        self.writer.write_record_end(dispatch_id, dispatch_end)

        # End context
        ctx_end = dispatch_end + 10
        self.writer.write_record_end(ctx_id, ctx_end)

        # End host
        host_end = ctx_end + 10
        self.writer.write_record_end(host_id, host_end)

        # Write footer
        self.writer.write_footer(capture_end_clk=host_end)
        self.writer.close()

        print(f"\nSimulation complete!")
        print(f"Trace written to: {self.config.output_file}")
        print(f"Final clock: {host_end} cycles ({host_end / self.config.clock_freq_mhz:.2f} us)")

        # Validate trace if requested
        if self.config.validate:
            print(f"\nValidating trace...")
            try:
                validate_trace(self.config.output_file)
                print(f"✓ Trace validation passed")
            except Exception as e:
                print(f"✗ Trace validation failed: {e}")
                return False

        return True


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description='GPU Simulator - Flash Attention Kernel Trace Generator',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Generate trace with default settings
  python gpu_sim_trace.py

  # Generate trace with custom output file
  python gpu_sim_trace.py -o my_trace.jets

  # Generate and validate trace with more thread blocks
  python gpu_sim_trace.py -b 16 --validate

  # Verbose mode with reproducible seed
  python gpu_sim_trace.py -v -s 12345
        '''
    )

    parser.add_argument('-o', '--output', dest='output_file', default='gpu_sim.jets',
                       help='Output filename (default: gpu_sim.jets)')
    parser.add_argument('-b', '--blocks', dest='num_thread_blocks', type=int, default=8,
                       help='Number of thread blocks to simulate (default: 8)')
    parser.add_argument('-s', '--seed', type=int, default=42,
                       help='Random seed for reproducibility (default: 42)')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Verbose output')
    parser.add_argument('--validate', action='store_true',
                       help='Validate trace after generation')

    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()

    # Set random seed for reproducibility
    random.seed(args.seed)

    # Create config from arguments
    config = SimConfig(
        output_file=args.output_file,
        num_thread_blocks=args.num_thread_blocks,
        verbose=args.verbose,
        validate=args.validate
    )

    # Run simulation
    simulator = GPUSimulator(config)
    success = simulator.run()

    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
