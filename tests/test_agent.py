"""Tests for Agent system prompt, respond(), and history trimming."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from openswarm.config.models import AgentConfig
from openswarm.core.agent import COLLABORATIVE_PROTOCOL, Agent
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


def test_system_prompt_contains_review_action(agent: Agent):
    prompt = agent._build_system_prompt()
    assert '"action": "review"' in prompt
    assert '"action": "revision"' in prompt


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


# --- History trimming ---


def test_history_trimming(agent_config: AgentConfig):
    agent = Agent(agent_config, max_history=4)
    # Manually fill history beyond limit
    for i in range(6):
        agent.history.append({"role": "user", "content": f"msg {i}"})
    agent._trim_history()
    assert len(agent.history) == 4
    assert agent.history[0]["content"] == "msg 2"


def test_history_no_trim_under_limit(agent_config: AgentConfig):
    agent = Agent(agent_config, max_history=10)
    agent.history.append({"role": "user", "content": "msg"})
    agent._trim_history()
    assert len(agent.history) == 1


def test_clear_history(agent: Agent):
    agent.history.append({"role": "user", "content": "old"})
    agent.history.append({"role": "assistant", "content": "old reply"})
    agent.clear_history()
    assert len(agent.history) == 0


# --- Protocol override ---


def test_protocol_override_in_system_prompt(agent: Agent):
    prompt = agent._build_system_prompt(protocol_override=COLLABORATIVE_PROTOCOL)
    assert "discuss" in prompt
    assert "agree" in prompt
    assert "delegate" not in prompt


def test_default_protocol_without_override(agent: Agent):
    prompt = agent._build_system_prompt()
    assert "delegate" in prompt
    assert "discuss" not in prompt


# --- Config max_history passthrough ---


def test_config_max_history(agent_config: AgentConfig):
    agent_config_custom = agent_config.model_copy(update={"max_history": 20})
    agent = Agent(agent_config_custom, max_history=agent_config_custom.max_history)
    assert agent.max_history == 20
