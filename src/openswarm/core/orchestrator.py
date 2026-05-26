"""Orchestrator: manages task flow between agents."""

from __future__ import annotations

import logging

from openswarm.core.message import Message
from openswarm.core.task import Task
from openswarm.core.team import Team
from openswarm.core.usage import RunResult, RunUsage
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
    ) -> RunResult:
        """Execute a task through the workflow and return RunResult with usage."""
        task = Task(description=task_description)
        result = await self.workflow.execute(
            task, self.team, self.max_rounds, self.message_log, on_message, on_progress
        )

        # Drain usage from all agents (so interactive runs don't double-count)
        usage = RunUsage()
        for agent in self.team.agents.values():
            usage.entries.extend(agent.usage_log)
            agent.usage_log.clear()

        return RunResult(result=result, usage=usage)
