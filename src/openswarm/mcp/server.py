"""MCP server exposing OpenSwarm teams as tools.

Auto-discovers team configs from:
  1. Project directory (cwd): team.yaml, openswarm.yaml, .openswarm.yaml, openswarm/*.yaml
  2. Global config: ~/.openswarm/teams/*.yaml
"""

from __future__ import annotations

from pathlib import Path

from openswarm.config.discovery import (
    LOCAL_CONFIG_NAMES,
    TeamResolutionError,
    config_source,
    find_all_configs,
    find_local_configs,
    find_team_configs,
    get_teams_dir,
    resolve_team,
)
from openswarm.config.loader import inspect_config, load_config
from openswarm.core.orchestrator import Orchestrator
from openswarm.core.team import Team
from openswarm.core.usage import RunResult
from openswarm.workflow import get_workflow

__all__ = [
    "LOCAL_CONFIG_NAMES",
    "find_local_configs",
    "find_all_configs",
    "find_team_configs",
    "run_task",
    "run_task_with_config",
    "list_teams",
    "team_info",
    "create_mcp_server",
    "main",
]


def _format_usage(run_result: RunResult) -> str:
    """Format a RunResult as text with usage summary appended."""
    lines = [run_result.result]
    usage = run_result.usage
    if usage.entries:
        lines.append("\n--- Token Usage ---")
        for agent_name, summary in usage.by_agent().items():
            cost_str = f", ${summary.cost_usd:.4f}" if summary.cost_usd is not None else ""
            lines.append(
                f"{agent_name} ({summary.model}): "
                f"{summary.prompt_tokens}p + {summary.completion_tokens}c "
                f"= {summary.total_tokens} tokens{cost_str}"
            )
        total_cost = usage.total_cost
        cost_total = f", ${total_cost:.4f}" if total_cost is not None else ""
        lines.append(f"Total: {usage.total_tokens} tokens{cost_total}")
    return "\n".join(lines)


async def _run(team_config, task: str) -> str:
    team = Team(team_config)
    workflow = get_workflow(team_config.workflow.type)
    orchestrator = Orchestrator(team, workflow)
    run_result = await orchestrator.run(task)
    return _format_usage(run_result)


async def run_task(task: str, team_name: str | None = None) -> str:
    """Run a task with a team. Auto-discovers config if no team specified."""
    try:
        _, path = resolve_team(team_name, configs=find_all_configs())
    except TeamResolutionError as e:
        return f"Error: {e}"

    try:
        team_config = load_config(path)
    except (FileNotFoundError, ValueError) as e:
        return f"Error loading config: {e}"

    try:
        return await _run(team_config, task)
    except Exception as e:
        return f"Error: the team run failed: {e}"


async def run_task_with_config(task: str, config_path: str) -> str:
    """Run a task using a config file path and return the result."""
    path = Path(config_path)
    if not path.exists():
        return f"Error: Config file not found: {config_path}"

    try:
        team_config = load_config(path)
    except Exception as e:
        return f"Error loading config: {e}"

    try:
        return await _run(team_config, task)
    except Exception as e:
        return f"Error: the team run failed: {e}"


async def list_teams() -> str:
    """List all available teams (local + global)."""
    configs = find_all_configs()
    if not configs:
        return (
            "No teams found. Add a team.yaml to your project "
            f"or place configs in {get_teams_dir()}."
        )

    lines = []
    for name, path in configs.items():
        try:
            tc, missing = inspect_config(path)
            env_note = f" [unset env: {', '.join(missing)}]" if missing else ""
            lines.append(
                f"• {name} [{config_source(path)}]: {tc.goal} "
                f"({len(tc.agents)} agents, {tc.workflow.type}){env_note}"
            )
        except Exception as e:
            lines.append(f"• {name}: [error loading: {e}]")
    return "\n".join(lines)


