"""Task lifecycle management."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    DONE = "done"


@dataclass
class Task:
    description: str
    status: TaskStatus = TaskStatus.PENDING
    assigned_to: str | None = None
    result: str | None = None

    def assign(self, agent_name: str) -> None:
        self.assigned_to = agent_name
        self.status = TaskStatus.ASSIGNED

    def complete(self, result: str) -> None:
        self.result = result
        self.status = TaskStatus.DONE
