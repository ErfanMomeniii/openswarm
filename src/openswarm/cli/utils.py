"""Shared CLI utilities."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from rich.console import Console
from rich.table import Table

from openswarm.config.discovery import config_source
from openswarm.config.models import TeamConfig
from openswarm.core.message import Message
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
