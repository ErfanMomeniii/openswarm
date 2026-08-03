"""CLI entry point for OpenSwarm."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from openswarm import __version__
from openswarm.cli.utils import (
    make_message_printer,
    make_status_updater,
    print_team_summary,
    print_teams_table,
    print_usage_table,
)
from openswarm.config import templates
from openswarm.config.discovery import (
    TeamResolutionError,
    config_source,
    find_all_configs,
    get_teams_dir,
)
from openswarm.config.discovery import resolve_team as discover_team
from openswarm.config.loader import inspect_config, load_config
from openswarm.config.models import TeamConfig
from openswarm.core.orchestrator import Orchestrator
from openswarm.core.team import Team
from openswarm.llm.client import LLMClient, LLMError
from openswarm.workflow import get_workflow

app = typer.Typer(
    name="openswarm",
    help="OpenSwarm — multi-agent orchestration. Cheap models do bulk work, "
    "expensive models make decisions.",
    no_args_is_help=True,
)
team_app = typer.Typer(help="Inspect configured teams.", no_args_is_help=True)
app.add_typer(team_app, name="team")

console = Console()
# Errors go to stderr so `openswarm run ... -q > out.md` never captures them.
err_console = Console(stderr=True)


def _setup_logging(verbose: bool) -> None:
    env_level = os.environ.get("OPENSWARM_LOG_LEVEL", "").upper()
    if verbose:
        level = logging.DEBUG
    elif env_level:
        level = getattr(logging, env_level, logging.INFO)
    else:
        level = logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _fail(message: str) -> None:
    """Print an error to stderr and exit with status 1."""
    err_console.print(f"[red]{message}[/red]")
    raise typer.Exit(1)


def _resolve_config_path(config: str | None, team: str | None) -> Path:
    """Resolve a config file path from --config, --team, or auto-discovery."""
    if config and team:
        _fail("--config and --team are mutually exclusive.")

    if config:
        path = Path(config).expanduser()
        if not path.is_file():
            _fail(f"Config file not found: {path}")
        return path

    try:
        _, path = discover_team(team)
    except TeamResolutionError as e:
        _fail(str(e))
    return path


def _load(path: Path) -> TeamConfig:
    """Load a config file, exiting with a clean message on any config problem."""
    try:
        return load_config(path)
    except (FileNotFoundError, ValueError) as e:
        _fail(f"Config error: {e}")


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"openswarm {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """OpenSwarm CLI."""


def _make_stream_printer() -> callable:
    """Create a progress callback that prints streaming tokens with agent labels."""
    current_agent: list[str] = [""]  # mutable container for closure

    def on_progress(agent_name: str, chunk: str) -> None:
        if agent_name != current_agent[0]:
            if current_agent[0]:
                console.print()  # newline after previous agent's output
            console.print(f"[bold cyan][{agent_name}][/bold cyan] ", end="")
            current_agent[0] = agent_name
        console.print(chunk, end="", highlight=False)

    return on_progress


@app.command()
def run(
    task: str = typer.Argument(help="Task description for the team"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to team YAML config"),
    team: Optional[str] = typer.Option(
        None, "--team", "-t", help="Team name (project-local or global config)"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show inter-agent messages"),
    stream: bool = typer.Option(False, "--stream", "-s", help="Stream agent output in real-time"),
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help="Print only the result — for piping and redirects"
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Write the result to a file"
    ),
    max_rounds: Optional[int] = typer.Option(
        None, "--max-rounds", help="Override the team's max_rounds for this run"
    ),
) -> None:
    """Run a task with an agent team.

    With no --config/--team, uses the project's team.yaml when there is exactly one.
    """
    _setup_logging(verbose)

    config_path = _resolve_config_path(config, team)
    team_config = _load(config_path)

    if max_rounds is not None:
        if max_rounds < 1:
            _fail("--max-rounds must be >= 1.")
        team_config.workflow.max_rounds = max_rounds

    if not quiet:
        console.print(Panel(f"[bold]{task}[/bold]", title="Task", border_style="blue"))
        print_team_summary(team_config, config_path)

    team_obj = Team(team_config)
    orchestrator = Orchestrator(team_obj, get_workflow(team_config.workflow.type))

    on_message = make_message_printer() if verbose and not quiet else None
    on_progress = _make_stream_printer() if stream and not quiet else None

    if not quiet and on_message is not None and on_progress is None:
        console.print("\n[bold yellow]Running...[/bold yellow]\n")

    try:
        run_result = _execute(
            orchestrator,
            task,
            on_message=on_message,
            on_progress=on_progress,
            show_status=not (quiet or stream or verbose),
        )
    except LLMError as e:
        _fail(f"LLM error: {e}")
    except KeyboardInterrupt:
        err_console.print("\n[yellow]Cancelled.[/yellow]")
        raise typer.Exit(130)

    if output is not None:
        try:
            output.expanduser().write_text(run_result.result)
        except OSError as e:
            _fail(f"Could not write {output}: {e}")

    if quiet:
        print(run_result.result)
        return

    if stream:
        console.print("\n")  # newline after streaming output
    console.print(Panel(run_result.result, title="Result", border_style="green"))
    if output is not None:
        console.print(f"[dim]Result written to {output}[/dim]")
    print_usage_table(run_result.usage)


def _execute(orchestrator, task, *, on_message, on_progress, show_status):
    """Run the orchestrator, optionally under a spinner naming the active agent."""
    if show_status:
        with console.status("[bold yellow]Starting...[/bold yellow]", spinner="dots") as status:
            return asyncio.run(orchestrator.run(task, on_message=make_status_updater(status)))
    return asyncio.run(orchestrator.run(task, on_message=on_message, on_progress=on_progress))


@app.command()
def interactive(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to team YAML config"),
    team: Optional[str] = typer.Option(
        None, "--team", "-t", help="Team name (project-local or global config)"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show inter-agent messages"),
) -> None:
    """Start an interactive REPL session with a team."""
    _setup_logging(verbose)

    config_path = _resolve_config_path(config, team)
    team_config = _load(config_path)
    team_obj = Team(team_config)

    from openswarm.cli.interactive import run_interactive

    run_interactive(team_obj, verbose=verbose)


@app.command()
def init(
    template: Optional[str] = typer.Option(
        None,
        "--template",
        "-T",
        help=f"Starter template: {', '.join(templates.TEMPLATES)}",
    ),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Team name"),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Where to write the config (default: ./team.yaml)"
    ),
    global_: bool = typer.Option(
        False, "--global", "-g", help=f"Write to {get_teams_dir()} instead of the project"
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite an existing file"),
    list_templates: bool = typer.Option(
        False, "--list-templates", "-l", help="List available templates and exit"
    ),
) -> None:
    """Create a starter team config in this project."""
    if list_templates:
        table = Table(title="Templates")
        table.add_column("Name", style="bold")
        table.add_column("Description")
        for key, desc in templates.TEMPLATE_DESCRIPTIONS.items():
            table.add_row(key, desc)
        console.print(table)
        return

    interactive_tty = template is None and sys.stdin.isatty()
    if interactive_tty:
        console.print("[bold]Pick a team layout:[/bold]")
        for key, desc in templates.TEMPLATE_DESCRIPTIONS.items():
            console.print(f"  • [bold]{key}[/bold] — {desc}")
        template = typer.prompt("Template", default="hierarchical")

    template = template or "hierarchical"
    if template not in templates.TEMPLATES:
        _fail(f"Unknown template '{template}'. Available: {', '.join(templates.TEMPLATES)}")

    default_name = _default_team_name()
    if name is None and interactive_tty:
        name = typer.prompt("Team name", default=default_name)
    team_name = name or default_name

    if output is None:
        output = get_teams_dir() / f"{team_name}.yaml" if global_ else Path("team.yaml")
    output = output.expanduser()

    if output.exists() and not force:
        _fail(f"{output} already exists. Pass --force to overwrite.")

    content = templates.render(template, team_name)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content)
    except OSError as e:
        _fail(f"Could not write {output}: {e}")

    console.print(f"[green]Created {output}[/green] ([bold]{template}[/bold] template)")

    _, missing = inspect_config(output)
    console.print("\n[bold]Next steps:[/bold]")
    step = 1
    if missing:
        console.print(f"  {step}. Export the API keys it references:")
        for var in missing:
            console.print(f"       export {var}=...")
        step += 1
    console.print(f"  {step}. Edit models and rules in {output} to match your team")
    console.print(f"  {step + 1}. Check the setup:  [bold]openswarm doctor[/bold]")
    console.print(f'  {step + 2}. Run a task:      [bold]openswarm run "..."[/bold]')


def _default_team_name() -> str:
    """Derive a sane default team name from the current directory."""
    stem = Path.cwd().name.strip().lower().replace(" ", "-").replace("_", "-")
    cleaned = "".join(ch for ch in stem if ch.isalnum() or ch == "-").strip("-")
    return f"{cleaned}-team" if cleaned else "my-team"


@app.command()
def doctor(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Check a specific config"),
    team: Optional[str] = typer.Option(None, "--team", "-t", help="Check a specific team"),
    check_connection: bool = typer.Option(
        False,
        "--check-connection",
        help="Send a 1-token request to each agent's endpoint (costs a fraction of a cent)",
    ),
) -> None:
    """Validate configs, environment, and (optionally) provider connectivity."""
    _setup_logging(False)

    console.print("[bold]Environment[/bold]")
    console.print(f"  openswarm  {__version__}")
    console.print(f"  python     {sys.version.split()[0]}")
    console.print(f"  mcp extra  {'installed' if _mcp_installed() else 'not installed'}")
    console.print(f"  teams dir  {get_teams_dir()}")

    if config or team:
        path = _resolve_config_path(config, team)
        targets = {path.stem: path}
    else:
        targets = find_all_configs()
        if not targets:
            console.print(
                "\n[yellow]No team configs found.[/yellow] "
                "Run [bold]openswarm init[/bold] to create one."
            )
            raise typer.Exit(1)

    problems = 0
    for tname, path in targets.items():
        console.print(f"\n[bold]{tname}[/bold] [dim]({config_source(path)} · {path})[/dim]")
        try:
            team_config, missing = inspect_config(path)
        except (FileNotFoundError, ValueError) as e:
            console.print(f"  [red]✗ invalid config:[/red] {e}")
            problems += 1
            continue

        console.print(
            f"  [green]✓[/green] {team_config.workflow.type} workflow, "
            f"{len(team_config.agents)} agents, max_rounds={team_config.workflow.max_rounds}"
        )

        if missing:
            problems += 1
            console.print(f"  [red]✗ unset env vars:[/red] {', '.join(missing)}")
            for var in missing:
                console.print(f"      export {var}=...")
        else:
            console.print("  [green]✓[/green] all referenced env vars are set")

        if check_connection:
            if missing:
                console.print("  [yellow]⚠ skipping connection check — env vars unset[/yellow]")
            else:
                problems += _check_connections(team_config)

    if problems:
        console.print(f"\n[red]{problems} problem(s) found.[/red]")
        raise typer.Exit(1)
    console.print("\n[green]All checks passed.[/green]")


def _mcp_installed() -> bool:
    from importlib.util import find_spec

    try:
        return find_spec("mcp.server.fastmcp") is not None
    except (ImportError, ValueError):
        return False


def _check_connections(team_config: TeamConfig) -> int:
    """Ping each agent's endpoint with a minimal request. Returns problem count."""
    problems = 0
    for agent in team_config.agents:
        probe = agent.model_copy(update={"max_tokens": 1})
        try:
            asyncio.run(LLMClient(probe).chat([{"role": "user", "content": "ping"}]))
            console.print(f"  [green]✓[/green] {agent.name} → {agent.model} reachable")
        except LLMError as e:
            problems += 1
            console.print(f"  [red]✗ {agent.name} → {agent.model}:[/red] {e}")
    return problems


