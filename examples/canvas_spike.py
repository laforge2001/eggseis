"""M6 canvas spike — verify qtpynodeeditor covers our requirements.

Throwaway. Run headless under QT_QPA_PLATFORM=offscreen.

Checks:
  1. Subclass NodeDataModel and attach plugin metadata.
  2. Multi-input node (`subtract` with ports a, b).
  3. Programmatic wiring via scene.create_connection.
  4. connection_created signal with src/dst port info.
  5. Cycle attempt — does the lib block it or do we?
  6. node_created / node_deleted signals.
"""

from __future__ import annotations

import sys

import qtpynodeeditor as qne
from qtpy.QtWidgets import QApplication
from qtpynodeeditor import (
    DataModelRegistry,
    FlowScene,
    NodeData,
    NodeDataModel,
    NodeDataType,
    Port,
    PortType,
)


class SectionData(NodeData):
    """Sentinel — actual ndarray lives in our GraphExecutor cache.

    qtpynodeeditor's data propagation is decorative for us; the canvas only
    knows 'output exists' / 'output absent'. Compute is owned by the executor.
    """

    data_type = NodeDataType("section", "Section")


_SECTION = SectionData.data_type


def _section_dict(n_in: int, n_out: int = 1) -> dict:
    return {
        "input": {i: _SECTION for i in range(n_in)},
        "output": {i: _SECTION for i in range(n_out)},
    }


class TraceAttrModel(NodeDataModel):
    name = "trace_attr"
    caption = "trace_attr"
    caption_visible = True
    num_ports = {PortType.input: 1, PortType.output: 1}
    data_type = _section_dict(1, 1)
    port_caption_visible = True
    port_caption = {"input": {0: "trace"}, "output": {0: "out"}}
    plugin_id = "spike.trace_attr"
    plugin_version = "0.1.0"

    def __init__(self, style=None, parent=None):
        super().__init__(style=style, parent=parent)
        self._has_output = False

    def out_data(self, port: int) -> NodeData | None:
        return SectionData() if self._has_output else None

    def set_in_data(self, data: NodeData, port: Port) -> None:
        self._has_output = True
        # Lib propagation is decorative for us; suppress emit to avoid
        # graphics-object NPE in headless / view-less scenes.


class SubtractModel(NodeDataModel):
    name = "subtract"
    caption = "subtract"
    caption_visible = True
    num_ports = {PortType.input: 2, PortType.output: 1}
    data_type = _section_dict(2, 1)
    port_caption_visible = True
    port_caption = {"input": {0: "a", 1: "b"}, "output": {0: "out"}}
    plugin_id = "spike.subtract"
    plugin_version = "0.1.0"

    def __init__(self, style=None, parent=None):
        super().__init__(style=style, parent=parent)
        self._inputs = {}

    def out_data(self, port: int) -> NodeData | None:
        return SectionData() if len(self._inputs) == 2 else None

    def set_in_data(self, data: NodeData, port: Port) -> None:
        self._inputs[port.index] = data
        # Lib propagation is decorative for us; suppress emit to avoid
        # graphics-object NPE in headless / view-less scenes.


def main() -> int:
    _app = QApplication(sys.argv)  # Qt requires a live QApplication; ref retained.

    registry = DataModelRegistry()
    registry.register_model(TraceAttrModel, category="Spike")
    registry.register_model(SubtractModel, category="Spike")

    scene = FlowScene(registry=registry)
    view = qne.FlowView(scene)
    view.resize(800, 600)
    # Don't show under offscreen, but instantiate so connection graphics_objects exist.

    events = []
    scene.connection_created.connect(
        lambda c: events.append(("conn", _conn_repr(c)))
    )
    scene.connection_deleted.connect(
        lambda c: events.append(("disconn", _conn_repr(c)))
    )
    scene.node_created.connect(lambda n: events.append(("node", n.model.name)))

    a = scene.create_node(TraceAttrModel)
    b = scene.create_node(TraceAttrModel)
    s = scene.create_node(SubtractModel)

    print(f"node ids: a={a.id} b={b.id} s={s.id}")
    print(f"a num_ports: {a.model.num_ports}")
    print(f"s num_ports: {s.model.num_ports}")
    print(f"s port_caption inputs: {s.model.port_caption['input']}")
    print(f"plugin metadata on a: {a.model.plugin_id} v{a.model.plugin_version}")

    # Wire: a.out -> s.a ; b.out -> s.b
    scene.create_connection(a[PortType.output][0], s[PortType.input][0])
    scene.create_connection(b[PortType.output][0], s[PortType.input][1])

    # Print incoming edges of subtract
    print("\nincoming edges of subtract:")
    for port_idx, port in s[PortType.input].items():
        for conn in port.connections:
            other = conn.get_node(PortType.output)
            print(f"  s.input[{port_idx}] <- {other.model.name}.out")

    # Disconnect via scene API (BEFORE the cycle attempt — lib may leave dangling state).
    print("\n-- delete an edge --")
    target = next(iter(s[PortType.input][0].connections))
    scene.delete_connection(target)
    print(f"after delete, s.input[0] connections: "
          f"{[c.get_node(PortType.output).model.name for c in s[PortType.input][0].connections]}")

    # Cycle attempt: wire s.out -> a.input[0]. b -> s -> ... wait s no longer has a.
    # Re-wire first.
    scene.create_connection(a[PortType.output][0], s[PortType.input][0])
    print("\n-- cycle attempt --")
    try:
        scene.create_connection(s[PortType.output][0], a[PortType.input][0])
        print("cycle wire SUCCEEDED — lib has no built-in cycle detection.")
    except Exception as e:
        print(f"cycle blocked: {type(e).__name__}: {e}")
    print(f"a.input[0] now connected to: "
          f"{[c.get_node(PortType.output).model.name for c in a[PortType.input][0].connections]}")

    print("\nevents log:")
    for e in events:
        print(f"  {e}")

    return 0


def _conn_repr(c) -> str:
    src = c.get_node(PortType.output)
    dst = c.get_node(PortType.input)
    src_idx = c.get_port_index(PortType.output)
    dst_idx = c.get_port_index(PortType.input)
    return f"{src.model.name}.out[{src_idx}] -> {dst.model.name}.in[{dst_idx}]"


if __name__ == "__main__":
    sys.exit(main())
