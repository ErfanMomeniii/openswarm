"""Usage tracking: per-call stats, run-level summaries, and run results."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class UsageStats:
    """Token usage and cost for a single LLM call."""

    agent_name: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float | None = None
    elapsed_seconds: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class UsageSummary:
    """Aggregated usage for one agent or one model."""

    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = None
    calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def _add(self, entry: UsageStats) -> None:
        self.prompt_tokens += entry.prompt_tokens
        self.completion_tokens += entry.completion_tokens
        if entry.cost_usd is not None:
            self.cost_usd = (self.cost_usd or 0.0) + entry.cost_usd
        self.calls += 1


@dataclass
class RunUsage:
    """Aggregated usage across all LLM calls in a run."""

    entries: list[UsageStats] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return sum(e.total_tokens for e in self.entries)

    @property
    def total_prompt_tokens(self) -> int:
        return sum(e.prompt_tokens for e in self.entries)

    @property
    def total_completion_tokens(self) -> int:
        return sum(e.completion_tokens for e in self.entries)

    @property
    def total_cost(self) -> float | None:
        costs = [e.cost_usd for e in self.entries if e.cost_usd is not None]
        return sum(costs) if costs else None

    def by_agent(self) -> dict[str, UsageSummary]:
        """Summarize usage grouped by agent name."""
        result: dict[str, UsageSummary] = {}
        for e in self.entries:
            if e.agent_name not in result:
                result[e.agent_name] = UsageSummary(model=e.model)
            result[e.agent_name]._add(e)
        return result

    def by_model(self) -> dict[str, UsageSummary]:
        """Summarize usage grouped by model."""
        result: dict[str, UsageSummary] = {}
        for e in self.entries:
            if e.model not in result:
                result[e.model] = UsageSummary(model=e.model)
            result[e.model]._add(e)
        return result


@dataclass
class RunResult:
    """Result of an orchestrator run: the output string plus usage data."""

    result: str
    usage: RunUsage
