"""Tests for MCP server tool functions."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import make_llm_response, mock_acompletion

from openswarm.mcp.server import (
    find_all_configs,
    find_local_configs,
    list_teams,
    run_task,
    run_task_with_config,
    team_info,
)

TEAM_YAML = textwrap.dedent("""\
    team:
      name: "test-team"
      goal: "Test goal"
      workflow: hierarchical
      lead: "lead"
      max_rounds: 3

    agents:
      - name: "lead"
        role: senior
        model: gpt-test
        host: https://api.test.com
        api_key: test-key
        max_tokens: 100
        rules:
          - "Lead rule"

      - name: "worker"
        role: junior
        model: gpt-test
        host: https://api.test.com
        api_key: test-key
        max_tokens: 50
        rules:
          - "Worker rule"
""")


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """Create a global config dir with a sample team."""
    teams_dir = tmp_path / "teams"
    teams_dir.mkdir()
    (teams_dir / "myteam.yaml").write_text(TEAM_YAML)
    return tmp_path


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a project dir with a local team.yaml."""
    (tmp_path / "team.yaml").write_text(TEAM_YAML)
    return tmp_path


# --- Local config discovery ---


def test_find_local_configs_team_yaml(project_dir: Path):
    configs = find_local_configs(project_dir)
    assert "team" in configs
    assert configs["team"] == project_dir / "team.yaml"


def test_find_local_configs_openswarm_dir(tmp_path: Path):
    swarm_dir = tmp_path / "openswarm"
    swarm_dir.mkdir()
    (swarm_dir / "backend.yaml").write_text(TEAM_YAML)
    (swarm_dir / "frontend.yml").write_text(TEAM_YAML)

    configs = find_local_configs(tmp_path)
    assert "backend" in configs
    assert "frontend" in configs


def test_find_local_configs_empty(tmp_path: Path):
    configs = find_local_configs(tmp_path)
    assert configs == {}


def test_find_all_configs_merges(config_dir: Path, project_dir: Path):
    """Local configs appear alongside global configs."""
    with patch("openswarm.config.discovery.get_config_dir", return_value=config_dir):
        configs = find_all_configs(project_dir)

    assert "myteam" in configs  # global
    assert "team" in configs  # local


def test_find_all_configs_local_overrides_global(tmp_path: Path):
    """Local config with same name as global wins."""
    # Global
    global_dir = tmp_path / "global"
    teams_dir = global_dir / "teams"
    teams_dir.mkdir(parents=True)
    (teams_dir / "shared.yaml").write_text(TEAM_YAML)

    # Local
    project = tmp_path / "project"
    project.mkdir()
    local_swarm = project / "openswarm"
    local_swarm.mkdir()
    (local_swarm / "shared.yaml").write_text(TEAM_YAML)

    with patch("openswarm.config.discovery.get_config_dir", return_value=global_dir):
        configs = find_all_configs(project)

    # Local version should win
    assert configs["shared"] == local_swarm / "shared.yaml"


# --- List teams ---


@pytest.mark.asyncio
async def test_list_teams(config_dir: Path):
    with patch("openswarm.mcp.server.find_all_configs") as mock:
        mock.return_value = {"myteam": config_dir / "teams" / "myteam.yaml"}
        result = await list_teams()

    assert "myteam" in result
    assert "Test goal" in result


@pytest.mark.asyncio
async def test_list_teams_empty():
    with patch("openswarm.mcp.server.find_all_configs", return_value={}):
        result = await list_teams()

    assert "No teams found" in result


# --- Team info ---


@pytest.mark.asyncio
async def test_team_info(config_dir: Path):
    with patch("openswarm.mcp.server.find_all_configs") as mock:
        mock.return_value = {"myteam": config_dir / "teams" / "myteam.yaml"}
        result = await team_info("myteam")

    assert "test-team" in result
    assert "lead" in result
    assert "worker" in result
    assert "hierarchical" in result


@pytest.mark.asyncio
async def test_team_info_not_found():
    with patch("openswarm.mcp.server.find_all_configs", return_value={}):
        result = await team_info("ghost")

    assert "Error" in result
    assert "ghost" in result


# --- Run task ---


@pytest.mark.asyncio
async def test_run_task(config_dir: Path):
    llm_mock = mock_acompletion(make_llm_response({"action": "respond", "content": "Task done!"}))

    with (
        patch(
            "openswarm.mcp.server.find_all_configs",
            return_value={"myteam": config_dir / "teams" / "myteam.yaml"},
        ),
        patch("openswarm.llm.client.litellm.acompletion", llm_mock),
    ):
        result = await run_task("Do something", "myteam")

    assert "Task done!" in result


@pytest.mark.asyncio
async def test_run_task_unknown_team():
    with patch("openswarm.mcp.server.find_all_configs", return_value={}):
        result = await run_task("Do something", "nope")

    assert "Error" in result
    assert "nope" in result


@pytest.mark.asyncio
async def test_run_task_auto_selects_single_team(config_dir: Path):
    """When no team specified and only one exists, auto-select it."""
    llm_mock = mock_acompletion(make_llm_response({"action": "respond", "content": "Auto!"}))

    with (
        patch(
            "openswarm.mcp.server.find_all_configs",
            return_value={"myteam": config_dir / "teams" / "myteam.yaml"},
        ),
        patch("openswarm.llm.client.litellm.acompletion", llm_mock),
    ):
        result = await run_task("Do something")

    assert "Auto!" in result


@pytest.mark.asyncio
async def test_run_task_no_team_no_configs():
    with patch("openswarm.mcp.server.find_all_configs", return_value={}):
        result = await run_task("Do something")

    assert "Error" in result
    assert "No team config found" in result


@pytest.mark.asyncio
async def test_run_task_no_team_multiple_configs():
    with patch(
        "openswarm.mcp.server.find_all_configs",
        return_value={"a": Path("a.yaml"), "b": Path("b.yaml")},
    ):
        result = await run_task("Do something")

    assert "Error" in result
    assert "Multiple teams" in result


# --- Run task with config ---


@pytest.mark.asyncio
async def test_run_task_with_config(project_dir: Path):
    llm_mock = mock_acompletion(make_llm_response({"action": "respond", "content": "Config done!"}))

    with patch("openswarm.llm.client.litellm.acompletion", llm_mock):
        result = await run_task_with_config("Do something", str(project_dir / "team.yaml"))

    assert "Config done!" in result


@pytest.mark.asyncio
async def test_run_task_with_config_not_found():
    result = await run_task_with_config("Do something", "/nonexistent/path.yaml")
    assert "Error" in result
    assert "not found" in result


# --- Tool descriptions ---


def test_tool_descriptions():
    """Verify MCP tool descriptions are detailed and informative."""
    try:
        from unittest.mock import MagicMock

        with patch("mcp.server.fastmcp.FastMCP") as mock_cls:
            mock_server = MagicMock()
            mock_cls.return_value = mock_server

            tools = {}

            def capture_tool():
                def decorator(func):
                    tools[func.__name__] = func.__doc__
                    return func

                return decorator

            mock_server.tool = capture_tool

            from openswarm.mcp.server import create_mcp_server

            create_mcp_server()

            expected_tools = ["openswarm_run", "openswarm_teams", "openswarm_team_info"]
            for name in expected_tools:
                assert name in tools, f"Tool {name} not registered"
                doc = tools[name]
                assert doc is not None, f"Tool {name} has no docstring"
                assert len(doc) > 50, f"Tool {name} docstring too short"
    except ImportError:
        pytest.skip("mcp package not installed")
