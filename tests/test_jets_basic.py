"""Basic JETS file loading test."""
import pytest
from pathlib import Path
import pyrox


def test_jets_file_loading():
    """Test loading JETS file."""
    jets_file = Path(__file__).parent.parent / "jets" / "gpu_sim.jets"

    # Verify file exists
    assert jets_file.exists(), f"JETS file not found: {jets_file}"

    # Load the JETS file
    wf = pyrox.Waveform(str(jets_file))

    # Verify the waveform object was created
    assert wf is not None

    # Note: Full hierarchy access is not yet implemented
    # The loader currently loads the JETS file but doesn't expose
    # the hierarchy through the Pyrox API yet.
    # This is Phase 1 - basic file loading and structure.


def test_jets_file_detection():
    """Test that .jets extension is properly detected."""
    jets_file = Path(__file__).parent.parent / "jets" / "gpu_sim.jets"

    # Should not raise an error
    wf = pyrox.Waveform(str(jets_file))
    assert wf is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
