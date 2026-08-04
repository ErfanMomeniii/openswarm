"""Workflow abstract base."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from openswarm.core.message import Message
from openswarm.core.task import Task
from openswarm.core.team import Team

MessageCallback = Callable[[Message], None]
ProgressCallback = Callable[[str, str], None]  # (agent_name, chunk)


def make_chunk_callback(on_progress: ProgressCallback, agent_name: str) -> Callable[[str], None]:
    """Bind an agent name to a progress callback.

    Built outside the loop so the closure captures this agent's name, not
    whatever the loop variable holds when the callback fires.
    """

    def chunk_cb(chunk: str) -> None:
        on_progress(agent_name, chunk)

    return chunk_cb


class Workflow(ABC):
    """Base class for workflow strategies."""

    @abstractmethod
    async def execute(
        self,
        task: Task,
        team: Team,
        max_rounds: int,
        message_log: list[Message],
        on_message: MessageCallback | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> str:
        """Run the workflow and return the final result string."""
        ...
