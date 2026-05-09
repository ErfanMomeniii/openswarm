"""Tests for Agent system prompt and respond()."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from openswarm.config.models import AgentConfig
from openswarm.core.agent import Agent
from openswarm.core.message import Message, MessageType

from conftest import mock_acompletion


@pytest.fixture
def agent_config() -> AgentConfig:
    return AgentConfig(
        name="tester",
        role="analyst",
        model="gpt-test",
        host="https://api.test.com",
        api_key="test-key",
        rules=["Be thorough", "Check edge cases"],
    )


@pytest.fixture
def agent(agent_config: AgentConfig) -> Agent:
    return Agent(agent_config)


def test_system_prompt_contains_role(agent: Agent):
    prompt = agent._build_system_prompt()
    assert "analyst" in prompt
    assert "tester" in prompt


def test_system_prompt_contains_rules(agent: Agent):
    prompt = agent._build_system_prompt()
    assert "Be thorough" in prompt
    assert "Check edge cases" in prompt


def test_lead_prompt_has_lead_text(agent: Agent):
    prompt = agent._build_system_prompt(is_lead=True)
    assert "lead agent" in prompt.lower()


def test_non_lead_prompt_no_lead_text(agent: Agent):
    prompt = agent._build_system_prompt(is_lead=False)
    assert "you are the lead agent" not in prompt.lower()


@pytest.mark.asyncio
async def test_respond_calls_llm(agent: Agent):
    msg = Message(
        from_agent="user",
        to_agent="tester",
        type=MessageType.TASK,
        content="Analyze this",
    )
    mock = mock_acompletion('{"action": "result", "content": "analysis done"}')
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await agent.respond(msg)

    assert "analysis done" in result
    mock.assert_called_once()
    call_kwargs = mock.call_args
    assert call_kwargs.kwargs["model"] == "gpt-test"


@pytest.mark.asyncio
async def test_respond_appends_history(agent: Agent):
    msg = Message(
        from_agent="user",
        to_agent="tester",
        type=MessageType.TASK,
        content="Do it",
    )
    mock = mock_acompletion('{"action": "result", "content": "done"}')
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        await agent.respond(msg)

    assert len(agent.history) == 2  # user + assistant
    assert agent.history[0]["role"] == "user"
    assert agent.history[1]["role"] == "assistant"
