"""File and shell actions agents can request, gated on user approval.

Nothing here runs without an explicit yes from the caller's approval callback,
and writes cannot leave the workspace directory. Both rules live here rather
than in the CLI, so no future caller can skip them by accident.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

#: Appended to an agent's system prompt only when tools are enabled, so agents
#: without permission never learn these actions exist.
TOOLS_PROTOCOL = """
You may also act on the workspace. To do so, respond with one of:

{
  "action": "write_file",
  "path": "<path relative to the workspace>",
  "content": "<the complete new file contents>"
}

{
  "action": "read_file",
  "path": "<path relative to the workspace>"
}

{
  "action": "run_command",
  "command": "<shell command to run>"
}

Every one of these needs the user's approval, and they may refuse. You will be
told the result either way; continue from there. Write whole files, not
fragments — "content" replaces the file completely.

Reply with one JSON object and nothing else. No XML or tool-call tags, no
markdown fences, no commentary before or after. For example:
{"action": "write_file", "path": "notes.txt", "content": "hello"}"""

TOOL_ACTIONS = ("write_file", "read_file", "run_command")

#: Output beyond this is truncated before it goes back into a prompt.
MAX_OUTPUT_CHARS = 10_000

COMMAND_TIMEOUT_SECONDS = 120


@dataclass
class ToolRequest:
    """A workspace action an agent asked for."""

    kind: str
    path: str = ""
    content: str = ""
    command: str = ""

    def describe(self) -> str:
        """One line naming exactly what will happen, for the approval prompt."""
        if self.kind == "write_file":
            lines = self.content.count("\n") + 1
            return f"write {self.path} ({lines} lines)"
        if self.kind == "read_file":
            return f"read {self.path}"
        return f"run: {self.command}"


class ToolError(Exception):
    """A tool request that cannot be honoured, reported back to the agent."""


def parse_tool_request(parsed: dict) -> ToolRequest | None:
    """Build a ToolRequest from a parsed agent response, or None if it isn't one."""
    action = parsed.get("action", "")
    if action not in TOOL_ACTIONS:
        return None
    return ToolRequest(
        kind=action,
        path=str(parsed.get("path", "")),
        content=str(parsed.get("content", "")),
        command=str(parsed.get("command", "")),
    )


def resolve_in_workspace(path: str, workspace: Path) -> Path:
    """Resolve a path, refusing anything outside the workspace.

    Absolute paths, `..`, and symlinks pointing outward are all rejected: an
    agent talked into writing `~/.ssh/authorized_keys` must not be able to.
    """
    if not path:
        raise ToolError("No path given")

    workspace = workspace.resolve()
    target = (workspace / path).resolve()
    if target != workspace and workspace not in target.parents:
        raise ToolError(f"Path escapes the workspace: {path}")
    return target


def execute(request: ToolRequest, workspace: Path) -> str:
    """Carry out an already-approved request and return a result for the agent."""
    if request.kind == "write_file":
        target = resolve_in_workspace(request.path, workspace)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(request.content)
        except OSError as e:
            raise ToolError(f"Could not write {request.path}: {e}") from e
        return f"Wrote {request.path} ({len(request.content)} bytes)."

    if request.kind == "read_file":
        target = resolve_in_workspace(request.path, workspace)
        try:
            content = target.read_text(errors="replace")
        except OSError as e:
            raise ToolError(f"Could not read {request.path}: {e}") from e
        return _clip(content)

    if request.kind == "run_command":
        if not request.command.strip():
            raise ToolError("No command given")
        try:
            done = subprocess.run(
                request.command,
                shell=True,
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as e:
            raise ToolError(f"Command timed out after {COMMAND_TIMEOUT_SECONDS}s") from e
        except OSError as e:
            raise ToolError(f"Could not run command: {e}") from e
        output = (done.stdout + done.stderr).strip() or "(no output)"
        return f"exit {done.returncode}\n{_clip(output)}"

    raise ToolError(f"Unknown tool action: {request.kind}")


def run_with_approval(
    request: ToolRequest,
    workspace: Path,
    approve: Callable[[ToolRequest], bool] | None,
) -> str:
    """Ask, then act. Returns the text handed back to the agent either way."""
    if approve is None:
        return "Refused: this session does not allow workspace actions."
    if not approve(request):
        return f"Refused by the user: {request.describe()}"
    return execute_safely(request, workspace)


def execute_safely(request: ToolRequest, workspace: Path) -> str:
    """Execute an approved request, reporting failures to the agent as text.

    A tool that cannot run is something the agent should work around, not an
    exception that ends the run.
    """
    try:
        return execute(request, workspace)
    except ToolError as e:
        return f"Failed: {e}"


def _clip(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + "\n... [truncated]"
