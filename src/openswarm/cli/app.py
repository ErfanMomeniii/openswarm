"""CLI entry point for OpenSwarm."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from openswarm.cli.utils import make_message_printer
from openswarm.config.discovery import find_team_configs, get_config_dir
from openswarm.config.loader import load_config
from openswarm.core.orchestrator import Orchestrator
from openswarm.core.team import Team
from openswarm.llm.client import LLMError
from openswarm.workflow import get_workflow

app = typer.Typer(name="swarm", help="OpenSwarm — Multi-agent orchestration")
console = Console()


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
    config_dir = get_config_dir()
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

    on_message = make_message_printer() if verbose else None

    console.print("\n[bold yellow]Running...[/bold yellow]\n")

    try:
        result = asyncio.run(orchestrator.run(task, on_message=on_message))
    except LLMError as e:
        console.print(f"[red]LLM error: {e}[/red]")
        raise typer.Exit(1)

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


@app.command(name="team-list")
def team_list() -> None:
    """List all configured teams."""
    configs = find_team_configs()
    if not configs:
        config_dir = get_config_dir()
        console.print(f"[dim]No teams found in {config_dir / 'teams'}[/dim]")
        return

    console.print("[bold]Available teams:[/bold]\n")
    for name, path in configs.items():
        try:
            tc = load_config(path)
            console.print(f"  • [bold]{name}[/bold]: {tc.goal} ({len(tc.agents)} agents)")
        except Exception as e:
            console.print(f"  • [bold]{name}[/bold]: [red]error loading: {e}[/red]")


@app.command(name="team-info")
def team_info(
    name: str = typer.Argument(help="Team name to show details for"),
) -> None:
    """Show detailed information about a configured team."""
    configs = find_team_configs()
    if name not in configs:
        available = ", ".join(configs) if configs else "none"
        console.print(f"[red]Team '{name}' not found. Available: {available}[/red]")
        raise typer.Exit(1)

    try:
        tc = load_config(configs[name])
    except Exception as e:
        console.print(f"[red]Error loading team '{name}': {e}[/red]")
        raise typer.Exit(1)

    console.print(f"\nTeam: [bold]{tc.name}[/bold]")
    console.print(f"Goal: {tc.goal}")
    console.print(
        f"Workflow: {tc.workflow.type} (lead: {tc.workflow.lead}, max_rounds: {tc.workflow.max_rounds})"
    )
    console.print("\n[bold]Agents:[/bold]")
    for a in tc.agents:
        rules_str = "; ".join(a.rules) if a.rules else "none"
        console.print(f"  • {a.name} ({a.role}) — model: {a.model}, rules: {rules_str}")


if __name__ == "__main__":
    app()
