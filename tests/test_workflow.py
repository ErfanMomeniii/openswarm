"""Tests for hierarchical workflow."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from openswarm.config.models import TeamConfig
from openswarm.core.message import Message, MessageType
from openswarm.core.task import Task
from openswarm.core.team import Team
from openswarm.workflow import get_workflow
from openswarm.workflow.collaborative import CollaborativeWorkflow
from openswarm.workflow.hierarchical import HierarchicalWorkflow, _parse_agent_response

from conftest import mock_acompletion, make_llm_response


# --- _parse_agent_response ---


def test_parse_raw_json():
    data = {"action": "respond", "content": "hello"}
    result = _parse_agent_response(json.dumps(data))
    assert result == data


def test_parse_json_with_code_fences():
    raw = '```json\n{"action": "respond", "content": "hello"}\n```'
    result = _parse_agent_response(raw)
    assert result == {"action": "respond", "content": "hello"}


def test_parse_json_with_bare_fences():
    raw = '```\n{"action": "result", "content": "ok"}\n```'
    result = _parse_agent_response(raw)
    assert result == {"action": "result", "content": "ok"}


def test_parse_invalid_json():
    with pytest.raises(json.JSONDecodeError):
        _parse_agent_response("not json at all")


# --- get_workflow factory ---


def test_get_workflow_hierarchical():
    w = get_workflow("hierarchical")
    assert isinstance(w, HierarchicalWorkflow)


def test_get_workflow_collaborative():
    w = get_workflow("collaborative")
    assert isinstance(w, CollaborativeWorkflow)


def test_get_workflow_unknown():
    with pytest.raises(ValueError, match="Unknown workflow type"):
        get_workflow("nonexistent")


# --- Full workflow loop ---


@pytest.mark.asyncio
async def test_workflow_delegate_then_respond(team_config: TeamConfig):
    """Lead delegates to worker, worker returns result, lead responds."""
    team = Team(team_config)
    workflow = HierarchicalWorkflow()
    task = Task(description="Build a thing")
    message_log: list[Message] = []

    lead_delegate = make_llm_response(
        {
            "action": "delegate",
            "to": "worker",
            "task": "Write the code",
        }
    )
    worker_result = make_llm_response(
        {
            "action": "result",
            "content": "Here is the code",
        }
    )
    lead_respond = make_llm_response(
        {
            "action": "respond",
            "content": "Task complete. Here is the final code.",
        }
    )

    mock = mock_acompletion(lead_delegate, worker_result, lead_respond)
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await workflow.execute(task, team, max_rounds=10, message_log=message_log)

    assert "Task complete" in result
    assert len(message_log) >= 3  # initial + delegate + result


@pytest.mark.asyncio
async def test_workflow_direct_respond(team_config: TeamConfig):
    """Lead responds immediately without delegating."""
    team = Team(team_config)
    workflow = HierarchicalWorkflow()
    task = Task(description="Simple question")
    message_log: list[Message] = []

    lead_respond = make_llm_response(
        {
            "action": "respond",
            "content": "Direct answer",
        }
    )

    mock = mock_acompletion(lead_respond)
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await workflow.execute(task, team, max_rounds=10, message_log=message_log)

    assert result == "Direct answer"


@pytest.mark.asyncio
async def test_workflow_max_rounds(team_config: TeamConfig):
    """Workflow stops after max rounds."""
    team = Team(team_config)
    workflow = HierarchicalWorkflow()
    task = Task(description="Loop forever")
    message_log: list[Message] = []

    # Lead keeps delegating, worker keeps returning — never a "respond"
    responses = []
    for _ in range(5):
        responses.append(make_llm_response({"action": "delegate", "to": "worker", "task": "more"}))
        responses.append(make_llm_response({"action": "result", "content": "partial"}))

    mock = mock_acompletion(*responses)
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await workflow.execute(task, team, max_rounds=3, message_log=message_log)

    assert "Max rounds" in result


@pytest.mark.asyncio
async def test_workflow_unknown_agent_delegation(team_config: TeamConfig):
    """Lead delegates to nonexistent agent — workflow recovers."""
    team = Team(team_config)
    workflow = HierarchicalWorkflow()
    task = Task(description="Bad delegation")
    message_log: list[Message] = []

    lead_bad_delegate = make_llm_response(
        {
            "action": "delegate",
            "to": "ghost",
            "task": "do stuff",
        }
    )
    lead_respond = make_llm_response(
        {
            "action": "respond",
            "content": "Fixed, here's the answer",
        }
    )

    mock = mock_acompletion(lead_bad_delegate, lead_respond)
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await workflow.execute(task, team, max_rounds=10, message_log=message_log)

    assert "Fixed" in result


# --- Review/revision cycle ---


@pytest.mark.asyncio
async def test_workflow_review_revision_cycle(team_config: TeamConfig):
    """Lead delegates, reviews worker output, worker revises, lead responds."""
    team = Team(team_config)
    workflow = HierarchicalWorkflow()
    task = Task(description="Code with review")
    message_log: list[Message] = []

    responses = [
        make_llm_response({"action": "delegate", "to": "worker", "task": "Write code"}),
        make_llm_response({"action": "result", "content": "first draft"}),
        make_llm_response({"action": "review", "to": "worker", "content": "Fix error handling"}),
        make_llm_response({"action": "revision", "content": "fixed version"}),
        make_llm_response({"action": "respond", "content": "Approved. Final code."}),
    ]

    mock = mock_acompletion(*responses)
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await workflow.execute(task, team, max_rounds=10, message_log=message_log)

    assert result == "Approved. Final code."
    # Check review and revision messages exist in log
    types = [m.type for m in message_log]
    assert MessageType.REVIEW in types
    assert MessageType.REVISION in types


@pytest.mark.asyncio
async def test_workflow_review_unknown_agent(team_config: TeamConfig):
    """Lead tries to review nonexistent agent — recovers."""
    team = Team(team_config)
    workflow = HierarchicalWorkflow()
    task = Task(description="Bad review")
    message_log: list[Message] = []

    responses = [
        make_llm_response({"action": "review", "to": "ghost", "content": "Fix it"}),
        make_llm_response({"action": "respond", "content": "Done anyway"}),
    ]

    mock = mock_acompletion(*responses)
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await workflow.execute(task, team, max_rounds=10, message_log=message_log)

    assert result == "Done anyway"
