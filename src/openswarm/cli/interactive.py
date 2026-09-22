"""Interactive REPL for chatting with agent teams."""

from __future__ import annotations

import asyncio
import re
import select
import subprocess
import sys
import termios
import threading
import tty
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.markdown import Markdown

from openswarm.cli.questions import _structured_questions, ask_questions, parse_questions
from openswarm.cli.utils import make_message_printer, make_status_updater, print_usage_table
from openswarm.config.discovery import get_config_dir
from openswarm.core.orchestrator import Orchestrator
from openswarm.core.team import Team
from openswarm.core.usage import RunUsage
from openswarm.llm.client import LLMClient
from openswarm.workflow import get_workflow

console = Console()

#: Two restrained shades, not a palette: enough to tell agents apart without
#: turning a developer tool into a colour chart.
AGENT_COLORS = ("cyan", "blue")


def agent_color(name: str) -> str:
    return AGENT_COLORS[sum(name.encode()) % len(AGENT_COLORS)]


SLASH_COMMANDS = {
    "/help": "Show these commands",
    "/quit": "Exit the REPL",
    "/team": "Show current team info",
    "/history": "Show message history",
    "/usage": "Show token usage and cost for this session",
    "/save": "Save the last result: /save notes.md",
    "/copy": "Print the last result unrendered, for copying",
    "/retry": "Run the previous task again",
    "/model": "Swap an agent's model: /model junior deepseek-chat",
    "/clear": "Clear message history",
    "/stream": "Toggle streaming output on/off",
}

#: Attached files are truncated so one `@big.log` cannot blow the context window.
MAX_ATTACHED_CHARS = 20_000

FILE_MENTION = re.compile(r"@([\w./~+-]+)")


class SlashCompleter(Completer):
    """Complete slash commands, showing each description alongside."""

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.lstrip()
        if not text.startswith("/") or " " in text:
            return
        for name, desc in SLASH_COMMANDS.items():
            if name.startswith(text):
                yield Completion(name, start_position=-len(text), display_meta=desc)


def _history_file() -> FileHistory | None:
    """Persist prompt history across sessions, as any decent REPL does."""
    try:
        path = get_config_dir()
        path.mkdir(parents=True, exist_ok=True)
        return FileHistory(str(path / "history"))
    except OSError:
        return None  # read-only home: history is a nicety, not a reason to fail


def expand_file_mentions(text: str) -> tuple[str, list[str]]:
    """Inline the contents of any `@path` mention.

    Agents have no filesystem access, so a path alone means nothing to them.
    Mentions that do not resolve to a readable file are left as typed.
    """
    attached: list[str] = []

    def replace(match: re.Match) -> str:
        path = Path(match.group(1)).expanduser()
        try:
            if not path.is_file():
                return match.group(0)
            content = path.read_text(errors="replace")
        except OSError:
            return match.group(0)

        if len(content) > MAX_ATTACHED_CHARS:
            content = content[:MAX_ATTACHED_CHARS] + "\n... [truncated]"
        attached.append(str(path))
        return f"\n\n--- {path} ---\n{content}\n--- end of {path} ---\n"

    return FILE_MENTION.sub(replace, text), attached


def _run_shell(command: str) -> None:
    """Run a shell command without leaving the REPL, like `!` in Claude Code."""
    if not command:
        console.print("[red]Usage: !<command>[/red]\n")
        return
    try:
        # The user typed this for their own shell; that is the entire point.
        done = subprocess.run(command, shell=True, capture_output=True, text=True)
    except OSError as e:
        console.print(f"[red]Could not run: {e}[/red]\n")
        return
    if done.stdout:
        print(done.stdout, end="")
    if done.stderr:
        console.print(f"[red]{done.stderr}[/red]", end="")
    if done.returncode:
        console.print(f"[dim]exit {done.returncode}[/dim]", highlight=False)
    console.print()


def _key_bindings() -> KeyBindings:
    """Enter sends; a trailing backslash or Esc+Enter continues on a new line."""
    kb = KeyBindings()

    @kb.add("enter")
    def _submit_or_continue(event) -> None:
        buffer = event.current_buffer
        if buffer.text.rstrip().endswith("\\"):
            buffer.insert_text("\n")
        else:
            buffer.validate_and_handle()

    @kb.add("escape", "enter")
    def _newline(event) -> None:
        event.current_buffer.insert_text("\n")

    return kb


HANDOFF_ARROWS = {
    "task": "→",
    "review": "⟲",
    "question": "?",
    "result": "←",
    "revision": "←",
    "answer": "←",
}


