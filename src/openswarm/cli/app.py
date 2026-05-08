"""CLI entry point for OpenSwarm."""

from __future__ import annotations

import asyncio
import logging

import typer
from rich.console import Console
from rich.panel import Panel

from openswarm.config.loader import load_config
from openswarm.core.orchestrator import Orchestrator
from openswarm.core.team import Team
from openswarm.workflow.hierarchical import HierarchicalWorkflow

app = typer.Typer(name="swarm", help="OpenSwarm — Multi-agent orchestration")
console = Console()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _print_message_log(message_log: list) -> None:
    """Print all inter-agent messages for verbose mode."""
    console.print("\n[bold]Message Log:[/bold]")
    for msg in message_log:
        color = {
            "task": "blue",
            "result": "green",
            "question": "yellow",
            "answer": "cyan",
            "review": "magenta",
            "revision": "white",
        }.get(msg.type.value, "white")
        console.print(
            f"  [{color}]{msg.from_agent} → {msg.to_agent}[/{color}] "
            f"({msg.type.value}): {msg.content[:200]}{'...' if len(msg.content) > 200 else ''}"
        )


@app.command()
def run(
    task: str = typer.Argument(help="Task description for the team"),
    config: str = typer.Option(..., "--config", "-c", help="Path to team YAML config"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show inter-agent messages"),
) -> None:
    """Run a task with a configured agent team."""
    _setup_logging(verbose)

    console.print(Panel(f"[bold]{task}[/bold]", title="Task", border_style="blue"))

    try:
        team_config = load_config(config)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Config error: {e}[/red]")
        raise typer.Exit(1)

    console.print(f"Team: [bold]{team_config.name}[/bold] ({len(team_config.agents)} agents)")
    for agent in team_config.agents:
        console.print(f"  • {agent.name} ({agent.role}) — {agent.model}")

    team = Team(team_config)

    # Phase 1: only hierarchical workflow
    workflow = HierarchicalWorkflow()
    orchestrator = Orchestrator(team, workflow)

    console.print("\n[bold yellow]Running...[/bold yellow]\n")

    result = asyncio.run(orchestrator.run(task))

    if verbose:
        _print_message_log(orchestrator.message_log)

    console.print(Panel(result, title="Result", border_style="green"))


if __name__ == "__main__":
    app()
