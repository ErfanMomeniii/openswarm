"""Load and validate YAML team configuration."""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from pydantic import ValidationError

from openswarm.config.models import AgentConfig, TeamConfig, WorkflowConfig

# ${VAR} or ${VAR:-default}
ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)(?::-([^}]*))?\}")

UNSET_PLACEHOLDER = "<unset:{name}>"


class ConfigError(ValueError):
    """Raised when a config file is malformed or references unset env vars."""


def _substitute_env_vars(value: str, missing: set[str]) -> str:
    """Replace ${VAR} / ${VAR:-default} placeholders, recording unset vars."""

    def replacer(match: re.Match) -> str:
        var_name, default = match.group(1), match.group(2)
        env_value = os.environ.get(var_name)
        if env_value:
            return env_value
        if default is not None:
            return default
        missing.add(var_name)
        return UNSET_PLACEHOLDER.format(name=var_name)

    return ENV_VAR_PATTERN.sub(replacer, value)


def _process(value, missing: set[str]):
    """Recursively substitute env vars in all string values."""
    if isinstance(value, str):
        return _substitute_env_vars(value, missing)
    if isinstance(value, dict):
        return {k: _process(v, missing) for k, v in value.items()}
    if isinstance(value, list):
        return [_process(item, missing) for item in value]
    return value


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    try:
        with open(path) as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {path}: {e}") from e

    if raw is None:
        raise ConfigError(f"Config file is empty: {path}")
    if not isinstance(raw, dict):
        raise ConfigError(f"Config root must be a mapping with 'team:' and 'agents:' keys: {path}")
    return raw


def _build(raw: dict, path: Path) -> TeamConfig:
    team_section = raw.get("team")
    if not isinstance(team_section, dict):
        raise ConfigError(f"Missing top-level 'team:' section in {path}")

    agents_raw = raw.get("agents")
    if not isinstance(agents_raw, list) or not agents_raw:
        raise ConfigError(f"Missing or empty top-level 'agents:' list in {path}")

    for key in ("name", "goal"):
        if not team_section.get(key):
            raise ConfigError(f"team.{key} is required in {path}")

    workflow = WorkflowConfig(
        type=team_section.get("workflow", "hierarchical"),
        lead=team_section.get("lead"),
        max_rounds=team_section.get("max_rounds", 10),
    )

    try:
        agents = [AgentConfig(**agent) for agent in agents_raw]
        return TeamConfig(
            name=team_section["name"],
            goal=team_section["goal"],
            workflow=workflow,
            agents=agents,
        )
    except ValidationError as e:
        raise ConfigError(f"Invalid config in {path}:\n{_format_validation_error(e)}") from e


def _format_validation_error(error: ValidationError) -> str:
    lines = []
    for err in error.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "config"
        lines.append(f"  • {loc}: {err['msg']}")
    return "\n".join(lines)


def inspect_config(path: str | Path) -> tuple[TeamConfig, list[str]]:
    """Load a config without failing on unset env vars.

    Unset ${VAR} references become "<unset:VAR>" placeholders and are returned
    as the second element. Use this for listing/validating configs, never for
    running them.
    """
    path = Path(path)
    missing: set[str] = set()
    raw = _process(_read_yaml(path), missing)
    return _build(raw, path), sorted(missing)


def load_config(path: str | Path) -> TeamConfig:
    """Load a YAML config file and return a validated TeamConfig.

    Raises ConfigError if any referenced environment variable is unset.
    """
    config, missing = inspect_config(path)
    if missing:
        listed = "\n".join(f"  export {name}=..." for name in missing)
        raise ConfigError(
            f"Unset environment variable(s) referenced by {path}: "
            f"{', '.join(missing)}\nSet them before running:\n{listed}"
        )
    return config
