"""
Snippet management system for saving and loading signal tree templates.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, TypeAlias, Any
from PySide6.QtCore import QStandardPaths, QObject, Signal

from wavescout.data_model import SignalNode, SignalNodeGroup, SignalNodeSignal
from wavescout.timing_utils import tprint

SnippetDict: TypeAlias = dict[str, "Snippet"]


@dataclass
class Snippet:
    """Represents a saved signal tree snippet."""
    name: str
    parent_name: str
    num_nodes: int
    nodes: list[SignalNode]
    description: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert snippet to dictionary for JSON serialization."""
        from wavescout.persistence import serialize_snippet_nodes
        
        return {
            "name": self.name,
            "parent_name": self.parent_name,
            "num_nodes": self.num_nodes,
            "description": self.description,
            "created_at": self.created_at.isoformat(),
            "nodes": serialize_snippet_nodes(self.nodes, self.parent_name)
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Snippet":
        """Create snippet from dictionary."""
        from wavescout.persistence import _deserialize_node
        
        parent_name = data["parent_name"]
        nodes = []
        
        for node_data in data["nodes"]:
            node = _deserialize_node(node_data, None)
            # Keep names as they are in the JSON - they should be relative names
            # Full path reconstruction happens during instantiation, not loading
            nodes.append(node)
        
        return cls(
            name=data["name"],
            parent_name=parent_name,
            num_nodes=data["num_nodes"],
            description=data.get("description", ""),
            created_at=datetime.fromisoformat(data.get("created_at", datetime.now().isoformat())),
            nodes=nodes
        )


class SnippetManager(QObject):
    """Singleton manager for snippet operations."""
    
    # Signals
    snippets_changed = Signal()
    
    _instance: Optional["SnippetManager"] = None
    
    def __new__(cls) -> "SnippetManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self) -> None:
        if not hasattr(self, '_initialized'):
            super().__init__()
            self._initialized = True
            self._snippets: SnippetDict = {}
            self._snippets_dir = self._get_snippets_dir()
            self._ensure_snippets_dir()
            self.load_snippets()
    
    def _get_snippets_dir(self) -> Path:
        """Get the snippets directory path."""
        app_data = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        return Path(app_data) / "snippets"
    
    def _ensure_snippets_dir(self) -> None:
        """Ensure snippets directory exists."""
        self._snippets_dir.mkdir(parents=True, exist_ok=True)
    
    def load_snippets(self) -> None:
        """Load all snippets from disk."""
        self._snippets.clear()
        
        if not self._snippets_dir.exists():
            return
        
        for json_file in self._snippets_dir.glob("*.json"):
            try:
                with open(json_file, 'r') as f:
                    data = json.load(f)
                    snippet = Snippet.from_dict(data)
                    self._snippets[snippet.name] = snippet
            except Exception as e:
                tprint(f"Error loading snippet {json_file}: {e}")
    
    def load_snippet_file(self, filename: str) -> Optional[Snippet]:
        """Load a specific snippet file from the snippets directory."""
        json_file = self._snippets_dir / filename
        if not json_file.exists():
            return None
        try:
            with open(json_file, 'r') as f:
                data = json.load(f)
                return Snippet.from_dict(data)
        except Exception as e:
            tprint(f"Error loading snippet {json_file}: {e}")
            return None
    
    def save_snippet(self, snippet: Snippet) -> bool:
        """Save snippet to disk."""
        try:
            file_path = self._snippets_dir / f"{snippet.name}.json"
            
            # Deep copy the nodes before modifying to avoid affecting the current session
            nodes_copy = [node.deep_copy() for node in snippet.nodes]
            
            # Set all handles to -1 before saving (snippets are waveform-agnostic)
            for node in self._walk_nodes(nodes_copy):
                if isinstance(node, SignalNodeSignal):
                    node.handle = -1
            
            # Create a new snippet with the copied nodes for saving
            snippet_to_save = Snippet(
                name=snippet.name,
                parent_name=snippet.parent_name,
                num_nodes=snippet.num_nodes,
                nodes=nodes_copy,
                description=snippet.description,
                created_at=snippet.created_at
            )
            
            with open(file_path, 'w') as f:
                json.dump(snippet_to_save.to_dict(), f, indent=2)
            
            self._snippets[snippet.name] = snippet
            self.snippets_changed.emit()
            return True
            
        except Exception as e:
            tprint(f"Error saving snippet: {e}")
            return False
    
    def delete_snippet(self, name: str) -> bool:
        """Delete snippet from disk and memory."""
        try:
            file_path = self._snippets_dir / f"{name}.json"
            if file_path.exists():
                file_path.unlink()
            
            if name in self._snippets:
                del self._snippets[name]
                self.snippets_changed.emit()
            
            return True
            
        except Exception as e:
            tprint(f"Error deleting snippet {name}: {e}")
            return False
    
    def get_snippet(self, name: str) -> Optional[Snippet]:
        """Get snippet by name."""
        return self._snippets.get(name)
    
    def get_all_snippets(self) -> list[Snippet]:
        """Get all loaded snippets."""
        return list(self._snippets.values())
    
    def snippet_exists(self, name: str) -> bool:
        """Check if snippet with given name exists."""
        return name in self._snippets
    
    def rename_snippet(self, old_name: str, new_name: str) -> bool:
        """Rename an existing snippet."""
        if old_name not in self._snippets:
            return False
        
        if new_name in self._snippets:
            return False  # Name already exists
        
        try:
            # Delete old file
            old_file = self._snippets_dir / f"{old_name}.json"
            if old_file.exists():
                old_file.unlink()
            
            # Update snippet name and save
            snippet = self._snippets[old_name]
            snippet.name = new_name
            self.save_snippet(snippet)
            
            # Remove old entry
            del self._snippets[old_name]
            
            return True
            
        except Exception as e:
            tprint(f"Error renaming snippet: {e}")
            return False
    
    def find_common_parent(self, group_node: SignalNode) -> str:
        """Find common parent scope for all signals in a group."""
        all_paths: list[str] = []
        
        def collect_paths(node: SignalNode) -> None:
            if not node.is_group:
                all_paths.append(node.name)
            elif isinstance(node, SignalNodeGroup):
                for child in node.children:
                    collect_paths(child)
        
        collect_paths(group_node)
        
        if not all_paths:
            return ""
        
        # Split all paths by '.'
        split_paths = [path.split('.') for path in all_paths]
        
        # Find common prefix
        common: list[str] = []
        min_len = min(len(p) for p in split_paths)
        
        for i in range(min_len):
            if all(p[i] == split_paths[0][i] for p in split_paths):
                common.append(split_paths[0][i])
            else:
                break
        
        return '.'.join(common)
    
    def _walk_nodes(self, nodes: list[SignalNode]) -> list[SignalNode]:
        """Walk all nodes in tree recursively."""
        result: list[SignalNode] = []
        
        def walk(node: SignalNode) -> None:
            result.append(node)
            if isinstance(node, SignalNodeGroup):
                for child in node.children:
                    walk(child)
        
        for node in nodes:
            walk(node)
        
        return result
