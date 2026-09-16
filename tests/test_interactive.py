"""Tests for interactive REPL and message callback."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from conftest import make_llm_response, mock_acompletion

from openswarm.config.models import TeamConfig
from openswarm.core.message import Message, MessageType
from openswarm.core.orchestrator import Orchestrator
from openswarm.core.task import Task
from openswarm.core.team import Team
from openswarm.workflow.hierarchical import HierarchicalWorkflow

# --- on_message callback ---


@pytest.mark.asyncio
async def test_callback_invoked_on_messages(team_config: TeamConfig):
    """on_message callback fires for every message logged."""
    team = Team(team_config)
    workflow = HierarchicalWorkflow()
    task = Task(description="Test callback")
    message_log: list[Message] = []
    received: list[Message] = []

    def on_msg(msg: Message) -> None:
        received.append(msg)

    responses = [
        make_llm_response({"action": "delegate", "to": "worker", "task": "sub"}),
        make_llm_response({"action": "result", "content": "done"}),
        make_llm_response({"action": "respond", "content": "final"}),
    ]

    mock = mock_acompletion(*responses)
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        await workflow.execute(
            task, team, max_rounds=10, message_log=message_log, on_message=on_msg
        )

    # Callback should receive same messages as message_log
    assert len(received) == len(message_log)
    assert received[0].type == MessageType.TASK


@pytest.mark.asyncio
async def test_callback_none_no_error(team_config: TeamConfig):
    """on_message=None doesn't break anything."""
    team = Team(team_config)
    workflow = HierarchicalWorkflow()
    task = Task(description="No callback")
    message_log: list[Message] = []

    mock = mock_acompletion(make_llm_response({"action": "respond", "content": "ok"}))
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await workflow.execute(
            task, team, max_rounds=10, message_log=message_log, on_message=None
        )

    assert result == "ok"


@pytest.mark.asyncio
async def test_orchestrator_passes_callback(team_config: TeamConfig):
    """Orchestrator.run() forwards on_message to workflow."""
    team = Team(team_config)
    workflow = HierarchicalWorkflow()
    orch = Orchestrator(team, workflow)
    received: list[Message] = []

    mock = mock_acompletion(make_llm_response({"action": "respond", "content": "done"}))
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        await orch.run("test", on_message=received.append)

    assert len(received) >= 1


# --- Slash command dispatch ---


def test_slash_quit(team_config: TeamConfig):
    from openswarm.cli.interactive import _handle_slash_command

    team = Team(team_config)
    orch = Orchestrator(team, HierarchicalWorkflow())
    assert _handle_slash_command("/quit", team, orch, [False]) is True


def test_slash_team(team_config: TeamConfig):
    from openswarm.cli.interactive import _handle_slash_command

    team = Team(team_config)
    orch = Orchestrator(team, HierarchicalWorkflow())
    assert _handle_slash_command("/team", team, orch, [False]) is False


def test_slash_history_empty(team_config: TeamConfig):
    from openswarm.cli.interactive import _handle_slash_command

    team = Team(team_config)
    orch = Orchestrator(team, HierarchicalWorkflow())
    assert _handle_slash_command("/history", team, orch, [False]) is False


def test_slash_clear(team_config: TeamConfig):
    from openswarm.cli.interactive import _handle_slash_command

    team = Team(team_config)
    orch = Orchestrator(team, HierarchicalWorkflow())
    orch.message_log.append(
        Message(from_agent="a", to_agent="b", type=MessageType.TASK, content="x")
    )
    _handle_slash_command("/clear", team, orch, [False])
    assert len(orch.message_log) == 0


def test_slash_clear_resets_agent_histories(team_config: TeamConfig):
    """'/clear' clears agent conversation histories too."""
    from openswarm.cli.interactive import _handle_slash_command

    team = Team(team_config)
    orch = Orchestrator(team, HierarchicalWorkflow())

    # Add some history to agents
    for agent in team.agents.values():
        agent.history.append({"role": "user", "content": "old msg"})
        agent.history.append({"role": "assistant", "content": "old reply"})

    _handle_slash_command("/clear", team, orch, [False])

    for agent in team.agents.values():
        assert len(agent.history) == 0


