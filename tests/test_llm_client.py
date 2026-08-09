"""Tests for LLM client error handling, retries, and temperature."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import litellm
import pytest
from conftest import mock_acompletion_stream

from openswarm.config.models import AgentConfig
from openswarm.llm.client import LLMClient, LLMError, LLMResult


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
    resp.usage.prompt_tokens = 30
    resp.usage.completion_tokens = 12
    resp.usage.total_tokens = 42
    return resp


@pytest.mark.asyncio
async def test_successful_call(client: LLMClient):
    mock = AsyncMock(return_value=_make_response("hello"))
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await client.chat([{"role": "user", "content": "hi"}])
    assert isinstance(result, LLMResult)
    assert result.content == "hello"


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
    with (
        patch("openswarm.llm.client.litellm.acompletion", mock),
        patch("openswarm.llm.client.asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await client.chat([{"role": "user", "content": "hi"}])
    assert result.content == "recovered"
    assert mock.call_count == 2


@pytest.mark.asyncio
async def test_raise_llm_error_on_permanent_failure(client: LLMClient):
    mock = AsyncMock(side_effect=litellm.AuthenticationError("bad key", "model", "provider", None))
    with (
        patch("openswarm.llm.client.litellm.acompletion", mock),
        pytest.raises(LLMError, match="bad key"),
    ):
        await client.chat([{"role": "user", "content": "hi"}])
    assert mock.call_count == 1  # no retry on permanent error


@pytest.mark.asyncio
async def test_raise_llm_error_after_retry_exhausted(client: LLMClient):
    error = litellm.RateLimitError("rate limited", "model", "provider", None)
    mock = AsyncMock(side_effect=[error, error, error])
    with (
        patch("openswarm.llm.client.litellm.acompletion", mock),
        patch("openswarm.llm.client.asyncio.sleep", new_callable=AsyncMock),
        pytest.raises(LLMError, match="after 3 attempts"),
    ):
        await client.chat([{"role": "user", "content": "hi"}])
    assert mock.call_count == 3


# --- Streaming tests ---


@pytest.mark.asyncio
async def test_chat_stream_accumulates_result(client: LLMClient):
    mock = mock_acompletion_stream("hello world")
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await client.chat_stream([{"role": "user", "content": "hi"}])
    assert isinstance(result, LLMResult)
    assert result.content == "hello world"


@pytest.mark.asyncio
async def test_chat_stream_calls_on_token(client: LLMClient):
    tokens: list[str] = []
    mock = mock_acompletion_stream("abc")
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await client.chat_stream(
            [{"role": "user", "content": "hi"}], on_token=tokens.append
        )
    assert result.content == "abc"
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
    with (
        patch("openswarm.llm.client.litellm.acompletion", mock),
        patch("openswarm.llm.client.asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await client.chat_stream([{"role": "user", "content": "hi"}])
    assert result.content == "recovered"
    assert mock.call_count == 2


@pytest.mark.asyncio
async def test_chat_stream_raises_on_permanent_failure(client: LLMClient):
    mock = AsyncMock(side_effect=litellm.AuthenticationError("bad key", "model", "provider", None))
    with (
        patch("openswarm.llm.client.litellm.acompletion", mock),
        pytest.raises(LLMError, match="bad key"),
    ):
        await client.chat_stream([{"role": "user", "content": "hi"}])


# --- Usage tracking tests ---


@pytest.mark.asyncio
async def test_chat_returns_usage_stats(client: LLMClient):
    mock = AsyncMock(return_value=_make_response("hello"))
    with (
        patch("openswarm.llm.client.litellm.acompletion", mock),
        patch("openswarm.llm.client.litellm.completion_cost", return_value=0.0015),
    ):
        result = await client.chat([{"role": "user", "content": "hi"}])
    assert result.usage is not None
    assert result.usage.total_tokens == 42
    assert result.usage.model == "gpt-test"
    assert result.usage.cost_usd == 0.0015


@pytest.mark.asyncio
async def test_chat_usage_none_when_no_usage(client: LLMClient):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = "hello"
    resp.usage = None
    mock = AsyncMock(return_value=resp)
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await client.chat([{"role": "user", "content": "hi"}])
    assert result.usage is None


@pytest.mark.asyncio
async def test_chat_stream_returns_usage_stats(client: LLMClient):
    mock = mock_acompletion_stream("abc")
    with (
        patch("openswarm.llm.client.litellm.acompletion", mock),
        patch("openswarm.llm.client.litellm.completion_cost", return_value=0.001),
    ):
        result = await client.chat_stream([{"role": "user", "content": "hi"}])
    assert result.usage is not None
    assert result.usage.total_tokens == 30


# --- Cross-provider streaming chunk shapes ---
#
# Different providers emit usage on different chunks:
#   OpenAI:       terminal chunk with choices=[] carries usage (needs stream_options)
#   Anthropic:    usage attached to the final content chunk (via litellm normalization)
#   Ollama:       no usage at all
# The client must handle all three without crashing or losing data.


def _chunk(content=None, usage=None, no_choices=False):
    c = MagicMock()
    if no_choices:
        c.choices = []
    else:
        c.choices = [MagicMock()]
        c.choices[0].delta.content = content
    if usage is None:
        c.usage = None
    else:
        c.usage = MagicMock()
        c.usage.prompt_tokens = usage[0]
        c.usage.completion_tokens = usage[1]
        c.usage.total_tokens = usage[0] + usage[1]
    return c


@pytest.mark.asyncio
async def test_chat_stream_openai_terminal_usage_chunk(client: LLMClient):
    """OpenAI emits a terminal chunk with empty choices that carries usage."""

    async def _stream():
        yield _chunk(content="Hel")
        yield _chunk(content="lo")
        yield _chunk(no_choices=True, usage=(10, 5))  # terminal usage-only

    mock = AsyncMock(return_value=_stream())
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await client.chat_stream([{"role": "user", "content": "hi"}])
    assert result.content == "Hello"
    assert result.usage is not None
    assert result.usage.prompt_tokens == 10
    assert result.usage.completion_tokens == 5


@pytest.mark.asyncio
async def test_chat_stream_anthropic_usage_on_last_content_chunk(client: LLMClient):
    """Anthropic via litellm: usage piggybacks on the final content chunk."""

    async def _stream():
        yield _chunk(content="Hel")
        yield _chunk(content="lo", usage=(15, 7))

    mock = AsyncMock(return_value=_stream())
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await client.chat_stream([{"role": "user", "content": "hi"}])
    assert result.content == "Hello"
    assert result.usage is not None
    assert result.usage.prompt_tokens == 15
    assert result.usage.completion_tokens == 7


@pytest.mark.asyncio
async def test_chat_stream_provider_with_no_usage(client: LLMClient):
    """Some providers (e.g. Ollama) never emit usage — must not crash."""

    async def _stream():
        yield _chunk(content="Hel")
        yield _chunk(content="lo")

    mock = AsyncMock(return_value=_stream())
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await client.chat_stream([{"role": "user", "content": "hi"}])
    assert result.content == "Hello"
    assert result.usage is None


@pytest.mark.asyncio
async def test_chat_stream_skips_chunks_with_empty_choices_mid_stream(client: LLMClient):
    """Defensive: empty-choices chunks anywhere in the stream don't crash."""

    async def _stream():
        yield _chunk(no_choices=True)  # weird leading chunk
        yield _chunk(content="ok")
        yield _chunk(no_choices=True, usage=(3, 4))

    mock = AsyncMock(return_value=_stream())
    with patch("openswarm.llm.client.litellm.acompletion", mock):
        result = await client.chat_stream([{"role": "user", "content": "hi"}])
    assert result.content == "ok"
    assert result.usage is not None
    assert result.usage.prompt_tokens == 3


