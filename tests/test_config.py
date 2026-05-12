"""Tests for config loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from openswarm.config.loader import load_config
from openswarm.config.models import AgentConfig, TeamConfig, WorkflowConfig


def test_load_valid_yaml(sample_yaml_file: Path):
    config = load_config(sample_yaml_file)
    assert config.name == "test-team"
    assert config.goal == "Test goal"
    assert config.workflow.type == "hierarchical"
    assert config.workflow.lead == "lead"
    assert config.workflow.max_rounds == 5
    assert len(config.agents) == 2
    assert config.agents[0].name == "lead"
    assert config.agents[1].name == "worker"


def test_env_var_substitution(sample_yaml_with_env: Path, monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", "secret-123")
    config = load_config(sample_yaml_with_env)
    assert config.agents[0].api_key == "secret-123"


def test_missing_env_var(sample_yaml_with_env: Path, monkeypatch):
    monkeypatch.delenv("TEST_API_KEY", raising=False)
    with pytest.raises(ValueError, match="TEST_API_KEY"):
        load_config(sample_yaml_with_env)


def test_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/path.yaml")


def test_missing_required_fields(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("team:\n  name: x\n")
    with pytest.raises(Exception):
        load_config(bad)


def test_agent_lookup_on_config(sample_yaml_file: Path):
    config = load_config(sample_yaml_file)
    agent = config.get_agent("lead")
    assert agent.name == "lead"
    with pytest.raises(ValueError, match="not found"):
        config.get_agent("nonexistent")


# --- Config validation ---


def test_lead_must_exist_in_agents():
    with pytest.raises(ValidationError, match="not found in agents"):
        TeamConfig(
            name="bad",
            goal="test",
            workflow=WorkflowConfig(type="hierarchical", lead="ghost"),
            agents=[
                AgentConfig(name="alice", role="dev", model="m", host="h", api_key="k"),
            ],
        )


def test_hierarchical_requires_lead():
    with pytest.raises(ValidationError, match="requires a 'lead'"):
        TeamConfig(
            name="bad",
            goal="test",
            workflow=WorkflowConfig(type="hierarchical"),
            agents=[
                AgentConfig(name="alice", role="dev", model="m", host="h", api_key="k"),
            ],
        )


def test_pipeline_no_lead_required():
    config = TeamConfig(
        name="ok",
        goal="test",
        workflow=WorkflowConfig(type="pipeline"),
        agents=[
            AgentConfig(name="alice", role="dev", model="m", host="h", api_key="k"),
        ],
    )
    assert config.workflow.lead is None


def test_max_tokens_must_be_positive():
    with pytest.raises(ValidationError, match="max_tokens must be >= 1"):
        AgentConfig(name="x", role="x", model="m", host="h", api_key="k", max_tokens=0)


def test_temperature_bounds():
    with pytest.raises(ValidationError, match="temperature must be between"):
        AgentConfig(name="x", role="x", model="m", host="h", api_key="k", temperature=-0.1)
    with pytest.raises(ValidationError, match="temperature must be between"):
        AgentConfig(name="x", role="x", model="m", host="h", api_key="k", temperature=2.1)


def test_temperature_valid_range():
    a = AgentConfig(name="x", role="x", model="m", host="h", api_key="k", temperature=1.5)
    assert a.temperature == 1.5


def test_temperature_default():
    a = AgentConfig(name="x", role="x", model="m", host="h", api_key="k")
    assert a.temperature == 0.7


def test_max_history_default():
    a = AgentConfig(name="x", role="x", model="m", host="h", api_key="k")
    assert a.max_history == 40


def test_max_history_custom():
    a = AgentConfig(name="x", role="x", model="m", host="h", api_key="k", max_history=10)
    assert a.max_history == 10


def test_max_history_must_be_positive():
    with pytest.raises(ValidationError, match="max_history must be >= 1"):
        AgentConfig(name="x", role="x", model="m", host="h", api_key="k", max_history=0)


def test_collaborative_requires_min_agents():
    with pytest.raises(ValidationError, match="at least 2 agents"):
        TeamConfig(
            name="solo",
            goal="test",
            workflow=WorkflowConfig(type="collaborative"),
            agents=[
                AgentConfig(name="alice", role="dev", model="m", host="h", api_key="k"),
            ],
        )


def test_collaborative_no_lead_required():
    config = TeamConfig(
        name="ok",
        goal="test",
        workflow=WorkflowConfig(type="collaborative"),
        agents=[
            AgentConfig(name="alice", role="dev", model="m", host="h", api_key="k"),
            AgentConfig(name="bob", role="dev", model="m", host="h", api_key="k"),
        ],
    )
    assert config.workflow.lead is None
