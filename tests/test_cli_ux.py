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


def _split_stream_runner() -> CliRunner:
    """A runner that keeps stdout and stderr apart, across click versions."""
    try:
        return CliRunner(mix_stderr=False)  # click < 8.2
    except TypeError:
        return CliRunner()  # click >= 8.2 separates the streams by default


def test_run_errors_go_to_stderr_not_stdout(isolated: Path):
    """`openswarm run -q > out.md` must never capture an error message."""
    result = _split_stream_runner().invoke(app, ["run", "Do something", "-q"])

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


# --- workspace tools default on, but never without someone to ask ---


def test_tools_are_enabled_by_default_on_a_terminal(tmp_path, monkeypatch):
    from openswarm.cli.app import resolve_tool_approver

    monkeypatch.setattr("openswarm.cli.app.sys.stdin.isatty", lambda: True)

    assert resolve_tool_approver(no_tools=False, workspace=tmp_path) is not None


def test_no_tools_opts_out(tmp_path, monkeypatch):
    from openswarm.cli.app import resolve_tool_approver

    monkeypatch.setattr("openswarm.cli.app.sys.stdin.isatty", lambda: True)

    assert resolve_tool_approver(no_tools=True, workspace=tmp_path) is None


def test_piped_session_gets_no_tools(tmp_path, monkeypatch):
    """Nobody is there to approve, so the agent gets nothing — quietly, not fatally."""
    from openswarm.cli.app import resolve_tool_approver

    monkeypatch.setattr("openswarm.cli.app.sys.stdin.isatty", lambda: False)

    assert resolve_tool_approver(no_tools=False, workspace=tmp_path) is None


def test_quiet_piped_run_still_works_with_tools_on(isolated: Path):
    """The new default must not break `openswarm run ... -q > file`."""
    (isolated / "team.yaml").write_text(SAMPLE_YAML)

    with patch("openswarm.llm.client.litellm.acompletion", _lead_responds("piped ok")):
        result = runner.invoke(app, ["run", "Do something", "-q"])

    assert result.exit_code == 0
    assert result.output.strip() == "piped ok"


# --- approval menu ---


def test_menu_yes_executes(tmp_path):
    from openswarm.cli.utils import make_tool_approver
    from openswarm.core.tools import ToolRequest

    approve = make_tool_approver(tmp_path, chooser=lambda options: 0)
    result = approve(ToolRequest(kind="write_file", path="a.py", content="x = 1"))

    assert "Wrote a.py" in result
    assert (tmp_path / "a.py").read_text() == "x = 1"


def test_menu_offers_four_options_including_dont_ask_again(tmp_path):
    from openswarm.cli.utils import make_tool_approver
    from openswarm.core.tools import ToolRequest

    seen: list[list[str]] = []

    def spy(options):
        seen.append(options)
        return 3

    approve = make_tool_approver(tmp_path, chooser=spy)
    approve(ToolRequest(kind="write_file", path="a.py", content="x"))

    assert len(seen[0]) == 4
    assert seen[0][0] == "Yes"
    assert "don't ask again" in seen[0][1]
    assert seen[0][-1] == "No"


def test_dont_ask_again_stops_asking_for_that_action(tmp_path):
    """Second write of the same kind must not reach the menu."""
    from openswarm.cli.utils import make_tool_approver
    from openswarm.core.tools import ToolRequest

    asked: list[str] = []

    def spy(options):
        asked.append("asked")
        return 1  # yes, and don't ask again

    approve = make_tool_approver(tmp_path, chooser=spy)
    approve(ToolRequest(kind="write_file", path="a.py", content="1"))
    approve(ToolRequest(kind="write_file", path="b.py", content="2"))

    assert len(asked) == 1
    assert (tmp_path / "b.py").read_text() == "2"


def test_dont_ask_again_is_scoped_to_one_action_kind(tmp_path):
    """Approving writes forever must not silently approve shell commands."""
    from openswarm.cli.utils import make_tool_approver
    from openswarm.core.tools import ToolRequest

    asked: list[str] = []

    def spy(options):
        asked.append("asked")
        return 1

    approve = make_tool_approver(tmp_path, chooser=spy)
    approve(ToolRequest(kind="write_file", path="a.py", content="1"))
    approve(ToolRequest(kind="run_command", command="echo hi"))

    assert len(asked) == 2  # the command still had to ask


def test_menu_no_with_feedback_reaches_the_agent(tmp_path):
    from openswarm.cli.utils import make_tool_approver
    from openswarm.core.tools import ToolRequest

    approve = make_tool_approver(tmp_path, chooser=lambda options: 2)
    with patch("openswarm.cli.utils.console.input", return_value="use pathlib instead"):
        result = approve(ToolRequest(kind="write_file", path="a.py", content="x"))

    assert result == "Refused by the user: use pathlib instead"
    assert not (tmp_path / "a.py").exists()


def test_menu_plain_no_refuses(tmp_path):
    from openswarm.cli.utils import make_tool_approver
    from openswarm.core.tools import ToolRequest

    approve = make_tool_approver(tmp_path, chooser=lambda options: 3)
    result = approve(ToolRequest(kind="write_file", path="a.py", content="x"))

    assert "Refused by the user" in result
    assert not (tmp_path / "a.py").exists()


