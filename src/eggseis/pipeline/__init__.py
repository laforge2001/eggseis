"""Pipeline data model + executor for chained trace-local plugins."""

from eggseis.pipeline.executor import PipelineExecutor
from eggseis.pipeline.model import SOURCE_ID, Node, Pipeline

__all__ = ["SOURCE_ID", "Node", "Pipeline", "PipelineExecutor"]
