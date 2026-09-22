"""Shared CLI utilities."""

from __future__ import annotations

import asyncio
import difflib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from prompt_toolkit.styles import Style
from rich.console import Console
from rich.table import Table

from openswarm.config.discovery import config_source
from openswarm.config.models import TeamConfig
from openswarm.core.message import Message
from openswarm.core.tools import ToolRequest
from openswarm.core.usage import RunUsage

console = Console()

#: Direction, not decoration: outbound work is cyan, returning work is green.
MESSAGE_COLORS = {
    "task": "cyan",
    "review": "cyan",
    "question": "cyan",
    "result": "green",
    "revision": "green",
    "answer": "green",
}


def make_message_printer() -> Callable[[Message], None]:
    """Return a callback that pretty-prints messages in real-time."""

    def _print_message(msg: Message) -> None:
        color = MESSAGE_COLORS.get(msg.type.value, "dim")
        truncated = msg.content[:200] + ("..." if len(msg.content) > 200 else "")
        console.print(
            f"  [{color}]{msg.from_agent} → {msg.to_agent}[/{color}] "
            f"({msg.type.value}): {truncated}"
        )

    return _print_message


def make_status_updater(status) -> Callable[[Message], None]:
    """Return a callback that reflects the active agent in a Rich status spinner.

    Messages are logged as they are handed to their recipient, so `to_agent` is
    whoever is about to burn tokens.
    """

    def _update(msg: Message) -> None:
        if msg.to_agent in ("user", "system"):
            return
        status.update(f"[dim]{msg.to_agent} working — {msg.type.value}...[/dim]")

    return _update


def print_team_summary(config: TeamConfig, path: Path | None = None) -> None:
    """Print a one-block summary of the team about to run."""
    header = f"Team: [bold]{config.name}[/bold] · {config.workflow.type}"
    if path is not None:
        header += f" · [dim]{path}[/dim]"
    console.print(header)
    for agent in config.agents:
        marker = " [dim](lead)[/dim]" if agent.name == config.workflow.lead else ""
        console.print(f"  • {agent.name} ({agent.role}) — {agent.model}{marker}")


def print_teams_table(configs: dict[str, Path], loader) -> None:
    """Print a table of discovered teams. `loader` returns (TeamConfig, missing_env)."""
    table = Table(title="Teams")
    table.add_column("Name", style="bold")
    table.add_column("Source")
    table.add_column("Workflow")
    table.add_column("Agents", justify="right")
    table.add_column("Goal")

    for name, path in configs.items():
        try:
            config, _ = loader(path)
        except Exception as e:
            table.add_row(name, config_source(path), "—", "—", f"[red]{e}[/red]")
            continue
        table.add_row(
            name,
            config_source(path),
            config.workflow.type,
            str(len(config.agents)),
            config.goal,
        )

    console.print(table)


def _share_bar(fraction: float, width: int = 10) -> str:
    """A proportion bar. The token split is the claim this project makes."""
    filled = round(fraction * width)
    return "█" * filled + "░" * (width - filled)


def print_usage_table(usage: RunUsage) -> None:
    """Print a Rich table summarizing token usage per agent."""
    if not usage.entries:
        return

    has_cost = usage.total_cost is not None
    total = usage.total_tokens or 1

    table = Table(title="Token Usage", show_footer=True, title_style="bold")
    table.add_column("Agent", footer="Total", style="bold")
    table.add_column("Model", style="dim")
    table.add_column("Prompt", justify="right", footer=str(usage.total_prompt_tokens))
    table.add_column("Completion", justify="right", footer=str(usage.total_completion_tokens))
    table.add_column("Total", justify="right", footer=str(usage.total_tokens))
    table.add_column("Share", justify="left", no_wrap=True, min_width=15)
    if has_cost:
        table.add_column("Cost", justify="right", footer=f"${usage.total_cost:.4f}")

    for agent_name, summary in usage.by_agent().items():
        share = summary.total_tokens / total
        row = [
            agent_name,
            summary.model,
            str(summary.prompt_tokens),
            str(summary.completion_tokens),
            str(summary.total_tokens),
            f"{_share_bar(share)} {share:>4.0%}",
        ]
        if has_cost:
            cost = summary.cost_usd
            row.append(f"${cost:.4f}" if cost is not None else "—")
        table.add_row(*row)

    console.print()
    console.print(table)


#: Only the decision itself is coloured: green approves, red refuses, and
#: "refuse with a note" stays neutral because it is neither.
OPTION_STYLES = ("green", "green", "", "red")


def choose(options: list[str], default: int = 0) -> int | None:
    """Inline arrow-key menu. Returns the chosen index, or None if cancelled.

    Deliberately not a full-screen dialog: the choice appears in the flow of the
    session, the way a shell prompt does.
    """
    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import to_formatted_text
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import HSplit, Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    selected = [default]

    def render():
        lines = []
        for i, option in enumerate(options):
            colour = OPTION_STYLES[i] if i < len(OPTION_STYLES) else ""
            if i == selected[0]:
                lines.append((f"reverse {colour}", f" > {option} \n"))
            else:
                lines.append((colour, f"   {option}\n"))
        return to_formatted_text(lines)

    keys = KeyBindings()

    @keys.add("up")
    @keys.add("k")
    def _up(event) -> None:
        selected[0] = (selected[0] - 1) % len(options)

    @keys.add("down")
    @keys.add("j")
    def _down(event) -> None:
        selected[0] = (selected[0] + 1) % len(options)

    @keys.add("enter")
    def _accept(event) -> None:
        event.app.exit(result=selected[0])

    @keys.add("escape")
    @keys.add("c-c")
    def _cancel(event) -> None:
        event.app.exit(result=None)

    for position in range(1, len(options) + 1):

        @keys.add(str(position))
        def _pick(event, index: int = position - 1) -> None:
            event.app.exit(result=index)

    app = Application(
        layout=Layout(HSplit([Window(FormattedTextControl(render), dont_extend_height=True)])),
        key_bindings=keys,
        style=Style.from_dict({"selected": "reverse"}),
        full_screen=False,
    )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return app.run()

    # Approvals are requested from inside the orchestrator's event loop, and
    # Application.run() starts its own. Give it a thread that has none.
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(app.run).result()


