"""Core domain types.

Agent, Team, and Orchestrator resolve lazily: they pull in the LLM client, which
imports back into this package. Eager imports here break
`from openswarm.llm import LLMClient` as a first import.
"""

from importlib import import_module

from openswarm.core.message import Message, MessageType
from openswarm.core.task import Task, TaskStatus

__all__ = ["Agent", "Message", "MessageType", "Orchestrator", "Task", "TaskStatus", "Team"]

_LAZY_ATTRS = {
    "Agent": ("openswarm.core.agent", "Agent"),
    "Team": ("openswarm.core.team", "Team"),
    "Orchestrator": ("openswarm.core.orchestrator", "Orchestrator"),
}


def __getattr__(name: str):
    if name in _LAZY_ATTRS:
        module_name, attr = _LAZY_ATTRS[name]
        return getattr(import_module(module_name), attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
