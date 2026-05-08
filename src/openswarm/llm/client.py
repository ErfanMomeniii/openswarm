"""Thin wrapper around litellm for unified LLM access."""

from __future__ import annotations

import litellm

from openswarm.config.models import AgentConfig


class LLMClient:
    """LLM client that talks to any provider via litellm."""

    def __init__(self, config: AgentConfig) -> None:
        self.model = config.model
        self.api_key = config.api_key
        self.api_base = config.host
        self.max_tokens = config.max_tokens

    async def chat(self, messages: list[dict[str, str]]) -> str:
        """Send messages to LLM, return assistant response text."""
        response = await litellm.acompletion(
            model=self.model,
            messages=messages,
            api_key=self.api_key,
            api_base=self.api_base,
            max_tokens=self.max_tokens,
        )
        return response.choices[0].message.content