MAX_PREVIEW_LINES = 30


def _preview_write(request: ToolRequest, workspace: Path) -> None:
    """Show a diff against the current file, or the content if it is new.

    Showing only the proposed content hides what an overwrite removes, which is
    the thing most worth seeing before saying yes.
    """
    target = workspace / request.path
    try:
        existing = target.read_text() if target.is_file() else None
    except OSError:
        existing = None

    if existing is None:
        lines = request.content.splitlines()
        console.print(f"[bold]create[/bold] {request.path} [dim]({len(lines)} lines)[/dim]")
        for line in lines[:MAX_PREVIEW_LINES]:
            console.print(f"  [green]+[/green] {line}", highlight=False)
        if len(lines) > MAX_PREVIEW_LINES:
            console.print(f"  [dim]... {len(lines) - MAX_PREVIEW_LINES} more lines[/dim]")
        return

    if existing == request.content:
        console.print(f"[bold]write[/bold] {request.path} [dim](no changes)[/dim]")
        return

    diff = list(
        difflib.unified_diff(existing.splitlines(), request.content.splitlines(), lineterm="", n=2)
    )[2:]  # drop the ---/+++ header; the path is already on the line above
    added = sum(1 for line in diff if line.startswith("+"))
    removed = sum(1 for line in diff if line.startswith("-"))
    console.print(
        f"[bold]edit[/bold] {request.path} "
        f"[dim]([green]+{added}[/green] [red]-{removed}[/red])[/dim]"
    )
    for line in diff[:MAX_PREVIEW_LINES]:
        if line.startswith("+"):
            console.print(f"  [green]{line}[/green]", highlight=False)
        elif line.startswith("-"):
            console.print(f"  [red]{line}[/red]", highlight=False)
        elif line.startswith("@@"):
            console.print(f"  [dim cyan]{line}[/dim cyan]", highlight=False)
        else:
            console.print(f"  [dim]{line}[/dim]", highlight=False)
    if len(diff) > MAX_PREVIEW_LINES:
        console.print(f"  [dim]... {len(diff) - MAX_PREVIEW_LINES} more diff lines[/dim]")


def _show_request(request: ToolRequest, workspace: Path) -> None:
    """Print what the agent wants to do, before asking."""
    console.print()
    if request.kind == "write_file":
        _preview_write(request, workspace)
    elif request.kind == "read_file":
        console.print(f"[bold]read[/bold] {request.path}")
    else:
        console.print(f"[bold]run[/bold] {request.command}", highlight=False)
        console.print(f"  [dim]in {workspace}[/dim]")


def _question_for(request: ToolRequest) -> str:
    """Name the decision being asked for, rather than a bare yes/no."""
    if request.kind == "write_file":
        return f"Apply this change to {request.path}?"
    if request.kind == "read_file":
        return f"Let the agent read {request.path}?"
    return "Run this command?"


def _show_outcome(outcome: str) -> None:
    """Confirm what actually happened, so approval is not a leap of faith."""
    first = outcome.splitlines()[0] if outcome else ""
    if outcome.startswith("Failed") or outcome.startswith("Refused"):
        console.print(f"  [red]x[/red] [dim]{first}[/dim]\n", highlight=False)
        return
    rest = len(outcome.splitlines()) - 1
    more = f" [dim](+{rest} more lines)[/dim]" if rest > 0 else ""
    console.print(f"  [green]+[/green] [dim]{first}[/dim]{more}\n", highlight=False)


def make_tool_approver(workspace: Path, pause=None, chooser=None) -> Callable[[ToolRequest], str]:
    """Ask before every workspace action, with a Claude Code style menu.

    Only usable on a terminal: with no one to ask there is no approval, so the
    caller must not install this in a piped or automated session.
    """
    from openswarm.core.tools import execute_safely

    pick = chooser or choose
    always_allowed: set[str] = set()

    def decide(request: ToolRequest) -> str:
        if request.kind in always_allowed:
            return execute_safely(request, workspace)

        _show_request(request, workspace)
        console.print(f"\n[bold]{_question_for(request)}[/bold]")
        options = [
            "Yes",
            f"Yes, and don't ask again for {request.kind} this session",
            "No, and tell the agent what to do instead",
            "No",
        ]
        choice = pick(options)

        if choice in (0, 1):
            if choice == 1:
                always_allowed.add(request.kind)
            outcome = execute_safely(request, workspace)
            _show_outcome(outcome)
            return outcome
        if choice == 2:
            feedback = console.input("[bold]What should it do instead?[/bold] ").strip()
            if feedback:
                return f"Refused by the user: {feedback}"
            return f"Refused by the user: {request.describe()}"
        return f"Refused by the user: {request.describe()}"

    def approve(request: ToolRequest) -> str:
        if pause is None:
            return decide(request)
        with pause():  # a spinner and a prompt cannot share the terminal
            return decide(request)

    return approve
