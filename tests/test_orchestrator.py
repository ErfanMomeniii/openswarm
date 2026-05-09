"""Tests for Orchestrator."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from openswarm.config.models import TeamConfig
from openswarm.core.orchestrator import Orchestrator
from openswarm.core.team import Team
from openswarm.workflow.hierarchical import HierarchicalWorkflow

from conftest import mock_acompletion, make_llm_response


@pytest.mark.asyncio
async def test_orchestrator_run(team_config: TeamConfig):
    team = Team(team_config)
    workflow = HierarchicalWorkflow()
    orch = Orchestrator(team, workflow)

    lead_respond = make_llm_response(
        {
            "action": "respond",
            "content": "All done",
        }
    )

    mock = mock_acompletion(lead_respond)
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await orch.run("Do the thing")

    assert result == "All done"
    assert len(orch.message_log) >= 1


@pytest.mark.asyncio
async def test_orchestrator_message_log_populated(team_config: TeamConfig):
    team = Team(team_config)
    workflow = HierarchicalWorkflow()
    orch = Orchestrator(team, workflow)

    responses = [
        make_llm_response({"action": "delegate", "to": "worker", "task": "subtask"}),
        make_llm_response({"action": "result", "content": "subtask done"}),
        make_llm_response({"action": "respond", "content": "final"}),
    ]

    mock = mock_acompletion(*responses)
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        await orch.run("Complex task")

    # initial + delegate + result = at least 3 messages
    assert len(orch.message_log) >= 3