def test_cancelling_the_menu_counts_as_no(tmp_path):
    """Esc and Ctrl-C return None; that must never be read as approval."""
    from openswarm.cli.utils import make_tool_approver
    from openswarm.core.tools import ToolRequest

    approve = make_tool_approver(tmp_path, chooser=lambda options: None)
    result = approve(ToolRequest(kind="run_command", command="rm -rf /"))

    assert "Refused by the user" in result


def _drive_menu(keys: str):
    """Run the real menu against synthetic keystrokes."""
    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from openswarm.cli.utils import choose

    with create_pipe_input() as pipe:
        pipe.send_text(keys)
        with create_app_session(input=pipe, output=DummyOutput()):
            return choose(["Yes", "Yes, always", "No with feedback", "No"])


def test_arrow_keys_move_the_selection():
    assert _drive_menu("\r") == 0  # Enter on the default
    assert _drive_menu("\x1b[B\r") == 1  # Down, Enter
    assert _drive_menu("\x1b[B\x1b[B\r") == 2  # Down, Down, Enter
    assert _drive_menu("\x1b[A\r") == 3  # Up wraps to the last option


def test_number_keys_pick_directly():
    assert _drive_menu("3") == 2


def test_ctrl_c_cancels_the_menu():
    assert _drive_menu("\x03") is None


def test_menu_works_inside_a_running_event_loop():
    """Approvals are requested from inside orchestrator.run(), which is async.

    Application.run() starts its own loop, so calling it directly there raised
    'asyncio.run() cannot be called from a running event loop' — every tool
    request crashed.
    """
    import asyncio

    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from openswarm.cli.utils import choose

    async def approve_mid_run():
        with create_pipe_input() as pipe:
            pipe.send_text("\x1b[B\r")
            with create_app_session(input=pipe, output=DummyOutput()):
                return choose(["Yes", "No"])

    assert asyncio.run(approve_mid_run()) == 1


def test_feedback_prompt_works_inside_a_running_loop(tmp_path):
    """The 'tell it what to do instead' branch also runs mid-orchestration."""
    import asyncio

    from openswarm.cli.utils import make_tool_approver
    from openswarm.core.tools import ToolRequest

    approve = make_tool_approver(tmp_path, chooser=lambda options: 2)

    async def refuse_mid_run():
        with patch("openswarm.cli.utils.console.input", return_value="use pathlib"):
            return approve(ToolRequest(kind="write_file", path="a.py", content="x"))

    assert asyncio.run(refuse_mid_run()) == "Refused by the user: use pathlib"


# --- approval preview ---


def _plain(capsys) -> str:
    import re

    return re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)


def test_overwrite_shows_a_diff_including_deletions(tmp_path, capsys):
    """Showing only the new content hides what an overwrite removes."""
    from openswarm.cli.utils import _show_request
    from openswarm.core.tools import ToolRequest

    (tmp_path / "utils.py").write_text("def keep():\n    pass\n\n\ndef doomed():\n    pass\n")
    new = "def keep():\n    pass\n"

    _show_request(ToolRequest(kind="write_file", path="utils.py", content=new), tmp_path)
    out = _plain(capsys)

    assert "Edit utils.py" in out
    assert "-def doomed():" in out  # the deletion is visible
    assert "+2" not in out.split("\n")[1]  # nothing claimed as added


def test_new_file_is_labelled_create_not_edit(tmp_path, capsys):
    from openswarm.cli.utils import _show_request
    from openswarm.core.tools import ToolRequest

    _show_request(ToolRequest(kind="write_file", path="fresh.py", content="x = 1\n"), tmp_path)
    out = _plain(capsys)

    assert "Create fresh.py" in out
    assert "Edit" not in out


def test_identical_write_says_no_changes(tmp_path, capsys):
    from openswarm.cli.utils import _show_request
    from openswarm.core.tools import ToolRequest

    (tmp_path / "same.py").write_text("x = 1\n")

    _show_request(ToolRequest(kind="write_file", path="same.py", content="x = 1\n"), tmp_path)

    assert "no changes" in _plain(capsys)


def test_command_preview_names_the_directory(tmp_path, capsys):
    """Where a command runs matters as much as what it runs."""
    from openswarm.cli.utils import _show_request
    from openswarm.core.tools import ToolRequest

    _show_request(ToolRequest(kind="run_command", command="pytest -q"), tmp_path)
    out = _plain(capsys)

    assert "pytest -q" in out
    # Rich wraps long paths, so compare with the line breaks removed.
    assert str(tmp_path) in out.replace("\n", "")


def test_outcome_is_reported_after_approval(tmp_path, capsys):
    """Approving should not be a leap of faith — say what happened."""
    from openswarm.cli.utils import make_tool_approver
    from openswarm.core.tools import ToolRequest

    approve = make_tool_approver(tmp_path, chooser=lambda options: 0)
    approve(ToolRequest(kind="write_file", path="a.py", content="x = 1"))

    assert "Wrote a.py" in _plain(capsys)


def test_failed_outcome_is_reported(tmp_path, capsys):
    from openswarm.cli.utils import make_tool_approver
    from openswarm.core.tools import ToolRequest

    approve = make_tool_approver(tmp_path, chooser=lambda options: 0)
    approve(ToolRequest(kind="write_file", path="../escape.py", content="x"))

    assert "escapes the workspace" in _plain(capsys)
