"""
Simple unit tests for CLI snippet loading without full Qt application.
"""

import sys
import json
import tempfile
from pathlib import Path
import pytest
from unittest.mock import Mock, patch, MagicMock

# Test the individual components
from wavescout.snippets.snippet_manager import Snippet, SnippetManager
from wavescout.snippets.snippet_dialogs import InstantiateSnippetDialog
from wavescout.core.data_model import TreeNode, GroupNode, SignalNode
from wavescout.core.waveform_db import AsyncLoadedSignal, WaveformDB
from wavescout.application.event_bus import EventBus
from .test_utils import MockVar, get_test_input_path


def test_validate_and_resolve_nodes_simple():
    """Test the static validation method works correctly with a real waveform DB."""
    # Create real waveform database using a small test VCD
    db = WaveformDB(EventBus())
    vcd_path = str(get_test_input_path("apb_sim.vcd"))
    db.open(vcd_path)

    # Get actual handles and vars
    pclk_h = db.find_handle_by_path(["apb_testbench", "pclk"])
    paddr_h = db.find_handle_by_path(["apb_testbench", "paddr"])
    assert pclk_h is not None and paddr_h is not None
    pclk_var = db.get_var(pclk_h)
    paddr_var = db.get_var(paddr_h)

    # Test successful validation - returns (validated_nodes, handles_to_load)
    nodes = [
        SignalNode(local_name="pclk", _waveform_scope=("apb_testbench",), var=pclk_var, handle=-1, signal=AsyncLoadedSignal(pclk_h, db)),
        SignalNode(local_name="paddr", _waveform_scope=("apb_testbench",), var=paddr_var, handle=-1, signal=AsyncLoadedSignal(paddr_h, db))
    ]

    validated, handles_to_load = InstantiateSnippetDialog.validate_and_resolve_nodes(nodes, db)
    assert len(validated) == 2
    assert validated[0].handle in (pclk_h, paddr_h)
    assert validated[1].handle in (pclk_h, paddr_h)
    # Don't assert cache status; just ensure it's a list of ints
    assert isinstance(handles_to_load, list)
    for h in handles_to_load:
        assert isinstance(h, int)

    # Test validation with group
    group_node = GroupNode(
        local_name="mygroup",
        children=[
            SignalNode(local_name="pclk", _waveform_scope=("apb_testbench",), var=pclk_var, handle=-1, signal=AsyncLoadedSignal(pclk_h, db))
        ]
    )

    validated, handles_to_load = InstantiateSnippetDialog.validate_and_resolve_nodes([group_node], db)
    assert len(validated) == 1
    assert validated[0].is_group
    assert len(validated[0].children) == 1
    assert validated[0].children[0].handle == pclk_h

    # Test validation failure for a non-existent signal
    bad_nodes = [SignalNode(local_name="signal", _waveform_scope=("bad",), var=MockVar("signal"), handle=-1, signal=AsyncLoadedSignal.placeholder(-1))]
    with pytest.raises(ValueError) as exc:
        InstantiateSnippetDialog.validate_and_resolve_nodes(bad_nodes, db)
    assert "Signal 'bad.signal' not found" in str(exc.value)


def test_remap_node_names():
    """Test the name remapping logic directly without creating dialog."""
    # We'll test the logic directly without instantiating the dialog
    # Since _remap_node_names doesn't depend on Qt widgets
    
    # Create a mock dialog object with just the method we need
    class MockDialog:
        def _remap_node_names(self, node: TreeNode, old_parent: str, new_parent: str) -> TreeNode:
            """Just remap names without validation."""
            new_node = node.deep_copy()

            if not node.is_group:
                # Calculate relative name
                if old_parent and node.name.startswith(old_parent + "."):
                    relative_name = node.name[len(old_parent) + 1:]
                elif not old_parent:
                    relative_name = node.name
                else:
                    # Handle case where node name doesn't start with parent
                    relative_name = node.name.split('.')[-1]

                # Build new name
                if new_parent:
                    new_name = f"{new_parent}.{relative_name}"
                else:
                    new_name = relative_name

                # Update node with new path structure
                parts = new_name.split('.')
                new_node.local_name = parts[-1] if parts else new_name
                if isinstance(new_node, SignalNode):
                    new_node._waveform_scope = tuple(parts[:-1]) if len(parts) > 1 else ()
                # Don't resolve handle here - leave that to validation
            
            if node.is_group:
                assert isinstance(new_node, GroupNode)
                new_children = [self._remap_node_names(child, old_parent, new_parent) for child in node.children]
                new_node.children = new_children
                for child in new_node.children:
                    child.parent = new_node
            
            return new_node
    
    dialog = MockDialog()
    
    # Test remapping
    node = SignalNode(local_name="signal1", _waveform_scope=("old", "scope"), var=MockVar("signal1"), handle=-1, signal=AsyncLoadedSignal.placeholder(-1))
    remapped = dialog._remap_node_names(node, "old.scope", "new.scope")

    assert remapped.name == "new.scope.signal1"
    assert remapped.handle == -1  # Handle not resolved during remapping

    # Test remapping with no old parent
    node2 = SignalNode(local_name="signal2", _waveform_scope=(), var=MockVar("signal2"), handle=-1, signal=AsyncLoadedSignal.placeholder(-1))
    remapped2 = dialog._remap_node_names(node2, "", "new.scope")
    assert remapped2.name == "new.scope.signal2"

    # Test remapping with no new parent
    node3 = SignalNode(local_name="signal3", _waveform_scope=("old", "scope"), var=MockVar("signal3"), handle=-1, signal=AsyncLoadedSignal.placeholder(-1))
    remapped3 = dialog._remap_node_names(node3, "old.scope", "")
    assert remapped3.name == "signal3"


