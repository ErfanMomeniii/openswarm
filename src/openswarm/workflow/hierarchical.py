"""Hierarchical workflow: lead delegates, reviews, assembles."""

from __future__ import annotations

import json
import logging
import re

from openswarm.core.message import Message, MessageType
from openswarm.core.task import Task
from openswarm.core.team import Team
from openswarm.workflow.base import MessageCallback, ProgressCallback, Workflow

logger = logging.getLogger(__name__)


def _parse_agent_response(raw: str) -> dict:
    """Parse JSON response from agent.

    Handles: bare JSON, markdown code fences, JSON embedded in prose,
    and broken JSON where content has unescaped characters.
    """
    text = raw.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines[1:] if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Extract first JSON object using balanced brace matching
    start = text.find("{")
    if start >= 0:
        brace_depth = 0
        in_string = False
        escape_next = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape_next:
                escape_next = False
                continue
            if ch == "\\":
                escape_next = True
                continue
            if ch == '"' and not escape_next:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                brace_depth += 1
            elif ch == "}":
                brace_depth -= 1
                if brace_depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break

    # Try to extract action field — model may have broken JSON with valid action
    action_match = re.search(r'"action"\s*:\s*"(\w+)"', text)
    if action_match:
        action = action_match.group(1)
        # Extract content between "content": " and the last "
        content_match = re.search(r'"content"\s*:\s*"(.*)', text, re.DOTALL)
        if content_match:
            content = content_match.group(1)
            # Remove trailing "} or similar
            content = re.sub(r'"\s*\}\s*$', "", content)
            return {"action": action, "content": content}

    raise json.JSONDecodeError("No valid JSON found", raw, 0)


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
        # Best partial output seen so far — salvaged if we run out of rounds.
        # Worker deliverables are preferred over lead chatter/delegation text.
        last_work: tuple[str, str] | None = None
        last_any: tuple[str, str] | None = None

        for round_num in range(max_rounds):
            logger.info(f"Round {round_num + 1}/{max_rounds}")

            is_lead = target_agent.name == lead.name
            if on_progress is not None:
                _name = target_agent.name

                def chunk_cb(chunk: str) -> None:
                    on_progress(_name, chunk)

                raw_response = await target_agent.respond_stream(
                    current_msg, is_lead=is_lead, on_chunk=chunk_cb
                )
            else:
                raw_response = await target_agent.respond(current_msg, is_lead=is_lead)

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

        # Max rounds hit — never throw away the work already paid for.
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
