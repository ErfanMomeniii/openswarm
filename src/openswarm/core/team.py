"""Team: collection of agents built from config."""

from __future__ import annotations

from openswarm.config.models import TeamConfig
from openswarm.core.agent import Agent


class Team:
    """A team of agents loaded from configuration."""

    def __init__(self, config: TeamConfig) -> None:
        self.config = config
        self.agents: dict[str, Agent] = {}
        for agent_config in config.agents:
            self.agents[agent_config.name] = Agent(agent_config)

    @property
    def lead(self) -> Agent:
        lead_name = self.config.workflow.lead
        if lead_name is None:
            raise ValueError("No lead agent configured for this workflow")
        if lead_name not in self.agents:
            raise ValueError(f"Lead agent '{lead_name}' not found in team")
        return self.agents[lead_name]

    def get_agent(self, name: str) -> Agent:
        if name not in self.agents:
            raise ValueError(f"Agent '{name}' not found in team")
        return self.agents[name]

    @property
    def agent_names(self) -> list[str]:
        return list(self.agents.keys())
