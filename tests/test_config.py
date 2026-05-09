"""Tests for config loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from openswarm.config.loader import load_config


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
