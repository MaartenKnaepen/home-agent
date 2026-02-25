"""Home agent main entry point.

Wires together config, database, MCP registry, agent, and Telegram bot.
This is the composition root — the only place where all components are assembled.
"""

from __future__ import annotations

import asyncio
import logging
from home_agent.agent import create_agent, get_agent_toolsets
from home_agent.bot import create_application
from home_agent.config import get_config
from home_agent.db import init_db
from home_agent.history import HistoryManager
from home_agent.mcp.registry import MCPRegistry
from home_agent.mcp.servers import get_jellyseerr_config
from home_agent.profile import ProfileManager

logger = logging.getLogger(__name__)


def setup_logging(log_level: str) -> None:
    """Configure root logger with the given level.

    Args:
        log_level: Logging level string (e.g. 'INFO', 'DEBUG').
    """
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    # Explicitly set the root logger level in case basicConfig was already
    # called (it is a no-op for handlers when called a second time).
    logging.getLogger().setLevel(numeric_level)


async def _async_main() -> None:
    """Async entry point: initializes all components and runs the bot.

    Lifecycle:
    1. Load configuration from environment
    2. Set up logging
    3. Initialize SQLite database (creates tables if needed)
    4. Create ProfileManager and HistoryManager
    5. Create MCPRegistry and register Jellyseerr server
    6. Create agent and enter its context (opens MCP connections once)
    7. Start Telegram bot polling (blocks until interrupted)
    8. On exit: agent context closes MCP connections cleanly
    """
    config = get_config()
    setup_logging(config.log_level)
    logger.info("Starting home-agent...")

    # Ensure DB directory exists
    config.db_path.parent.mkdir(parents=True, exist_ok=True)

    # Initialize database
    logger.info("Initializing database at %s", config.db_path)
    await init_db(config.db_path)

    # Create managers
    profile_manager = ProfileManager(db_path=config.db_path)
    history_manager = HistoryManager(db_path=config.db_path)

    # Register MCP servers
    registry = MCPRegistry()
    registry.register(get_jellyseerr_config(mcp_port=config.mcp_port))
    logger.info("Registered MCP servers: %s", registry.get_tool_names())

    # Create agent with MCP toolsets
    toolsets = get_agent_toolsets(registry)
    logger.info("Creating agent with %d MCP toolsets", len(toolsets))
    logger.info("Using LLM model: %s", config.llm_model)
    agent = create_agent(toolsets=toolsets, model=config.llm_model)

    # Open MCP connections once for the lifetime of the bot
    async with agent:
        logger.info("MCP connections established, starting Telegram bot...")
        app = create_application(config, profile_manager, history_manager, agent)
        async with app:
            await app.start()
            assert app.updater is not None
            await app.updater.start_polling()
            logger.info("Bot is polling. Press Ctrl-C to stop.")
            # Block until stopped
            await asyncio.Event().wait()


def main() -> None:
    """Synchronous entry point — runs the async main loop.

    Raises:
        KeyboardInterrupt: Caught and handled for graceful shutdown.
    """
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        logger.info("Shutting down home-agent...")


if __name__ == "__main__":
    main()
