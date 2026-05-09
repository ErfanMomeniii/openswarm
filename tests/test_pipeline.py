"""Tests for pipeline workflow."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from openswarm.config.models import AgentConfig, TeamConfig, WorkflowConfig
from openswarm.core.message import Message, MessageType
from openswarm.core.task import Task
from openswarm.core.team import Team
from openswarm.workflow import get_workflow
from openswarm.workflow.pipeline import PipelineWorkflow

from conftest import mock_acompletion


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