async def team_info(team_name: str) -> str:
    """Show detailed info about a team."""
    configs = find_all_configs()
    if team_name not in configs:
        available = ", ".join(configs) if configs else "none"
        return f"Error: Team '{team_name}' not found. Available: {available}"

    try:
        tc, _ = inspect_config(configs[team_name])
    except (FileNotFoundError, ValueError) as e:
        return f"Error loading team '{team_name}': {e}"

    lines = [
        f"Team: {tc.name}",
        f"Goal: {tc.goal}",
        f"Workflow: {tc.workflow.type} (lead: {tc.workflow.lead}, max_rounds: {tc.workflow.max_rounds})",
        "",
        "Agents:",
    ]
    for a in tc.agents:
        rules_str = "; ".join(a.rules) if a.rules else "none"
        lines.append(f"  • {a.name} ({a.role}) — model: {a.model}, rules: {rules_str}")
    return "\n".join(lines)


def _build_instructions() -> str:
    """Build MCP server instructions based on discovered team configs.

    When a team.yaml exists, instructions tell the IDE to always delegate
    coding tasks through the team — no user prompting needed.
    """
    configs = find_all_configs()

    if not configs:
        return (
            "OpenSwarm multi-agent orchestration. "
            "No team config found. Add a team.yaml to the project to enable "
            "automatic task delegation to an AI agent team."
        )

    # Build team summary for the instructions
    team_summaries = []
    for name, path in configs.items():
        try:
            tc, _ = inspect_config(path)
            agents_desc = ", ".join(f"{a.name} ({a.role})" for a in tc.agents)
            team_summaries.append(
                f"- {tc.name}: {tc.goal} [{tc.workflow.type} workflow, agents: {agents_desc}]"
            )
        except Exception:
            team_summaries.append(f"- {name}: [config error]")

    teams_info = "\n".join(team_summaries)

    return (
        "IMPORTANT: This project has an OpenSwarm agent team configured. "
        "You MUST use the openswarm_run tool for ALL coding tasks — "
        "building features, fixing bugs, writing tests, refactoring, everything. "
        "Do NOT write code directly. Always pass the task to openswarm_run.\n\n"
        "The team will decide if it can handle the task. If the task is outside "
        "the team's scope, the team will tell you — then you can handle it directly. "
        "But always try the team first.\n\n"
        "Only respond directly for non-coding tasks (questions, explanations, "
        "file reading, git commands).\n\n"
        f"Available teams:\n{teams_info}"
    )


def create_mcp_server():
    """Create and return the FastMCP server instance."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("openswarm", instructions=_build_instructions())

    @mcp.tool()
    async def openswarm_run(task: str, team: str = "") -> str:
        """Delegate a task to the OpenSwarm agent team. ALWAYS use this tool for
        any coding task. Do NOT write code directly. The team will handle the task
        if it's within their scope, or respond that it's outside their capabilities
        so you can handle it yourself.

        Args:
            task: What the team should do. Be specific and detailed — include
                  requirements, constraints, file paths, and expected behavior.
            team: Team name (optional — auto-selects if only one team exists).

        Returns:
            The final result from the agent team, or a message indicating the
            task is outside the team's scope.
        """
        return await run_task(task, team if team else None)

    @mcp.tool()
    async def openswarm_teams() -> str:
        """List available OpenSwarm teams and their capabilities.

        Shows all teams from the project directory (team.yaml, openswarm/*.yaml)
        and global config (~/.openswarm/teams/). Each entry shows the team's goal
        and number of agents.

        Returns:
            Formatted list of available teams.
        """
        return await list_teams()

    @mcp.tool()
    async def openswarm_team_info(team: str) -> str:
        """Show detailed info about an OpenSwarm team — agents, roles, models, workflow.

        Args:
            team: Team name to inspect.

        Returns:
            Team details including workflow type and all agents with their
            roles, models, and rules.
        """
        return await team_info(team)

    return mcp


def main():
    """Entry point for the openswarm-mcp command."""
    server = create_mcp_server()
    server.run()


if __name__ == "__main__":
    main()
