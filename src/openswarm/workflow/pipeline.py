"""Pipeline workflow: sequential agent chain."""

from __future__ import annotations

import logging

from openswarm.core.message import Message, MessageType
from openswarm.core.task import Task
from openswarm.core.team import Team
from openswarm.workflow.base import MessageCallback, ProgressCallback, Workflow

logger = logging.getLogger(__name__)


class PipelineWorkflow(Workflow):
    """Sequential chain — each agent gets previous agent's output as input."""

    async def execute(
        self,
        task: Task,
        team: Team,
        max_rounds: int,
        message_log: list[Message],
        on_message: MessageCallback | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> str:
        def _log(msg: Message) -> None:
            message_log.append(msg)
            if on_message is not None:
                on_message(msg)

        agent_names = team.agent_names
        if not agent_names:
            task.complete("No agents in team.")
            return "No agents in team."

        current_input = task.description

        for i, agent_name in enumerate(agent_names):
            agent = team.get_agent(agent_name)
            from_name = agent_names[i - 1] if i > 0 else "user"

            input_msg = Message(
                from_agent=from_name,
                to_agent=agent_name,
                type=MessageType.TASK,
                content=current_input,
            )
            _log(input_msg)

            logger.info(f"Pipeline step {i + 1}/{len(agent_names)}: {agent_name}")
            if on_progress is not None:
                _name = agent_name

                def chunk_cb(chunk: str) -> None:
                    on_progress(_name, chunk)

                response_text = await agent.respond_stream(input_msg, on_chunk=chunk_cb)
            else:
                response_text = await agent.respond(input_msg)

            result_msg = Message(
                from_agent=agent_name,
                to_agent=agent_names[i + 1] if i + 1 < len(agent_names) else "user",
                type=MessageType.RESULT,
                content=response_text,
            )
            _log(result_msg)

            current_input = response_text

        task.complete(current_input)
        return current_input
