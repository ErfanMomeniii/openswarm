"""CLI entry point for OpenSwarm."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from openswarm.config.loader import load_config
from openswarm.core.orchestrator import Orchestrator
from openswarm.core.team import Team
from openswarm.workflow import get_workflow

app = typer.Typer(name="swarm", help="OpenSwarm — Multi-agent orchestration")
console = Console()


def _get_config_dir() -> Path:
    return Path(os.environ.get("OPENSWARM_CONFIG_DIR", "~/.openswarm")).expanduser()


def _setup_logging(verbose: bool) -> None:
    env_level = os.environ.get("OPENSWARM_LOG_LEVEL", "").upper()
    if verbose:
        level = logging.DEBUG
    elif env_level:
        level = getattr(logging, env_level, logging.INFO)
    else:
        level = logging.INFO
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


def _resolve_config(
    config: str | None,
    team: str | None,
) -> str:
    """Resolve config file path from --config or --team."""
    if config and team:
        console.print("[red]Error: --config and --team are mutually exclusive[/red]")
        raise typer.Exit(1)
    if not config and not team:
        console.print("[red]Error: either --config or --team is required[/red]")
        raise typer.Exit(1)

    if config:
        return config

    # --team: look up in config dir
    config_dir = _get_config_dir()
    team_path = config_dir / "teams" / f"{team}.yaml"
    if not team_path.exists():
        # Also try .yml
        team_path = config_dir / "teams" / f"{team}.yml"
    if not team_path.exists():
        console.print(f"[red]Team config not found: {team_path}[/red]")
        raise typer.Exit(1)
    return str(team_path)


@app.command()
def run(
    task: str = typer.Argument(help="Task description for the team"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to team YAML config"),
    team: Optional[str] = typer.Option(
        None, "--team", "-t", help="Team name (looks up in config dir)"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show inter-agent messages"),
) -> None:
    """Run a task with a configured agent team."""
    _setup_logging(verbose)

    config_path = _resolve_config(config, team)

    console.print(Panel(f"[bold]{task}[/bold]", title="Task", border_style="blue"))

    try:
        team_config = load_config(config_path)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Config error: {e}[/red]")
        raise typer.Exit(1)

    console.print(f"Team: [bold]{team_config.name}[/bold] ({len(team_config.agents)} agents)")
    for agent in team_config.agents:
        console.print(f"  • {agent.name} ({agent.role}) — {agent.model}")

    team_obj = Team(team_config)

    workflow = get_workflow(team_config.workflow.type)
    orchestrator = Orchestrator(team_obj, workflow)

    console.print("\n[bold yellow]Running...[/bold yellow]\n")

    result = asyncio.run(orchestrator.run(task))

    if verbose:
        _print_message_log(orchestrator.message_log)

    console.print(Panel(result, title="Result", border_style="green"))


@app.command()
def interactive(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to team YAML config"),
    team: Optional[str] = typer.Option(
        None, "--team", "-t", help="Team name (looks up in config dir)"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show inter-agent messages"),
) -> None:
    """Start an interactive REPL session with a team."""
    _setup_logging(verbose)

    config_path = _resolve_config(config, team)

    try:
        team_config = load_config(config_path)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Config error: {e}[/red]")
        raise typer.Exit(1)

    team_obj = Team(team_config)

    from openswarm.cli.interactive import run_interactive

    run_interactive(team_obj, verbose=verbose)


if __name__ == "__main__":
    app()
