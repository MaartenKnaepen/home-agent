"""PydanticAI Model wrapper that retries on HTTP 429 with exponential backoff."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Any

from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters, ModelSettings, StreamedResponse

logger = logging.getLogger(__name__)

OnRetryCallback = Callable[[int, float], Coroutine[Any, Any, None]]


class RetryingModel(Model):
    """A PydanticAI Model wrapper that retries on HTTP 429 with exponential backoff.

    Wraps any :class:`pydantic_ai.models.Model` and intercepts
    :class:`pydantic_ai.exceptions.ModelHTTPError` with ``status_code == 429``,
    sleeping with exponential backoff before re-trying up to ``max_retries`` times.

    Streaming requests are delegated directly without retry because streaming
    responses are stateful and cannot be safely replayed.

    The inner model is resolved lazily from a model name string so that API key
    validation is deferred until the first actual request (honouring
    ``defer_model_check`` semantics used elsewhere in the project).

    Attributes:
        _inner_model: The resolved underlying model (populated on first use).
        _model_name_or_instance: The model name string or Model instance passed at init.
        max_retries: Maximum number of retry attempts after the initial failure.
        base_delay: Base delay in seconds for the first retry. Doubles each attempt.
        max_delay: Maximum delay in seconds for exponential backoff (caps the doubling).
        on_retry: Optional async callback invoked before each retry with
            ``(attempt, wait_seconds)``.
    """

    def __init__(
        self,
        inner: Model | str,
        *,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        on_retry: OnRetryCallback | None = None,
    ) -> None:
        """Initialise the retrying model wrapper.

        Args:
            inner: The underlying PydanticAI model to wrap, or a model name string
                (e.g. ``"openrouter:qwen/qwq-32b:free"``).  When a string is given,
                the model is resolved lazily on the first request so that provider
                API-key validation is deferred.
            max_retries: Maximum number of additional attempts after the first failure.
                Defaults to 3 (i.e. up to 4 total attempts).
            base_delay: Delay in seconds before the first retry. Doubles each retry.
                Defaults to 1.0.
            max_delay: Maximum delay in seconds for exponential backoff. Caps the
                doubling so delays never exceed this value. Defaults to 30.0.
            on_retry: Optional async callback called before each sleep with
                ``(attempt: int, wait_seconds: float)``.  Useful for logging or
                telemetry in tests.
        """
        self._model_name_or_instance = inner
        self._inner_model: Model | None = inner if isinstance(inner, Model) else None
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.on_retry = on_retry

    @property
    def inner(self) -> Model:
        """Resolve and return the inner model, instantiating it if necessary.

        Returns:
            The resolved :class:`~pydantic_ai.models.Model` instance.
        """
        if self._inner_model is None:
            from pydantic_ai.models import infer_model

            self._inner_model = infer_model(self._model_name_or_instance)
        return self._inner_model

    @property
    def model_name(self) -> str:
        """Return the name of the wrapped model.

        Returns:
            The model name string from the inner model.
        """
        return self.inner.model_name

    @property
    def system(self) -> str:
        """Return the system/provider name of the wrapped model.

        Returns:
            The provider system string (e.g. ``"openai"``) from the inner model.
        """
        return self.inner.system

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        """Make a request to the wrapped model, retrying on HTTP 429.

        Retries up to ``max_retries`` times with exponential backoff when the
        inner model raises :class:`~pydantic_ai.exceptions.ModelHTTPError` with
        ``status_code == 429``.  All other exceptions propagate immediately.

        Args:
            messages: The conversation messages to send.
            model_settings: Optional model-level settings (temperature, etc.).
            model_request_parameters: Parameters for this specific request.

        Returns:
            The :class:`~pydantic_ai.messages.ModelResponse` from the model.

        Raises:
            ModelHTTPError: Re-raised after all retries are exhausted, or immediately
                for non-429 HTTP errors.
            Exception: Any non-HTTP exception is propagated immediately.
        """
        delay = self.base_delay
        for attempt in range(self.max_retries + 1):
            try:
                return await self.inner.request(
                    messages, model_settings, model_request_parameters
                )
            except ModelHTTPError as exc:
                if exc.status_code != 429 or attempt >= self.max_retries:
                    raise
                logger.warning(
                    "HTTP 429 rate limit on attempt %d/%d; retrying in %.1fs",
                    attempt + 1,
                    self.max_retries + 1,
                    delay,
                )
                if self.on_retry is not None:
                    await self.on_retry(attempt, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.max_delay)

        # Unreachable — the loop always returns or raises, but satisfies type checkers.
        raise RuntimeError("Retry loop exited unexpectedly")  # pragma: no cover

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> AsyncIterator[StreamedResponse]:
        """Delegate a streaming request to the inner model without retry.

        Streaming responses are stateful and cannot be safely replayed, so no
        retry logic is applied here.

        Args:
            messages: The conversation messages to send.
            model_settings: Optional model-level settings.
            model_request_parameters: Parameters for this specific request.

        Yields:
            The :class:`~pydantic_ai.models.StreamedResponse` from the inner model.
        """
        async with self.inner.request_stream(
            messages, model_settings, model_request_parameters
        ) as stream:
            yield stream
