"""Tests for approval-gated workspace tools.

The escape and approval tests are the point of this module: everything else is
convenience, but those two are what stop an agent writing outside the project
or acting without being asked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openswarm.core.tools import (
    ToolError,
    ToolRequest,
    execute,
    parse_tool_request,
    resolve_in_workspace,
    run_with_approval,
)

# --- approval gate ---


def test_nothing_runs_without_approval(tmp_path: Path):
    request = ToolRequest(kind="write_file", path="x.py", content="print(1)")

    result = run_with_approval(request, tmp_path, approve=lambda _: False)

    assert "Refused by the user" in result
    assert not (tmp_path / "x.py").exists()


def test_no_approver_means_no_action(tmp_path: Path):
    """Non-interactive callers (MCP, pipes) must not silently get write access."""
    request = ToolRequest(kind="write_file", path="x.py", content="print(1)")

    result = run_with_approval(request, tmp_path, approve=None)

    assert "does not allow" in result
    assert not (tmp_path / "x.py").exists()


def test_approved_write_happens(tmp_path: Path):
    request = ToolRequest(kind="write_file", path="pkg/x.py", content="print(1)")

    result = run_with_approval(request, tmp_path, approve=lambda _: True)

    assert "Wrote pkg/x.py" in result
    assert (tmp_path / "pkg" / "x.py").read_text() == "print(1)"


def test_approver_sees_what_it_is_approving(tmp_path: Path):
    seen: list[str] = []
    request = ToolRequest(kind="write_file", path="x.py", content="a\nb\nc")

    def refuse(r: ToolRequest) -> bool:
        seen.append(r.describe())
        return False

    run_with_approval(request, tmp_path, approve=refuse)

    assert seen == ["write x.py (3 lines)"]


# --- workspace confinement ---


@pytest.mark.parametrize(
    "escape",
    ["../outside.txt", "../../etc/passwd", "/etc/passwd", "sub/../../outside.txt"],
)
def test_paths_cannot_escape_the_workspace(tmp_path: Path, escape: str):
    workspace = tmp_path / "project"
    workspace.mkdir()

    with pytest.raises(ToolError, match="escapes the workspace"):
        resolve_in_workspace(escape, workspace)


def test_symlink_pointing_outside_is_refused(tmp_path: Path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    (tmp_path / "secrets").mkdir()
    (workspace / "link").symlink_to(tmp_path / "secrets")

    with pytest.raises(ToolError, match="escapes the workspace"):
        resolve_in_workspace("link/creds.txt", workspace)


def test_escape_attempt_is_reported_not_raised(tmp_path: Path):
    """The agent gets told no; the run carries on."""
    workspace = tmp_path / "project"
    workspace.mkdir()
    request = ToolRequest(kind="write_file", path="../evil.txt", content="x")

    result = run_with_approval(request, workspace, approve=lambda _: True)

    assert "Failed" in result and "escapes the workspace" in result
    assert not (tmp_path / "evil.txt").exists()


def test_paths_inside_the_workspace_are_fine(tmp_path: Path):
    assert resolve_in_workspace("a/b/c.py", tmp_path) == (tmp_path / "a/b/c.py").resolve()


# --- individual actions ---


def test_read_file(tmp_path: Path):
    (tmp_path / "notes.md").write_text("hello")

    assert execute(ToolRequest(kind="read_file", path="notes.md"), tmp_path) == "hello"


def test_read_missing_file_reports_failure(tmp_path: Path):
    with pytest.raises(ToolError, match="Could not read"):
        execute(ToolRequest(kind="read_file", path="nope.md"), tmp_path)


def test_run_command_captures_output_and_exit_code(tmp_path: Path):
    result = execute(ToolRequest(kind="run_command", command="echo hi; exit 2"), tmp_path)

    assert "exit 2" in result
    assert "hi" in result


def test_run_command_runs_inside_the_workspace(tmp_path: Path):
    (tmp_path / "marker.txt").write_text("x")

    result = execute(ToolRequest(kind="run_command", command="ls"), tmp_path)

    assert "marker.txt" in result


def test_empty_command_is_refused(tmp_path: Path):
    with pytest.raises(ToolError, match="No command"):
        execute(ToolRequest(kind="run_command", command="   "), tmp_path)


def test_large_output_is_truncated(tmp_path: Path):
    from openswarm.core.tools import MAX_OUTPUT_CHARS

    (tmp_path / "big.txt").write_text("x" * (MAX_OUTPUT_CHARS + 1000))

    result = execute(ToolRequest(kind="read_file", path="big.txt"), tmp_path)

    assert "[truncated]" in result
    assert len(result) < MAX_OUTPUT_CHARS + 200


# --- parsing ---


def test_parses_tool_actions():
    request = parse_tool_request({"action": "write_file", "path": "a.py", "content": "x"})

    assert request is not None
    assert (request.kind, request.path, request.content) == ("write_file", "a.py", "x")


def test_ordinary_actions_are_not_tool_requests():
    for action in ("respond", "delegate", "result", "review"):
        assert parse_tool_request({"action": action, "content": "x"}) is None
