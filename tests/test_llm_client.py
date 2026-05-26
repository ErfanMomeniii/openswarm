"""Tests for LLM client error handling, retries, and temperature."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import litellm

from openswarm.config.models import AgentConfig
from openswarm.llm.client import LLMClient, LLMError

from conftest import mock_acompletion_stream


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
    mock = AsyncMock(side_effect=[error, error, error])
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        with patch("openswarm.llm.client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(LLMError, match="after 3 attempts"):
                await client.chat([{"role": "user", "content": "hi"}])
    assert mock.call_count == 3


# --- Streaming tests ---


@pytest.mark.asyncio
async def test_chat_stream_accumulates_result(client: LLMClient):
    mock = mock_acompletion_stream("hello world")
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await client.chat_stream([{"role": "user", "content": "hi"}])
    assert result == "hello world"


@pytest.mark.asyncio
async def test_chat_stream_calls_on_token(client: LLMClient):
    tokens: list[str] = []
    mock = mock_acompletion_stream("abc")
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await client.chat_stream(
            [{"role": "user", "content": "hi"}], on_token=tokens.append
        )
    assert result == "abc"
    assert tokens == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_chat_stream_passes_stream_true(client: LLMClient):
    mock = mock_acompletion_stream("ok")
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        await client.chat_stream([{"role": "user", "content": "hi"}])
    assert mock.call_args.kwargs["stream"] is True


@pytest.mark.asyncio
async def test_chat_stream_retries_on_transient_error(client: LLMClient):
    error = litellm.RateLimitError("rate limited", "model", "provider", None)

    async def _stream():
        for ch in "recovered":
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = ch
            yield chunk

    mock = AsyncMock(side_effect=[error, _stream()])
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        with patch("openswarm.llm.client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.chat_stream([{"role": "user", "content": "hi"}])
    assert result == "recovered"
    assert mock.call_count == 2


@pytest.mark.asyncio
async def test_chat_stream_raises_on_permanent_failure(client: LLMClient):
    mock = AsyncMock(side_effect=litellm.AuthenticationError("bad key", "model", "provider", None))
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        with pytest.raises(LLMError, match="bad key"):
            await client.chat_stream([{"role": "user", "content": "hi"}])
