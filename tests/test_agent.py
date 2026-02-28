"""Tests for src/home_agent/agent.py.

Covers agent instantiation, tool registration, system prompt injection,
tool side-effects, and basic output behaviour. Never calls a real LLM —
uses PydanticAI's TestModel throughout.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from home_agent.agent import AgentDeps, create_agent, get_agent_toolsets
from home_agent.config import AppConfig
from home_agent.history import HistoryManager
from home_agent.profile import ProfileManager, UserProfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_agent_deps(
    config: AppConfig,
    profile_manager: ProfileManager,
    history_manager: HistoryManager,
    user_id: int = 123,
) -> AgentDeps:
    """Build an AgentDeps with a pre-populated UserProfile.

    Args:
        config: Application configuration.
        profile_manager: Manages user profile persistence.
        history_manager: Manages conversation history.
        user_id: Telegram user ID to use for the profile.

    Returns:
        Fully populated AgentDeps ready for agent.run().
    """
    profile = UserProfile(
        user_id=user_id,
        name="Alice",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    return AgentDeps(
        config=config,
        profile_manager=profile_manager,
        history_manager=history_manager,
        user_profile=profile,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_agent_instantiates() -> None:
    """Agent object exists and has the correct deps_type."""
    agent_instance = create_agent()
    assert agent_instance is not None
    assert agent_instance.deps_type is AgentDeps


async def test_agent_has_update_user_note_tool(
    mock_config: AppConfig, test_db: Path
) -> None:
    """update_user_note tool is registered on the agent."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    deps = make_agent_deps(mock_config, profile_manager, history_manager)

    agent_instance = create_agent()
    m = TestModel()
    with agent_instance.override(model=m):
        async with agent_instance:
            await agent_instance.run("hello", deps=deps)

    assert m.last_model_request_parameters is not None
    tool_names = [t.name for t in m.last_model_request_parameters.function_tools]
    assert "update_user_note" in tool_names


async def test_system_prompt_contains_user_profile(
    mock_config: AppConfig, test_db: Path
) -> None:
    """Dynamic system prompt includes the user's name."""
    from pydantic_ai.messages import SystemPromptPart

    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    deps = make_agent_deps(mock_config, profile_manager, history_manager)

    agent_instance = create_agent()
    m = TestModel()
    with agent_instance.override(model=m):
        async with agent_instance:
            result = await agent_instance.run("hello", deps=deps)

    # The system prompt parts are embedded in the ModelRequest of all_messages()
    all_system_text = " ".join(
        part.content
        for msg in result.all_messages()
        for part in msg.parts
        if isinstance(part, SystemPromptPart)
    )
    assert "Alice" in all_system_text


async def test_update_user_note_tool_persists_note(
    mock_config: AppConfig, test_db: Path
) -> None:
    """Calling update_user_note saves the note to the user profile via ProfileManager."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    deps = make_agent_deps(mock_config, profile_manager, history_manager, user_id=42)

    # Save the initial profile so ProfileManager.save() can update it
    await profile_manager.save(deps.user_profile)

    agent_instance = create_agent()
    m = TestModel(call_tools=["update_user_note"])
    with agent_instance.override(model=m):
        async with agent_instance:
            await agent_instance.run("remember that I like sci-fi", deps=deps)

    # The profile in deps should have the note appended
    assert len(deps.user_profile.notes) > 0

    # And the note should be persisted in the DB
    saved_profile = await profile_manager.get(42)
    assert len(saved_profile.notes) > 0


async def test_update_user_note_updates_deps(
    mock_config: AppConfig, test_db: Path
) -> None:
    """update_user_note tool updates ctx.deps.user_profile.notes."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    deps = make_agent_deps(mock_config, profile_manager, history_manager, user_id=55)
    await profile_manager.save(deps.user_profile)

    agent_instance = create_agent()
    m = TestModel(call_tools=["update_user_note"])
    with agent_instance.override(model=m):
        async with agent_instance:
            await agent_instance.run("I love sci-fi movies", deps=deps)

    assert len(deps.user_profile.notes) > 0


