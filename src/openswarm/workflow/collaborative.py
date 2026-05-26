"""Collaborative workflow: agents discuss, reach consensus."""

from __future__ import annotations

import logging

from openswarm.core.agent import COLLABORATIVE_PROTOCOL
from openswarm.core.message import Message, MessageType
from openswarm.core.task import Task
from openswarm.core.team import Team
from openswarm.workflow.base import MessageCallback, ProgressCallback, Workflow
from openswarm.workflow.hierarchical import _parse_agent_response

logger = logging.getLogger(__name__)


class CollaborativeWorkflow(Workflow):
    """All agents discuss a task, moderator synthesizes consensus."""

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
        moderator_name = agent_names[0]
        discussion: list[str] = []

        for round_num in range(max_rounds - 1):
            logger.info(f"Discussion round {round_num + 1}/{max_rounds - 1}")
            all_agree = True

            for agent_name in agent_names:
                agent = team.get_agent(agent_name)

                # Build content: task + prior discussion
                content = f"Task: {task.description}"
                if discussion:
                    content += "\n\nDiscussion so far:\n" + "\n".join(discussion)

                input_msg = Message(
                    from_agent="moderator" if round_num > 0 else "user",
                    to_agent=agent_name,
                    type=MessageType.TASK if round_num == 0 else MessageType.DISCUSS,
                    content=content,
                )
                _log(input_msg)

                if on_progress is not None:
                    _name = agent_name

                    def chunk_cb(chunk: str) -> None:
                        on_progress(_name, chunk)

                    raw = await agent.respond_stream(
                        input_msg, protocol_override=COLLABORATIVE_PROTOCOL, on_chunk=chunk_cb
                    )
                else:
                    raw = await agent.respond(input_msg, protocol_override=COLLABORATIVE_PROTOCOL)

                # Parse response
                action = "discuss"
                response_content = raw
                try:
                    parsed = _parse_agent_response(raw)
                    action = parsed.get("action", "discuss")
                    response_content = parsed.get("content", raw)
                except Exception:
                    logger.warning(f"Bad JSON from '{agent_name}', treating as discuss")

                msg_type = MessageType.AGREE if action == "agree" else MessageType.DISCUSS
                result_msg = Message(
                    from_agent=agent_name,
                    to_agent="all",
                    type=msg_type,
                    content=response_content,
                )
                _log(result_msg)
                discussion.append(f"[{agent_name}] ({action}): {response_content}")

                if action != "agree":
                    all_agree = False

            if all_agree:
                logger.info("All agents agree — ending discussion early")
                break

        # Final synthesis by moderator
        moderator = team.get_agent(moderator_name)
        synthesis_content = (
            f"Task: {task.description}\n\n"
            f"Full discussion:\n" + "\n".join(discussion) + "\n\n"
            "Synthesize the discussion into a final answer."
        )
        synthesis_msg = Message(
            from_agent="system",
            to_agent=moderator_name,
            type=MessageType.TASK,
            content=synthesis_content,
        )
        _log(synthesis_msg)

        if on_progress is not None:
            _mod_name = moderator_name

            def mod_chunk_cb(chunk: str) -> None:
                on_progress(_mod_name, chunk)

            raw = await moderator.respond_stream(
                synthesis_msg, protocol_override=COLLABORATIVE_PROTOCOL, on_chunk=mod_chunk_cb
            )
        else:
            raw = await moderator.respond(synthesis_msg, protocol_override=COLLABORATIVE_PROTOCOL)

        # Parse final response
        final_content = raw
        try:
            parsed = _parse_agent_response(raw)
            if parsed.get("action") == "respond":
                final_content = parsed.get("content", raw)
        except Exception:
            pass

        task.complete(final_content)
        return final_content
