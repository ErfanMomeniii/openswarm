"""Tests for pipeline workflow."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from conftest import mock_acompletion

from openswarm.config.models import AgentConfig, TeamConfig, WorkflowConfig
from openswarm.core.message import Message, MessageType
from openswarm.core.task import Task
from openswarm.core.team import Team
from openswarm.workflow import get_workflow
from openswarm.workflow.pipeline import PipelineWorkflow


@pytest.fixture
def pipeline_config() -> TeamConfig:
    return TeamConfig(
        name="pipe-team",
        goal="Pipeline test",
        workflow=WorkflowConfig(type="pipeline", max_rounds=5),
        agents=[
            AgentConfig(
                name="writer",
                role="writer",
                model="gpt-test",
                host="https://api.test.com",
                api_key="test-key",
            ),
            AgentConfig(
                name="editor",
                role="editor",
                model="gpt-test",
                host="https://api.test.com",
                api_key="test-key",
            ),
        ],
    )


def test_get_workflow_pipeline():
    w = get_workflow("pipeline")
    assert isinstance(w, PipelineWorkflow)


@pytest.mark.asyncio
async def test_two_agent_pipeline(pipeline_config: TeamConfig):
    team = Team(pipeline_config)
    workflow = PipelineWorkflow()
    task = Task(description="Write a story")
    message_log: list[Message] = []

    mock = mock_acompletion(
        "Draft story here",
        "Edited story here",
    )
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await workflow.execute(task, team, max_rounds=5, message_log=message_log)

    assert result == "Edited story here"
    assert len(message_log) == 4  # task+result for each agent


@pytest.mark.asyncio
async def test_three_agent_pipeline():
    config = TeamConfig(
        name="triple",
        goal="Three stage",
        workflow=WorkflowConfig(type="pipeline", max_rounds=5),
        agents=[
            AgentConfig(name="a", role="first", model="m", host="h", api_key="k"),
            AgentConfig(name="b", role="second", model="m", host="h", api_key="k"),
            AgentConfig(name="c", role="third", model="m", host="h", api_key="k"),
        ],
    )
    team = Team(config)
    workflow = PipelineWorkflow()
    task = Task(description="Start")
    message_log: list[Message] = []

    mock = mock_acompletion("step1", "step2", "step3")
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await workflow.execute(task, team, max_rounds=5, message_log=message_log)

    assert result == "step3"
    assert mock.call_count == 3
    assert len(message_log) == 6  # 2 messages per agent


@pytest.mark.asyncio
async def test_pipeline_unwraps_json_protocol(pipeline_config: TeamConfig):
    """Agents answer in the JSON protocol — users must not see the envelope."""
    from conftest import make_llm_response

    team = Team(pipeline_config)
    workflow = PipelineWorkflow()
    task = Task(description="Write a story")
    message_log: list[Message] = []

    mock = mock_acompletion(
        make_llm_response({"action": "result", "content": "draft story"}),
        make_llm_response({"action": "result", "content": "polished story"}),
    )
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await workflow.execute(task, team, max_rounds=5, message_log=message_log)

    assert result == "polished story"
    # The second agent receives the first agent's content, not its JSON envelope.
    second_input = message_log[2]
    assert second_input.content == "draft story"
    assert "action" not in second_input.content


@pytest.mark.asyncio
async def test_pipeline_passes_through_non_json_replies(pipeline_config: TeamConfig):
    """Models that ignore the protocol still work — raw prose flows through."""
    team = Team(pipeline_config)
    workflow = PipelineWorkflow()
    task = Task(description="Write a story")

    mock = mock_acompletion("plain draft", "plain final")
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await workflow.execute(task, team, max_rounds=5, message_log=[])

    assert result == "plain final"


@pytest.mark.asyncio
async def test_pipeline_json_without_content_falls_back(pipeline_config: TeamConfig):
    from conftest import make_llm_response

    team = Team(pipeline_config)
    workflow = PipelineWorkflow()
    task = Task(description="Write a story")

    envelope = make_llm_response({"action": "result"})
    mock = mock_acompletion(envelope, envelope)
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await workflow.execute(task, team, max_rounds=5, message_log=[])

    assert result == envelope


@pytest.mark.asyncio
async def test_pipeline_callback_fires(pipeline_config: TeamConfig):
    team = Team(pipeline_config)
    workflow = PipelineWorkflow()
    task = Task(description="Test callbacks")
    message_log: list[Message] = []
    received: list[Message] = []

    mock = mock_acompletion("out1", "out2")
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        await workflow.execute(
            task, team, max_rounds=5, message_log=message_log, on_message=received.append
        )

    assert len(received) == len(message_log)
    assert received[0].type == MessageType.TASK


@pytest.mark.asyncio
async def test_pipeline_output_flows_through(pipeline_config: TeamConfig):
    """Second agent receives first agent's output as input."""
    team = Team(pipeline_config)
    workflow = PipelineWorkflow()
    task = Task(description="Original input")
    message_log: list[Message] = []

    mock = mock_acompletion("transformed", "final")
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        await workflow.execute(task, team, max_rounds=5, message_log=message_log)

    # Second task message should contain first agent's output
    task_to_editor = [
        m for m in message_log if m.to_agent == "editor" and m.type == MessageType.TASK
    ]
    assert len(task_to_editor) == 1
    assert task_to_editor[0].content == "transformed"


