"""Tests for collaborative workflow."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from conftest import make_llm_response, mock_acompletion

from openswarm.config.models import AgentConfig, TeamConfig, WorkflowConfig
from openswarm.core.message import Message, MessageType
from openswarm.core.task import Task
from openswarm.core.team import Team
from openswarm.workflow.collaborative import CollaborativeWorkflow


@pytest.fixture
def collab_config() -> TeamConfig:
    return TeamConfig(
        name="collab-team",
        goal="Discuss and decide",
        workflow=WorkflowConfig(type="collaborative", max_rounds=5),
        agents=[
            AgentConfig(
                name="alice",
                role="analyst",
                model="gpt-test",
                host="https://api.test.com",
                api_key="test-key",
                rules=["Analyze thoroughly"],
            ),
            AgentConfig(
                name="bob",
                role="reviewer",
                model="gpt-test",
                host="https://api.test.com",
                api_key="test-key",
                rules=["Review carefully"],
            ),
        ],
    )


@pytest.mark.asyncio
async def test_basic_discussion_and_synthesis(collab_config: TeamConfig):
    """Two agents discuss, moderator synthesizes."""
    team = Team(collab_config)
    workflow = CollaborativeWorkflow()
    task = Task(description="Should we use REST or GraphQL?")
    message_log: list[Message] = []

    responses = [
        # Round 0: alice discusses, bob discusses
        make_llm_response({"action": "discuss", "content": "REST is simpler"}),
        make_llm_response({"action": "discuss", "content": "GraphQL is flexible"}),
        # Round 1: alice discusses, bob discusses
        make_llm_response({"action": "discuss", "content": "REST for this use case"}),
        make_llm_response({"action": "discuss", "content": "I see your point"}),
        # Round 2: alice discusses, bob discusses
        make_llm_response({"action": "discuss", "content": "Let's go REST"}),
        make_llm_response({"action": "discuss", "content": "Agreed on REST"}),
        # Round 3: alice discusses, bob discusses
        make_llm_response({"action": "discuss", "content": "REST final"}),
        make_llm_response({"action": "discuss", "content": "REST final too"}),
        # Synthesis by alice (moderator)
        make_llm_response({"action": "respond", "content": "Consensus: use REST API"}),
    ]

    mock = mock_acompletion(*responses)
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await workflow.execute(task, team, max_rounds=5, message_log=message_log)

    assert "REST" in result
    assert task.result == result


@pytest.mark.asyncio
async def test_early_consensus(collab_config: TeamConfig):
    """All agents agree in round → breaks early, then synthesis."""
    team = Team(collab_config)
    workflow = CollaborativeWorkflow()
    task = Task(description="Quick decision")
    message_log: list[Message] = []

    responses = [
        # Round 0: both discuss first
        make_llm_response({"action": "discuss", "content": "Option A looks good"}),
        make_llm_response({"action": "discuss", "content": "Option A indeed"}),
        # Round 1: both agree
        make_llm_response({"action": "agree", "content": "Option A"}),
        make_llm_response({"action": "agree", "content": "Option A"}),
        # Synthesis
        make_llm_response({"action": "respond", "content": "All agreed on Option A"}),
    ]

    mock = mock_acompletion(*responses)
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await workflow.execute(task, team, max_rounds=5, message_log=message_log)

    assert "Option A" in result
    # Should have used fewer rounds (early exit after round 1)
    agree_msgs = [m for m in message_log if m.type == MessageType.AGREE]
    assert len(agree_msgs) == 2


@pytest.mark.asyncio
async def test_callback_fires(collab_config: TeamConfig):
    """on_message callback fires for every logged message."""
    team = Team(collab_config)
    workflow = CollaborativeWorkflow()
    task = Task(description="Test callback")
    message_log: list[Message] = []
    received: list[Message] = []

    responses = [
        make_llm_response({"action": "agree", "content": "yes"}),
        make_llm_response({"action": "agree", "content": "yes"}),
        make_llm_response({"action": "respond", "content": "done"}),
    ]

    mock = mock_acompletion(*responses)
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        await workflow.execute(
            task, team, max_rounds=2, message_log=message_log, on_message=received.append
        )

    assert len(received) == len(message_log)
    assert len(received) > 0


@pytest.mark.asyncio
async def test_bad_json_treated_as_discuss(collab_config: TeamConfig):
    """Unparseable response treated as discuss."""
    team = Team(collab_config)
    workflow = CollaborativeWorkflow()
    task = Task(description="Bad JSON test")
    message_log: list[Message] = []

    responses = [
        "not valid json at all",  # alice bad json
        make_llm_response({"action": "agree", "content": "ok"}),  # bob agrees
        # Both agree next round (alice recovers)
        make_llm_response({"action": "agree", "content": "ok"}),
        make_llm_response({"action": "agree", "content": "ok"}),
        # Synthesis
        make_llm_response({"action": "respond", "content": "synthesized"}),
    ]

    mock = mock_acompletion(*responses)
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await workflow.execute(task, team, max_rounds=4, message_log=message_log)

    assert result == "synthesized"
    # First alice response should be logged as DISCUSS (fallback)
    discuss_msgs = [m for m in message_log if m.type == MessageType.DISCUSS]
    assert len(discuss_msgs) >= 1


def test_collaborative_min_agents_validation():
    """Collaborative workflow requires at least 2 agents."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="at least 2 agents"):
        TeamConfig(
            name="solo",
            goal="test",
            workflow=WorkflowConfig(type="collaborative"),
            agents=[
                AgentConfig(name="alone", role="dev", model="m", host="h", api_key="k"),
            ],
        )


@pytest.mark.asyncio
async def test_collaborative_skips_unavailable_agent(collab_config: TeamConfig):
    """One unreachable provider must not end the discussion."""
    from openswarm.llm.client import LLMError

    team = Team(collab_config)
    workflow = CollaborativeWorkflow()
    task = Task(description="Pick an option")

    async def flaky(*args, **kwargs):
        raise LLMError("frontend provider down")

    responses = [
        make_llm_response({"action": "discuss", "content": "I like A"}),
        make_llm_response({"action": "respond", "content": "Decision: A"}),
    ]
    mock = mock_acompletion(*responses)
    with (
        patch("openswarm.llm.client.litellm.acompletion", mock),
        patch.object(team.get_agent(team.agent_names[1]), "respond", side_effect=flaky),
    ):
        result = await workflow.execute(task, team, max_rounds=2, message_log=[])

    assert "Decision: A" in result


@pytest.mark.asyncio
async def test_collaborative_keeps_provider_errors_out_of_the_transcript(
    collab_config: TeamConfig,
):
    from openswarm.llm.client import LLMError

    secret = "GATEWAY-STACKTRACE-should-not-be-forwarded"
    team = Team(collab_config)
    workflow = CollaborativeWorkflow()
    task = Task(description="Pick an option")
    message_log: list[Message] = []

    async def flaky(*args, **kwargs):
        raise LLMError(secret)

    responses = [
        make_llm_response({"action": "discuss", "content": "I like A"}),
        make_llm_response({"action": "respond", "content": "Decision: A"}),
    ]
    mock = mock_acompletion(*responses)
    with (
        patch("openswarm.llm.client.litellm.acompletion", mock),
        patch.object(team.get_agent(team.agent_names[1]), "respond", side_effect=flaky),
    ):
        await workflow.execute(task, team, max_rounds=2, message_log=message_log)

    assert all(secret not in m.content for m in message_log)