async def test_agent_returns_output(
    mock_config: AppConfig, test_db: Path
) -> None:
    """Agent returns the custom_output_text when configured on TestModel."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    deps = make_agent_deps(mock_config, profile_manager, history_manager)

    agent_instance = create_agent()
    m = TestModel(custom_output_text="Hello from the agent!")
    with agent_instance.override(model=m):
        async with agent_instance:
            result = await agent_instance.run("hi", deps=deps)

    assert result.output == "Hello from the agent!"


def test_get_agent_toolsets_delegates_to_registry() -> None:
    """get_agent_toolsets() returns whatever registry.get_toolsets() returns."""
    from unittest.mock import MagicMock

    from home_agent.mcp.registry import MCPRegistry

    mock_registry = MagicMock(spec=MCPRegistry)
    mock_registry.get_toolsets.return_value = ["toolset_a", "toolset_b"]

    result = get_agent_toolsets(mock_registry)

    mock_registry.get_toolsets.assert_called_once()
    assert result == ["toolset_a", "toolset_b"]


async def test_dynamic_prompt_shows_not_set_when_quality_is_none(
    mock_config: AppConfig, test_db: Path
) -> None:
    """Dynamic prompt shows 'NOT SET' when movie/series quality is not configured."""
    from pydantic_ai.messages import SystemPromptPart

    from home_agent.profile import MediaPreferences

    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    # Profile with no quality set
    profile = UserProfile(
        user_id=99,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        media_preferences=MediaPreferences(movie_quality=None, series_quality=None),
    )
    deps = AgentDeps(
        config=mock_config,
        profile_manager=profile_manager,
        history_manager=history_manager,
        user_profile=profile,
    )

    agent_instance = create_agent()
    m = TestModel()
    with agent_instance.override(model=m):
        async with agent_instance:
            result = await agent_instance.run("hello", deps=deps)

    all_system_text = " ".join(
        part.content
        for msg in result.all_messages()
        for part in msg.parts
        if isinstance(part, SystemPromptPart)
    )
    assert "NOT SET" in all_system_text


async def test_dynamic_prompt_shows_language(
    mock_config: AppConfig, test_db: Path
) -> None:
    """Dynamic prompt includes the user's reply language."""
    from pydantic_ai.messages import SystemPromptPart

    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    profile = UserProfile(
        user_id=100,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        reply_language="Dutch",
    )
    deps = AgentDeps(
        config=mock_config,
        profile_manager=profile_manager,
        history_manager=history_manager,
        user_profile=profile,
    )

    agent_instance = create_agent()
    m = TestModel()
    with agent_instance.override(model=m):
        async with agent_instance:
            result = await agent_instance.run("hello", deps=deps)

    all_system_text = " ".join(
        part.content
        for msg in result.all_messages()
        for part in msg.parts
        if isinstance(part, SystemPromptPart)
    )
    assert "Dutch" in all_system_text


async def test_dynamic_prompt_shows_confirmation_mode(
    mock_config: AppConfig, test_db: Path
) -> None:
    """Dynamic prompt includes the confirmation mode."""
    from pydantic_ai.messages import SystemPromptPart

    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    profile = UserProfile(
        user_id=101,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        confirmation_mode="never",
    )
    deps = AgentDeps(
        config=mock_config,
        profile_manager=profile_manager,
        history_manager=history_manager,
        user_profile=profile,
    )

    agent_instance = create_agent()
    m = TestModel()
    with agent_instance.override(model=m):
        async with agent_instance:
            result = await agent_instance.run("hello", deps=deps)

    all_system_text = " ".join(
        part.content
        for msg in result.all_messages()
        for part in msg.parts
        if isinstance(part, SystemPromptPart)
    )
    assert "never" in all_system_text


async def test_dynamic_prompt_shows_quality_when_set(
    mock_config: AppConfig, test_db: Path
) -> None:
    """Dynamic prompt shows quality values when they are configured."""
    from pydantic_ai.messages import SystemPromptPart

    from home_agent.profile import MediaPreferences

    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    profile = UserProfile(
        user_id=102,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        media_preferences=MediaPreferences(movie_quality="4k", series_quality="1080p"),
    )
    deps = AgentDeps(
        config=mock_config,
        profile_manager=profile_manager,
        history_manager=history_manager,
        user_profile=profile,
    )

    agent_instance = create_agent()
    m = TestModel()
    with agent_instance.override(model=m):
        async with agent_instance:
            result = await agent_instance.run("hello", deps=deps)

    all_system_text = " ".join(
        part.content
        for msg in result.all_messages()
        for part in msg.parts
        if isinstance(part, SystemPromptPart)
    )
    assert "4k" in all_system_text
    assert "1080p" in all_system_text
    # The dynamic portion should NOT contain the "NOT SET" placeholder phrase
    assert "NOT SET — ask the user before making any movie request" not in all_system_text
    assert "NOT SET — ask the user before making any series request" not in all_system_text