@team_app.command("list")
def team_list() -> None:
    """List all configured teams (project-local and global)."""
    configs = find_all_configs()
    if not configs:
        console.print(
            f"[dim]No teams found in this project or {get_teams_dir()}.[/dim]\n"
            "Run [bold]openswarm init[/bold] to create one."
        )
        return
    print_teams_table(configs, inspect_config)


@team_app.command("info")
def team_info(
    name: str = typer.Argument(help="Team name to show details for"),
) -> None:
    """Show detailed information about a configured team."""
    configs = find_all_configs()
    if name not in configs:
        available = ", ".join(configs) if configs else "none"
        _fail(f"Team '{name}' not found. Available: {available}")

    path = configs[name]
    try:
        tc, missing = inspect_config(path)
    except (FileNotFoundError, ValueError) as e:
        _fail(f"Error loading team '{name}': {e}")

    console.print(f"\nTeam: [bold]{tc.name}[/bold] [dim]({config_source(path)} · {path})[/dim]")
    console.print(f"Goal: {tc.goal}")
    console.print(
        f"Workflow: {tc.workflow.type} "
        f"(lead: {tc.workflow.lead}, max_rounds: {tc.workflow.max_rounds})"
    )
    if missing:
        console.print(f"[yellow]Unset env vars: {', '.join(missing)}[/yellow]")

    table = Table(show_header=True)
    table.add_column("Agent", style="bold")
    table.add_column("Role")
    table.add_column("Model")
    table.add_column("Max tokens", justify="right")
    table.add_column("Temp", justify="right")
    for a in tc.agents:
        label = f"{a.name} (lead)" if a.name == tc.workflow.lead else a.name
        table.add_row(label, a.role, a.model, str(a.max_tokens), f"{a.temperature:g}")
    console.print(table)

    for a in tc.agents:
        if a.rules:
            console.print(f"\n[bold]{a.name}[/bold] rules:")
            for rule in a.rules:
                console.print(f"  • {rule}")


# Deprecated flat aliases, kept so existing scripts keep working.
app.command(name="team-list", hidden=True)(team_list)
app.command(name="team-info", hidden=True)(team_info)


if __name__ == "__main__":
    app()
