import pytest
from wavescout import WaveScoutWidget, WaveformSession
from wavescout.waveform_loader import create_signal_node_from_var, create_sample_session
from wavescout.data_model import SignalNode, SignalNodeGroup, GroupRenderMode, RenderType, AnalogScalingMode
from .test_utils import get_test_input_path


def _find_vars_by_names(db, names):
    hierarchy = db.hierarchy
    found = {}
    # Iterate all vars and match by local name or full name ending
    for i in range(db.num_vars()):
        var = db.get_var(i)
        if not var:
            continue
        local = var.name(hierarchy)
        full = var.full_name(hierarchy)
        if local in names or any(full.endswith(n) for n in names):
            found[local] = (i, var)
            if len(found) == len(names):
                break
    return found


@pytest.mark.qt
def test_overlapped_group_periodic_signals(qtbot):
    # Load the provided periodic_signals.vcd
    vcd_path = get_test_input_path("periodic_signals.vcd")
    session: WaveformSession = create_sample_session(str(vcd_path))

    # Build three signal nodes from the DB
    db = session.waveform_db
    assert db is not None
    names = ["sine_1khz", "cosine_2khz", "square_4khz"]
    found = _find_vars_by_names(db, names)
    assert len(found) >= 3, "Expected to find at least 3 periodic signals"

    # Create child nodes
    children = []
    hierarchy = db.hierarchy
    for nm in names:
        handle, var = found[nm]
        node = create_signal_node_from_var(var, hierarchy, handle)
        children.append(node)

    # Create group and attach children
    group = SignalNodeGroup(name="PeriodicGroup", is_expanded=True)
    for ch in children:
        ch.parent = group
        group.children.append(ch)

    # Add to session
    session.root_nodes.append(group)

    # Create widget and set session
    widget = WaveScoutWidget()
    qtbot.addWidget(widget)
    widget.resize(800, 400)
    widget.setSession(session)
    widget.show()
    qtbot.waitExposed(widget)

    # Switch to overlapped mode
    widget.controller.set_group_render_mode(group.instance_id, GroupRenderMode.OVERLAPPED)

    # Verify children were coerced to analog, scale-to-all, and colors assigned
    for ch in children:
        assert ch.format.render_type == RenderType.ANALOG
        assert ch.format.analog_scaling_mode == AnalogScalingMode.SCALE_TO_ALL_DATA
        assert ch.format.color is not None

    # Force canvas to rebuild visible nodes and check for virtual node
    canvas = widget._canvas
    canvas.updateVisibleNodes()
    
    # Check that a virtual node was created for the overlapped group
    virtual_nodes = [n for n in canvas._visible_nodes if hasattr(n, '_group_render_parent')]
    assert len(virtual_nodes) == 1, "Virtual node for overlapped rendering not created"
    assert getattr(virtual_nodes[0], '_group_render_parent') == group, "Virtual node parent mismatch"
    
    params = canvas._collect_render_params()

    # Try rendering to an image to ensure no exceptions
    image, gen, t = canvas._render_to_image(params, generation=0)
    assert image is not None
    
    # Test that collapsing the group hides the overlapped rendering
    group.is_expanded = False
    canvas.updateVisibleNodes()
    
    # Check that no virtual node exists when group is collapsed
    virtual_nodes_collapsed = [n for n in canvas._visible_nodes if hasattr(n, '_group_render_parent')]
    assert len(virtual_nodes_collapsed) == 0, "Virtual node should not exist when group is collapsed"


@pytest.mark.qt
def test_overlapped_mode_triggers_immediate_rerender(qtbot):
    # Load periodic signals VCD
    vcd_path = get_test_input_path("periodic_signals.vcd")
    session = create_sample_session(str(vcd_path))
    db = session.waveform_db
    assert db is not None

    # Collect three known signals by name suffixes
    names = ["sine_1khz", "cosine_2khz", "square_4khz"]
    found = {}
    hier = db.hierarchy
    for i in range(db.num_vars()):
        var = db.get_var(i)
        if not var:
            continue
        local = var.name(hier)
        full = var.full_name(hier)
        if local in names or any(full.endswith(n) for n in names):
            found[local] = (i, var)
        if len(found) >= 3:
            break
    assert len(found) >= 3

    # Create nodes and group
    children = []
    for nm in names:
        handle, var = found[nm]
        node = create_signal_node_from_var(var, hier, handle)
        children.append(node)
    group = SignalNodeGroup(name="G", is_expanded=True)
    for ch in children:
        ch.parent = group
        group.children.append(ch)
    session.root_nodes.append(group)

    # Widget
    widget = WaveScoutWidget()
    qtbot.addWidget(widget)
    widget.resize(800, 400)
    widget.setSession(session)
    widget.show()
    qtbot.waitExposed(widget)

    # Toggle to overlapped
    widget.controller.set_group_render_mode(group.instance_id, GroupRenderMode.OVERLAPPED)

    # Allow Qt events to process model reset/layout updates
    qtbot.wait(50)

    # Now the canvas should have rebuilt visible nodes including a virtual node
    canvas = widget._canvas
    # Check that a virtual node was created for the overlapped group
    virtual_nodes = [n for n in canvas._visible_nodes if hasattr(n, '_group_render_parent')]
    assert len(virtual_nodes) == 1, "Virtual node should be created immediately after mode switch"
    assert getattr(virtual_nodes[0], '_group_render_parent') == group, "Virtual node parent mismatch"
