"""Agent: role + model + rules + message loop."""

from __future__ import annotations

import json
import logging

from openswarm.config.models import AgentConfig
from openswarm.core.message import Message
from openswarm.llm.client import LLMClient

logger = logging.getLogger(__name__)

COMMUNICATION_PROTOCOL = """You communicate using JSON. Always respond with a single JSON object.

As lead agent, respond with one of:
{
  "action": "delegate",
  "to": "<agent_name>",
  "task": "<task description for that agent>"
}

{
  "action": "respond",
  "content": "<your final answer to the user's task>"
}

{
  "action": "question",
  "to": "<agent_name>",
  "content": "<your question>"
}

As a worker agent receiving a task, respond with:
{
  "action": "result",
  "content": "<your work output>"
}

As a worker agent receiving a question, respond with:
{
  "action": "answer",
  "content": "<your answer>"
}

Always respond with valid JSON only. No text outside the JSON object."""


class Agent:
    """An agent with a role, rules, and LLM connection."""

    def __init__(self, config: AgentConfig) -> None:
        self.name = config.name
        self.role = config.role
        self.rules = config.rules
        self.llm = LLMClient(config)
        self.history: list[dict[str, str]] = []

    def _build_system_prompt(self, is_lead: bool = False) -> str:
        parts = [
            f"You are '{self.name}', a {self.role} agent.",
            "",
            "Your rules:",
        ]
        for rule in self.rules:
            parts.append(f"- {rule}")
        parts.append("")
        parts.append(COMMUNICATION_PROTOCOL)
        if is_lead:
            parts.append(
                "\nYou are the lead agent. You receive tasks from the user and can delegate to other agents."
            )
        return "\n".join(parts)

    async def respond(self, message: Message, is_lead: bool = False) -> str:
        """Process incoming message and return raw LLM response."""
        system_prompt = self._build_system_prompt(is_lead=is_lead)

        user_content = f"[{message.type.value}] from {message.from_agent}: {message.content}"
        if message.attachments:
            user_content += f"\n\nAttachments:\n{json.dumps(message.attachments, indent=2)}"

        self.history.append({"role": "user", "content": user_content})

        messages = [{"role": "system", "content": system_prompt}] + self.history

        logger.debug(f"Agent '{self.name}' calling LLM with {len(messages)} messages")
        response_text = await self.llm.chat(messages)

        self.history.append({"role": "assistant", "content": response_text})
        return response_text
