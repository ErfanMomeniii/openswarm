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


# --- the spinner must not fight the approval prompt for the terminal ---


def test_pauser_stops_and_restarts_the_thinking_spinner():
    from openswarm.cli.app import StatusPauser
    from openswarm.cli.interactive import Thinking

    thinking = Thinking()
    thinking.show("junior thinking...")
    pauser = StatusPauser()
    pauser.status = thinking

    assert thinking._status is not None
    with pauser.paused():
        assert thinking._status is None  # terminal handed over to the prompt
    assert thinking._status is not None  # and handed back

    thinking.hide()


def test_approval_prompt_runs_with_the_spinner_paused():
    """The REPL hung because the spinner kept drawing over the menu."""
    import pathlib

    from openswarm.cli.app import StatusPauser
    from openswarm.cli.interactive import Thinking
    from openswarm.cli.utils import make_tool_approver
    from openswarm.core.tools import ToolRequest

    thinking = Thinking()
    thinking.show("junior thinking...")
    pauser = StatusPauser()
    pauser.status = thinking

    spinner_during_prompt: list[bool] = []

    def chooser(options):
        spinner_during_prompt.append(thinking._status is not None)
        return 3  # No

    approve = make_tool_approver(pathlib.Path("/tmp"), pause=pauser.paused, chooser=chooser)
    approve(ToolRequest(kind="read_file", path="ali.txt"))

    assert spinner_during_prompt == [False]
    thinking.hide()


def test_interactive_is_given_a_pauser():
    """A missing pause hook is exactly what caused the hang, so assert the wiring."""
    import inspect

    from openswarm.cli import app as cli_app

    source = inspect.getsource(cli_app.interactive)
    assert "pause=pauser.paused" in source
    assert "pauser=pauser" in source


# --- typing while the team works ---


def test_typing_is_queued_on_enter():
    """Characters accumulate, Enter commits the line, Backspace corrects it."""
    from openswarm.cli.interactive import QueuedInput

    echoed: list[str] = []
    queue = QueuedInput(on_typing=echoed.append)

    for char in "next taskX":
        queue.feed(char)
    queue.feed("\x7f")  # backspace removes the stray X
    assert echoed[-1] == "next task"
    assert queue.lines == []  # nothing queued until Enter

    queue.feed("\r")
    assert queue.lines == ["next task"]
    assert echoed[-1] == ""  # the line is cleared once queued


def test_blank_line_queues_nothing():
    from openswarm.cli.interactive import QueuedInput

    queue = QueuedInput()
    queue.feed("\r")
    queue.feed(" ")
    queue.feed("\r")

    assert queue.lines == []


def test_queue_is_not_started_without_a_terminal(monkeypatch):
    """Piped sessions have no one typing; a reader would eat the pipe."""
    import io

    from openswarm.cli.interactive import QueuedInput

    monkeypatch.setattr("openswarm.cli.interactive.sys.stdin", io.StringIO("data\n"))
    monkeypatch.setattr("openswarm.cli.interactive.sys.stdin.isatty", lambda: False, raising=False)

    queue = QueuedInput()
    queue.start()

    assert queue._thread is None
    assert queue.drain() == []


def test_pausable_releases_stdin_and_the_spinner_together():
    """The approval menu needs the terminal to itself, or keystrokes go missing."""
    from openswarm.cli.interactive import Pausable, QueuedInput, Thinking

    thinking = Thinking()
    thinking.show("junior thinking...")
    queue = QueuedInput()
    both = Pausable(thinking, queue)

    both.stop()
    assert thinking._status is None
    assert queue._thread is None

    thinking.hide()


def test_queued_lines_survive_a_pause():
    """Pausing for an approval must not throw away what was already typed."""
    from openswarm.cli.interactive import QueuedInput

    queue = QueuedInput()
    queue.lines.append("do the next thing")
    queue.stop()

    assert queue.drain() == ["do the next thing"]


def test_usage_line_reports_elapsed_time():
    """When you are waiting, how long it took matters as much as what it cost."""
    from openswarm.cli.interactive import _usage_line
    from openswarm.core.usage import RunUsage, UsageStats

    line = _usage_line(
        RunUsage(
            entries=[
                UsageStats("a", "m", 10, 5, elapsed_seconds=2.0),
                UsageStats("b", "m", 10, 5, elapsed_seconds=1.5),
            ]
        )
    )

    assert "3.5s" in line
    assert "30 tokens" in line
    assert "\n" not in line


def test_usage_line_without_timings_still_reads_well():
    from openswarm.cli.interactive import _usage_line
    from openswarm.core.usage import RunUsage, UsageStats

    assert _usage_line(RunUsage(entries=[UsageStats("a", "m", 10, 5)])) == "[dim]15 tokens[/dim]"


