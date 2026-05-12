"""Tests for Task lifecycle."""

from openswarm.core.task import Task, TaskStatus


def test_fresh_task_is_pending():
    t = Task(description="build thing")
    assert t.status == TaskStatus.PENDING
    assert t.assigned_to is None
    assert t.result is None


def test_assign():
    t = Task(description="build thing")
    t.assign("worker-1")
    assert t.status == TaskStatus.ASSIGNED
    assert t.assigned_to == "worker-1"


def test_complete():
    t = Task(description="build thing")
    t.assign("worker-1")
    t.complete("done result")
    assert t.status == TaskStatus.DONE
    assert t.result == "done result"
