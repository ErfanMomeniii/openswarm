"""Shared fixtures for OpenSwarm tests."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from openswarm.config.models import AgentConfig, TeamConfig, WorkflowConfig
from openswarm.core.team import Team


SAMPLE_YAML = textwrap.dedent("""\
    team:
      name: "test-team"
      goal: "Test goal"
      workflow: hierarchical
      lead: "lead"
      max_rounds: 5

    agents:
      - name: "lead"
        role: senior
        model: gpt-test
        host: https://api.test.com
        api_key: test-key
        max_tokens: 100
        rules:
          - "Lead rule one"
          - "Lead rule two"

      - name: "worker"
        role: junior
        model: gpt-test-cheap
        host: https://api.test.com
        api_key: test-key
        max_tokens: 50
        rules:
          - "Worker rule one"
""")

SAMPLE_YAML_WITH_ENV = textwrap.dedent("""\
    team:
      name: "env-team"
      goal: "Test env"
      workflow: hierarchical
      lead: "lead"

    agents:
      - name: "lead"
        role: senior
        model: gpt-test
        host: https://api.test.com
        api_key: ${TEST_API_KEY}
        rules: []
""")


@pytest.fixture
def sample_yaml_file(tmp_path: Path) -> Path:
    p = tmp_path / "team.yaml"
    p.write_text(SAMPLE_YAML)
    return p


@pytest.fixture
def sample_yaml_with_env(tmp_path: Path) -> Path:
    p = tmp_path / "team_env.yaml"
    p.write_text(SAMPLE_YAML_WITH_ENV)
    return p


@pytest.fixture
def team_config() -> TeamConfig:
    return TeamConfig(
        name="test-team",
        goal="Test goal",
        workflow=WorkflowConfig(type="hierarchical", lead="lead", max_rounds=5),
        agents=[
            AgentConfig(
                name="lead",
                role="senior",
                model="gpt-test",
                host="https://api.test.com",
                api_key="test-key",
                max_tokens=100,
                rules=["Lead rule one", "Lead rule two"],
            ),
            AgentConfig(
                name="worker",
                role="junior",
                model="gpt-test-cheap",
                host="https://api.test.com",
                api_key="test-key",
                max_tokens=50,
                rules=["Worker rule one"],
            ),
        ],
    )


@pytest.fixture
def team(team_config: TeamConfig) -> Team:
    return Team(team_config)


def make_llm_response(data: dict) -> str:
    """Helper: turn a dict into JSON string (as LLM would return)."""
    return json.dumps(data)


def mock_acompletion(*responses: str) -> AsyncMock:
    """Create a mock for litellm.acompletion that returns given responses in order."""
    mock = AsyncMock()
    side_effects = []
    for text in responses:
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = text
        side_effects.append(resp)
    mock.side_effect = side_effects
    return mock
