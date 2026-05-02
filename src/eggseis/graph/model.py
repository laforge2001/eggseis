"""Graph data model: Graph, Node, Edge + port_hash math + undo/redo + serialise.

A `Graph` is a DAG of plugin `Node`s connected via `Edge`s. The implicit
`Source` node (id = SOURCE_ID) emits raw section reads on three output ports:
`inline`, `xline`, `timeslice`. Each non-Source node has N input ports drawn
from `spec.inputs` and a single output port `"out"` in v1.0.

The `port_hash` digest is the cache key chain for M6: it folds the upstream
cone into one blake2b digest per (node_id, port). Disabled single-input nodes
pass parent's hash through unchanged (skip = identity); disabled multi-input
nodes are not allowed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

from eggseis.compute.cache import params_hash
from eggseis.plugin import PluginSpec

SOURCE_ID = "source"
SOURCE_PORTS: tuple[str, ...] = ("inline", "xline", "timeslice")


def read_source_at(volume, port: str, index: int):
    """Read the implicit Source node's output for the given port."""
    if port == "inline":
        return volume.read_inline(index)
    if port == "xline":
        return volume.read_xline(index)
    if port == "timeslice":
        return volume.read_timeslice(index)
    raise ValueError(f"unknown source port {port!r}")


class CycleError(ValueError):
    """Raised when adding an edge would introduce a cycle."""


class OrphanPluginError(KeyError):
    """Raised by `Graph.from_dict` when a plugin id is missing from the registry."""


class OrphanHorizonError(KeyError):
    """Raised by Graph.from_dict when a horizon name is missing from the registry."""


@dataclass(frozen=True)
class Association:
    """Dashed-reference link from a horizon node to its bound Source.

    v1.0 has only the implicit Source so source_node_id defaults to SOURCE_ID.
    Multi-source graphs (M7+) will let a single project carry multiple Sources;
    each horizon associates with exactly one of them.
    """

    horizon_node_id: str
    source_node_id: str = SOURCE_ID


@dataclass(frozen=True)
class Edge:
    src_node_id: str
    src_port: str
    dst_node_id: str
    dst_port: str


@dataclass
class Node:
    spec: PluginSpec | None
    params: BaseModel | None = None
    enabled: bool = True
    pos: tuple[float, float] = (0.0, 0.0)
    node_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    kind: Literal["plugin", "horizon"] = "plugin"
    horizon_name: str | None = None

    def __post_init__(self) -> None:
        if self.kind == "plugin":
            if self.spec is None:
                raise ValueError("plugin nodes require a spec")
            if self.horizon_name is not None:
                raise ValueError("plugin nodes must not set horizon_name")
        elif self.kind == "horizon":
            if self.horizon_name is None:
                raise ValueError("horizon nodes require horizon_name")
            if self.spec is not None or self.params is not None:
                raise ValueError("horizon nodes must not set spec or params")
        else:
            raise ValueError(f"unknown Node kind {self.kind!r}")


