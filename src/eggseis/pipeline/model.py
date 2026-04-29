"""Pipeline + Node data model.

A Pipeline is a linear sequence of plugin Nodes plus an implicit Source at
position 0. The user picks a tap (a node id, or `SOURCE_ID`); execution
walks Source → tap and the section viewer paints the tap's output.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from pydantic import BaseModel

from eggseis.plugin import PluginSpec

SOURCE_ID = "source"


@dataclass
class Node:
    spec: PluginSpec
    params: BaseModel
    enabled: bool = True
    node_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class Pipeline:
    nodes: list[Node] = field(default_factory=list)
    tap_node_id: str = SOURCE_ID

    def _index(self, node_id: str) -> int:
        for i, n in enumerate(self.nodes):
            if n.node_id == node_id:
                return i
        raise KeyError(node_id)

    def append(self, node: Node) -> None:
        self.nodes.append(node)

    def remove(self, node_id: str) -> None:
        del self.nodes[self._index(node_id)]
        if self.tap_node_id == node_id:
            self.tap_node_id = SOURCE_ID

    def move(self, node_id: str, new_index: int) -> None:
        """Reposition a node to `new_index`.

        Out-of-bounds indices follow ``list.insert`` semantics (clamped/appended).
        """
        i = self._index(node_id)
        node = self.nodes.pop(i)
        self.nodes.insert(new_index, node)

    def set_enabled(self, node_id: str, on: bool) -> None:
        self.nodes[self._index(node_id)].enabled = on
        if not on and self.tap_node_id == node_id:
            self.set_tap(node_id)  # set_tap handles the upstream shift

    def set_params(self, node_id: str, params: BaseModel) -> None:
        self.nodes[self._index(node_id)].params = params

    def set_tap(self, node_id: str) -> None:
        if node_id == SOURCE_ID:
            self.tap_node_id = SOURCE_ID
            return
        idx = self._index(node_id)
        target = self.nodes[idx]
        if target.enabled:
            self.tap_node_id = node_id
            return
        for i in range(idx - 1, -1, -1):
            if self.nodes[i].enabled:
                self.tap_node_id = self.nodes[i].node_id
                return
        self.tap_node_id = SOURCE_ID

    def nodes_up_to_tap(self) -> list[Node]:
        """Enabled nodes from index 0 through the tap, inclusive.

        If the tap is SOURCE_ID, returns []. Disabled nodes are filtered.
        """
        if self.tap_node_id == SOURCE_ID:
            return []
        tap_idx = self._index(self.tap_node_id)
        return [n for n in self.nodes[: tap_idx + 1] if n.enabled]
