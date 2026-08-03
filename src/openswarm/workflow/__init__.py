from openswarm.config.models import WORKFLOW_TYPES
from openswarm.workflow.base import Workflow
from openswarm.workflow.collaborative import CollaborativeWorkflow
from openswarm.workflow.hierarchical import HierarchicalWorkflow
from openswarm.workflow.pipeline import PipelineWorkflow

__all__ = [
    "WORKFLOWS",
    "CollaborativeWorkflow",
    "HierarchicalWorkflow",
    "PipelineWorkflow",
    "Workflow",
    "get_workflow",
]

WORKFLOWS: dict[str, type[Workflow]] = {
    "hierarchical": HierarchicalWorkflow,
    "pipeline": PipelineWorkflow,
    "collaborative": CollaborativeWorkflow,
}

# Config validation and the factory must agree on what's supported.
assert set(WORKFLOWS) == set(WORKFLOW_TYPES), "WORKFLOWS drifted from config.WORKFLOW_TYPES"


def get_workflow(workflow_type: str) -> Workflow:
    """Factory: return a Workflow instance for the given type string."""
    if workflow_type not in WORKFLOWS:
        raise ValueError(
            f"Unknown workflow type '{workflow_type}'. Available: {', '.join(WORKFLOWS)}"
        )
    return WORKFLOWS[workflow_type]()
