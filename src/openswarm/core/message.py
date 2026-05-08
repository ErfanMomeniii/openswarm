"""Structured inter-agent messages."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class MessageType(str, Enum):
    TASK = "task"
    RESULT = "result"
    QUESTION = "question"
    ANSWER = "answer"
    REVIEW = "review"
    REVISION = "revision"


@dataclass
class Message:
    from_agent: str
    to_agent: str
    type: MessageType
    content: str
    attachments: dict = field(default_factory=dict)