@dataclass
class Graph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    tap_port: tuple[str, str] = (SOURCE_ID, "inline")
    associations: list[Association] = field(default_factory=list)
    pinned_overlays: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self._undo: list[tuple] = []
        self._redo: list[tuple] = []
        self._replaying = False

    # --- topology mutators ------------------------------------------------

    def add_node(self, node: Node) -> None:
        if node.node_id == SOURCE_ID:
            raise ValueError(f"node_id {SOURCE_ID!r} is reserved for the implicit Source")
        if node.node_id in self.nodes:
            raise ValueError(f"node_id {node.node_id!r} already in graph")
        if len(node.spec.inputs) != 1 and not node.enabled:
            raise ValueError("multi-input nodes cannot be created disabled")
        self.nodes[node.node_id] = node
        self._record(("remove_node", node.node_id))

    def add_horizon_node(
        self,
        horizon_name: str,
        *,
        pos: tuple[float, float] = (0.0, 0.0),
    ) -> str:
        node = Node(
            spec=None,
            params=None,
            kind="horizon",
            horizon_name=horizon_name,
            pos=pos,
        )
        self.nodes[node.node_id] = node
        self.associations.append(
            Association(horizon_node_id=node.node_id, source_node_id=SOURCE_ID)
        )
        self.pinned_overlays.add(node.node_id)
        return node.node_id

    def pin_overlay(self, node_id: str) -> None:
        node = self.nodes[node_id]
        if node.kind != "horizon":
            raise ValueError(
                f"pin_overlay: node {node_id!r} kind={node.kind!r} (expected horizon)"
            )
        self.pinned_overlays.add(node_id)

    def unpin_overlay(self, node_id: str) -> None:
        self.pinned_overlays.discard(node_id)

    def remove_node(self, node_id: str) -> None:
        if node_id == SOURCE_ID:
            raise ValueError("cannot remove implicit Source node")
        node = self.nodes.pop(node_id)
        removed_edges = [e for e in self.edges if node_id in (e.src_node_id, e.dst_node_id)]
        self.edges = [e for e in self.edges if e not in removed_edges]
        if self.tap_port[0] == node_id:
            self.tap_port = (SOURCE_ID, "inline")
        self.associations = [
            a for a in self.associations
            if a.horizon_node_id != node_id and a.source_node_id != node_id
        ]
        self.pinned_overlays.discard(node_id)
        self._record(("add_node_full", node, list(removed_edges), self.tap_port))

    def connect(self, edge: Edge) -> None:
        self._validate_edge(edge)
        if self.has_cycle_if_added(edge):
            raise CycleError(
                f"edge {edge.src_node_id}.{edge.src_port} -> "
                f"{edge.dst_node_id}.{edge.dst_port} would create a cycle"
            )
        # Replace any existing edge into the same (dst_node_id, dst_port).
        existing = [
            e for e in self.edges
            if e.dst_node_id == edge.dst_node_id and e.dst_port == edge.dst_port
        ]
        for e in existing:
            self.edges.remove(e)
        self.edges.append(edge)
        self._record(("disconnect_full", edge, existing))

    def disconnect(self, edge: Edge) -> None:
        if edge not in self.edges:
            raise KeyError(f"edge {edge} not present")
        self.edges.remove(edge)
        self._record(("connect_raw", edge))

    def set_params(self, node_id: str, params: BaseModel) -> None:
        node = self.nodes[node_id]
        prev = node.params
        node.params = params
        self._record(("set_params", node_id, prev))

    def set_enabled(self, node_id: str, on: bool) -> None:
        node = self.nodes[node_id]
        if not on and len(node.spec.inputs) != 1:
            raise ValueError(
                f"cannot disable multi-input node {node.spec.name!r} "
                f"(has {len(node.spec.inputs)} input ports); remove instead"
            )
        prev = node.enabled
        node.enabled = on
        self._record(("set_enabled", node_id, prev))

    def set_tap(self, node_id: str, port: str = "out") -> None:
        if node_id == SOURCE_ID:
            if port not in SOURCE_PORTS:
                raise ValueError(f"Source has no output port {port!r}")
        elif node_id not in self.nodes:
            raise KeyError(node_id)
        elif port != "out":
            raise ValueError(f"v1.0 plugin nodes only have 'out' port, got {port!r}")
        prev = self.tap_port
        self.tap_port = (node_id, port)
        self._record(("set_tap", prev))

    def _validate_edge(self, edge: Edge) -> None:
        if edge.src_node_id == SOURCE_ID:
            if edge.src_port not in SOURCE_PORTS:
                raise ValueError(f"Source has no output port {edge.src_port!r}")
        else:
            if edge.src_node_id not in self.nodes:
                raise KeyError(f"src node {edge.src_node_id!r} not in graph")
            if edge.src_port != "out":
                raise ValueError("plugin nodes only have 'out' output port")
        if edge.dst_node_id == SOURCE_ID:
            raise ValueError("Source has no input ports")
        if edge.dst_node_id not in self.nodes:
            raise KeyError(f"dst node {edge.dst_node_id!r} not in graph")
        dst = self.nodes[edge.dst_node_id]
        if edge.dst_port not in dst.spec.inputs:
            raise ValueError(
                f"node {dst.spec.name!r} has no input port {edge.dst_port!r}; "
                f"valid: {dst.spec.inputs}"
            )

    # --- queries ----------------------------------------------------------

    def incoming_edges(self, node_id: str) -> dict[str, Edge]:
        return {e.dst_port: e for e in self.edges if e.dst_node_id == node_id}

    def has_cycle_if_added(self, edge: Edge) -> bool:
        # DFS from edge.dst_node_id following outgoing edges. If we reach
        # edge.src_node_id, a cycle would form.
        if edge.src_node_id == SOURCE_ID:
            return False  # Source has no incoming edges; can't cycle.
        target = edge.src_node_id
        stack = [edge.dst_node_id]
        seen: set[str] = set()
        while stack:
            cur = stack.pop()
            if cur == target:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            for e in self.edges:
                if e.src_node_id == cur:
                    stack.append(e.dst_node_id)
        return False

    def upstream_cone(self, node_id: str, port: str) -> list[str]:
        """Topo-ordered list of node ids whose output reaches (node_id, port).

        Includes (node_id) itself. Includes SOURCE_ID iff reached. Disabled
        single-input nodes are kept in the order but their identity-skip is
        handled by `port_hash`.
        """
        # Reverse-BFS to collect the cone, then topo-sort.
        cone: set[str] = set()
        stack = [node_id]
        while stack:
            cur = stack.pop()
            if cur in cone:
                continue
            cone.add(cur)
            if cur == SOURCE_ID:
                continue
            for e in self.edges:
                if e.dst_node_id == cur:
                    stack.append(e.src_node_id)
        # Topo sort within the cone.
        return self._topo_sort(cone)

    def _topo_sort(self, ids: set[str]) -> list[str]:
        in_degree: dict[str, int] = {nid: 0 for nid in ids}
        for e in self.edges:
            if e.src_node_id in ids and e.dst_node_id in ids:
                in_degree[e.dst_node_id] += 1
        ready = [nid for nid, d in in_degree.items() if d == 0]
        ready.sort()  # determinism
        out: list[str] = []
        while ready:
            cur = ready.pop(0)
            out.append(cur)
            for e in self.edges:
                if e.src_node_id == cur and e.dst_node_id in ids:
                    in_degree[e.dst_node_id] -= 1
                    if in_degree[e.dst_node_id] == 0:
                        ready.append(e.dst_node_id)
                        ready.sort()
        if len(out) != len(ids):
            raise CycleError("graph has a cycle (should never happen — connect() blocks)")
        return out

    # --- hashing ----------------------------------------------------------

    def port_hash(
        self, node_id: str, port: str, volume_version: tuple, axis: str
    ) -> str:
        """blake2b digest of the upstream cone of (node_id, port).

        Source ports: hash(volume_version || axis || port). Other nodes: fold
        plugin_id + version + params_hash + sorted upstream input port hashes.
        Disabled single-input nodes pass parent's hash through unchanged.
        """
        if node_id == SOURCE_ID:
            if port not in SOURCE_PORTS:
                raise ValueError(f"Source has no port {port!r}")
            blob = json.dumps(
                {"volume_version": list(volume_version), "axis": axis, "port": port},
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
            return hashlib.blake2b(blob, digest_size=16).hexdigest()

        node = self.nodes[node_id]
        incoming = self.incoming_edges(node_id)

        # Disabled single-input node: pass parent's hash through.
        if not node.enabled:
            assert len(node.spec.inputs) == 1, "multi-input cannot be disabled"
            parent_edge = incoming.get(node.spec.inputs[0])
            if parent_edge is None:
                raise ValueError(
                    f"disabled node {node.spec.name!r} has no incoming edge "
                    f"on port {node.spec.inputs[0]!r}; cannot compute identity-hash"
                )
            return self.port_hash(
                parent_edge.src_node_id, parent_edge.src_port, volume_version, axis
            )

        input_hashes: list[str] = []
        for input_port in node.spec.inputs:
            edge = incoming.get(input_port)
            if edge is None:
                raise ValueError(
                    f"node {node.spec.name!r} input port {input_port!r} is unconnected"
                )
            input_hashes.append(
                self.port_hash(edge.src_node_id, edge.src_port, volume_version, axis)
            )

        payload = {
            "plugin_id": node.spec.id,
            "version": node.spec.version,
            "params_hash": params_hash(node.params.model_dump()),
            "inputs": sorted(input_hashes),
            "port": port,
        }
        blob = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        return hashlib.blake2b(blob, digest_size=16).hexdigest()

    def deterministic_through(self, node_id: str, port: str) -> bool:
        if node_id == SOURCE_ID:
            return True
        cone = self.upstream_cone(node_id, port)
        for nid in cone:
            if nid == SOURCE_ID:
                continue
            node = self.nodes[nid]
            if node.enabled and not node.spec.deterministic:
                return False
        return True

    # --- undo / redo ------------------------------------------------------

    def _record(self, op: tuple) -> None:
        if self._replaying:
            return
        self._undo.append(op)
        if len(self._undo) > 20:
            self._undo.pop(0)
        self._redo.clear()

    def undo(self) -> None:
        if not self._undo:
            return
        op = self._undo.pop()
        forward = self._snapshot()
        self._replaying = True
        try:
            self._apply_inverse(op)
        finally:
            self._replaying = False
        self._redo.append(("snapshot", forward))

    def redo(self) -> None:
        if not self._redo:
            return
        op = self._redo.pop()
        if op[0] == "snapshot":
            backward = self._snapshot()
            self._replaying = True
            try:
                self._restore(op[1])
            finally:
                self._replaying = False
            self._undo.append(("snapshot", backward))

    def _snapshot(self) -> dict:
        return {
            "nodes": {nid: copy.copy(n) for nid, n in self.nodes.items()},
            "edges": list(self.edges),
            "tap_port": self.tap_port,
        }

    def _restore(self, snap: dict) -> None:
        self.nodes = {nid: copy.copy(n) for nid, n in snap["nodes"].items()}
        self.edges = list(snap["edges"])
        self.tap_port = snap["tap_port"]

    def _apply_inverse(self, op: tuple) -> None:
        kind = op[0]
        if kind == "remove_node":
            del self.nodes[op[1]]
            self.edges = [
                e for e in self.edges
                if e.src_node_id != op[1] and e.dst_node_id != op[1]
            ]
        elif kind == "add_node_full":
            node, edges, tap = op[1], op[2], op[3]
            self.nodes[node.node_id] = copy.copy(node)
            for e in edges:
                self.edges.append(e)
            self.tap_port = tap
        elif kind == "disconnect_full":
            edge, prior = op[1], op[2]
            if edge in self.edges:
                self.edges.remove(edge)
            for e in prior:
                self.edges.append(e)
        elif kind == "connect_raw":
            self.edges.append(op[1])
        elif kind == "set_params":
            self.nodes[op[1]].params = op[2]
        elif kind == "set_enabled":
            self.nodes[op[1]].enabled = op[2]
        elif kind == "set_tap":
            self.tap_port = op[1]
        else:
            raise AssertionError(f"unknown undo op: {kind}")

    # --- serialisation ----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [
                {
                    "node_id": n.node_id,
                    "plugin_id": n.spec.id,
                    "plugin_version": n.spec.version,
                    "params": n.params.model_dump(),
                    "enabled": n.enabled,
                    "pos": list(n.pos),
                }
                for n in self.nodes.values()
            ],
            "edges": [
                {
                    "src_node_id": e.src_node_id,
                    "src_port": e.src_port,
                    "dst_node_id": e.dst_node_id,
                    "dst_port": e.dst_port,
                }
                for e in self.edges
            ],
            "tap_port": list(self.tap_port),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any], registry: dict[str, PluginSpec]) -> Graph:
        g = cls()
        for node_dict in d["nodes"]:
            plugin_id = node_dict["plugin_id"]
            spec = registry.get(plugin_id)
            if spec is None:
                raise OrphanPluginError(plugin_id)
            params = spec.param_model(**node_dict["params"])
            node = Node(
                spec=spec,
                params=params,
                enabled=node_dict.get("enabled", True),
                pos=tuple(node_dict.get("pos", (0.0, 0.0))),
                node_id=node_dict["node_id"],
            )
            g.nodes[node.node_id] = node
        for edge_dict in d["edges"]:
            g.edges.append(
                Edge(
                    src_node_id=edge_dict["src_node_id"],
                    src_port=edge_dict["src_port"],
                    dst_node_id=edge_dict["dst_node_id"],
                    dst_port=edge_dict["dst_port"],
                )
            )
        g.tap_port = tuple(d.get("tap_port", (SOURCE_ID, "inline")))
        # Skip undo recording for the load path.
        g._undo.clear()
        g._redo.clear()
        return g
