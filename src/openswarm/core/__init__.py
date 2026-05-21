from openswarm.core.message import Message, MessageType
from openswarm.core.task import Task, TaskStatus
from openswarm.core.agent import Agent
from openswarm.core.team import Team

__all__ = ["Message", "MessageType", "Task", "TaskStatus", "Agent", "Team"]


def __getattr__(name: str):
    """Lazy import for Orchestrator to avoid circular imports."""
    if name == "Orchestrator":
        from openswarm.core.orchestrator import Orchestrator

        return Orchestrator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
