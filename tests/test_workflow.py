"""Tests for hierarchical workflow."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from conftest import make_llm_response, mock_acompletion, mock_acompletion_stream

from openswarm.config.models import TeamConfig
from openswarm.core.message import Message, MessageType
from openswarm.core.task import Task
from openswarm.core.team import Team
from openswarm.workflow import get_workflow
from openswarm.workflow.collaborative import CollaborativeWorkflow
from openswarm.workflow.hierarchical import HierarchicalWorkflow, _parse_agent_response

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
    # Work already paid for is salvaged instead of discarded.
    assert "partial" in result
    assert task.result == result


@pytest.mark.asyncio
async def test_workflow_max_rounds_without_any_output(team_config: TeamConfig):
    """No usable content anywhere — say so instead of pretending."""
    team = Team(team_config)
    workflow = HierarchicalWorkflow()
    task = Task(description="Loop forever")

    responses = [make_llm_response({"action": "noop"}) for _ in range(4)]
    mock = mock_acompletion(*responses)
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await workflow.execute(task, team, max_rounds=2, message_log=[])

    assert "Max rounds" in result
    assert "No usable output" in result


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


# --- Streaming / on_progress ---


@pytest.mark.asyncio
async def test_workflow_on_progress_fires_chunks(team_config: TeamConfig):
    """on_progress callback receives agent name and chunks during streaming."""
    team = Team(team_config)
    workflow = HierarchicalWorkflow()
    task = Task(description="Stream test")
    message_log: list[Message] = []

    lead_respond = make_llm_response({"action": "respond", "content": "done"})
    mock = mock_acompletion_stream(lead_respond)

    progress_events: list[tuple[str, str]] = []

    def on_progress(agent_name: str, chunk: str) -> None:
        progress_events.append((agent_name, chunk))

    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await workflow.execute(
            task, team, max_rounds=10, message_log=message_log, on_progress=on_progress
        )

    assert result == "done"
    assert len(progress_events) > 0
    # All chunks should be from the lead agent
    assert all(name == "lead" for name, _ in progress_events)
    # Chunks should reconstruct the full response
    reconstructed = "".join(chunk for _, chunk in progress_events)
    assert reconstructed == lead_respond


@pytest.mark.asyncio
async def test_workflow_on_progress_with_delegation(team_config: TeamConfig):
    """on_progress fires for both lead and worker agents."""
    team = Team(team_config)
    workflow = HierarchicalWorkflow()
    task = Task(description="Delegate stream test")
    message_log: list[Message] = []

    lead_delegate = make_llm_response({"action": "delegate", "to": "worker", "task": "Do work"})
    worker_result = make_llm_response({"action": "result", "content": "worker done"})
    lead_respond = make_llm_response({"action": "respond", "content": "all done"})

    mock = mock_acompletion_stream(lead_delegate, worker_result, lead_respond)

    agent_names_seen: set[str] = set()

    def on_progress(agent_name: str, chunk: str) -> None:
        agent_names_seen.add(agent_name)

    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await workflow.execute(
            task, team, max_rounds=10, message_log=message_log, on_progress=on_progress
        )

    assert result == "all done"
    assert "lead" in agent_names_seen
    assert "worker" in agent_names_seen


# --- Provider failures must not kill the whole team ---


@pytest.mark.asyncio
async def test_worker_failure_is_reported_to_lead(team_config: TeamConfig):
    """A worker's provider going down is routed back to the lead, not raised."""
    from openswarm.llm.client import LLMError

    team = Team(team_config)
    workflow = HierarchicalWorkflow()
    task = Task(description="Do the thing")
    message_log: list[Message] = []

    async def flaky(*args, **kwargs):
        raise LLMError("provider exploded")

    responses = [
        make_llm_response({"action": "delegate", "to": "worker", "task": "sub"}),
        make_llm_response({"action": "respond", "content": "handled it myself"}),
    ]
    mock = mock_acompletion(*responses)

    with patch("openswarm.llm.client.litellm.acompletion", mock):
        worker = team.get_agent("worker")
        with patch.object(worker, "respond", side_effect=flaky):
            result = await workflow.execute(task, team, max_rounds=6, message_log=message_log)

    assert result == "handled it myself"
    failures = [m for m in message_log if m.from_agent == "system"]
    assert failures and "unavailable" in failures[0].content


@pytest.mark.asyncio
async def test_lead_failure_still_raises(team_config: TeamConfig):
    """Without the lead there is nothing to route around — surface the error."""
    from openswarm.llm.client import LLMError

    team = Team(team_config)
    workflow = HierarchicalWorkflow()
    task = Task(description="Do the thing")

    async def flaky(*args, **kwargs):
        raise LLMError("lead provider down")

    with (
        patch.object(team.get_agent("lead"), "respond", side_effect=flaky),
        pytest.raises(LLMError, match="lead provider down"),
    ):
        await workflow.execute(task, team, max_rounds=3, message_log=[])


@pytest.mark.asyncio
async def test_provider_error_text_never_reaches_another_prompt(team_config: TeamConfig):
    """Provider error bodies are untrusted and unbounded — log them, don't forward them."""
    from openswarm.llm.client import LLMError

    secret = "PROVIDER-INTERNAL-DETAIL-should-not-be-forwarded"
    team = Team(team_config)
    workflow = HierarchicalWorkflow()
    task = Task(description="Do the thing")
    message_log: list[Message] = []

    async def flaky(*args, **kwargs):
        raise LLMError(secret)

    responses = [
        make_llm_response({"action": "delegate", "to": "worker", "task": "sub"}),
        make_llm_response({"action": "respond", "content": "done"}),
    ]
    mock = mock_acompletion(*responses)
    with (
        patch("openswarm.llm.client.litellm.acompletion", mock),
        patch.object(team.get_agent("worker"), "respond", side_effect=flaky),
    ):
        await workflow.execute(task, team, max_rounds=6, message_log=message_log)

    assert all(secret not in m.content for m in message_log)
    assert all(secret not in turn["content"] for turn in team.get_agent("lead").history)


# --- Regression: escaped newlines must survive the regex fallback ---


def test_regex_fallback_unescapes_newlines():
    """A code block returned via the fallback path must not arrive as one line."""
    raw = '{"action": "respond", "content": "Run `python "x.py"`:\\n\\n```python\\ncode()\\n```"}'
    content = _parse_agent_response(raw)["content"]

    assert "\\n" not in content
    assert content.count("\n") == 4


def test_regex_fallback_unescapes_quotes():
    raw = '{"action": "respond", "content": "say "hi":\\n\\ndef f():\\n    return \\"x\\""}'
    content = _parse_agent_response(raw)["content"]

    assert '\\"' not in content
    assert 'return "x"' in content


def test_strict_json_path_still_unescapes():
    content = _parse_agent_response('{"action": "respond", "content": "a\\nb"}')["content"]
    assert content == "a\nb"
