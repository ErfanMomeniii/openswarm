"""Tests for onboarding and discovery UX: init, doctor, team commands, run flags."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import SAMPLE_YAML, make_llm_response, mock_acompletion
from typer.testing import CliRunner

from openswarm.cli.app import app
from openswarm.llm.client import LLMError

runner = CliRunner()


def _lead_responds(text: str = "done"):
    return mock_acompletion(make_llm_response({"action": "respond", "content": text}))


# --- version ---


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "openswarm" in result.output


def test_no_args_shows_help():
    result = runner.invoke(app, [])
    assert "init" in result.output
    assert "doctor" in result.output


# --- run: discovery ---


def test_run_auto_discovers_project_config(isolated: Path):
    (isolated / "team.yaml").write_text(SAMPLE_YAML)

    with patch("openswarm.llm.client.litellm.acompletion", _lead_responds("auto discovered")):
        result = runner.invoke(app, ["run", "Do something"])

    assert result.exit_code == 0
    assert "auto discovered" in result.output


def test_run_without_any_config_hints_init(isolated: Path):
    result = runner.invoke(app, ["run", "Do something"])
    assert result.exit_code == 1
    assert "openswarm init" in result.output


def test_run_ambiguous_configs_requires_choice(isolated: Path):
    (isolated / "team.yaml").write_text(SAMPLE_YAML)
    (isolated / "openswarm.yaml").write_text(SAMPLE_YAML)

    result = runner.invoke(app, ["run", "Do something"])
    assert result.exit_code == 1
    assert "Multiple teams" in result.output


def test_run_team_name_resolves_project_local_config(isolated: Path):
    """--team used to only look at the global dir; project-local now counts too."""
    (isolated / "openswarm").mkdir()
    (isolated / "openswarm" / "backend.yaml").write_text(SAMPLE_YAML)

    with patch("openswarm.llm.client.litellm.acompletion", _lead_responds("local team")):
        result = runner.invoke(app, ["run", "Do something", "--team", "backend"])

    assert result.exit_code == 0
    assert "local team" in result.output


def test_run_unknown_team_lists_available(isolated: Path):
    (isolated / "team.yaml").write_text(SAMPLE_YAML)
    result = runner.invoke(app, ["run", "x", "--team", "ghost"])
    assert result.exit_code == 1
    assert "Available teams" in result.output
    assert "team" in result.output


# --- run: output flags ---


def test_run_quiet_prints_only_result(isolated: Path):
    (isolated / "team.yaml").write_text(SAMPLE_YAML)

    with patch("openswarm.llm.client.litellm.acompletion", _lead_responds("bare output")):
        result = runner.invoke(app, ["run", "Do something", "-q"])

    assert result.exit_code == 0
    assert result.output.strip() == "bare output"


def test_run_writes_output_file(isolated: Path):
    (isolated / "team.yaml").write_text(SAMPLE_YAML)
    out = isolated / "result.md"

    with patch("openswarm.llm.client.litellm.acompletion", _lead_responds("saved result")):
        result = runner.invoke(app, ["run", "Do something", "-o", str(out)])

    assert result.exit_code == 0
    assert out.read_text() == "saved result"


def test_verbose_does_not_enable_third_party_debug_logs(isolated: Path):
    """-v shows inter-agent messages, not httpcore/openai request dumps."""
    import logging

    (isolated / "team.yaml").write_text(SAMPLE_YAML)

    with patch("openswarm.llm.client.litellm.acompletion", _lead_responds("ok")):
        result = runner.invoke(app, ["run", "Do something", "-v"])

    assert result.exit_code == 0
    assert logging.getLogger("openswarm").level == logging.DEBUG
    for name in ("httpx", "httpcore", "openai", "LiteLLM"):
        assert logging.getLogger(name).level == logging.WARNING


def test_run_errors_go_to_stderr_not_stdout(isolated: Path):
    """`openswarm run -q > out.md` must never capture an error message."""
    split_runner = CliRunner(mix_stderr=False)
    result = split_runner.invoke(app, ["run", "Do something", "-q"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "openswarm init" in result.stderr


def test_run_max_rounds_override_validated(isolated: Path):
    (isolated / "team.yaml").write_text(SAMPLE_YAML)
    result = runner.invoke(app, ["run", "x", "--max-rounds", "0"])
    assert result.exit_code == 1
    assert "max-rounds" in result.output


# --- init ---


def test_init_creates_project_config(isolated: Path):
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    config = isolated / "team.yaml"
    assert config.exists()
    assert "workflow: hierarchical" in config.read_text()
    assert "Next steps" in result.output


def test_init_refuses_overwrite_without_force(isolated: Path):
    (isolated / "team.yaml").write_text("existing")
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 1
    assert "--force" in result.output
    assert (isolated / "team.yaml").read_text() == "existing"


def test_init_force_overwrites(isolated: Path):
    (isolated / "team.yaml").write_text("existing")
    result = runner.invoke(app, ["init", "--force"])
    assert result.exit_code == 0
    assert "existing" not in (isolated / "team.yaml").read_text()


def test_init_unknown_template(isolated: Path):
    result = runner.invoke(app, ["init", "--template", "nope"])
    assert result.exit_code == 1
    assert "Unknown template" in result.output


def test_init_list_templates(isolated: Path):
    result = runner.invoke(app, ["init", "--list-templates"])
    assert result.exit_code == 0
    for name in ("hierarchical", "pipeline", "collaborative", "local"):
        assert name in result.output
    assert not (isolated / "team.yaml").exists()


def test_init_global_writes_to_teams_dir(isolated: Path, tmp_path: Path):
    result = runner.invoke(app, ["init", "--global", "--name", "shared"])
    assert result.exit_code == 0
    assert (tmp_path / "home" / "teams" / "shared.yaml").exists()


def test_init_every_template_produces_loadable_config(isolated: Path, monkeypatch):
    from openswarm.config import templates
    from openswarm.config.loader import inspect_config

    for name in templates.TEMPLATES:
        out = isolated / f"{name}.yaml"
        result = runner.invoke(app, ["init", "--template", name, "--output", str(out)])
        assert result.exit_code == 0, result.output
        config, _ = inspect_config(out)
        assert config.agents


def test_init_local_template_needs_no_keys(isolated: Path):
    result = runner.invoke(app, ["init", "--template", "local"])
    assert result.exit_code == 0
    assert "export" not in result.output


# --- doctor ---


def test_doctor_no_configs(isolated: Path):
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "openswarm init" in result.output


def test_doctor_valid_config(isolated: Path):
    (isolated / "team.yaml").write_text(SAMPLE_YAML)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "All checks passed" in result.output


def test_doctor_reports_unset_env_vars(isolated: Path, monkeypatch):
    monkeypatch.delenv("MISSING_KEY", raising=False)
    (isolated / "team.yaml").write_text(SAMPLE_YAML.replace("test-key", "${MISSING_KEY}"))

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "MISSING_KEY" in result.output


def test_doctor_reports_invalid_config(isolated: Path):
    (isolated / "team.yaml").write_text("team:\n  name: x\n")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "invalid config" in result.output


def test_doctor_connection_check_success(isolated: Path):
    (isolated / "team.yaml").write_text(SAMPLE_YAML)
    with patch("openswarm.llm.client.litellm.acompletion", mock_acompletion("ok", "ok")):
        result = runner.invoke(app, ["doctor", "--check-connection"])
    assert result.exit_code == 0
    assert "reachable" in result.output


def test_doctor_connection_check_skipped_when_env_unset(isolated: Path, monkeypatch):
    """Never send a placeholder API key to a provider."""
    monkeypatch.delenv("MISSING_KEY", raising=False)
    (isolated / "team.yaml").write_text(SAMPLE_YAML.replace("test-key", "${MISSING_KEY}"))

    with patch("openswarm.cli.app.LLMClient.chat") as chat:
        result = runner.invoke(app, ["doctor", "--check-connection"])

    assert result.exit_code == 1
    assert "skipping connection check" in result.output
    chat.assert_not_called()


def test_doctor_any_probe_failure_is_a_problem(isolated: Path):
    """Gateways collapse different faults onto the same errors — never pass a guess."""
    import litellm

    (isolated / "team.yaml").write_text(SAMPLE_YAML)
    error = LLMError(
        "provider blew up", original=litellm.InternalServerError("boom", "gpt-test", "openai")
    )
    with patch("openswarm.cli.app.LLMClient.chat", side_effect=error):
        result = runner.invoke(app, ["doctor", "--check-connection"])

    assert result.exit_code == 1
    assert "hint:" in result.output


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, "api_key"), (403, "api_key"), (404, "model name"), (400, "rejected"), (503, "provider")],
)
def test_failure_hints_follow_http_status(status: int, expected: str):
    from openswarm.llm.client import describe_failure

    original = Exception("x")
    original.status_code = status
    assert expected in describe_failure(LLMError("boom", original=original))


def test_failure_hint_without_a_status_is_still_useful():
    from openswarm.llm.client import describe_failure

    assert "host" in describe_failure(LLMError("boom"))


def test_doctor_connection_probe_leaves_room_for_reasoning(isolated: Path):
    """A 1-token probe makes reasoning models return empty; keep a workable budget."""
    from openswarm.cli.app import PROBE_MAX_TOKENS

    assert PROBE_MAX_TOKENS >= 8


def test_doctor_reports_bad_credentials_as_a_problem(isolated: Path):
    import litellm

    (isolated / "team.yaml").write_text(SAMPLE_YAML)
    error = LLMError(
        "bad api key", original=litellm.AuthenticationError("bad api key", "gpt-test", "openai")
    )
    with patch("openswarm.cli.app.LLMClient.chat", side_effect=error):
        result = runner.invoke(app, ["doctor", "--check-connection"])
    assert result.exit_code == 1
    assert "bad api key" in result.output


def test_doctor_reports_unreachable_host_as_a_problem(isolated: Path):
    import litellm

    (isolated / "team.yaml").write_text(SAMPLE_YAML)
    error = LLMError(
        "connection refused",
        original=litellm.APIConnectionError(
            message="connection refused", model="gpt-test", llm_provider="openai"
        ),
    )
    with patch("openswarm.cli.app.LLMClient.chat", side_effect=error):
        result = runner.invoke(app, ["doctor", "--check-connection"])
    assert result.exit_code == 1


def test_doctor_reports_unknown_model_as_a_problem(isolated: Path):
    import litellm

    (isolated / "team.yaml").write_text(SAMPLE_YAML)
    error = LLMError(
        "model not found",
        original=litellm.NotFoundError("model not found", "gpt-test", "openai"),
    )
    with patch("openswarm.cli.app.LLMClient.chat", side_effect=error):
        result = runner.invoke(app, ["doctor", "--check-connection"])
    assert result.exit_code == 1


# --- team subcommands ---


def test_team_list_includes_local_and_global(isolated: Path, tmp_path: Path):
    teams_dir = tmp_path / "home" / "teams"
    teams_dir.mkdir(parents=True)
    (teams_dir / "global-team.yaml").write_text(SAMPLE_YAML)
    (isolated / "team.yaml").write_text(SAMPLE_YAML)

    result = runner.invoke(app, ["team", "list"])
    assert result.exit_code == 0
    assert "global" in result.output
    assert "local" in result.output


def test_team_list_empty(isolated: Path):
    result = runner.invoke(app, ["team", "list"])
    assert result.exit_code == 0
    assert "No teams found" in result.output


def test_team_info_shows_agents_and_rules(isolated: Path):
    (isolated / "team.yaml").write_text(SAMPLE_YAML)
    result = runner.invoke(app, ["team", "info", "team"])
    assert result.exit_code == 0
    assert "Lead rule one" in result.output
    assert "worker" in result.output


def test_team_info_tolerates_unset_env(isolated: Path, monkeypatch):
    monkeypatch.delenv("MISSING_KEY", raising=False)
    (isolated / "team.yaml").write_text(SAMPLE_YAML.replace("test-key", "${MISSING_KEY}"))
    result = runner.invoke(app, ["team", "info", "team"])
    assert result.exit_code == 0
    assert "MISSING_KEY" in result.output


def test_flat_aliases_still_work(isolated: Path):
    (isolated / "team.yaml").write_text(SAMPLE_YAML)
    assert runner.invoke(app, ["team-list"]).exit_code == 0
    assert runner.invoke(app, ["team-info", "team"]).exit_code == 0


def test_doctor_probe_retries_transient_blips(isolated: Path):
    """Providers flake; a healthy config must not fail on one bad response."""
    from openswarm.cli.app import PROBE_ATTEMPTS

    assert PROBE_ATTEMPTS >= 2

    (isolated / "team.yaml").write_text(SAMPLE_YAML)
    calls: list[int] = []

    async def flaky_once(self, messages, attempts=3):
        calls.append(1)
        raise LLMError("transient blip")

    with patch("openswarm.cli.app.LLMClient.chat", flaky_once):
        runner.invoke(app, ["doctor", "--check-connection"])

    # chat() owns the retry loop, so doctor calls it once per agent and passes
    # the attempt budget down.
    assert len(calls) == 2  # two agents in SAMPLE_YAML
