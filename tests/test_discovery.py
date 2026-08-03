"""Tests for unified team config discovery."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import SAMPLE_YAML

from openswarm.config.discovery import (
    TeamResolutionError,
    config_source,
    find_all_configs,
    find_local_configs,
    find_team_configs,
    get_teams_dir,
    resolve_team,
)


def test_local_config_names_discovered(isolated: Path):
    (isolated / "team.yaml").write_text(SAMPLE_YAML)
    (isolated / "openswarm.yml").write_text(SAMPLE_YAML)
    configs = find_local_configs(isolated)
    assert set(configs) == {"team", "openswarm"}


def test_local_subdirectory_discovered(isolated: Path):
    (isolated / "openswarm").mkdir()
    (isolated / "openswarm" / "backend.yaml").write_text(SAMPLE_YAML)
    (isolated / "openswarm" / "notes.txt").write_text("ignored")
    assert set(find_local_configs(isolated)) == {"backend"}


def test_global_configs_discovered(isolated: Path):
    teams = get_teams_dir()
    teams.mkdir(parents=True)
    (teams / "backend.yaml").write_text(SAMPLE_YAML)
    assert set(find_team_configs()) == {"backend"}


def test_local_overrides_global_on_name_clash(isolated: Path):
    teams = get_teams_dir()
    teams.mkdir(parents=True)
    (teams / "team.yaml").write_text(SAMPLE_YAML)
    local = isolated / "team.yaml"
    local.write_text(SAMPLE_YAML)

    assert find_all_configs(isolated)["team"] == local


def test_config_source_labels(isolated: Path):
    teams = get_teams_dir()
    teams.mkdir(parents=True)
    global_path = teams / "g.yaml"
    global_path.write_text(SAMPLE_YAML)
    local_path = isolated / "team.yaml"
    local_path.write_text(SAMPLE_YAML)

    assert config_source(global_path) == "global"
    assert config_source(local_path) == "local"


def test_resolve_team_auto_selects_single(isolated: Path):
    (isolated / "team.yaml").write_text(SAMPLE_YAML)
    name, path = resolve_team(project_dir=isolated)
    assert name == "team"
    assert path == isolated / "team.yaml"


def test_resolve_team_ambiguous(isolated: Path):
    (isolated / "team.yaml").write_text(SAMPLE_YAML)
    (isolated / "openswarm.yaml").write_text(SAMPLE_YAML)
    with pytest.raises(TeamResolutionError, match="Multiple teams"):
        resolve_team(project_dir=isolated)


def test_resolve_team_none_found_hints_init(isolated: Path):
    with pytest.raises(TeamResolutionError, match="openswarm init"):
        resolve_team(project_dir=isolated)


def test_resolve_team_unknown_name_lists_available(isolated: Path):
    (isolated / "team.yaml").write_text(SAMPLE_YAML)
    with pytest.raises(TeamResolutionError, match="Available teams"):
        resolve_team("ghost", project_dir=isolated)


def test_resolve_team_accepts_explicit_configs():
    name, path = resolve_team("x", configs={"x": Path("/tmp/x.yaml")})
    assert name == "x"
    assert path == Path("/tmp/x.yaml")
