from openswarm.workflow.base import Workflow
from openswarm.workflow.hierarchical import HierarchicalWorkflow
from openswarm.workflow.pipeline import PipelineWorkflow

__all__ = ["Workflow", "HierarchicalWorkflow", "PipelineWorkflow", "get_workflow"]


def get_workflow(workflow_type: str) -> Workflow:
    """Factory: return a Workflow instance for the given type string."""
    workflows = {
        "hierarchical": HierarchicalWorkflow,
        "pipeline": PipelineWorkflow,
    }
    if workflow_type not in workflows:
        raise ValueError(
            f"Unknown workflow type '{workflow_type}'. Available: {', '.join(workflows)}"
        )
    return workflows[workflow_type]()
