"""Shared CLI utilities."""

from __future__ import annotations

from collections.abc import Callable
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

MESSAGE_COLORS = {
    "task": "blue",
    "result": "green",
    "question": "yellow",
    "answer": "cyan",
    "review": "magenta",
    "revision": "white",
    "discuss": "bright_blue",
    "agree": "bright_green",
}


def make_message_printer() -> Callable[[Message], None]:
    """Return a callback that pretty-prints messages in real-time."""

    def _print_message(msg: Message) -> None:
        color = MESSAGE_COLORS.get(msg.type.value, "white")
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
        status.update(f"[bold yellow]{msg.to_agent}[/bold yellow] working — {msg.type.value}...")

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


def print_usage_table(usage: RunUsage) -> None:
    """Print a Rich table summarizing token usage per agent."""
    if not usage.entries:
        return

    has_cost = usage.total_cost is not None

    table = Table(title="Token Usage", show_footer=True)
    table.add_column("Agent", footer="Total")
    table.add_column("Model")
    table.add_column("Prompt", justify="right", footer=str(usage.total_prompt_tokens))
    table.add_column("Completion", justify="right", footer=str(usage.total_completion_tokens))
    table.add_column("Total", justify="right", footer=str(usage.total_tokens))
    if has_cost:
        table.add_column(
            "Cost",
            justify="right",
            footer=f"${usage.total_cost:.4f}",
        )

    for agent_name, summary in usage.by_agent().items():
        row = [
            agent_name,
            summary.model,
            str(summary.prompt_tokens),
            str(summary.completion_tokens),
            str(summary.total_tokens),
        ]
        if has_cost:
            cost = summary.cost_usd
            row.append(f"${cost:.4f}" if cost is not None else "—")
        table.add_row(*row)

    console.print()
    console.print(table)


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
            if i == selected[0]:
                lines.append(("class:selected", f" > {option}\n"))
            else:
                lines.append(("", f"   {option}\n"))
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
    return app.run()


def _show_request(request: ToolRequest) -> None:
    """Print what the agent wants to do, before asking."""
    console.print()
    if request.kind == "write_file":
        console.print(f"[bold yellow]Write[/bold yellow] {request.path}")
        lines = request.content.splitlines()
        for line in lines[:20]:
            console.print(f"  [dim]|[/dim] {line}")
        if len(lines) > 20:
            console.print(f"  [dim]| ... {len(lines) - 20} more lines[/dim]")
    elif request.kind == "read_file":
        console.print(f"[bold yellow]Read[/bold yellow] {request.path}")
    else:
        console.print(f"[bold yellow]Run[/bold yellow] {request.command}")


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

        _show_request(request)
        options = [
            "Yes",
            f"Yes, and don't ask again for {request.kind} this session",
            "No, and tell the agent what to do instead",
            "No",
        ]
        choice = pick(options)

        if choice == 0:
            return execute_safely(request, workspace)
        if choice == 1:
            always_allowed.add(request.kind)
            return execute_safely(request, workspace)
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
