"""Tests for src/home_agent/models/retry_model.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelResponse, TextPart

from home_agent.models.retry_model import RetryingModel


def make_inner_model(response: ModelResponse | None = None) -> MagicMock:
    """Create a mock inner model with a given response.

    Args:
        response: The ModelResponse to return from ``request``.
            Defaults to a simple text response.

    Returns:
        A MagicMock instance specced as Model with ``model_name`` and async ``request``.
    """
    from pydantic_ai.models import Model

    if response is None:
        response = ModelResponse(parts=[TextPart(content="ok")], model_name="test-model")
    inner = MagicMock(spec=Model)
    inner.model_name = "test-inner-model"
    inner.system = "test"
    inner.request = AsyncMock(return_value=response)
    return inner


def make_429_error() -> ModelHTTPError:
    """Create a 429 ModelHTTPError for testing.

    Returns:
        A ModelHTTPError with status_code=429.
    """
    return ModelHTTPError(status_code=429, model_name="test-model", body={"message": "rate limited"})


def make_500_error() -> ModelHTTPError:
    """Create a 500 ModelHTTPError for testing.

    Returns:
        A ModelHTTPError with status_code=500.
    """
    return ModelHTTPError(status_code=500, model_name="test-model", body={"message": "server error"})


async def test_successful_request_no_retry() -> None:
    """A successful request returns immediately without any retry."""
    inner = make_inner_model()
    model = RetryingModel(inner, max_retries=3, base_delay=1.0)

    with patch("home_agent.models.retry_model.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await model.request([], None, MagicMock())

    assert result is not None
    inner.request.assert_called_once()
    mock_sleep.assert_not_called()


async def test_retries_on_429_then_succeeds() -> None:
    """A 429 error triggers a retry; success on second attempt returns the response."""
    from pydantic_ai.models import Model

    inner = MagicMock(spec=Model)
    inner.model_name = "test-model"
    inner.system = "test"
    good_response = ModelResponse(parts=[TextPart(content="ok")], model_name="test-model")
    inner.request = AsyncMock(side_effect=[make_429_error(), good_response])

    model = RetryingModel(inner, max_retries=3, base_delay=1.0)

    with patch("home_agent.models.retry_model.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await model.request([], None, MagicMock())

    assert result is good_response
    assert inner.request.call_count == 2
    mock_sleep.assert_called_once_with(1.0)


async def test_exponential_backoff_delays() -> None:
    """Delays double on each retry: 1.0, 2.0, 4.0."""
    from pydantic_ai.models import Model

    inner = MagicMock(spec=Model)
    inner.model_name = "test-model"
    inner.system = "test"
    good_response = ModelResponse(parts=[TextPart(content="ok")], model_name="test-model")
    inner.request = AsyncMock(
        side_effect=[make_429_error(), make_429_error(), make_429_error(), good_response]
    )

    model = RetryingModel(inner, max_retries=3, base_delay=1.0)

    with patch("home_agent.models.retry_model.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await model.request([], None, MagicMock())

    assert result is good_response
    delays = [call.args[0] for call in mock_sleep.call_args_list]
    assert delays == [1.0, 2.0, 4.0]


async def test_raises_after_max_retries_exhausted() -> None:
    """After max_retries 429 errors, the final 429 is re-raised."""
    from pydantic_ai.models import Model

    inner = MagicMock(spec=Model)
    inner.model_name = "test-model"
    inner.system = "test"
    inner.request = AsyncMock(side_effect=make_429_error())

    model = RetryingModel(inner, max_retries=2, base_delay=0.1)

    with patch("home_agent.models.retry_model.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(ModelHTTPError) as exc_info:
            await model.request([], None, MagicMock())

    assert exc_info.value.status_code == 429
    # 1 initial + 2 retries = 3 total calls
    assert inner.request.call_count == 3


async def test_non_429_http_error_not_retried() -> None:
    """A non-429 HTTP error (e.g. 500) is raised immediately without retry."""
    from pydantic_ai.models import Model

    inner = MagicMock(spec=Model)
    inner.model_name = "test-model"
    inner.system = "test"
    inner.request = AsyncMock(side_effect=make_500_error())

    model = RetryingModel(inner, max_retries=3, base_delay=1.0)

    with patch("home_agent.models.retry_model.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(ModelHTTPError) as exc_info:
            await model.request([], None, MagicMock())

    assert exc_info.value.status_code == 500
    inner.request.assert_called_once()
    mock_sleep.assert_not_called()


async def test_on_retry_callback_invoked() -> None:
    """The on_retry callback is called with attempt index and wait_seconds."""
    from pydantic_ai.models import Model

    inner = MagicMock(spec=Model)
    inner.model_name = "test-model"
    inner.system = "test"
    good_response = ModelResponse(parts=[TextPart(content="ok")], model_name="test-model")
    inner.request = AsyncMock(side_effect=[make_429_error(), make_429_error(), good_response])

    on_retry = AsyncMock()
    model = RetryingModel(inner, max_retries=3, base_delay=2.0, on_retry=on_retry)

    with patch("home_agent.models.retry_model.asyncio.sleep", new_callable=AsyncMock):
        await model.request([], None, MagicMock())

    assert on_retry.call_count == 2
    on_retry.assert_any_call(0, 2.0)
    on_retry.assert_any_call(1, 4.0)
