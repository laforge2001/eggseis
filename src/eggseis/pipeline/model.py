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
