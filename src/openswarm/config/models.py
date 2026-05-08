"""Pydantic models for team/agent configuration."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    """Configuration for a single agent."""

    name: str
    role: str
    model: str
    host: str
    api_key: str
    max_tokens: int = 4096
    rules: list[str] = Field(default_factory=list)


class WorkflowConfig(BaseModel):
    """Workflow settings within a team config."""

    type: str = "hierarchical"
    lead: str
    max_rounds: int = 10


class TeamConfig(BaseModel):
    """Top-level team configuration loaded from YAML."""

    name: str
    goal: str
    workflow: WorkflowConfig
    agents: list[AgentConfig]

    def get_agent(self, name: str) -> AgentConfig:
        for agent in self.agents:
            if agent.name == name:
                return agent
        raise ValueError(f"Agent '{name}' not found in team '{self.name}'")
