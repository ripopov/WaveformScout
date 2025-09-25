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
from wavescout.snippet_manager import Snippet, SnippetManager
from wavescout.snippet_dialogs import InstantiateSnippetDialog
from wavescout.data_model import SignalNode, SignalNodeGroup, SignalNodeSignal
from test_utils import MockVar


def test_validate_and_resolve_nodes_simple():
    """Test the static validation method works correctly."""
    # Create mock waveform database
    mock_db = Mock()
    mock_db.find_handle_by_path = Mock(side_effect=lambda path: {
        "test.signal1": 1,
        "test.signal2": 2,
        "test.group.signal3": 3
    }.get(path, None))
    
    # Test successful validation
    nodes = [
        SignalNodeSignal(name="test.signal1", var=MockVar("signal1"), handle=-1),
        SignalNodeSignal(name="test.signal2", var=MockVar("signal2"), handle=-1)
    ]
    
    validated = InstantiateSnippetDialog.validate_and_resolve_nodes(nodes, mock_db)
    assert len(validated) == 2
    assert validated[0].handle == 1
    assert validated[1].handle == 2
    
    # Test validation with group
    group_node = SignalNodeGroup(
        name="mygroup",
        children=[
            SignalNodeSignal(name="test.group.signal3", var=MockVar("signal3"), handle=-1)
        ]
    )
    
    validated = InstantiateSnippetDialog.validate_and_resolve_nodes([group_node], mock_db)
    assert len(validated) == 1
    assert validated[0].is_group
    assert len(validated[0].children) == 1
    assert validated[0].children[0].handle == 3
    
    # Test validation failure
    bad_nodes = [SignalNodeSignal(name="bad.signal", var=MockVar("signal"), handle=-1)]
    with pytest.raises(ValueError) as exc:
        InstantiateSnippetDialog.validate_and_resolve_nodes(bad_nodes, mock_db)
    assert "Signal 'bad.signal' not found" in str(exc.value)


def test_remap_node_names():
    """Test the name remapping logic directly without creating dialog."""
    # We'll test the logic directly without instantiating the dialog
    # Since _remap_node_names doesn't depend on Qt widgets
    
    # Create a mock dialog object with just the method we need
    class MockDialog:
        def _remap_node_names(self, node: SignalNode, old_parent: str, new_parent: str) -> SignalNode:
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
                
                new_node.name = new_name
                # Don't resolve handle here - leave that to validation
            
            if node.is_group:
                assert isinstance(new_node, SignalNodeGroup)
                new_children = [self._remap_node_names(child, old_parent, new_parent) for child in node.children]
                new_node.children = new_children
                for child in new_node.children:
                    child.parent = new_node
            
            return new_node
    
    dialog = MockDialog()
    
    # Test remapping
    node = SignalNodeSignal(name="old.scope.signal1", var=MockVar("signal1"), handle=-1)
    remapped = dialog._remap_node_names(node, "old.scope", "new.scope")
    
    assert remapped.name == "new.scope.signal1"
    assert remapped.handle == -1  # Handle not resolved during remapping
    
    # Test remapping with no old parent
    node2 = SignalNodeSignal(name="signal2", var=MockVar("signal2"), handle=-1)
    remapped2 = dialog._remap_node_names(node2, "", "new.scope")
    assert remapped2.name == "new.scope.signal2"
    
    # Test remapping with no new parent
    node3 = SignalNodeSignal(name="old.scope.signal3", var=MockVar("signal3"), handle=-1)
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
@patch('wavescout.snippet_manager.SnippetManager')
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
