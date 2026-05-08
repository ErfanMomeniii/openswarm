"""Workflow abstract base."""

from __future__ import annotations

from abc import ABC, abstractmethod

from openswarm.core.message import Message
from openswarm.core.task import Task
from openswarm.core.team import Team


class Workflow(ABC):
    """Base class for workflow strategies."""

    @abstractmethod
    async def execute(
        self,
        task: Task,
        team: Team,
        max_rounds: int,
        message_log: list[Message],
    ) -> str:
        """Run the workflow and return the final result string."""
        ...
