"""Every public import path must work as the first openswarm import.

These run in fresh interpreters: circular-import bugs only show up when a module
is imported first, which never happens inside a test session that already
imported something else.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

IMPORT_PATHS = [
    "from openswarm.llm.client import LLMClient",
    "from openswarm.llm import LLMClient",
    "from openswarm.core import Agent, Message, Orchestrator, Task, Team",
    "from openswarm.core.agent import Agent",
    "from openswarm.core.orchestrator import Orchestrator",
    "from openswarm.workflow import get_workflow",
    "from openswarm.workflow.pipeline import PipelineWorkflow",
    "from openswarm.config import load_config",
    "from openswarm.config.discovery import resolve_team",
    "from openswarm.cli.app import app",
    "import openswarm",
]


@pytest.mark.parametrize("statement", IMPORT_PATHS)
def test_import_works_in_a_fresh_interpreter(statement: str):
    result = subprocess.run(
        [sys.executable, "-c", statement], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, f"{statement} failed:\n{result.stderr}"