@pytest.mark.asyncio
async def test_pipeline_skips_unavailable_stage(pipeline_config: TeamConfig):
    """A dead provider mid-chain passes the previous output on instead of aborting."""
    from openswarm.llm.client import LLMError

    team = Team(pipeline_config)
    workflow = PipelineWorkflow()
    task = Task(description="Write a story")

    async def flaky(*args, **kwargs):
        raise LLMError("editor provider down")

    mock = mock_acompletion("the draft")
    with (
        patch("openswarm.llm.client.litellm.acompletion", mock),
        patch.object(team.get_agent("editor"), "respond", side_effect=flaky),
    ):
        result = await workflow.execute(task, team, max_rounds=5, message_log=[])

    assert result == "the draft"


@pytest.mark.asyncio
async def test_pipeline_all_stages_failing_raises(pipeline_config: TeamConfig):
    """If nothing ran, the user's own prompt must not come back as the answer."""
    from openswarm.llm.client import LLMError

    team = Team(pipeline_config)
    workflow = PipelineWorkflow()
    task = Task(description="Original task text")

    async def flaky(*args, **kwargs):
        raise LLMError("provider down")

    with (
        patch.object(team.get_agent("writer"), "respond", side_effect=flaky),
        patch.object(team.get_agent("editor"), "respond", side_effect=flaky),
        pytest.raises(LLMError, match="Every agent in the pipeline"),
    ):
        await workflow.execute(task, team, max_rounds=5, message_log=[])


@pytest.mark.asyncio
async def test_pipeline_agents_get_the_pipeline_protocol(pipeline_config: TeamConfig):
    """Pipeline stages must not be offered delegate/review actions that cannot work."""
    from openswarm.core.agent import PIPELINE_PROTOCOL

    team = Team(pipeline_config)
    workflow = PipelineWorkflow()
    task = Task(description="Write a story")
    seen: list[str | None] = []

    async def capture(self, message, is_lead=False, protocol_override=None, **kw):
        seen.append(protocol_override)
        return "draft"

    with patch("openswarm.core.agent.Agent.respond", capture):
        await workflow.execute(task, team, max_rounds=5, message_log=[])

    assert seen and all(p == PIPELINE_PROTOCOL for p in seen)
    # No action a pipeline stage cannot actually perform.
    for forbidden in ('"action": "delegate"', '"action": "review"', '"action": "question"'):
        assert forbidden not in PIPELINE_PROTOCOL
    assert '"action": "result"' in PIPELINE_PROTOCOL
