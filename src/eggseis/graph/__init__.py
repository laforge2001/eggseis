"""DAG plugin composition: Graph, Node, Edge, port_hash, executor.

M6 supersedes M5's linear pipeline. A `Graph` is a directed acyclic
collection of `Node`s connected via named-port `Edge`s. The implicit
`Source` node (id = SOURCE_ID) emits raw section reads on three output
ports: `inline`, `xline`, `timeslice`.
"""

from eggseis.graph.executor import GraphExecutor
from eggseis.graph.model import (
    SOURCE_ID,
    SOURCE_PORTS,
    Association,
    CycleError,
    Edge,
    Graph,
    Node,
    OrphanHorizonError,
    OrphanPluginError,
)

__all__ = [
    "SOURCE_ID",
    "SOURCE_PORTS",
    "Association",
    "CycleError",
    "Edge",
    "Graph",
    "GraphExecutor",
    "Node",
    "OrphanHorizonError",
    "OrphanPluginError",
]
