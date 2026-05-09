"""Tests for LLM client error handling, retries, and temperature."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import litellm

from openswarm.config.models import AgentConfig
from openswarm.llm.client import LLMClient, LLMError


@pytest.fixture
def agent_config() -> AgentConfig:
    return AgentConfig(
        name="test",
        role="tester",
        model="gpt-test",
        host="https://api.test.com",
        api_key="test-key",
        temperature=0.5,
    )


@pytest.fixture
def client(agent_config: AgentConfig) -> LLMClient:
    return LLMClient(agent_config)


def _make_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.usage = MagicMock()
    resp.usage.total_tokens = 42
    return resp


@pytest.mark.asyncio
async def test_successful_call(client: LLMClient):
    mock = AsyncMock(return_value=_make_response("hello"))
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await client.chat([{"role": "user", "content": "hi"}])
    assert result == "hello"


@pytest.mark.asyncio
async def test_temperature_passed(client: LLMClient):
    mock = AsyncMock(return_value=_make_response("ok"))
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        await client.chat([{"role": "user", "content": "hi"}])
    assert mock.call_args.kwargs["temperature"] == 0.5


@pytest.mark.asyncio
async def test_retry_on_transient_error(client: LLMClient):
    mock = AsyncMock(
        side_effect=[
            litellm.RateLimitError("rate limited", "model", "provider", None),
            _make_response("recovered"),
        ]
    )
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        with patch("openswarm.llm.client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.chat([{"role": "user", "content": "hi"}])
    assert result == "recovered"
    assert mock.call_count == 2


@pytest.mark.asyncio
async def test_raise_llm_error_on_permanent_failure(client: LLMClient):
    mock = AsyncMock(side_effect=litellm.AuthenticationError("bad key", "model", "provider", None))
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        with pytest.raises(LLMError, match="bad key"):
            await client.chat([{"role": "user", "content": "hi"}])
    assert mock.call_count == 1  # no retry on permanent error


@pytest.mark.asyncio
async def test_raise_llm_error_after_retry_exhausted(client: LLMClient):
    error = litellm.RateLimitError("rate limited", "model", "provider", None)
    mock = AsyncMock(side_effect=[error, error])
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        with patch("openswarm.llm.client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(LLMError, match="after retry"):
                await client.chat([{"role": "user", "content": "hi"}])
    assert mock.call_count == 2
