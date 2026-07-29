"""Interactive REPL for chatting with agent teams."""

from __future__ import annotations

import asyncio
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.panel import Panel

from openswarm.cli.utils import make_message_printer, make_status_updater, print_usage_table
from openswarm.core.orchestrator import Orchestrator
from openswarm.core.team import Team
from openswarm.core.usage import RunUsage
from openswarm.workflow import get_workflow

console = Console()

SLASH_COMMANDS = {
    "/help": "Show these commands",
    "/quit": "Exit the REPL",
    "/team": "Show current team info",
    "/history": "Show message history",
    "/usage": "Show token usage and cost for this session",
    "/save": "Save the last result: /save notes.md",
    "/clear": "Clear message history",
    "/stream": "Toggle streaming output on/off",
}


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
        for name, desc in SLASH_COMMANDS.items():
            console.print(f"  [bold]{name}[/bold] — {desc}")
        console.print()
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


def _make_stream_printer() -> callable:
    """Create a progress callback that prints streaming tokens with agent labels."""
    current_agent: list[str] = [""]

    def on_progress(agent_name: str, chunk: str) -> None:
        if agent_name != current_agent[0]:
            if current_agent[0]:
                console.print()
            console.print(f"[bold cyan][{agent_name}][/bold cyan] ", end="")
            current_agent[0] = agent_name
        console.print(chunk, end="", highlight=False)

    return on_progress


def run_interactive(team: Team, verbose: bool = False) -> None:
    """Run the interactive REPL loop."""
    workflow = get_workflow(team.config.workflow.type)
    orchestrator = Orchestrator(team, workflow)
    on_message = make_message_printer() if verbose else None
    stream_state: list[bool] = [False]
    session_usage = RunUsage()
    last_result: list[str] = [""]

    console.print(
        Panel(
            f"Team: [bold]{team.config.name}[/bold] — {team.config.goal}\n"
            f"Agents: {', '.join(team.agent_names)}\n"
            "Type a task, or /help for commands.",
            title="OpenSwarm Interactive",
            border_style="blue",
        )
    )

    session: PromptSession[str] = PromptSession(
        "swarm> ", completer=WordCompleter(list(SLASH_COMMANDS))
    )

    while True:
        try:
            with patch_stdout():
                user_input = session.prompt()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Bye.[/dim]")
            break

        text = user_input.strip()
        if not text:
            continue

        if text.startswith("/"):
            should_exit = _handle_slash_command(
                text, team, orchestrator, stream_state, session_usage, last_result
            )
            if should_exit:
                console.print("[dim]Bye.[/dim]")
                break
            continue

        on_progress = _make_stream_printer() if stream_state[0] else None
        show_status = not stream_state[0] and not verbose

        try:
            if show_status:
                with console.status("[bold yellow]Starting...[/bold yellow]", spinner="dots") as st:
                    run_result = asyncio.run(
                        orchestrator.run(text, on_message=make_status_updater(st))
                    )
            else:
                console.print("[bold yellow]Running...[/bold yellow]\n")
                run_result = asyncio.run(
                    orchestrator.run(text, on_message=on_message, on_progress=on_progress)
                )
            if stream_state[0]:
                console.print("\n")
            last_result[0] = run_result.result
            session_usage.entries.extend(run_result.usage.entries)
            console.print(Panel(run_result.result, title="Result", border_style="green"))
            print_usage_table(run_result.usage)
        except KeyboardInterrupt:
            console.print("\n[yellow]Task cancelled.[/yellow]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")

        console.print()
