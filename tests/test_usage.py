"""Tests for UsageStats, RunUsage, and RunResult."""

from __future__ import annotations

import pytest

from openswarm.core.usage import RunResult, RunUsage, UsageStats, UsageSummary


def _make_stats(
    agent: str, model: str, prompt: int, completion: int, cost: float | None = None
) -> UsageStats:
    return UsageStats(
        agent_name=agent,
        model=model,
        prompt_tokens=prompt,
        completion_tokens=completion,
        cost_usd=cost,
        elapsed_seconds=1.0,
    )


# --- UsageStats ---


def test_usage_stats_total_tokens():
    s = _make_stats("a", "m", 100, 50)
    assert s.total_tokens == 150


# --- RunUsage ---


def test_run_usage_empty():
    usage = RunUsage()
    assert usage.total_tokens == 0
    assert usage.total_prompt_tokens == 0
    assert usage.total_completion_tokens == 0
    assert usage.total_cost is None
    assert usage.by_agent() == {}
    assert usage.by_model() == {}


def test_run_usage_totals():
    usage = RunUsage(
        entries=[
            _make_stats("lead", "gpt-4", 100, 50, 0.01),
            _make_stats("worker", "gpt-3.5", 200, 100, 0.002),
        ]
    )
    assert usage.total_tokens == 450
    assert usage.total_prompt_tokens == 300
    assert usage.total_completion_tokens == 150
    assert usage.total_cost == pytest.approx(0.012)


def test_run_usage_cost_none_when_no_costs():
    usage = RunUsage(
        entries=[
            _make_stats("lead", "gpt-4", 100, 50),
        ]
    )
    assert usage.total_cost is None


def test_run_usage_cost_partial():
    """When some entries have cost and others don't, total_cost sums the known ones."""
    usage = RunUsage(
        entries=[
            _make_stats("lead", "gpt-4", 100, 50, 0.01),
            _make_stats("worker", "gpt-3.5", 200, 100),  # no cost
        ]
    )
    assert usage.total_cost == pytest.approx(0.01)


# --- by_agent / by_model ---


def test_by_agent_returns_usage_summary():
    usage = RunUsage(
        entries=[
            _make_stats("lead", "gpt-4", 100, 50, 0.01),
            _make_stats("lead", "gpt-4", 80, 40, 0.008),
            _make_stats("worker", "gpt-3.5", 200, 100, 0.002),
        ]
    )
    by_agent = usage.by_agent()
    assert set(by_agent.keys()) == {"lead", "worker"}

    lead = by_agent["lead"]
    assert isinstance(lead, UsageSummary)
    assert lead.total_tokens == 270
    assert lead.prompt_tokens == 180
    assert lead.completion_tokens == 90
    assert lead.cost_usd == pytest.approx(0.018)
    assert lead.calls == 2

    worker = by_agent["worker"]
    assert worker.total_tokens == 300
    assert worker.calls == 1


def test_by_agent_cost_none_when_no_cost():
    usage = RunUsage(entries=[_make_stats("lead", "gpt-4", 100, 50)])
    lead = usage.by_agent()["lead"]
    assert lead.cost_usd is None


def test_by_model():
    usage = RunUsage(
        entries=[
            _make_stats("lead", "gpt-4", 100, 50, 0.01),
            _make_stats("worker", "gpt-4", 200, 100, 0.02),
            _make_stats("worker", "gpt-3.5", 50, 25, 0.001),
        ]
    )
    by_model = usage.by_model()
    assert set(by_model.keys()) == {"gpt-4", "gpt-3.5"}
    assert by_model["gpt-4"].total_tokens == 450
    assert by_model["gpt-4"].calls == 2
    assert by_model["gpt-3.5"].total_tokens == 75


# --- RunResult ---


def test_run_result():
    usage = RunUsage(entries=[_make_stats("lead", "gpt-4", 10, 5, 0.001)])
    result = RunResult(result="done", usage=usage)
    assert result.result == "done"
    assert result.usage.total_tokens == 15
