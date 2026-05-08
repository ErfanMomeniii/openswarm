"""Load and validate YAML team configuration."""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

from openswarm.config.models import AgentConfig, TeamConfig, WorkflowConfig

ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


def _substitute_env_vars(value: str) -> str:
    """Replace ${ENV_VAR} placeholders with environment variable values."""

    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        env_value = os.environ.get(var_name)
        if env_value is None:
            raise ValueError(f"Environment variable '{var_name}' is not set")
        return env_value

    return ENV_VAR_PATTERN.sub(replacer, value)


def _process_dict(data: dict) -> dict:
    """Recursively substitute env vars in all string values."""
    result = {}
    for key, value in data.items():
        if isinstance(value, str):
            result[key] = _substitute_env_vars(value)
        elif isinstance(value, dict):
            result[key] = _process_dict(value)
        elif isinstance(value, list):
            result[key] = [
                _process_dict(item) if isinstance(item, dict) else item for item in value
            ]
        else:
            result[key] = value
    return result


def load_config(path: str | Path) -> TeamConfig:
    """Load a YAML config file and return a validated TeamConfig."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    raw = _process_dict(raw)

    team_section = raw.get("team", {})
    agents_raw = raw.get("agents", [])

    workflow = WorkflowConfig(
        type=team_section.get("workflow", "hierarchical"),
        lead=team_section["lead"],
        max_rounds=team_section.get("max_rounds", 10),
    )

    agents = [AgentConfig(**agent) for agent in agents_raw]

    return TeamConfig(
        name=team_section["name"],
        goal=team_section["goal"],
        workflow=workflow,
        agents=agents,
    )
