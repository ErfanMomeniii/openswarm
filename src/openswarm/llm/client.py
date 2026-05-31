"""Thin wrapper around litellm for unified LLM access."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx
import litellm

from openswarm.config.models import AgentConfig
from openswarm.core.usage import UsageStats

litellm.use_aiohttp_transport = False
litellm.disable_aiohttp_transport = True

litellm.aclient_session = httpx.AsyncClient(trust_env=False, follow_redirects=True)

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Raised when an LLM call fails after retries."""

    def __init__(self, message: str, original: Exception | None = None) -> None:
        super().__init__(message)
        self.original = original


@dataclass
class LLMResult:
    """LLM response content paired with optional usage stats."""

    content: str
    usage: UsageStats | None = None


# Transient errors worth retrying once
_TRANSIENT_EXCEPTIONS = (
    litellm.RateLimitError,
    litellm.Timeout,
    litellm.APIConnectionError,
    litellm.ServiceUnavailableError,
    litellm.InternalServerError,
)


def _extract_usage(response, model: str, elapsed: float) -> UsageStats | None:
    """Extract usage stats from a litellm response, return None on failure."""
    usage = getattr(response, "usage", None)
    if not usage:
        return None

    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
    completion_tokens = getattr(usage, "completion_tokens", 0) or 0

    cost: float | None = None
    try:
        cost = litellm.completion_cost(completion_response=response)
    except Exception:
        pass

    return UsageStats(
        agent_name="",  # filled by Agent
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost,
        elapsed_seconds=elapsed,
    )


class LLMClient:
    """LLM client that talks to any provider via litellm."""

    def __init__(self, config: AgentConfig) -> None:
        self.model = config.model
        self.api_key = config.api_key
        self.api_base = config.host
        self.max_tokens = config.max_tokens
        self.temperature = config.temperature

    async def chat(self, messages: list[dict[str, str]]) -> LLMResult:
        """Send messages to LLM, return LLMResult with content and usage.

        Retries up to 2 times on transient errors (rate limit, timeout, connection).
        Raises LLMError on permanent failures.
        """
        max_attempts = 3
        last_error: Exception | None = None

        for attempt in range(max_attempts):
            if attempt > 0:
                wait = 2.0 * attempt
                logger.info(f"Retrying LLM call to {self.model} after {wait}s...")
                await asyncio.sleep(wait)

            try:
                start = time.monotonic()
                response = await litellm.acompletion(
                    model=self.model,
                    messages=messages,
                    api_key=self.api_key,
                    api_base=self.api_base,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                )
                elapsed = time.monotonic() - start

                usage_stats = _extract_usage(response, self.model, elapsed)

                tokens = f", tokens={usage_stats.total_tokens}" if usage_stats else ""
                logger.info(f"LLM call to {self.model}: {elapsed:.2f}s{tokens}")

                content = response.choices[0].message.content
                return LLMResult(content=content, usage=usage_stats)

            except _TRANSIENT_EXCEPTIONS as e:
                last_error = e
                logger.warning(f"Transient LLM error (attempt {attempt + 1}/{max_attempts}): {e}")
                if attempt < max_attempts - 1:
                    continue
                raise LLMError(
                    f"LLM call to {self.model} failed after {max_attempts} attempts: {e}",
                    original=e,
                ) from e

            except Exception as e:
                raise LLMError(f"LLM call to {self.model} failed: {e}", original=e) from e

        # Should not reach here, but safety net
        raise LLMError(f"LLM call to {self.model} failed: {last_error}", original=last_error)

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        on_token: Callable[[str], None] | None = None,
    ) -> LLMResult:
        """Send messages to LLM with streaming, return LLMResult.

        Calls on_token(chunk) for each streamed token. Same retry logic as chat().
        """
        max_attempts = 3
        last_error: Exception | None = None

        for attempt in range(max_attempts):
            if attempt > 0:
                wait = 2.0 * attempt
                logger.info(f"Retrying streaming LLM call to {self.model} after {wait}s...")
                await asyncio.sleep(wait)

            try:
                start = time.monotonic()
                response = await litellm.acompletion(
                    model=self.model,
                    messages=messages,
                    api_key=self.api_key,
                    api_base=self.api_base,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    stream=True,
                    stream_options={"include_usage": True},
                )

                accumulated = []
                usage_chunk = None
                async for chunk in response:
                    if getattr(chunk, "usage", None):
                        usage_chunk = chunk
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    content = getattr(delta, "content", None)
                    if content:
                        accumulated.append(content)
                        if on_token:
                            on_token(content)

                elapsed = time.monotonic() - start
                result = "".join(accumulated)

                # OpenAI-compatible streams put usage on a terminal chunk with empty choices.
                usage_stats = (
                    _extract_usage(usage_chunk, self.model, elapsed) if usage_chunk else None
                )

                tokens = f", tokens={usage_stats.total_tokens}" if usage_stats else ""
                logger.info(f"Streaming LLM call to {self.model}: {elapsed:.2f}s{tokens}")
                return LLMResult(content=result, usage=usage_stats)

            except _TRANSIENT_EXCEPTIONS as e:
                last_error = e
                logger.warning(f"Transient LLM error (attempt {attempt + 1}/{max_attempts}): {e}")
                if attempt < max_attempts - 1:
                    continue
                raise LLMError(
                    f"Streaming LLM call to {self.model} failed after {max_attempts} attempts: {e}",
                    original=e,
                ) from e

            except Exception as e:
                raise LLMError(f"Streaming LLM call to {self.model} failed: {e}", original=e) from e

        raise LLMError(
            f"Streaming LLM call to {self.model} failed: {last_error}", original=last_error
        )