async def test_static_prompt_contains_media_request_instructions(
    mock_config: AppConfig, test_db: Path
) -> None:
    """Static system prompt contains key media request instructions."""
    from pydantic_ai.messages import SystemPromptPart

    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    deps = make_agent_deps(mock_config, profile_manager, history_manager)

    agent_instance = create_agent()
    m = TestModel()
    with agent_instance.override(model=m):
        async with agent_instance:
            result = await agent_instance.run("hello", deps=deps)

    all_system_text = " ".join(
        part.content
        for msg in result.all_messages()
        for part in msg.parts
        if isinstance(part, SystemPromptPart)
    )
    # Key structural instructions from the numbered media request flow
    assert "search_media" in all_system_text
    assert "SEARCH FIRST" in all_system_text
    assert "DISAMBIGUATE" in all_system_text
    assert "CONFIRM" in all_system_text
    assert "quality" in all_system_text.lower()


async def test_set_movie_quality_tool_is_callable_when_quality_unset(
    mock_config: AppConfig, test_db: Path
) -> None:
    """Agent can call set_movie_quality tool when movie quality is not set.

    This verifies the tool is registered and callable — simulating the
    agent deciding to ask for quality during a media request.
    """
    from home_agent.profile import MediaPreferences

    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    profile = UserProfile(
        user_id=103,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        media_preferences=MediaPreferences(movie_quality=None),
    )
    await profile_manager.save(profile)

    deps = AgentDeps(
        config=mock_config,
        profile_manager=profile_manager,
        history_manager=history_manager,
        user_profile=profile,
    )

    agent_instance = create_agent()
    # TestModel configured to call set_movie_quality — simulates the agent
    # deciding to set quality based on the NOT SET prompt instruction
    m = TestModel(call_tools=["set_movie_quality"])
    with agent_instance.override(model=m):
        async with agent_instance:
            await agent_instance.run("I want to download Troy", deps=deps)

    # Tool should have updated movie_quality on the profile in deps
    assert deps.user_profile.media_preferences.movie_quality is not None

    # And persisted to DB
    saved = await profile_manager.get(103)
    assert saved.media_preferences.movie_quality is not None


async def test_static_prompt_contains_disambiguation_instructions(
    mock_config: AppConfig, test_db: Path
) -> None:
    """Static system prompt contains disambiguation instructions."""
    from pydantic_ai.messages import SystemPromptPart

    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    deps = make_agent_deps(mock_config, profile_manager, history_manager)

    agent_instance = create_agent()
    m = TestModel()
    with agent_instance.override(model=m):
        async with agent_instance:
            result = await agent_instance.run("hello", deps=deps)

    all_system_text = " ".join(
        part.content
        for msg in result.all_messages()
        for part in msg.parts
        if isinstance(part, SystemPromptPart)
    )
    # Disambiguation instructions must be present
    assert "DISAMBIGUATE" in all_system_text
    assert "numbered list" in all_system_text
    # Must never suggest exposing technical IDs
    assert "TMDB" in all_system_text  # mentions to NEVER expose it
    assert "technical identifiers" in all_system_text


async def test_static_prompt_handles_single_result_skip(
    mock_config: AppConfig, test_db: Path
) -> None:
    """Static system prompt instructs agent to skip disambiguation for single clear match."""
    from pydantic_ai.messages import SystemPromptPart

    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    deps = make_agent_deps(mock_config, profile_manager, history_manager)

    agent_instance = create_agent()
    m = TestModel()
    with agent_instance.override(model=m):
        async with agent_instance:
            result = await agent_instance.run("hello", deps=deps)

    all_system_text = " ".join(
        part.content
        for msg in result.all_messages()
        for part in msg.parts
        if isinstance(part, SystemPromptPart)
    )
    # Single match should skip to quality step
    assert "ONE clear match" in all_system_text or "only ONE" in all_system_text


async def test_static_prompt_handles_franchise_disambiguation(
    mock_config: AppConfig, test_db: Path
) -> None:
    """Static system prompt instructs agent to disambiguate sequels and franchises."""
    from pydantic_ai.messages import SystemPromptPart

    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    deps = make_agent_deps(mock_config, profile_manager, history_manager)

    agent_instance = create_agent()
    m = TestModel()
    with agent_instance.override(model=m):
        async with agent_instance:
            result = await agent_instance.run("hello", deps=deps)

    all_system_text = " ".join(
        part.content
        for msg in result.all_messages()
        for part in msg.parts
        if isinstance(part, SystemPromptPart)
    )
    # Franchise/sequel handling must be mentioned
    assert "sequels" in all_system_text or "franchise" in all_system_text
