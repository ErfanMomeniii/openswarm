"""Team config discovery — project-local files and the global config directory.

Single source of truth for "where do team configs live". Both the CLI and the
MCP server resolve teams through here so they always see the same set.
"""

from __future__ import annotations

import os
from pathlib import Path

# Well-known project-local config filenames, in priority order.
LOCAL_CONFIG_NAMES = [
    "team.yaml",
    "team.yml",
    "openswarm.yaml",
    "openswarm.yml",
    ".openswarm.yaml",
    ".openswarm.yml",
]

CONFIG_SUFFIXES = (".yaml", ".yml")


class TeamResolutionError(Exception):
    """Raised when a team name cannot be resolved to exactly one config file."""


def get_config_dir() -> Path:
    """Return the OpenSwarm global config directory."""
    return Path(os.environ.get("OPENSWARM_CONFIG_DIR", "~/.openswarm")).expanduser()


def get_teams_dir() -> Path:
    """Return the directory holding global team configs."""
    return get_config_dir() / "teams"


def find_team_configs() -> dict[str, Path]:
    """Discover team YAML files in the global config directory."""
    teams_dir = get_teams_dir()
    if not teams_dir.is_dir():
        return {}
    configs: dict[str, Path] = {}
    for p in sorted(teams_dir.iterdir()):
        if p.suffix in CONFIG_SUFFIXES:
            configs[p.stem] = p
    return configs


def find_local_configs(project_dir: Path | None = None) -> dict[str, Path]:
    """Find team configs in the project directory.

    Looks for well-known filenames and an openswarm/ subdirectory.
    """
    root = project_dir or Path.cwd()
    configs: dict[str, Path] = {}

    for name in LOCAL_CONFIG_NAMES:
        path = root / name
        if path.is_file():
            configs[path.stem] = path

    swarm_dir = root / "openswarm"
    if swarm_dir.is_dir():
        for p in sorted(swarm_dir.iterdir()):
            if p.suffix in CONFIG_SUFFIXES:
                configs[p.stem] = p

    return configs


def find_all_configs(project_dir: Path | None = None) -> dict[str, Path]:
    """Find all team configs — global first, project-local wins on name clash."""
    configs = find_team_configs()
    configs.update(find_local_configs(project_dir))
    return configs


def config_source(path: Path) -> str:
    """Label a config path as "local" or "global"."""
    try:
        return "global" if path.parent.resolve() == get_teams_dir().resolve() else "local"
    except OSError:  # unresolvable path — treat as local
        return "local"


def resolve_team(
    team: str | None = None,
    project_dir: Path | None = None,
    configs: dict[str, Path] | None = None,
) -> tuple[str, Path]:
    """Resolve a team name to its config file.

    With no name, auto-selects when exactly one config is discoverable.
    Raises TeamResolutionError with an actionable message otherwise.
    Pass `configs` to resolve against an already-discovered set.
    """
    if configs is None:
        configs = find_all_configs(project_dir)

    if team:
        if team in configs:
            return team, configs[team]
        raise TeamResolutionError(f"Team '{team}' not found.\n{_available_hint(configs)}")

    if len(configs) == 1:
        return next(iter(configs.items()))

    if not configs:
        raise TeamResolutionError(
            "No team config found.\n"
            "Run 'openswarm init' to create a team.yaml in this project, "
            f"or add one to {get_teams_dir()}."
        )

    names = ", ".join(configs)
    raise TeamResolutionError(
        f"Multiple teams found ({names}). Pick one with --team <name> or --config <path>."
    )


def _available_hint(configs: dict[str, Path]) -> str:
    if not configs:
        return (
            "No teams are configured. Run 'openswarm init' to create one, "
            f"or add a YAML file to {get_teams_dir()}."
        )
    listed = "\n".join(f"  • {name} ({config_source(p)}) — {p}" for name, p in configs.items())
    return f"Available teams:\n{listed}"