def _show_handoff(msg) -> None:
    """Print one dim line per agent-to-agent handoff.

    A team working is the thing worth watching here, and it was only visible
    with -v before.
    """
    if msg.from_agent in ("user", "system") or msg.to_agent in ("user", "system", "all"):
        return
    arrow = HANDOFF_ARROWS.get(msg.type.value, "·")
    summary = " ".join(msg.content.split())[:60]
    if len(" ".join(msg.content.split())) > 60:
        summary += "…"
    sender, receiver = agent_color(msg.from_agent), agent_color(msg.to_agent)
    console.print(
        f"  [{sender}]{msg.from_agent}[/{sender}] [dim]{arrow}[/dim] "
        f"[{receiver}]{msg.to_agent}[/{receiver}]  [dim]{summary}[/dim]"
    )


def _make_announcer(thinking: Thinking, on_message) -> callable:
    """Name whoever is about to work, so the wait is not anonymous.

    Built outside the loop so the closure captures this turn's indicator.
    """

    def announce(msg) -> None:
        _show_handoff(msg)
        if msg.to_agent not in ("user", "system"):
            colour = agent_color(msg.to_agent)
            thinking.show(f"[{colour}]●[/{colour}] {msg.to_agent} thinking...")
        if on_message is not None:
            on_message(msg)

    return announce


def _render_result(text: str) -> None:
    """Render a result as markdown so code blocks stay readable.

    Deliberately unboxed: a border around every answer wastes width and makes a
    session look like a form. `/copy` prints the unrendered text.
    """
    console.print()
    console.print(Markdown(text))


def _usage_line(usage: RunUsage) -> str:
    """One-line run summary; the full table is on /usage."""
    parts = []
    elapsed = sum(entry.elapsed_seconds for entry in usage.entries)
    if elapsed:
        parts.append(f"{elapsed:.1f}s")
    parts.append(f"{usage.total_tokens} tokens")
    if usage.total_cost is not None:
        parts.append(f"${usage.total_cost:.4f}")
    return "[dim]" + " · ".join(parts) + "[/dim]"


def _handle_slash_command(
    command: str,
    team: Team,
    orchestrator: Orchestrator,
    stream_state: list[bool],
    session_usage: RunUsage | None = None,
    last_result: list[str] | None = None,
) -> bool:
    """Handle slash command. Return True if REPL should exit."""
    raw = command.strip()
    cmd, _, arg = raw.partition(" ")
    cmd = cmd.lower()
    arg = arg.strip()

    if cmd in ("/quit", "/exit", "/q"):
        return True

    if cmd == "/help":
        console.print()
        width = max(len(name) for name in SLASH_COMMANDS)
        for name, desc in SLASH_COMMANDS.items():
            console.print(f"  [bold cyan]{name:<{width}}[/bold cyan]  [dim]{desc}[/dim]")
        console.print("\n[dim]Ctrl+C cancels a running task · Ctrl+D exits[/dim]\n")
        return False

    if cmd == "/usage":
        if session_usage is None or not session_usage.entries:
            console.print("[dim]No usage recorded yet.[/dim]\n")
        else:
            print_usage_table(session_usage)
            console.print()
        return False

    if cmd == "/save":
        if not arg:
            console.print("[red]Usage: /save <path>[/red]\n")
            return False
        if not last_result or not last_result[0]:
            console.print("[dim]Nothing to save yet.[/dim]\n")
            return False
        try:
            Path(arg).expanduser().write_text(last_result[0])
            console.print(f"[green]Saved to {arg}[/green]\n")
        except OSError as e:
            console.print(f"[red]Could not write {arg}: {e}[/red]\n")
        return False

    if cmd == "/copy":
        if not last_result or not last_result[0]:
            console.print("[dim]Nothing to copy yet.[/dim]\n")
        else:
            # Unrendered and unpanelled, so it can be selected and pasted.
            print(last_result[0])
            console.print()
        return False

    if cmd == "/team":
        console.print(f"\nTeam: [bold]{team.config.name}[/bold]")
        console.print(f"Goal: {team.config.goal}")
        console.print(f"Workflow: {team.config.workflow.type}")
        console.print(f"Lead: {team.config.workflow.lead}")
        for ac in team.config.agents:
            console.print(f"  • {ac.name} ({ac.role}) — {ac.model}")
        console.print()
        return False

    if cmd == "/history":
        if not orchestrator.message_log:
            console.print("[dim]No messages yet.[/dim]\n")
        else:
            console.print(f"\n[bold]Messages ({len(orchestrator.message_log)}):[/bold]")
            for msg in orchestrator.message_log:
                console.print(
                    f"  {msg.from_agent} → {msg.to_agent} ({msg.type.value}): "
                    f"{msg.content[:120]}{'...' if len(msg.content) > 120 else ''}"
                )
            console.print()
        return False

    if cmd == "/model":
        parts = arg.split()
        if len(parts) != 2:
            console.print("[red]Usage: /model <agent> <model>[/red]\n")
            return False
        name, new_model = parts
        if name not in team.agents:
            console.print(
                f"[red]No agent '{name}'. Team has: {', '.join(team.agent_names)}[/red]\n"
            )
            return False
        old = team.config.get_agent(name)
        updated = old.model_copy(update={"model": new_model})
        # Config and live client both, or /team would report a stale model.
        team.config.agents[team.config.agents.index(old)] = updated
        team.agents[name].llm = LLMClient(updated)
        console.print(f"[green]{name}: {old.model} → {new_model}[/green]\n")
        return False

    if cmd == "/clear":
        orchestrator.message_log.clear()
        for agent in orchestrator.team.agents.values():
            agent.clear_history()
        console.print("[dim]Message history cleared.[/dim]\n")
        return False

    if cmd == "/stream":
        stream_state[0] = not stream_state[0]
        status = "on" if stream_state[0] else "off"
        console.print(f"[dim]Streaming {status}.[/dim]\n")
        return False

    console.print(f"[red]Unknown command: {cmd}[/red]")
    console.print("Available: " + ", ".join(SLASH_COMMANDS) + "\n")
    return False