# --- Provider response quirks ---


@pytest.mark.asyncio
async def test_null_content_becomes_empty_string(client: LLMClient):
    """Providers return content=null for content filters, tool calls, truncation."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = None
    resp.usage = MagicMock(prompt_tokens=5, completion_tokens=0)

    with patch("openswarm.llm.client.litellm.acompletion", AsyncMock(return_value=resp)):
        result = await client.chat([{"role": "user", "content": "hi"}])

    assert result.content == ""


@pytest.mark.asyncio
async def test_missing_choices_raises_a_clear_error(client: LLMClient):
    """Some gateways answer 200 with an empty choices list."""
    resp = MagicMock()
    resp.choices = []
    resp.usage = None

    with (
        patch("openswarm.llm.client.litellm.acompletion", AsyncMock(return_value=resp)),
        pytest.raises(LLMError, match="no choices"),
    ):
        await client.chat([{"role": "user", "content": "hi"}])


def test_failure_hint_uses_status_not_message_text():
    """Gateways word errors differently; the HTTP status is the only usable signal."""
    from openswarm.llm.client import describe_failure

    def err(status):
        original = Exception("wording varies wildly between gateways")
        original.status_code = status
        return LLMError("boom", original=original)

    assert "api_key" in describe_failure(err(401))
    assert "model name" in describe_failure(err(404))
    assert "provider-side" in describe_failure(err(502))
    assert "host" in describe_failure(LLMError("no original exception at all"))


@pytest.mark.asyncio
async def test_truncated_response_is_flagged(client: LLMClient, caplog):
    """Reasoning models burn the budget thinking; silent truncation looks like an answer."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = "half an ans"
    resp.choices[0].finish_reason = "length"
    resp.usage = MagicMock(prompt_tokens=5, completion_tokens=10)

    with (
        caplog.at_level("WARNING"),
        patch("openswarm.llm.client.litellm.acompletion", AsyncMock(return_value=resp)),
    ):
        result = await client.chat([{"role": "user", "content": "hi"}])

    assert result.content == "half an ans"
    assert "max_tokens" in caplog.text


@pytest.mark.asyncio
async def test_complete_response_is_not_flagged(client: LLMClient, caplog):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = "done"
    resp.choices[0].finish_reason = "stop"
    resp.usage = MagicMock(prompt_tokens=5, completion_tokens=2)

    with (
        caplog.at_level("WARNING"),
        patch("openswarm.llm.client.litellm.acompletion", AsyncMock(return_value=resp)),
    ):
        await client.chat([{"role": "user", "content": "hi"}])

    assert "truncated" not in caplog.text