def test_terminal_settings_are_always_restored(monkeypatch):
    """Raw mode left on would wreck the user's shell after an error."""
    import openswarm.cli.interactive as interactive

    restored: list[str] = []
    monkeypatch.setattr(interactive.termios, "tcgetattr", lambda fd: "original")
    monkeypatch.setattr(
        interactive.termios, "tcsetattr", lambda fd, when, value: restored.append(value)
    )
    monkeypatch.setattr(interactive.tty, "setcbreak", lambda fd: None)
    monkeypatch.setattr(interactive.select, "select", lambda *a: (_ for _ in ()).throw(OSError()))

    queue = interactive.QueuedInput()
    with pytest.raises(OSError):
        queue._read()

    assert restored == ["original"]


def test_reader_gives_up_quietly_when_stdin_is_not_a_terminal(monkeypatch):
    import openswarm.cli.interactive as interactive

    def no_tty(fd):
        raise interactive.termios.error("not a tty")

    monkeypatch.setattr(interactive.termios, "tcgetattr", no_tty)

    interactive.QueuedInput()._read()  # must not raise


def test_each_agent_keeps_a_stable_colour():
    """A transcript is only scannable if an agent looks the same every turn."""
    from openswarm.cli.interactive import AGENT_COLORS, agent_color

    assert agent_color("senior") == agent_color("senior")
    assert agent_color("senior") in AGENT_COLORS
    assert agent_color("junior") in AGENT_COLORS


def test_handoffs_between_agents_are_shown(capsys):
    """Watching the team delegate is the point; it used to need -v."""
    import re

    from openswarm.cli.interactive import _show_handoff
    from openswarm.core.message import Message, MessageType

    _show_handoff(
        Message(
            from_agent="senior",
            to_agent="junior",
            type=MessageType.TASK,
            content="Write the User model",
        )
    )
    out = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)

    assert "senior" in out and "junior" in out and "→" in out
    assert "Write the User model" in out


def test_messages_to_the_user_are_not_handoffs(capsys):
    from openswarm.cli.interactive import _show_handoff
    from openswarm.core.message import Message, MessageType

    _show_handoff(
        Message(from_agent="user", to_agent="senior", type=MessageType.TASK, content="hi")
    )
    _show_handoff(
        Message(from_agent="senior", to_agent="user", type=MessageType.RESULT, content="done")
    )

    assert capsys.readouterr().out == ""


def test_long_handoff_content_is_truncated(capsys):
    import re

    from openswarm.cli.interactive import _show_handoff
    from openswarm.core.message import Message, MessageType

    _show_handoff(
        Message(from_agent="a", to_agent="b", type=MessageType.TASK, content="word " * 200)
    )
    out = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)

    assert "…" in out
    assert len(out) < 120


# --- the first screen ---


def _welcome(team, on_tool, capsys) -> str:
    import re

    from openswarm.cli.interactive import _print_welcome

    _print_welcome(team, on_tool)
    return re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)


def test_welcome_names_the_models_you_will_pay_for(team_config: TeamConfig, capsys):
    out = _welcome(Team(team_config), None, capsys)

    assert "lead" in out
    for agent in team_config.agents:
        assert agent.name in out
        assert agent.model in out


def test_welcome_says_where_agents_can_write(team_config: TeamConfig, capsys):
    """Tools are on by default, so the workspace must be stated up front."""
    out = _welcome(Team(team_config), lambda request: "", capsys)

    assert "workspace" in out
    assert "ask first" in out


def test_welcome_says_when_actions_are_off(team_config: TeamConfig, capsys):
    out = _welcome(Team(team_config), None, capsys)

    assert "--no-tools" in out


def test_arrow_keys_are_not_queued_as_text():
    """Arrows reached the reader as escape sequences and queued rubbish: "[A[B"."""
    from openswarm.cli.interactive import QueuedInput

    queue = QueuedInput()
    for char in "\x1b[A\x1b[B\x1b[B":  # up, down, down
        queue.feed(char)

    assert queue._typed == ""

    for char in "real text":
        queue.feed(char)
    queue.feed("\r")

    assert queue.lines == ["real text"]


def test_question_form_runs_after_the_turn_winds_down():
    """The form needs stdin to itself; a live spinner or reader breaks it."""
    import inspect

    from openswarm.cli import interactive

    source = inspect.getsource(interactive.run_interactive)
    finally_at = source.index("pending.extend(queue.drain())")
    form_at = source.index("ask_questions(questions_to_ask)")

    assert form_at > finally_at