class ContentStream:
    """Turn a stream of protocol JSON into just the text the user cares about.

    Agents answer with `{"action": ..., "content": "..."}`, so streaming raw
    tokens shows the envelope and the escape sequences. This emits only the
    `content` string, decoded. A model that answers in prose instead of JSON is
    passed through untouched; if neither shape appears, nothing is shown and the
    rendered result still arrives at the end.
    """

    def __init__(self) -> None:
        self._pending = ""
        self._mode = "undecided"
        self._escaped = False

    def feed(self, chunk: str) -> str:
        if self._mode == "done":
            return ""
        if self._mode == "prose":
            return chunk

        self._pending += chunk

        if self._mode == "undecided":
            stripped = self._pending.lstrip()
            if not stripped:
                return ""
            if stripped[0] == "<":
                # A tool call in XML form: the approval prompt renders it
                # properly, so it should not also scroll past as raw markup.
                self._mode = "done"
                return ""
            if stripped[0] not in "{`":
                self._mode = "prose"
                out, self._pending = self._pending, ""
                return out
            self._mode = "seeking"

        if self._mode == "seeking":
            match = re.search(r'"content"\s*:\s*"', self._pending)
            if not match:
                return ""
            self._pending = self._pending[match.end() :]
            self._mode = "emitting"

        return self._drain()

    def _drain(self) -> str:
        out = []
        for char in self._pending:
            if self._escaped:
                out.append({"n": "\n", "t": "\t", "r": ""}.get(char, char))
                self._escaped = False
            elif char == "\\":
                self._escaped = True
            elif char == '"':
                self._mode = "done"
                break
            else:
                out.append(char)
        self._pending = ""
        return "".join(out)


class QueuedInput:
    """Collect lines typed while the team is working.

    Claude Code lets you keep typing during a turn and runs what you queued when
    it finishes. Reading happens on a worker thread so the orchestrator is never
    blocked waiting on a keystroke.
    """

    def __init__(self, on_typing=None) -> None:
        self.lines: list[str] = []
        self._typed = ""
        self._in_escape = False
        self._on_typing = on_typing
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not sys.stdin.isatty():
            return  # nothing to collect from a pipe
        self._stop.clear()
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _echo(self) -> None:
        if self._on_typing is not None:
            self._on_typing(self._typed)

    def _read(self) -> None:
        """Read keystrokes without waiting for Enter, so typing is visible.

        The terminal's own echo would be overwritten by the spinner, so echo is
        switched off here and the buffer is drawn in the spinner line instead.
        """
        try:
            settings = termios.tcgetattr(sys.stdin)
        except (termios.error, ValueError):
            return  # not a real terminal after all
        try:
            tty.setcbreak(sys.stdin.fileno())
            while not self._stop.is_set():
                ready, _, _ = select.select([sys.stdin], [], [], 0.1)
                if not ready:
                    continue
                char = sys.stdin.read(1)
                if not char:
                    return
                self.feed(char)
        finally:
            # Always hand the terminal back the way it was found.
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, settings)

    def feed(self, char: str) -> None:
        """Apply one keystroke: Enter queues the line, backspace deletes.

        Escape sequences (arrows, function keys) are swallowed: they are not
        text, and letting them through queues rubbish like "[A[B".
        """
        if self._in_escape:
            # CSI sequences end at the first letter or '~'.
            if char.isalpha() or char == "~":
                self._in_escape = False
            return
        if char == "\x1b":
            self._in_escape = True
            return
        if char in "\r\n":
            text = self._typed.strip()
            self._typed = ""
            self._echo()
            if text:
                self.lines.append(text)
                console.print(f"[dim]queued: {text}[/dim]")
        elif char in ("\x7f", "\b"):
            self._typed = self._typed[:-1]
            self._echo()
        elif char.isprintable():
            self._typed += char
            self._echo()

    def stop(self) -> None:
        """Release stdin, keeping anything already typed."""
        self._stop.set()
        self._typed = ""
        self._echo()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def drain(self) -> list[str]:
        """Stop collecting and hand back whatever was typed."""
        self.stop()
        queued, self.lines = self.lines, []
        return queued


