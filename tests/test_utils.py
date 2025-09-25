"""Common test utilities and fixtures for WaveScout tests."""

from pathlib import Path
from typing import Optional


class MockVar:
    """Mock Var object for tests that don't have a real waveform_db."""

    def __init__(self, name: str = "test_signal", bitwidth: int = 1, var_type: str = "Wire"):
        self._name = name
        self._bitwidth = bitwidth
        self._var_type = var_type

    def name(self, hier=None) -> str:
        return self._name

    def full_name(self, hier=None) -> str:
        return self._name

    def bitwidth(self) -> int:
        return self._bitwidth

    def var_type(self) -> str:
        return self._var_type

    def is_1bit(self) -> bool:
        return self._bitwidth == 1

    def signal_handle(self) -> int:
        return -1  # Invalid handle for test purposes


def get_repo_root() -> Path:
    """Get the repository root directory.
    
    Returns the absolute path to the WaveScout repository root.
    """
    # This file is in tests/, so parent is the repo root
    return Path(__file__).parent.parent.resolve()


def get_test_input_path(filename: str) -> Path:
    """Get the absolute path to a test input file.
    
    Args:
        filename: Name of the file in test_inputs directory
        
    Returns:
        Absolute path to the test input file
        
    Raises:
        FileNotFoundError: If the file doesn't exist
    """
    repo_root = get_repo_root()
    file_path = repo_root / "test_inputs" / filename
    
    if not file_path.exists():
        raise FileNotFoundError(f"Test input file not found: {file_path}")
    
    return file_path


def get_test_inputs_dir() -> Path:
    """Get the absolute path to the test_inputs directory.
    
    Returns:
        Absolute path to test_inputs directory
    """
    repo_root = get_repo_root()
    return repo_root / "test_inputs"


# Common test file constants
class TestFiles:
    """Constants for commonly used test files."""
    
    # VCD files
    APB_SIM_VCD = "apb_sim.vcd"
    SWERV1_VCD = "swerv1.vcd"
    VCD_EXTENSIONS = "vcd_extensions.vcd"
    PULSE_TEST_VCD = "pulse_test.vcd"
    STAIRCASE_VCD = "staircase.vcd"
    EVENT_TEST_VCD = "event_test.vcd"
    ANALOG_SIGNALS_VCD = "analog_signals.vcd"
    ANALOG_SIGNALS_SHORT_VCD = "analog_signals_short.vcd"
    DESIGN_GPT5_VCD = "design-gpt5.vcd"
    DESIGN_CLAUDE_VCD = "design_claude.vcd"
    BENCHMARK_DESIGN_VCD = "benchmark_design.vcd"
    
    # FST files
    DES_FST = "des.fst"
    VCD_EXTENSIONS_FST = "vcd_extensions.fst"
    ANALOG_SIGNALS_FST = "analog_signals.fst"
    ANALOG_SIGNALS_SHORT_FST = "analog_signals_short.fst"
    BENCHMARK_SIGNALS_FST = "benchmark_signals.fst"
    DESIGN_CLAUDE_FST = "design_claude.fst"
    
    @classmethod
    def get_path(cls, filename: str) -> Path:
        """Get the absolute path for a test file constant.
        
        Args:
            filename: One of the file constants from this class
            
        Returns:
            Absolute path to the test file
        """
        return get_test_input_path(filename)


def ensure_test_file_exists(filename: str) -> Path:
    """Ensure a test file exists and return its absolute path.
    
    Args:
        filename: Name of the test file
        
    Returns:
        Absolute path to the test file
        
    Raises:
        FileNotFoundError: If the file doesn't exist
    """
    path = get_test_input_path(filename)
    if not path.exists():
        available_files = list(get_test_inputs_dir().glob("*"))
        available_names = [f.name for f in available_files if f.is_file()]
        raise FileNotFoundError(
            f"Test file '{filename}' not found in test_inputs/.\n"
            f"Available files: {', '.join(sorted(available_names))}"
        )
    return path


def get_small_test_file() -> Path:
    """Get a small test file suitable for quick tests.
    
    Returns:
        Path to apb_sim.vcd which is a small file (4.5KB)
    """
    return get_test_input_path(TestFiles.APB_SIM_VCD)


def get_medium_test_file() -> Path:
    """Get a medium-sized test file for more comprehensive tests.
    
    Returns:
        Path to swerv1.vcd which is a medium file (14MB)
    """
    return get_test_input_path(TestFiles.SWERV1_VCD)


def get_fst_test_file() -> Path:
    """Get an FST format test file.
    
    Returns:
        Path to des.fst
    """
    return get_test_input_path(TestFiles.DES_FST)