def test_snippet_manager_load_file():
    """Test loading a specific snippet file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        snippets_dir = Path(tmpdir) / "snippets"
        snippets_dir.mkdir()
        
        # Create a test snippet file
        snippet_data = {
            "name": "test",
            "parent_name": "scope",
            "num_nodes": 1,
            "description": "Test snippet",
            "created_at": "2024-01-01T00:00:00",
            "nodes": [
                {
                    "name": "scope.signal",
                    "handle": -1,
                    "is_group": False,
                    "children": []
                }
            ]
        }
        
        snippet_file = snippets_dir / "test.json"
        with open(snippet_file, 'w') as f:
            json.dump(snippet_data, f)
        
        # Mock the snippets directory
        manager = SnippetManager()
        manager._snippets_dir = snippets_dir
        
        # Test loading
        snippet = manager.load_snippet_file("test.json")
        assert snippet is not None
        assert snippet.name == "test"
        assert len(snippet.nodes) == 1
        
        # Test missing file
        missing = manager.load_snippet_file("missing.json")
        assert missing is None


def test_cli_snippets_argument_parsing():
    """Test that CLI arguments are parsed correctly."""
    import argparse
    
    # Create the parser as in scout.py
    parser = argparse.ArgumentParser()
    parser.add_argument("--load_wave", nargs='+', metavar=('WAVE_FILE', 'SNIPPET'))
    
    # Test parsing with snippets
    args = parser.parse_args(["--load_wave", "test.vcd", "snippet1.json", "snippet2.json"])
    assert args.load_wave == ["test.vcd", "snippet1.json", "snippet2.json"]
    
    # Test parsing without snippets
    args2 = parser.parse_args(["--load_wave", "test.vcd"])
    assert args2.load_wave == ["test.vcd"]


def test_loading_state_cli_snippets():
    """Test that LoadingState properly stores CLI snippets."""
    from scout import LoadingState
    
    state = LoadingState()
    assert state.cli_snippets == []
    
    state.cli_snippets = ["snippet1.json", "snippet2.json"]
    assert len(state.cli_snippets) == 2
    
    state.clear()
    assert state.cli_snippets == []


@patch('sys.exit')
@patch('wavescout.snippets.snippet_manager.SnippetManager')
def test_load_cli_snippets_error_handling(mock_manager_class, mock_exit):
    """Test error handling in _load_cli_snippets method."""
    # This would normally be in scout.py but we'll test the logic
    
    # Mock manager that returns None for missing snippet
    mock_manager = Mock()
    mock_manager.load_snippet_file = Mock(return_value=None)
    mock_manager_class.return_value = mock_manager
    
    # Test the error path
    from scout import WaveScoutMainWindow
    
    # We can't actually instantiate the window without Qt, but we can test
    # the logic by mocking
    window_mock = Mock(spec=WaveScoutMainWindow)
    window_mock.wave_widget = Mock()
    window_mock.wave_widget.session = Mock()
    window_mock.wave_widget.session.waveform_db = Mock()
    
    # Import the actual method
    from scout import WaveScoutMainWindow
    
    # Call the method with a mock self
    try:
        WaveScoutMainWindow._load_cli_snippets(window_mock, ["missing.json"])
    except SystemExit:
        pass  # Expected
    
    # Check that exit was called with code 1
    mock_exit.assert_called_once_with(1)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