class Pausable:
    """Hand the terminal to an approval prompt, then give it back.

    Both the spinner and the queue reader own part of the terminal; a prompt
    needs all of it, so they are paused together.
    """

    def __init__(self, *targets) -> None:
        self._targets = targets

    def stop(self) -> None:
        for target in self._targets:
            target.stop()

    def start(self) -> None:
        for target in self._targets:
            target.start()


class Thinking:
    """Animated indicator for the wait before an agent produces visible text.

    Reasoning models spend that time thinking, and the protocol envelope is
    filtered out, so without this the terminal just sits blank.
    """

    def __init__(self) -> None:
        self._status = None
        self._label = ""
        self._typed = ""

    def show(self, label: str) -> None:
        self._label = label
        if self._status is None:
            self._status = console.status("", spinner="dots")
            self._status.start()
        self._refresh()

    def set_typed(self, text: str) -> None:
        """Draw what the user is typing, since terminal echo is switched off."""
        self._typed = text
        if self._status is not None:
            self._refresh()

    def _refresh(self) -> None:
        line = self._label
        if self._typed:
            line += f"\n[ansicyan bold]>[/ansicyan bold] {self._typed} [dim](queued on Enter)[/dim]"
        self._status.update(line)

    def hide(self) -> None:
        if self._status is not None:
            self._status.stop()
            self._status = None

    # stop/start let an approval prompt borrow the terminal, then hand it back.
    def stop(self) -> None:
        if self._status is not None:
            self._status.stop()
            self._status = None

    def start(self) -> None:
        if self._label:
            self.show(self._label)


def _make_stream_printer(thinking: Thinking | None = None) -> callable:
    """Create a progress callback that prints an agent's answer as it arrives."""
    current_agent: list[str] = [""]
    filters: dict[str, ContentStream] = {}

    def on_progress(agent_name: str, chunk: str) -> None:
        text = filters.setdefault(agent_name, ContentStream()).feed(chunk)
        if not text:
            return
        if thinking is not None:
            thinking.hide()  # real output beats a spinner
        if agent_name != current_agent[0]:
            if current_agent[0]:
                console.print()
            colour = agent_color(agent_name)
            console.print(
                f"[{colour}]●[/{colour}] [bold {colour}]{agent_name}[/bold {colour}] ", end=""
            )
            current_agent[0] = agent_name
        console.print(text, end="", highlight=False, markup=False)

    return on_progress


def _print_welcome(team: Team, on_tool) -> None:
    """Opening screen: who is on the team, which models, and where they can write."""
    from openswarm import __version__

    console.print()
    console.print(
        f"[bold cyan]OpenSwarm[/bold cyan] [dim]v{__version__}[/dim]  "
        f"[bold]{team.config.name}[/bold] [dim]· {team.config.workflow.type}[/dim]"
    )
    console.print(f"[dim]{team.config.goal}[/dim]\n")

    for name in team.agent_names:
        colour = agent_color(name)
        lead = " [dim](lead)[/dim]" if name == team.config.workflow.lead else ""
        console.print(
            f"  [{colour}]●[/{colour}] [bold]{name}[/bold]{lead}  "
            f"[dim]{team.config.get_agent(name).model}[/dim]"
        )

    console.print()
    if on_tool is not None:
        console.print(f"  [dim]workspace[/dim] {Path.cwd()} [dim]— actions ask first[/dim]")
    else:
        console.print("  [dim]workspace actions off (--no-tools)[/dim]")
    console.print("  [dim]/help  ·  @file attaches  ·  !cmd runs a shell command[/dim]\n")


