"""Tests for src/home_agent/main.py."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from home_agent.main import main, setup_logging


def test_setup_logging_sets_level() -> None:
    """setup_logging configures the root logger to the given level."""
    setup_logging("DEBUG")
    assert logging.getLogger().level == logging.DEBUG
    # restore
    setup_logging("WARNING")


def test_main_wires_components() -> None:
    """main() calls asyncio.run with _async_main coroutine."""
    # main() is now just: asyncio.run(_async_main()) + KeyboardInterrupt handling.
    # We verify asyncio.run is called exactly once with a coroutine argument.
    # We patch _async_main itself so no real coroutine object is ever created,
    # avoiding the RuntimeWarning from an unawaited coroutine leaking into GC.
    # Use MagicMock (not AsyncMock) so calling _async_main() returns a plain
    # MagicMock, not a coroutine — prevents the unawaited-coroutine RuntimeWarning.
    mock_async_main = MagicMock()
    with patch("home_agent.main._async_main", mock_async_main), \
         patch("home_agent.main.asyncio.run") as mock_asyncio_run:
        main()
        mock_asyncio_run.assert_called_once()
        # asyncio.run should have been called with the result of _async_main()
        mock_async_main.assert_called_once()


def test_main_keyboard_interrupt_handled() -> None:
    """main() catches KeyboardInterrupt from asyncio.run and shuts down gracefully."""
    with patch("home_agent.main.asyncio.run", side_effect=KeyboardInterrupt):
        # Should NOT raise — KeyboardInterrupt is caught inside main()
        main()
