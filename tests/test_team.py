"""Tests for Team creation and agent lookup."""

from __future__ import annotations

import pytest

from openswarm.config.models import TeamConfig
from openswarm.core.team import Team


def test_team_agents_populated(team_config: TeamConfig):
    t = Team(team_config)
    assert "lead" in t.agents
    assert "worker" in t.agents
    assert len(t.agents) == 2


def test_team_lead(team_config: TeamConfig):
    t = Team(team_config)
    assert t.lead.name == "lead"


def test_get_agent(team_config: TeamConfig):
    t = Team(team_config)
    agent = t.get_agent("worker")
    assert agent.name == "worker"


def test_get_agent_not_found(team_config: TeamConfig):
    t = Team(team_config)
    with pytest.raises(ValueError, match="not found"):
        t.get_agent("ghost")


def test_agent_names(team_config: TeamConfig):
    t = Team(team_config)
    assert set(t.agent_names) == {"lead", "worker"}