def run_interactive(team: Team, verbose: bool = False, on_tool=None, pauser=None) -> None:
    """Run the interactive REPL loop."""
    workflow = get_workflow(team.config.workflow.type)
    orchestrator = Orchestrator(team, workflow)
    on_message = make_message_printer() if verbose else None
    stream_state: list[bool] = [True]  # watching it work beats staring at a spinner
    session_usage = RunUsage()
    last_result: list[str] = [""]
    last_task: list[str] = [""]
    pending: list[str] = []  # typed while the team was working

    _print_welcome(team, on_tool)

    def toolbar() -> str:
        parts = [team.config.name, team.config.workflow.type]
        if not stream_state[0]:
            parts.append("stream off")
        parts.append(f"{session_usage.total_tokens} tokens")
        if session_usage.total_cost:
            parts.append(f"${session_usage.total_cost:.4f}")
        return "  " + "  ·  ".join(parts)

    session: PromptSession[str] = PromptSession(
        FormattedText([("ansicyan bold", "> ")]),
        completer=SlashCompleter(),
        auto_suggest=AutoSuggestFromHistory(),
        history=_history_file(),
        bottom_toolbar=toolbar,
        placeholder=FormattedText([("class:placeholder", "Ask the team to build something...")]),
        style=Style.from_dict({"placeholder": "#6a6a6a italic"}),
        multiline=True,
        key_bindings=_key_bindings(),
        prompt_continuation="  ",
    )

    while True:
        if pending:
            user_input = pending.pop(0)
            console.print(f"[ansicyan bold]>[/ansicyan bold] {user_input} [dim](queued)[/dim]")
        else:
            try:
                with patch_stdout():
                    user_input = session.prompt()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Bye.[/dim]")
                break

        text = user_input.strip()
        if not text:
            continue

        # Continuation backslashes are input syntax, not part of the task.
        text = re.sub(r"\\\s*\n", "\n", text).strip()

        if text.startswith("!"):
            _run_shell(text[1:].strip())
            continue

        if text == "/retry":
            if not last_task[0]:
                console.print("[dim]Nothing to retry yet.[/dim]\n")
                continue
            text = last_task[0]
            console.print(f"[dim]retrying: {text.splitlines()[0][:70]}[/dim]")

        if text.startswith("/"):
            should_exit = _handle_slash_command(
                text, team, orchestrator, stream_state, session_usage, last_result
            )
            if should_exit:
                console.print("[dim]Bye.[/dim]")
                break
            continue

        last_task[0] = text
        text, attached = expand_file_mentions(text)
        if attached:
            console.print(f"[dim]attached: {', '.join(attached)}[/dim]")

        thinking = Thinking()
        queue = QueuedInput(on_typing=thinking.set_typed)
        if pauser is not None:
            # An approval prompt needs the whole terminal: no spinner drawing
            # over it, and no background reader eating its keystrokes.
            pauser.status = Pausable(thinking, queue)
        on_progress = _make_stream_printer(thinking) if stream_state[0] else None
        show_status = not stream_state[0] and not verbose

        announce = _make_announcer(thinking, on_message)

        questions_to_ask: list = []
        queue.start()
        try:
            if show_status:
                with console.status("[dim]working...[/dim]", spinner="dots") as st:
                    run_result = asyncio.run(
                        orchestrator.run(text, on_message=make_status_updater(st), on_tool=on_tool)
                    )
            else:
                run_result = asyncio.run(
                    orchestrator.run(
                        text, on_message=announce, on_progress=on_progress, on_tool=on_tool
                    )
                )
            if stream_state[0]:
                console.print("\n")
            last_result[0] = run_result.result
            session_usage.entries.extend(run_result.usage.entries)
            asked = parse_questions(run_result.result) if on_tool is not None else []
            questions_to_ask = asked
            if asked and _structured_questions(run_result.result):
                # An ask_user payload is scaffolding, not an answer: show the
                # form rather than the JSON behind it.
                pass
            elif on_progress is None:
                _render_result(run_result.result)
            else:
                # Streaming already printed it live — printing it again is the
                # same answer twice. `/copy` still has the raw text.
                console.print()
            console.print(_usage_line(run_result.usage))
            console.print("[dim]" + "─" * min(console.width, 60) + "[/dim]")

        except KeyboardInterrupt:
            console.print("\n[dim]Cancelled.[/dim]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
        finally:
            thinking.hide()
            pending.extend(queue.drain())

        # Only now, with the spinner stopped and the reader off stdin, can a
        # form have the terminal to itself.
        if questions_to_ask:
            composed = ask_questions(questions_to_ask)
            if composed:
                pending.insert(0, composed)

        console.print()