def test_slash_stream_toggle(team_config: TeamConfig):
    from openswarm.cli.interactive import _handle_slash_command

    team = Team(team_config)
    orch = Orchestrator(team, HierarchicalWorkflow())
    stream_state = [False]
    assert _handle_slash_command("/stream", team, orch, stream_state) is False
    assert stream_state[0] is True
    assert _handle_slash_command("/stream", team, orch, stream_state) is False
    assert stream_state[0] is False


def test_slash_help(team_config: TeamConfig):
    from openswarm.cli.interactive import _handle_slash_command

    team = Team(team_config)
    orch = Orchestrator(team, HierarchicalWorkflow())
    assert _handle_slash_command("/help", team, orch, [False]) is False


def test_slash_quit_aliases(team_config: TeamConfig):
    from openswarm.cli.interactive import _handle_slash_command

    team = Team(team_config)
    orch = Orchestrator(team, HierarchicalWorkflow())
    for cmd in ("/quit", "/exit", "/q"):
        assert _handle_slash_command(cmd, team, orch, [False]) is True


def test_slash_usage_empty_and_populated(team_config: TeamConfig):
    from openswarm.cli.interactive import _handle_slash_command
    from openswarm.core.usage import RunUsage, UsageStats

    team = Team(team_config)
    orch = Orchestrator(team, HierarchicalWorkflow())

    assert _handle_slash_command("/usage", team, orch, [False], RunUsage()) is False

    usage = RunUsage(entries=[UsageStats("lead", "gpt-test", 10, 5)])
    assert _handle_slash_command("/usage", team, orch, [False], usage) is False


def test_slash_save_writes_last_result(team_config: TeamConfig, tmp_path):
    from openswarm.cli.interactive import _handle_slash_command

    team = Team(team_config)
    orch = Orchestrator(team, HierarchicalWorkflow())
    out = tmp_path / "out.md"

    _handle_slash_command(f"/save {out}", team, orch, [False], None, ["the result"])
    assert out.read_text() == "the result"


def test_slash_save_without_result(team_config: TeamConfig, tmp_path):
    from openswarm.cli.interactive import _handle_slash_command

    team = Team(team_config)
    orch = Orchestrator(team, HierarchicalWorkflow())
    out = tmp_path / "out.md"

    _handle_slash_command(f"/save {out}", team, orch, [False], None, [""])
    assert not out.exists()


def test_slash_save_requires_path(team_config: TeamConfig):
    from openswarm.cli.interactive import _handle_slash_command

    team = Team(team_config)
    orch = Orchestrator(team, HierarchicalWorkflow())
    assert _handle_slash_command("/save", team, orch, [False], None, ["x"]) is False


def test_slash_unknown(team_config: TeamConfig):
    from openswarm.cli.interactive import _handle_slash_command

    team = Team(team_config)
    orch = Orchestrator(team, HierarchicalWorkflow())
    assert _handle_slash_command("/nope", team, orch, [False]) is False


# --- make_message_printer (now in cli.utils) ---


def test_make_message_printer():
    from openswarm.cli.utils import make_message_printer

    cb = make_message_printer()
    assert cb is not None
    assert callable(cb)


# --- REPL polish: completion, markdown rendering, persistent history ---


def test_slash_completer_offers_commands_with_descriptions():
    from prompt_toolkit.document import Document

    from openswarm.cli.interactive import SLASH_COMMANDS, SlashCompleter

    items = list(SlashCompleter().get_completions(Document("/s"), None))
    names = [c.text for c in items]

    assert "/save" in names and "/stream" in names
    assert "/help" not in names  # does not start with "/s"
    assert all(c.display_meta_text == SLASH_COMMANDS[c.text] for c in items)


def test_slash_completer_silent_once_an_argument_is_typed():
    from prompt_toolkit.document import Document

    from openswarm.cli.interactive import SlashCompleter

    assert list(SlashCompleter().get_completions(Document("/save out.md"), None)) == []
    assert list(SlashCompleter().get_completions(Document("write a function"), None)) == []


