"""Team config discovery utilities."""

from __future__ import annotations

import os
from pathlib import Path


def get_config_dir() -> Path:
    """Return the OpenSwarm config directory."""
    return Path(os.environ.get("OPENSWARM_CONFIG_DIR", "~/.openswarm")).expanduser()


def find_team_configs() -> dict[str, Path]:
    """Discover all team YAML files in the config directory."""
    teams_dir = get_config_dir() / "teams"
    if not teams_dir.exists():
        return {}
    configs: dict[str, Path] = {}
    for p in sorted(teams_dir.iterdir()):
        if p.suffix in (".yaml", ".yml"):
            configs[p.stem] = p
    return configs
