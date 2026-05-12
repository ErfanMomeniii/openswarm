"""Tests for Message and MessageType."""

from openswarm.core.message import Message, MessageType


def test_message_construction():
    msg = Message(
        from_agent="alice",
        to_agent="bob",
        type=MessageType.TASK,
        content="Do something",
    )
    assert msg.from_agent == "alice"
    assert msg.to_agent == "bob"
    assert msg.type == MessageType.TASK
    assert msg.content == "Do something"
    assert msg.attachments == {}


def test_message_with_attachments():
    msg = Message(
        from_agent="a",
        to_agent="b",
        type=MessageType.RESULT,
        content="done",
        attachments={"code": "print('hi')"},
    )
    assert msg.attachments == {"code": "print('hi')"}


def test_all_message_types():
    expected = {"task", "result", "question", "answer", "review", "revision", "discuss", "agree"}
    actual = {t.value for t in MessageType}
    assert actual == expected