def test_result_renders_code_blocks_as_markdown(capsys):
    import re

    from openswarm.cli.interactive import _render_result

    _render_result("Here:\n\n```python\ndef f():\n    return 1\n```\n")
    # Syntax highlighting injects ANSI codes between tokens; compare on plain text.
    plain = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)

    assert "```" not in plain  # fences consumed by the markdown renderer
    assert "def" in plain and "return 1" in plain


def test_copy_prints_the_raw_result(team_config: TeamConfig, capsys):
    """Rendered output is nice to read but bad to paste; /copy gives the original."""
    from openswarm.cli.interactive import _handle_slash_command

    team = Team(team_config)
    orch = Orchestrator(team, HierarchicalWorkflow())
    raw = "```python\nx = 1\n```"

    _handle_slash_command("/copy", team, orch, [False], None, [raw])
    assert raw in capsys.readouterr().out


def test_usage_line_is_one_line():
    from openswarm.cli.interactive import _usage_line
    from openswarm.core.usage import RunUsage, UsageStats

    line = _usage_line(RunUsage(entries=[UsageStats("a", "m", 10, 5)]))
    assert "\n" not in line
    assert "15 tokens" in line


def test_history_file_lands_in_the_config_dir(tmp_path, monkeypatch):
    from openswarm.cli.interactive import _history_file

    monkeypatch.setenv("OPENSWARM_CONFIG_DIR", str(tmp_path / "cfg"))
    history = _history_file()

    assert history is not None
    assert (tmp_path / "cfg").is_dir()


# --- @file attachment, !shell, /model, /retry ---


def test_file_mention_inlines_content(tmp_path, monkeypatch):
    """Agents have no filesystem, so a bare path tells them nothing."""
    from openswarm.cli.interactive import expand_file_mentions

    target = tmp_path / "notes.md"
    target.write_text("SECRET_MARKER content")
    monkeypatch.chdir(tmp_path)

    expanded, attached = expand_file_mentions("summarise @notes.md please")

    assert "SECRET_MARKER content" in expanded
    assert attached == ["notes.md"]
    assert "@notes.md" not in expanded


def test_unresolvable_mention_is_left_alone():
    from openswarm.cli.interactive import expand_file_mentions

    expanded, attached = expand_file_mentions("ask @someone about @nope.txt")

    assert expanded == "ask @someone about @nope.txt"
    assert attached == []


def test_large_attachment_is_truncated(tmp_path, monkeypatch):
    from openswarm.cli.interactive import MAX_ATTACHED_CHARS, expand_file_mentions

    big = tmp_path / "big.log"
    big.write_text("x" * (MAX_ATTACHED_CHARS + 5_000))
    monkeypatch.chdir(tmp_path)

    expanded, attached = expand_file_mentions("@big.log")

    assert "[truncated]" in expanded
    assert len(expanded) < MAX_ATTACHED_CHARS + 500
    assert attached == ["big.log"]


def test_model_swap_updates_config_and_client(team_config: TeamConfig):
    """/team must not report a model the agent is no longer using."""
    from openswarm.cli.interactive import _handle_slash_command

    team = Team(team_config)
    orch = Orchestrator(team, HierarchicalWorkflow())

    _handle_slash_command("/model worker new-model-x", team, orch, [False])

    assert team.config.get_agent("worker").model == "new-model-x"
    assert team.agents["worker"].llm.model == "new-model-x"


def test_model_swap_rejects_unknown_agent(team_config: TeamConfig):
    from openswarm.cli.interactive import _handle_slash_command

    team = Team(team_config)
    orch = Orchestrator(team, HierarchicalWorkflow())

    _handle_slash_command("/model ghost some-model", team, orch, [False])

    assert all(a.model != "some-model" for a in team.config.agents)


def test_model_swap_needs_two_arguments(team_config: TeamConfig):
    from openswarm.cli.interactive import _handle_slash_command

    team = Team(team_config)
    orch = Orchestrator(team, HierarchicalWorkflow())
    assert _handle_slash_command("/model worker", team, orch, [False]) is False


