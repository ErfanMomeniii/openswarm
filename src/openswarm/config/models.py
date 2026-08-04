"""Pydantic models for team/agent configuration."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

#: Lives here rather than in openswarm.workflow to keep config validation
#: import-cycle free. The workflow factory asserts it matches.
WORKFLOW_TYPES = ("hierarchical", "pipeline", "collaborative")


class AgentConfig(BaseModel):
    """Configuration for a single agent."""

    name: str
    role: str
    model: str
    host: str
    api_key: str
    max_tokens: int = 4096
    temperature: float = 0.7
    max_history: int = 40
    rules: list[str] = Field(default_factory=list)

    @field_validator("name", "role", "model", "host", "api_key")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v.strip()

    @field_validator("max_history")
    @classmethod
    def max_history_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_history must be >= 1")
        return v

    @field_validator("max_tokens")
    @classmethod
    def max_tokens_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_tokens must be >= 1")
        return v

    @field_validator("temperature")
    @classmethod
    def temperature_range(cls, v: float) -> float:
        if v < 0.0 or v > 2.0:
            raise ValueError("temperature must be between 0.0 and 2.0")
        return v


class WorkflowConfig(BaseModel):
    """Workflow settings within a team config."""

    type: str = "hierarchical"
    lead: str | None = None
    max_rounds: int = 10

    @field_validator("type")
    @classmethod
    def known_type(cls, v: str) -> str:
        if v not in WORKFLOW_TYPES:
            raise ValueError(f"unknown workflow '{v}'. Available: {', '.join(WORKFLOW_TYPES)}")
        return v

    @field_validator("max_rounds")
    @classmethod
    def max_rounds_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_rounds must be >= 1")
        return v


class TeamConfig(BaseModel):
    """Top-level team configuration loaded from YAML."""

    name: str
    goal: str
    workflow: WorkflowConfig
    agents: list[AgentConfig]

    @model_validator(mode="after")
    def validate_agents_present(self) -> TeamConfig:
        if not self.agents:
            raise ValueError("Team requires at least one agent")
        return self

    @model_validator(mode="after")
    def validate_unique_agent_names(self) -> TeamConfig:
        seen: set[str] = set()
        for agent in self.agents:
            if agent.name in seen:
                raise ValueError(f"Duplicate agent name '{agent.name}' — names must be unique")
            seen.add(agent.name)
        return self

    @model_validator(mode="after")
    def validate_lead_exists(self) -> TeamConfig:
        if self.workflow.type == "hierarchical":
            if self.workflow.lead is None:
                raise ValueError("Hierarchical workflow requires a 'lead' agent")
            agent_names = [a.name for a in self.agents]
            if self.workflow.lead not in agent_names:
                raise ValueError(
                    f"Lead agent '{self.workflow.lead}' not found in agents: {agent_names}"
                )
        return self

    @model_validator(mode="after")
    def validate_collaborative_min_agents(self) -> TeamConfig:
        if self.workflow.type == "collaborative" and len(self.agents) < 2:
            raise ValueError("Collaborative workflow requires at least 2 agents")
        return self

    def get_agent(self, name: str) -> AgentConfig:
        for agent in self.agents:
            if agent.name == name:
                return agent
        raise ValueError(f"Agent '{name}' not found in team '{self.name}'")
