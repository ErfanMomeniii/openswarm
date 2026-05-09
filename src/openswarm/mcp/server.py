"""MCP server exposing OpenSwarm teams as tools."""

from __future__ import annotations

import os
from pathlib import Path

from openswarm.config.loader import load_config
from openswarm.core.orchestrator import Orchestrator
from openswarm.core.team import Team
from openswarm.workflow import get_workflow


def _get_config_dir() -> Path:
    return Path(os.environ.get("OPENSWARM_CONFIG_DIR", "~/.openswarm")).expanduser()


def _find_team_configs() -> dict[str, Path]:
    """Discover all team YAML files in the config directory."""
    teams_dir = _get_config_dir() / "teams"
    if not teams_dir.exists():
        return {}
    configs: dict[str, Path] = {}
    for p in sorted(teams_dir.iterdir()):
        if p.suffix in (".yaml", ".yml"):
            configs[p.stem] = p
    return configs


async def run_task(task: str, team_name: str) -> str:
    """Run a task with a named team and return the result."""
    configs = _find_team_configs()
    if team_name not in configs:
        available = ", ".join(configs) if configs else "none"
        return f"Error: Team '{team_name}' not found. Available: {available}"

    team_config = load_config(configs[team_name])
    team = Team(team_config)
    workflow = get_workflow(team_config.workflow.type)
    orchestrator = Orchestrator(team, workflow)
    return await orchestrator.run(task)


async def list_teams() -> str:
    """List all configured teams."""
    configs = _find_team_configs()
    if not configs:
        return f"No teams found in {_get_config_dir() / 'teams'}"

    lines = []
    for name, path in configs.items():
        try:
            tc = load_config(path)
            lines.append(f"• {name}: {tc.goal} ({len(tc.agents)} agents)")
        except Exception as e:
            lines.append(f"• {name}: [error loading: {e}]")
    return "\n".join(lines)


async def team_info(team_name: str) -> str:
    """Show detailed info about a team."""
    configs = _find_team_configs()
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


def create_mcp_server():
    """Create and return the FastMCP server instance."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("openswarm", instructions="Multi-agent orchestration framework")

    @mcp.tool()
    async def mcp_run_task(task: str, team_name: str) -> str:
        """Run a task with a configured agent team."""
        return await run_task(task, team_name)

    @mcp.tool()
    async def mcp_list_teams() -> str:
        """List all configured teams."""
        return await list_teams()

    @mcp.tool()
    async def mcp_team_info(team_name: str) -> str:
        """Show detailed information about a team."""
        return await team_info(team_name)

    return mcp


if __name__ == "__main__":
    server = create_mcp_server()
    server.run()
