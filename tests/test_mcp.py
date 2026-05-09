"""Tests for MCP server tool functions."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from openswarm.mcp.server import list_teams, run_task, team_info

from conftest import make_llm_response, mock_acompletion


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """Create a config dir with a sample team."""
    teams_dir = tmp_path / "teams"
    teams_dir.mkdir()

    yaml_content = textwrap.dedent("""\
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
    (teams_dir / "myteam.yaml").write_text(yaml_content)
    return tmp_path


@pytest.mark.asyncio
async def test_list_teams(config_dir: Path):
    with patch("openswarm.mcp.server._get_config_dir", return_value=config_dir):
        result = await list_teams()

    assert "myteam" in result
    assert "Test goal" in result


@pytest.mark.asyncio
async def test_list_teams_empty(tmp_path: Path):
    with patch("openswarm.mcp.server._get_config_dir", return_value=tmp_path):
        result = await list_teams()

    assert "No teams found" in result


@pytest.mark.asyncio
async def test_team_info(config_dir: Path):
    with patch("openswarm.mcp.server._get_config_dir", return_value=config_dir):
        result = await team_info("myteam")

    assert "test-team" in result
    assert "lead" in result
    assert "worker" in result
    assert "hierarchical" in result


@pytest.mark.asyncio
async def test_team_info_not_found(config_dir: Path):
    with patch("openswarm.mcp.server._get_config_dir", return_value=config_dir):
        result = await team_info("ghost")

    assert "Error" in result
    assert "ghost" in result


@pytest.mark.asyncio
async def test_run_task(config_dir: Path):
    llm_mock = mock_acompletion(make_llm_response({"action": "respond", "content": "Task done!"}))

    with (
        patch("openswarm.mcp.server._get_config_dir", return_value=config_dir),
        patch("openswarm.llm.client.litellm.acompletion", llm_mock),
    ):
        result = await run_task("Do something", "myteam")

    assert "Task done!" in result


@pytest.mark.asyncio
async def test_run_task_unknown_team(config_dir: Path):
    with patch("openswarm.mcp.server._get_config_dir", return_value=config_dir):
        result = await run_task("Do something", "nope")

    assert "Error" in result
    assert "nope" in result
