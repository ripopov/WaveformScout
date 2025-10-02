#!/usr/bin/env python3
"""Integration tests for multi-file waveform support."""

import sys
import tempfile
import pathlib
from pathlib import Path

import pytest

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from wavescout.core.waveform_db import WaveformDB
from wavescout.core.data_model import (
    WaveformSession,
    TreeNode,
    SignalNode,
    DisplayFormat,
    WaveformFileReference,
)
from wavescout.core.waveform_controller import WaveformController
from wavescout.core.persistence import save_session, load_session
from wavescout.application.event_bus import EventBus
from tests.test_utils import TestFiles, get_test_input_path


class TestMultipleWaveforms:
    """Test suite for loading and working with multiple waveform files simultaneously."""

    def test_load_two_waveforms(self):
        """Test loading two waveform files at the same time."""
        print("\n=== Testing Multiple Waveform Loading ===")

        # Get test file paths
        apb_path = str(get_test_input_path(TestFiles.APB_SIM_VCD))
        swerv_path = str(get_test_input_path(TestFiles.SWERV1_VCD))

        # Create session with event bus
        event_bus = EventBus()
        session = WaveformSession()

        # Load first waveform
        db1 = WaveformDB(event_bus=event_bus)
        db1.open(apb_path)
        file_ref1 = session.add_waveform_file(apb_path, db1)
        print(f"✓ Loaded first waveform: {TestFiles.APB_SIM_VCD}")

        # Load second waveform
        db2 = WaveformDB(event_bus=event_bus)
        db2.open(swerv_path)
        file_ref2 = session.add_waveform_file(swerv_path, db2)
        print(f"✓ Loaded second waveform: {TestFiles.SWERV1_VCD}")

        # Verify both files are in session
        assert len(session.waveform_files) == 2, "Expected 2 waveform files in session"
        assert session.waveform_files[0].file_id == 0, "First file should have ID 0"
        assert session.waveform_files[1].file_id == 1, "Second file should have ID 1"
        assert session.next_file_id == 2, "Next file ID should be 2"
        print(f"✓ Session contains {len(session.waveform_files)} waveform files")

        # Verify file references
        assert file_ref1.file_path == apb_path
        assert file_ref2.file_path == swerv_path
        assert file_ref1.waveform_db is db1
        assert file_ref2.waveform_db is db2
        print("✓ File references correctly stored")

    def test_add_signals_from_different_files(self):
        """Test adding signals from different waveform files to the session."""
        print("\n=== Testing Signal Addition from Multiple Files ===")

        # Setup: Load two waveforms
        event_bus = EventBus()
        session = WaveformSession()

        apb_path = str(get_test_input_path(TestFiles.APB_SIM_VCD))
        swerv_path = str(get_test_input_path(TestFiles.SWERV1_VCD))

        db1 = WaveformDB(event_bus=event_bus)
        db1.open(apb_path)
        file_ref1 = session.add_waveform_file(apb_path, db1)

        db2 = WaveformDB(event_bus=event_bus)
        db2.open(swerv_path)
        file_ref2 = session.add_waveform_file(swerv_path, db2)

        # Add signals from first waveform (apb_sim.vcd)
        apb_signals = []
        for handle in list(db1.get_all_handles())[:3]:  # Add first 3 signals
            var = db1.var_from_handle(handle)
            if var:
                name = var.full_name(db1.hierarchy)
                signal = SignalNode(
                    name=name,
                    var=var,
                    handle=handle,
                    signal=db1.load_signal(handle),
                    format=DisplayFormat(),
                    file_id=file_ref1.file_id,  # Set file_id
                )
                apb_signals.append(signal)
                session.root_nodes.append(signal)

        print(f"✓ Added {len(apb_signals)} signals from {TestFiles.APB_SIM_VCD}")

        # Add signals from second waveform (swerv1.vcd)
        swerv_signals = []
        for handle in list(db2.get_all_handles())[:3]:  # Add first 3 signals
            var = db2.var_from_handle(handle)
            if var:
                name = var.full_name(db2.hierarchy)
                signal = SignalNode(
                    name=name,
                    var=var,
                    handle=handle,
                    signal=db2.load_signal(handle),
                    format=DisplayFormat(),
                    file_id=file_ref2.file_id,  # Set file_id
                )
                swerv_signals.append(signal)
                session.root_nodes.append(signal)

        print(f"✓ Added {len(swerv_signals)} signals from {TestFiles.SWERV1_VCD}")

        # Verify all signals are in session
        assert len(session.root_nodes) == len(apb_signals) + len(swerv_signals)
        print(f"✓ Total signals in session: {len(session.root_nodes)}")

        # Verify file_id is correctly set
        for signal in apb_signals:
            assert signal.file_id == file_ref1.file_id, f"APB signal should have file_id {file_ref1.file_id}"
        for signal in swerv_signals:
            assert signal.file_id == file_ref2.file_id, f"SWERV signal should have file_id {file_ref2.file_id}"
        print("✓ All signals have correct file_id")

        # Verify file lookup works
        for signal in apb_signals:
            file_ref = session.get_file_by_id(signal.file_id)
            assert file_ref is not None
            assert file_ref.waveform_db is db1
        for signal in swerv_signals:
            file_ref = session.get_file_by_id(signal.file_id)
            assert file_ref is not None
            assert file_ref.waveform_db is db2
        print("✓ File lookup by ID works correctly")

    def test_multi_file_session_persistence(self):
        """Test saving and loading a session with multiple waveform files."""
        print("\n=== Testing Multi-File Session Persistence ===")

        # Create session with two waveforms and signals
        event_bus = EventBus()
        original_session = WaveformSession()

        apb_path = str(get_test_input_path(TestFiles.APB_SIM_VCD))
        swerv_path = str(get_test_input_path(TestFiles.SWERV1_VCD))

        # Load waveforms
        db1 = WaveformDB(event_bus=event_bus)
        db1.open(apb_path)
        file_ref1 = original_session.add_waveform_file(apb_path, db1)

        db2 = WaveformDB(event_bus=event_bus)
        db2.open(swerv_path)
        file_ref2 = original_session.add_waveform_file(swerv_path, db2)

        # Add signals from both files
        apb_handles = list(db1.get_all_handles())[:2]
        swerv_handles = list(db2.get_all_handles())[:2]

        for handle in apb_handles:
            var = db1.var_from_handle(handle)
            if var:
                name = var.full_name(db1.hierarchy)
                signal = SignalNode(
                    name=name,
                    var=var,
                    handle=handle,
                    signal=db1.load_signal(handle),
                    format=DisplayFormat(),
                    file_id=file_ref1.file_id,
                )
                original_session.root_nodes.append(signal)

        for handle in swerv_handles:
            var = db2.var_from_handle(handle)
            if var:
                name = var.full_name(db2.hierarchy)
                signal = SignalNode(
                    name=name,
                    var=var,
                    handle=handle,
                    signal=db2.load_signal(handle),
                    format=DisplayFormat(),
                    file_id=file_ref2.file_id,
                )
                original_session.root_nodes.append(signal)

        print(f"✓ Created session with {len(original_session.root_nodes)} signals")

        # Save session to temporary file
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            temp_path = pathlib.Path(f.name)

        try:
            save_session(original_session, temp_path)
            print(f"✓ Session saved to {temp_path}")

            # Load session back
            loaded_session = load_session(temp_path)
            print("✓ Session loaded successfully")

            # Verify waveform files
            assert len(loaded_session.waveform_files) == 2, "Loaded session should have 2 waveform files"
            assert loaded_session.waveform_files[0].file_id == 0
            assert loaded_session.waveform_files[1].file_id == 1
            assert loaded_session.next_file_id == 2
            print(f"✓ Loaded session has {len(loaded_session.waveform_files)} waveform files")

            # Verify file paths
            assert Path(loaded_session.waveform_files[0].file_path) == Path(apb_path)
            assert Path(loaded_session.waveform_files[1].file_path) == Path(swerv_path)
            print("✓ File paths preserved correctly")

            # Verify signals
            assert len(loaded_session.root_nodes) == len(original_session.root_nodes)
            print(f"✓ Loaded session has {len(loaded_session.root_nodes)} signals")

            # Verify file_id for each signal
            apb_signal_count = sum(1 for s in loaded_session.root_nodes if isinstance(s, SignalNode) and s.file_id == 0)
            swerv_signal_count = sum(1 for s in loaded_session.root_nodes if isinstance(s, SignalNode) and s.file_id == 1)
            assert apb_signal_count == len(apb_handles)
            assert swerv_signal_count == len(swerv_handles)
            print(f"✓ Signal file_id preserved: {apb_signal_count} from file 0, {swerv_signal_count} from file 1")

            # Verify signals can be accessed
            for signal in loaded_session.root_nodes:
                if isinstance(signal, SignalNode):
                    file_ref = loaded_session.get_file_by_id(signal.file_id)
                    assert file_ref is not None, f"File reference not found for signal {signal.name}"
                    assert file_ref.waveform_db is not None, f"WaveformDB not loaded for signal {signal.name}"
            print("✓ All signals have valid file references")

        finally:
            # Cleanup
            if temp_path.exists():
                temp_path.unlink()
            print("✓ Cleanup completed")

    def test_file_prefix_display_data(self):
        """Test that file prefix information is correctly stored in signal nodes."""
        print("\n=== Testing File Prefix Display Data ===")

        event_bus = EventBus()
        session = WaveformSession()

        apb_path = str(get_test_input_path(TestFiles.APB_SIM_VCD))
        swerv_path = str(get_test_input_path(TestFiles.SWERV1_VCD))

        # Load waveforms
        db1 = WaveformDB(event_bus=event_bus)
        db1.open(apb_path)
        file_ref1 = session.add_waveform_file(apb_path, db1)

        db2 = WaveformDB(event_bus=event_bus)
        db2.open(swerv_path)
        file_ref2 = session.add_waveform_file(swerv_path, db2)

        # Add a signal from each file
        apb_handle = list(db1.get_all_handles())[0]
        apb_var = db1.var_from_handle(apb_handle)
        apb_signal = SignalNode(
            name=apb_var.full_name(db1.hierarchy),
            var=apb_var,
            handle=apb_handle,
            signal=db1.load_signal(apb_handle),
            format=DisplayFormat(),
            file_id=file_ref1.file_id,
        )

        swerv_handle = list(db2.get_all_handles())[0]
        swerv_var = db2.var_from_handle(swerv_handle)
        swerv_signal = SignalNode(
            name=swerv_var.full_name(db2.hierarchy),
            var=swerv_var,
            handle=swerv_handle,
            signal=db2.load_signal(swerv_handle),
            format=DisplayFormat(),
            file_id=file_ref2.file_id,
        )

        # Verify file_id is stored
        assert apb_signal.file_id == 0, "APB signal should have file_id 0"
        assert swerv_signal.file_id == 1, "SWERV signal should have file_id 1"
        print("✓ file_id correctly stored in signal nodes")

        # Verify file lookup
        apb_file = session.get_file_by_id(apb_signal.file_id)
        swerv_file = session.get_file_by_id(swerv_signal.file_id)

        assert apb_file is not None
        assert swerv_file is not None
        assert Path(apb_file.file_path).name == TestFiles.APB_SIM_VCD
        assert Path(swerv_file.file_path).name == TestFiles.SWERV1_VCD
        print("✓ File information retrievable from session")

        # Test primary file detection
        primary_file = session.get_primary_file()
        assert primary_file is not None
        assert primary_file.file_id == 0
        assert primary_file == file_ref1
        print("✓ Primary file correctly identified")

    def test_controller_with_multiple_files(self):
        """Test WaveformController with multiple waveform files."""
        print("\n=== Testing WaveformController with Multiple Files ===")

        event_bus = EventBus()
        controller = WaveformController(event_bus=event_bus)
        session = WaveformSession()

        apb_path = str(get_test_input_path(TestFiles.APB_SIM_VCD))
        swerv_path = str(get_test_input_path(TestFiles.SWERV1_VCD))

        # Load waveforms
        db1 = WaveformDB(event_bus=event_bus)
        db1.open(apb_path)
        file_ref1 = session.add_waveform_file(apb_path, db1)

        db2 = WaveformDB(event_bus=event_bus)
        db2.open(swerv_path)
        file_ref2 = session.add_waveform_file(swerv_path, db2)

        # Create signals from both files
        apb_handle = list(db1.get_all_handles())[0]
        apb_var = db1.var_from_handle(apb_handle)
        apb_signal = SignalNode(
            name=apb_var.full_name(db1.hierarchy),
            var=apb_var,
            handle=apb_handle,
            signal=db1.load_signal(apb_handle),
            format=DisplayFormat(),
            file_id=file_ref1.file_id,
        )
        session.root_nodes.append(apb_signal)

        swerv_handle = list(db2.get_all_handles())[0]
        swerv_var = db2.var_from_handle(swerv_handle)
        swerv_signal = SignalNode(
            name=swerv_var.full_name(db2.hierarchy),
            var=swerv_var,
            handle=swerv_handle,
            signal=db2.load_signal(swerv_handle),
            format=DisplayFormat(),
            file_id=file_ref2.file_id,
        )
        session.root_nodes.append(swerv_signal)

        # Set session on controller
        controller.set_session(session)
        print("✓ Session set on controller")

        # Test get_waveform_db_for_signal
        apb_db = controller.get_waveform_db_for_signal(apb_signal)
        swerv_db = controller.get_waveform_db_for_signal(swerv_signal)

        assert apb_db is db1, "Should return correct WaveformDB for APB signal"
        assert swerv_db is db2, "Should return correct WaveformDB for SWERV signal"
        print("✓ get_waveform_db_for_signal returns correct DB for each signal")

        # Verify controller session has multiple files
        assert len(controller.session.waveform_files) == 2
        print(f"✓ Controller session has {len(controller.session.waveform_files)} waveform files")


if __name__ == "__main__":
    # Run all tests
    pytest.main([__file__, "-v", "-s"])