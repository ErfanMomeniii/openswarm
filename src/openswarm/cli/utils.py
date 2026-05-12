"""Shared CLI utilities."""

from __future__ import annotations

from rich.console import Console

from openswarm.core.message import Message

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
