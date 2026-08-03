"""Tests for Orchestrator."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from conftest import make_llm_response, mock_acompletion

from openswarm.config.models import TeamConfig
from openswarm.core.orchestrator import Orchestrator
from openswarm.core.team import Team
from openswarm.core.usage import RunResult
from openswarm.workflow.hierarchical import HierarchicalWorkflow


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
        run_result = await orch.run("Do the thing")

    assert isinstance(run_result, RunResult)
    assert run_result.result == "All done"
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
        run_result = await orch.run("Complex task")

    # initial + delegate + result = at least 3 messages
    assert len(orch.message_log) >= 3
    # Verify usage data was collected
    assert run_result.usage.total_tokens > 0
    assert len(run_result.usage.entries) > 0


@pytest.mark.asyncio
async def test_orchestrator_drains_usage_between_runs(team_config: TeamConfig):
    """Usage logs are drained after each run, so interactive mode doesn't double-count."""
    team = Team(team_config)
    workflow = HierarchicalWorkflow()
    orch = Orchestrator(team, workflow)

    respond = make_llm_response({"action": "respond", "content": "done"})

    # First run
    mock = mock_acompletion(respond)
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result1 = await orch.run("Task one")
    tokens1 = result1.usage.total_tokens

    # Second run — should NOT include first run's tokens
    mock = mock_acompletion(respond)
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result2 = await orch.run("Task two")
    tokens2 = result2.usage.total_tokens

    assert tokens1 == tokens2  # same mock, same token count
    assert tokens1 > 0
