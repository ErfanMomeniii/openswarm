"""Pipeline workflow: sequential agent chain."""

from __future__ import annotations

import json
import logging

from openswarm.core.message import Message, MessageType
from openswarm.core.task import Task
from openswarm.core.team import Team
from openswarm.llm.client import LLMError
from openswarm.workflow.base import (
    MessageCallback,
    ProgressCallback,
    Workflow,
    make_chunk_callback,
)
from openswarm.workflow.parsing import parse_agent_response

logger = logging.getLogger(__name__)


def _extract_content(raw: str, agent_name: str) -> str:
    """Pull the payload out of an agent's JSON envelope.

    Passing the envelope on would feed the next agent, and the user,
    `{"action": ...}` noise. Prose replies pass through unchanged.
    """
    try:
        parsed = parse_agent_response(raw)
    except (json.JSONDecodeError, KeyError):
        logger.debug(f"Agent '{agent_name}' replied outside the JSON protocol; using raw text")
        return raw

    content = parsed.get("content")
    if isinstance(content, str) and content.strip():
        return content

    logger.warning(f"Agent '{agent_name}' returned JSON without usable content; using raw text")
    return raw


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
        failed_stages: list[str] = []

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
            try:
                if on_progress is not None:
                    raw_response = await agent.respond_stream(
                        input_msg, on_chunk=make_chunk_callback(on_progress, agent_name)
                    )
                else:
                    raw_response = await agent.respond(input_msg)
            except LLMError as e:
                logger.warning(f"Agent '{agent_name}' unavailable, skipping stage: {e}")
                failed_stages.append(agent_name)
                continue

            response_text = _extract_content(raw_response, agent_name)

            result_msg = Message(
                from_agent=agent_name,
                to_agent=agent_names[i + 1] if i + 1 < len(agent_names) else "user",
                type=MessageType.RESULT,
                content=response_text,
            )
            _log(result_msg)

            current_input = response_text

        if len(failed_stages) == len(agent_names):
            # Nothing ran, so current_input is still the user's own task text.
            raise LLMError(
                "Every agent in the pipeline was unavailable: " + ", ".join(failed_stages)
            )

        if failed_stages:
            # Warned, not folded into the result: `-o` output stays clean.
            logger.warning(
                f"Pipeline completed with {len(failed_stages)} skipped stage(s): "
                f"{', '.join(failed_stages)}"
            )

        task.complete(current_input)
        return current_input
