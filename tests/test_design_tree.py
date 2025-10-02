"""Test DesignTreeNode functionality."""

import pytest
from wavescout.models.scope_tree_model import DesignTreeNode


def test_design_tree_node():
    """Test DesignTreeNode creation."""
    # Test scope node
    scope = DesignTreeNode("testbench", is_scope=True)
    assert scope.name == "testbench"
    assert scope.is_scope == True
    assert scope.var_type == ""
    assert scope.bit_range == ""
    assert len(scope.children) == 0
    
    # Test signal node
    signal = DesignTreeNode("clk", is_scope=False, var_type="reg", bit_range="[0]")
    assert signal.name == "clk"
    assert signal.is_scope == False
    assert signal.var_type == "reg"
    assert signal.bit_range == "[0]"
    
    # Test parent-child relationship
    scope.add_child(signal)
    assert len(scope.children) == 1
    assert signal.parent == scope


if __name__ == "__main__":
    pytest.main([__file__, "-v"])