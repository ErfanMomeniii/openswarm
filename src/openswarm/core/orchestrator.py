"""Orchestrator: manages task flow between agents."""

from __future__ import annotations

import logging

from openswarm.core.message import Message
from openswarm.core.task import Task
from openswarm.core.team import Team
from openswarm.workflow.base import MessageCallback, ProgressCallback, Workflow

logger = logging.getLogger(__name__)


class Orchestrator:
    """Receives user task, runs workflow loop until done or max rounds hit."""

    def __init__(self, team: Team, workflow: Workflow) -> None:
        self.team = team
        self.workflow = workflow
        self.max_rounds = team.config.workflow.max_rounds
        self.message_log: list[Message] = []

    async def run(
        self,
        task_description: str,
        on_message: MessageCallback | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> str:
        """Execute a task through the workflow and return the final result."""
        task = Task(description=task_description)
        result = await self.workflow.execute(
            task, self.team, self.max_rounds, self.message_log, on_message, on_progress
        )
        return result