def test_shell_escape_runs_the_command(capsys):
    from openswarm.cli.interactive import _run_shell

    _run_shell("echo REPL_SHELL_OK")
    assert "REPL_SHELL_OK" in capsys.readouterr().out


def test_shell_escape_reports_failure(capsys):
    from openswarm.cli.interactive import _run_shell

    _run_shell("exit 3")
    assert "exit 3" in capsys.readouterr().out


# --- streaming shows the answer, not the protocol envelope ---


def _stream(chunks: list[str]) -> str:
    from openswarm.cli.interactive import ContentStream

    f = ContentStream()
    return "".join(f.feed(c) for c in chunks)


def test_stream_emits_only_the_content_field():
    out = _stream(['{"action": "res', 'ult", "con', 'tent": "hello ', 'world"}'])
    assert out == "hello world"


def test_stream_decodes_escapes_as_they_arrive():
    out = _stream(['{"action":"respond","content":"line1\\nline2\\n', '```py\\ncode()\\n```"}'])
    assert out == "line1\nline2\n```py\ncode()\n```"
    assert "\\n" not in out


def test_stream_stops_at_the_closing_quote():
    out = _stream(['{"action":"respond","content":"done","to":"lead"}'])
    assert out == "done"


def test_stream_passes_prose_through():
    """Models that ignore the protocol should still be watchable."""
    out = _stream(["The bug is ", "an off-by-one."])
    assert out == "The bug is an off-by-one."


def test_stream_hides_an_envelope_with_no_content():
    """A delegate envelope carries no user-facing text — show nothing."""
    out = _stream(['{"action": "delegate", "to": "worker", "task": "do it"}'])
    assert out == ""


def test_stream_handles_escaped_quotes_in_content():
    out = _stream(['{"content": "say \\"hi\\" now"}'])
    assert out == 'say "hi" now'


# --- thinking indicator ---


def test_thinking_indicator_starts_updates_and_stops():
    from openswarm.cli.interactive import Thinking

    t = Thinking()
    assert t._status is None

    t.show("senior is thinking...")
    assert t._status is not None
    t.show("junior is thinking...")  # update, not a second spinner
    first = t._status

    t.show("junior is thinking...")
    assert t._status is first

    t.hide()
    assert t._status is None
    t.hide()  # idempotent: the finally-block calls it even when never shown


def test_streamed_output_stops_the_spinner():
    """Once real text arrives the spinner must get out of the way."""
    from openswarm.cli.interactive import Thinking, _make_stream_printer

    t = Thinking()
    t.show("senior is thinking...")
    printer = _make_stream_printer(t)

    printer("senior", '{"action":"respond","content":"hel')
    assert t._status is None


def test_spinner_survives_envelope_only_chunks():
    """Delegation envelopes produce no visible text, so keep thinking."""
    from openswarm.cli.interactive import Thinking, _make_stream_printer

    t = Thinking()
    t.show("senior is thinking...")
    printer = _make_stream_printer(t)

    printer("senior", '{"action": "delegate", "to": "junior"}')
    assert t._status is not None
    t.hide()


def test_announcer_names_the_working_agent():
    from openswarm.cli.interactive import Thinking, _make_announcer
    from openswarm.core.message import Message, MessageType

    t = Thinking()
    seen = []
    announce = _make_announcer(t, seen.append)

    announce(Message(from_agent="lead", to_agent="junior", type=MessageType.TASK, content="go"))
    assert t._status is not None
    assert len(seen) == 1  # the user's own on_message still fires

    t.hide()
    announce(Message(from_agent="lead", to_agent="user", type=MessageType.RESULT, content="done"))
    assert t._status is None  # nothing is "thinking" when the answer is for the user


def test_stream_hides_xml_tool_calls():
    """The approval prompt renders these; they should not scroll past as markup."""
    out = _stream(['<minimax:tool_call>\n<invoke name="write_file">\n', "<parameter"])
    assert out == ""
