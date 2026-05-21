"""Thin wrapper around litellm for unified LLM access."""

from __future__ import annotations

import asyncio
import logging
import time

import httpx
import litellm

from openswarm.config.models import AgentConfig

litellm.use_aiohttp_transport = False
litellm.disable_aiohttp_transport = True

litellm.aclient_session = httpx.AsyncClient(trust_env=False, follow_redirects=True)

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Raised when an LLM call fails after retries."""

    def __init__(self, message: str, original: Exception | None = None) -> None:
        super().__init__(message)
        self.original = original


# Transient errors worth retrying once
_TRANSIENT_EXCEPTIONS = (
    litellm.RateLimitError,
    litellm.Timeout,
    litellm.APIConnectionError,
    litellm.ServiceUnavailableError,
    litellm.InternalServerError,
)


class LLMClient:
    """LLM client that talks to any provider via litellm."""

    def __init__(self, config: AgentConfig) -> None:
        self.model = config.model
        self.api_key = config.api_key
        self.api_base = config.host
        self.max_tokens = config.max_tokens
        self.temperature = config.temperature

    async def chat(self, messages: list[dict[str, str]]) -> str:
        """Send messages to LLM, return assistant response text.

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

                usage = getattr(response, "usage", None)
                tokens = f", tokens={usage.total_tokens}" if usage else ""
                logger.info(f"LLM call to {self.model}: {elapsed:.2f}s{tokens}")

                return response.choices[0].message.content

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
