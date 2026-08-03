"""Tests for CLI invocation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from conftest import SAMPLE_YAML, make_llm_response, mock_acompletion, mock_acompletion_stream
from typer.testing import CliRunner

from openswarm.cli.app import app

runner = CliRunner()


def test_run_with_config(tmp_path: Path):
    config_file = tmp_path / "team.yaml"
    config_file.write_text(SAMPLE_YAML)

    lead_respond = make_llm_response({"action": "respond", "content": "CLI test done"})
    mock = mock_acompletion(lead_respond)

    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = runner.invoke(app, ["run", "Do something", "--config", str(config_file)])

    assert result.exit_code == 0
    assert "CLI test done" in result.output
    assert "Token Usage" in result.output


def test_run_missing_config():
    result = runner.invoke(app, ["run", "Do something", "--config", "/nonexistent.yaml"])
    assert result.exit_code == 1


def test_run_no_config_no_team(isolated: Path):
    result = runner.invoke(app, ["run", "Do something"])
    assert result.exit_code == 1


def test_run_both_config_and_team(tmp_path: Path):
    config_file = tmp_path / "team.yaml"
    config_file.write_text(SAMPLE_YAML)
    result = runner.invoke(
        app, ["run", "Do something", "--config", str(config_file), "--team", "foo"]
    )
    assert result.exit_code == 1


def test_run_with_team(tmp_path: Path, monkeypatch):
    teams_dir = tmp_path / "teams"
    teams_dir.mkdir()
    config_file = teams_dir / "myteam.yaml"
    config_file.write_text(SAMPLE_YAML)

    monkeypatch.setenv("OPENSWARM_CONFIG_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    lead_respond = make_llm_response({"action": "respond", "content": "team lookup works"})
    mock = mock_acompletion(lead_respond)

    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = runner.invoke(app, ["run", "Do something", "--team", "myteam"])

    assert result.exit_code == 0
    assert "team lookup works" in result.output


def test_run_with_team_not_found(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENSWARM_CONFIG_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["run", "Do something", "--team", "nope"])
    assert result.exit_code == 1


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "run" in result.output.lower()


# --- Team discovery commands ---


def test_team_list_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENSWARM_CONFIG_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["team-list"])
    assert result.exit_code == 0
    assert "No teams" in result.output


def test_team_list_with_teams(tmp_path: Path, monkeypatch):
    teams_dir = tmp_path / "teams"
    teams_dir.mkdir()
    (teams_dir / "backend.yaml").write_text(SAMPLE_YAML)

    monkeypatch.setenv("OPENSWARM_CONFIG_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["team-list"])
    assert result.exit_code == 0
    assert "backend" in result.output
    assert "Test goal" in result.output


def test_team_info(tmp_path: Path, monkeypatch):
    teams_dir = tmp_path / "teams"
    teams_dir.mkdir()
    (teams_dir / "backend.yaml").write_text(SAMPLE_YAML)

    monkeypatch.setenv("OPENSWARM_CONFIG_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["team-info", "backend"])
    assert result.exit_code == 0
    assert "test-team" in result.output
    assert "lead" in result.output
    assert "worker" in result.output


def test_team_info_not_found(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENSWARM_CONFIG_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["team-info", "nope"])
    assert result.exit_code == 1
    assert "not found" in result.output


# --- Streaming flag ---


def test_run_with_stream_flag(tmp_path: Path):
    config_file = tmp_path / "team.yaml"
    config_file.write_text(SAMPLE_YAML)

    lead_respond = make_llm_response({"action": "respond", "content": "streamed result"})
    mock = mock_acompletion_stream(lead_respond)

    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = runner.invoke(
            app, ["run", "Do something", "--config", str(config_file), "--stream"]
        )

    assert result.exit_code == 0
    assert "streamed result" in result.output


def test_run_stream_short_flag(tmp_path: Path):
    config_file = tmp_path / "team.yaml"
    config_file.write_text(SAMPLE_YAML)

    lead_respond = make_llm_response({"action": "respond", "content": "ok"})
    mock = mock_acompletion_stream(lead_respond)

    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = runner.invoke(app, ["run", "Do something", "--config", str(config_file), "-s"])

    assert result.exit_code == 0
