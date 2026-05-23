"""MCP server exposing OpenSwarm teams as tools.

Auto-discovers team configs from:
  1. Project directory (cwd): team.yaml, openswarm.yaml, .openswarm.yaml, openswarm/*.yaml
  2. Global config: ~/.openswarm/teams/*.yaml
"""

from __future__ import annotations

from pathlib import Path

from openswarm.config.discovery import find_team_configs, get_config_dir
from openswarm.config.loader import load_config
from openswarm.core.orchestrator import Orchestrator
from openswarm.core.team import Team
from openswarm.workflow import get_workflow

# File names to look for in project directory (in priority order)
LOCAL_CONFIG_NAMES = [
    "team.yaml",
    "team.yml",
    "openswarm.yaml",
    "openswarm.yml",
    ".openswarm.yaml",
    ".openswarm.yml",
]


def find_local_configs(project_dir: Path | None = None) -> dict[str, Path]:
    """Find team configs in the project directory.

    Looks for well-known filenames and openswarm/ subdirectory.
    """
    root = project_dir or Path.cwd()
    configs: dict[str, Path] = {}

    # Check well-known filenames
    for name in LOCAL_CONFIG_NAMES:
        path = root / name
        if path.exists():
            configs[path.stem] = path

    # Check openswarm/ subdirectory
    swarm_dir = root / "openswarm"
    if swarm_dir.is_dir():
        for p in sorted(swarm_dir.iterdir()):
            if p.suffix in (".yaml", ".yml"):
                configs[p.stem] = p

    return configs


def find_all_configs(project_dir: Path | None = None) -> dict[str, Path]:
    """Find all team configs — local project configs first, then global."""
    # Global configs
    configs = find_team_configs()
    # Local configs override global ones with same name
    configs.update(find_local_configs(project_dir))
    return configs


async def run_task(task: str, team_name: str | None = None) -> str:
    """Run a task with a team. Auto-discovers config if no team specified."""
    configs = find_all_configs()

    if not team_name:
        # Auto-select: if there's exactly one config, use it
        if len(configs) == 1:
            team_name = next(iter(configs))
        elif len(configs) == 0:
            return (
                "Error: No team config found. "
                "Add a team.yaml to your project or ~/.openswarm/teams/."
            )
        else:
            available = ", ".join(configs)
            return f"Error: Multiple teams found ({available}). Specify which team to use."

    if team_name not in configs:
        available = ", ".join(configs) if configs else "none"
        return f"Error: Team '{team_name}' not found. Available: {available}"

    team_config = load_config(configs[team_name])
    team = Team(team_config)
    workflow = get_workflow(team_config.workflow.type)
    orchestrator = Orchestrator(team, workflow)
    return await orchestrator.run(task)


async def run_task_with_config(task: str, config_path: str) -> str:
    """Run a task using a config file path and return the result."""
    path = Path(config_path)
    if not path.exists():
        return f"Error: Config file not found: {config_path}"

    try:
        team_config = load_config(path)
    except Exception as e:
        return f"Error loading config: {e}"

    team = Team(team_config)
    workflow = get_workflow(team_config.workflow.type)
    orchestrator = Orchestrator(team, workflow)
    return await orchestrator.run(task)


async def list_teams() -> str:
    """List all available teams (local + global)."""
    configs = find_all_configs()
    if not configs:
        return (
            "No teams found. Add a team.yaml to your project "
            f"or place configs in {get_config_dir() / 'teams'}."
        )

    lines = []
    for name, path in configs.items():
        try:
            tc = load_config(path)
            source = "local" if path.parent != get_config_dir() / "teams" else "global"
            lines.append(f"• {name} [{source}]: {tc.goal} ({len(tc.agents)} agents)")
        except Exception as e:
            lines.append(f"• {name}: [error loading: {e}]")
    return "\n".join(lines)


async def team_info(team_name: str) -> str:
    """Show detailed info about a team."""
    configs = find_all_configs()
    if team_name not in configs:
        available = ", ".join(configs) if configs else "none"
        return f"Error: Team '{team_name}' not found. Available: {available}"

    tc = load_config(configs[team_name])
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
            tc = load_config(path)
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
