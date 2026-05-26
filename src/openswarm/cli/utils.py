"""Shared CLI utilities."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from openswarm.core.message import Message
from openswarm.core.usage import RunUsage

console = Console()


def make_message_printer() -> callable:
    """Return a callback that pretty-prints messages in real-time."""

    def _print_message(msg: Message) -> None:
        color = {
            "task": "blue",
            "result": "green",
            "question": "yellow",
            "answer": "cyan",
            "review": "magenta",
            "revision": "white",
            "discuss": "bright_blue",
            "agree": "bright_green",
        }.get(msg.type.value, "white")
        truncated = msg.content[:200] + ("..." if len(msg.content) > 200 else "")
        console.print(
            f"  [{color}]{msg.from_agent} → {msg.to_agent}[/{color}] "
            f"({msg.type.value}): {truncated}"
        )

    return _print_message


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
