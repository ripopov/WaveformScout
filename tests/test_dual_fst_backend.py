"""Test dual FST backend support functionality."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from wavescout.waveform_db import WaveformDB
from wavescout.backends import BackendFactory, BackendType
from wavescout.backends.pylibfst_backend import PylibfstBackend
from .test_utils import get_test_input_path, TestFiles


def test_backend_factory_registration():
    """Test that backends are registered with the factory."""
    available_backends = BackendFactory.get_available_backends()
    # pyrox should always be available as the primary backend
    assert BackendType.PYROX in available_backends
    # pylibfst should be available
    assert BackendType.PYLIBFST in available_backends


def test_vcd_backend_selection():
    """Test that VCD files use pyrox backend."""
    vcd_file = get_test_input_path(TestFiles.SWERV1_VCD)
    
    if not vcd_file.exists():
        pytest.skip(f"Test VCD file not found: {vcd_file}")
    
    # Test default (should use pyrox)
    db_default = WaveformDB()
    db_default.open(str(vcd_file))
    assert db_default.get_backend_type() == BackendType.PYROX
    db_default.close()


    # Test with pylibfst preference - should use pyrox for VCD (pylibfst doesn't support VCD)
    db_pylibfst = WaveformDB(backend_preference="pylibfst")
    db_pylibfst.open(str(vcd_file))
    assert db_pylibfst.get_backend_type() == BackendType.PYROX
    db_pylibfst.close()


def test_fst_backend_preference():
    """Test that FST files respect backend preference."""
    fst_file = get_test_input_path(TestFiles.DES_FST)
    
    if not fst_file.exists():
        pytest.skip(f"Test FST file not found: {fst_file}")
    
    # Test default (should use pyrox)
    db_default = WaveformDB()
    db_default.open(str(fst_file))
    assert db_default.get_backend_type() == BackendType.PYROX
    db_default.close()

    # Test with pylibfst preference  
    db_pylibfst = WaveformDB(backend_preference="pylibfst")
    db_pylibfst.open(str(fst_file))
    assert db_pylibfst.get_backend_type() == BackendType.PYLIBFST
    db_pylibfst.close()


def test_backend_preference_persistence():
    """Test that backend preference can be set and retrieved."""
    db = WaveformDB(backend_preference="pyrox")
    assert db._backend_preference == "pyrox"

    db.set_backend_preference("pylibfst")
    assert db._backend_preference == "pylibfst"

    db.set_backend_preference("pyrox")
    assert db._backend_preference == "pyrox"


def test_invalid_backend_preference():
    """Test handling of invalid backend preference."""
    # Invalid preference in init gets stored as-is
    db = WaveformDB(backend_preference="invalid")
    assert db._backend_preference == "invalid"
    
    # When opening a file, invalid preference defaults to pyrox
    # This would be tested when opening a file, but we can't test it without a file


def test_backend_protocol_conformance():
    """Test that backends conform to the expected protocol."""
    from wavescout.backend_types import WWaveform, WHierarchy, WSignal, WVar
    from wavescout.backends.pyrox_backend import PyroxBackend

    # Check that backend methods exist and have correct signatures
    for backend_class in [PyroxBackend, PylibfstBackend]:
        backend = backend_class("dummy_path")
        
        # Check required methods exist
        assert hasattr(backend, 'load_waveform')
        assert hasattr(backend, 'get_hierarchy')
        assert hasattr(backend, 'get_time_table')
        assert hasattr(backend, 'get_signal')
        assert hasattr(backend, 'load_signals')
        assert hasattr(backend, 'supports_file_format')
        
        # Check that load_signals has the multithreaded parameter
        import inspect
        sig = inspect.signature(backend.load_signals)
        assert 'multithreaded' in sig.parameters


def test_pylibfst_time_table_adapter():
    """Test that pylibfst's TimeTableAdapter works correctly."""
    from wavescout.backends.pylibfst_backend import TimeTableAdapter
    
    # Test with time range
    adapter = TimeTableAdapter((100, 2000))
    assert len(adapter) == 2
    assert adapter[0] == 100
    assert adapter[1] == 2000
    
    # Test out of bounds access
    with pytest.raises(IndexError):
        _ = adapter[2]
    
    # Test with None time range
    adapter_none = TimeTableAdapter(None)
    assert len(adapter_none) == 0
    with pytest.raises(IndexError):
        _ = adapter_none[0]


def test_backend_file_format_support():
    """Test that backends correctly report supported file formats."""
    from wavescout.backends.pyrox_backend import PyroxBackend

    pyrox_backend = PyroxBackend("dummy.vcd")
    assert pyrox_backend.supports_file_format("test.vcd")
    assert pyrox_backend.supports_file_format("test.fst")
    assert not pyrox_backend.supports_file_format("test.txt")
    
    pylibfst_backend = PylibfstBackend("dummy.fst")
    assert not pylibfst_backend.supports_file_format("test.vcd")
    assert pylibfst_backend.supports_file_format("test.fst")
    assert not pylibfst_backend.supports_file_format("test.txt")


def test_waveform_db_backend_switching():
    """Test that WaveformDB can switch backends between file loads."""
    vcd_file = get_test_input_path(TestFiles.SWERV1_VCD)
    
    if not vcd_file.exists():
        pytest.skip(f"Test VCD file not found: {vcd_file}")
    
    db = WaveformDB(backend_preference="pyrox")

    # Load with pyrox
    db.open(str(vcd_file))
    assert db.get_backend_type() == BackendType.PYROX
    db.close()
    
    # Switch preference to pylibfst
    db.set_backend_preference("pylibfst")
    assert db._backend_preference == "pylibfst"
    
    # Load VCD again - should use pyrox (pylibfst doesn't support VCD)
    db.open(str(vcd_file))
    assert db.get_backend_type() == BackendType.PYROX
    db.close()


@pytest.mark.skipif(
    not get_test_input_path(TestFiles.DES_FST).exists(),
    reason="FST test file not available"
)
def test_fst_backend_data_consistency():
    """Test that both backends produce consistent data for FST files."""
    fst_file = get_test_input_path(TestFiles.DES_FST)
    
    # Load with pyrox backend
    db_pyrox = WaveformDB(backend_preference="pyrox")
    db_pyrox.open(str(fst_file))

    # Get some basic info
    hierarchy_pyrox = db_pyrox.hierarchy
    num_vars_pyrox = db_pyrox.num_vars()

    # Load with pylibfst backend
    db_pylibfst = WaveformDB(backend_preference="pylibfst")
    db_pylibfst.open(str(fst_file))

    hierarchy_pylibfst = db_pylibfst.hierarchy
    num_vars_pylibfst = db_pylibfst.num_vars()

    # Both backends should report same hierarchy structure
    assert hierarchy_pyrox is not None
    assert hierarchy_pylibfst is not None

    # Both should have same number of variables
    assert num_vars_pyrox == num_vars_pylibfst

    # Clean up
    db_pyrox.close()
    db_pylibfst.close()