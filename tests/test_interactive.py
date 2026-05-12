"""Tests for interactive REPL and message callback."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from openswarm.config.models import TeamConfig
from openswarm.core.message import Message, MessageType
from openswarm.core.orchestrator import Orchestrator
from openswarm.core.task import Task
from openswarm.core.team import Team
from openswarm.workflow.hierarchical import HierarchicalWorkflow

from conftest import make_llm_response, mock_acompletion


# --- on_message callback ---


@pytest.mark.asyncio
async def test_callback_invoked_on_messages(team_config: TeamConfig):
    """on_message callback fires for every message logged."""
    team = Team(team_config)
    workflow = HierarchicalWorkflow()
    task = Task(description="Test callback")
    message_log: list[Message] = []
    received: list[Message] = []

    def on_msg(msg: Message) -> None:
        received.append(msg)

    responses = [
        make_llm_response({"action": "delegate", "to": "worker", "task": "sub"}),
        make_llm_response({"action": "result", "content": "done"}),
        make_llm_response({"action": "respond", "content": "final"}),
    ]

    mock = mock_acompletion(*responses)
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        await workflow.execute(
            task, team, max_rounds=10, message_log=message_log, on_message=on_msg
        )

    # Callback should receive same messages as message_log
    assert len(received) == len(message_log)
    assert received[0].type == MessageType.TASK


@pytest.mark.asyncio
async def test_callback_none_no_error(team_config: TeamConfig):
    """on_message=None doesn't break anything."""
    team = Team(team_config)
    workflow = HierarchicalWorkflow()
    task = Task(description="No callback")
    message_log: list[Message] = []

    mock = mock_acompletion(make_llm_response({"action": "respond", "content": "ok"}))
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await workflow.execute(
            task, team, max_rounds=10, message_log=message_log, on_message=None
        )

    assert result == "ok"


@pytest.mark.asyncio
async def test_orchestrator_passes_callback(team_config: TeamConfig):
    """Orchestrator.run() forwards on_message to workflow."""
    team = Team(team_config)
    workflow = HierarchicalWorkflow()
    orch = Orchestrator(team, workflow)
    received: list[Message] = []

    mock = mock_acompletion(make_llm_response({"action": "respond", "content": "done"}))
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        await orch.run("test", on_message=received.append)

    assert len(received) >= 1


# --- Slash command dispatch ---


def test_slash_quit(team_config: TeamConfig):
    from openswarm.cli.interactive import _handle_slash_command

    team = Team(team_config)
    orch = Orchestrator(team, HierarchicalWorkflow())
    assert _handle_slash_command("/quit", team, orch) is True


def test_slash_team(team_config: TeamConfig):
    from openswarm.cli.interactive import _handle_slash_command

    team = Team(team_config)
    orch = Orchestrator(team, HierarchicalWorkflow())
    assert _handle_slash_command("/team", team, orch) is False


def test_slash_history_empty(team_config: TeamConfig):
    from openswarm.cli.interactive import _handle_slash_command

    team = Team(team_config)
    orch = Orchestrator(team, HierarchicalWorkflow())
    assert _handle_slash_command("/history", team, orch) is False


def test_slash_clear(team_config: TeamConfig):
    from openswarm.cli.interactive import _handle_slash_command

    team = Team(team_config)
    orch = Orchestrator(team, HierarchicalWorkflow())
    orch.message_log.append(
        Message(from_agent="a", to_agent="b", type=MessageType.TASK, content="x")
    )
    _handle_slash_command("/clear", team, orch)
    assert len(orch.message_log) == 0


def test_slash_clear_resets_agent_histories(team_config: TeamConfig):
    """'/clear' clears agent conversation histories too."""
    from openswarm.cli.interactive import _handle_slash_command

    team = Team(team_config)
    orch = Orchestrator(team, HierarchicalWorkflow())

    # Add some history to agents
    for agent in team.agents.values():
        agent.history.append({"role": "user", "content": "old msg"})
        agent.history.append({"role": "assistant", "content": "old reply"})

    _handle_slash_command("/clear", team, orch)

    for agent in team.agents.values():
        assert len(agent.history) == 0


def test_slash_unknown(team_config: TeamConfig):
    from openswarm.cli.interactive import _handle_slash_command

    team = Team(team_config)
    orch = Orchestrator(team, HierarchicalWorkflow())
    assert _handle_slash_command("/nope", team, orch) is False


# --- make_message_printer (now in cli.utils) ---


def test_make_message_printer():
    from openswarm.cli.utils import make_message_printer

    cb = make_message_printer()
    assert cb is not None
    assert callable(cb)
