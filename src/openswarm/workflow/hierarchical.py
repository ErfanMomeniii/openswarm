"""Hierarchical workflow: lead delegates, reviews, assembles."""

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

# Kept as a module-level alias: collaborative and existing callers import this name.
_parse_agent_response = parse_agent_response


class HierarchicalWorkflow(Workflow):
    """Lead agent receives task, delegates to workers, reviews results."""

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

        lead = team.lead
        available_agents = [n for n in team.agent_names if n != lead.name]

        # Initial message to lead
        initial_msg = Message(
            from_agent="user",
            to_agent=lead.name,
            type=MessageType.TASK,
            content=f"{task.description}\n\nAvailable team members: {', '.join(available_agents)}",
        )
        _log(initial_msg)

        current_msg = initial_msg
        target_agent = lead
        # Salvaged if we run out of rounds; deliverables beat lead chatter.
        last_work: tuple[str, str] | None = None
        last_any: tuple[str, str] | None = None

        for round_num in range(max_rounds):
            logger.info(f"Round {round_num + 1}/{max_rounds}")

            is_lead = target_agent.name == lead.name
            try:
                if on_progress is not None:
                    raw_response = await target_agent.respond_stream(
                        current_msg,
                        is_lead=is_lead,
                        on_chunk=make_chunk_callback(on_progress, target_agent.name),
                    )
                else:
                    raw_response = await target_agent.respond(current_msg, is_lead=is_lead)
            except LLMError as e:
                # Without the lead there is nobody to route around the failure.
                if is_lead:
                    raise
                logger.warning(f"Agent '{target_agent.name}' unavailable: {e}")
                # Error text is untrusted and unbounded: logged, never forwarded.
                failure_msg = Message(
                    from_agent="system",
                    to_agent=lead.name,
                    type=MessageType.RESULT,
                    content=(
                        f"Error: agent '{target_agent.name}' is unavailable and cannot be "
                        "reached. Delegate to another agent or complete the task yourself."
                    ),
                )
                _log(failure_msg)
                current_msg = failure_msg
                target_agent = lead
                continue

            logger.debug(f"Agent '{target_agent.name}' response: {raw_response}")

            try:
                parsed = _parse_agent_response(raw_response)
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to parse response from '{target_agent.name}': {e}")
                # If lead gave unparseable response, treat as final answer
                if is_lead:
                    task.complete(raw_response)
                    return raw_response
                # Worker gave bad response — send back to lead as-is
                result_msg = Message(
                    from_agent=target_agent.name,
                    to_agent=lead.name,
                    type=MessageType.RESULT,
                    content=raw_response,
                )
                _log(result_msg)
                current_msg = result_msg
                target_agent = lead
                continue

            action = parsed.get("action", "")

            candidate = parsed.get("content") or parsed.get("task") or ""
            if isinstance(candidate, str) and candidate.strip():
                last_any = (target_agent.name, candidate)
                if action in ("result", "answer", "revision"):
                    last_work = (target_agent.name, candidate)

            if action == "respond":
                # Lead is done — return final answer
                final_content = parsed.get("content", raw_response)
                task.complete(final_content)
                return final_content

            elif action == "delegate":
                # Lead delegates to worker
                worker_name = parsed.get("to", "")
                subtask_desc = parsed.get("task", "")
                if worker_name not in team.agents:
                    logger.warning(f"Lead tried to delegate to unknown agent '{worker_name}'")
                    error_msg = Message(
                        from_agent="system",
                        to_agent=lead.name,
                        type=MessageType.RESULT,
                        content=f"Error: Agent '{worker_name}' not found. Available: {', '.join(available_agents)}",
                    )
                    _log(error_msg)
                    current_msg = error_msg
                    target_agent = lead
                    continue

                delegate_msg = Message(
                    from_agent=lead.name,
                    to_agent=worker_name,
                    type=MessageType.TASK,
                    content=subtask_desc,
                )
                _log(delegate_msg)
                current_msg = delegate_msg
                target_agent = team.get_agent(worker_name)

            elif action == "question":
                # Lead asks worker a question
                worker_name = parsed.get("to", "")
                question_content = parsed.get("content", "")
                question_msg = Message(
                    from_agent=lead.name,
                    to_agent=worker_name,
                    type=MessageType.QUESTION,
                    content=question_content,
                )
                _log(question_msg)
                current_msg = question_msg
                target_agent = team.get_agent(worker_name)

            elif action == "review":
                # Lead sends review feedback to worker
                worker_name = parsed.get("to", "")
                review_content = parsed.get("content", "")
                if worker_name not in team.agents:
                    logger.warning(f"Lead tried to review unknown agent '{worker_name}'")
                    error_msg = Message(
                        from_agent="system",
                        to_agent=lead.name,
                        type=MessageType.RESULT,
                        content=f"Error: Agent '{worker_name}' not found. Available: {', '.join(available_agents)}",
                    )
                    _log(error_msg)
                    current_msg = error_msg
                    target_agent = lead
                    continue

                review_msg = Message(
                    from_agent=lead.name,
                    to_agent=worker_name,
                    type=MessageType.REVIEW,
                    content=review_content,
                )
                _log(review_msg)
                current_msg = review_msg
                target_agent = team.get_agent(worker_name)

            elif action in ("result", "answer", "revision"):
                # Worker sending result/answer/revision back to lead
                type_map = {
                    "result": MessageType.RESULT,
                    "answer": MessageType.ANSWER,
                    "revision": MessageType.REVISION,
                }
                result_msg = Message(
                    from_agent=target_agent.name,
                    to_agent=lead.name,
                    type=type_map[action],
                    content=parsed.get("content", ""),
                )
                _log(result_msg)
                current_msg = result_msg
                target_agent = lead

            else:
                logger.warning(f"Unknown action '{action}' from '{target_agent.name}'")
                # Send raw back to lead
                fallback_msg = Message(
                    from_agent=target_agent.name,
                    to_agent=lead.name,
                    type=MessageType.RESULT,
                    content=raw_response,
                )
                _log(fallback_msg)
                current_msg = fallback_msg
                target_agent = lead

        # Max rounds hit
        logger.warning(f"Max rounds ({max_rounds}) reached without the lead marking the task done")
        final = f"Max rounds ({max_rounds}) reached — the lead never marked the task done."
        salvaged = last_work or last_any
        if salvaged:
            agent_name, content = salvaged
            final += f"\n\nLast output from '{agent_name}':\n\n{content}"
        else:
            final += " No usable output was produced."
        task.complete(final)
        return final
