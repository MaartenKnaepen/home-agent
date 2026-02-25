"""Tests for src/home_agent/main.py."""

from __future__ import annotations

import inspect
import logging
from unittest.mock import patch

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
    # We verify it calls asyncio.run and doesn't raise.
    with patch("home_agent.main.asyncio.run") as mock_asyncio_run:
        main()
        mock_asyncio_run.assert_called_once()
        # The argument should be a coroutine (_async_main())
        args = mock_asyncio_run.call_args[0]
        assert inspect.iscoroutine(args[0])
        args[0].close()  # clean up the coroutine


def test_main_keyboard_interrupt_handled() -> None:
    """main() catches KeyboardInterrupt from asyncio.run and shuts down gracefully."""
    with patch("home_agent.main.asyncio.run", side_effect=KeyboardInterrupt):
        # Should NOT raise — KeyboardInterrupt is caught inside main()
        main()
