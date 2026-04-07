"""Shared fixtures for the test suite."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from deckboard_homeassistant.interfaces import (
    Action,
    CommandBus,
    StateCallback,
    StateProvider,
)


# ---------------------------------------------------------------------------
# Mock StateProvider
# ---------------------------------------------------------------------------


class MockStateProvider(StateProvider):
    """In-memory StateProvider for testing."""

    def __init__(self) -> None:
        self._values: dict[str, Any] = {}
        self._entity_states: dict[str, dict[str, Any]] = {}
        self._subscribers: dict[str, list[StateCallback]] = {}

    async def get_value(self, key: str) -> Any:
        return self._values.get(key)

    def get_entity_state(self, entity_id: str) -> dict[str, Any]:
        return dict(self._entity_states.get(entity_id, {}))

    def subscribe(self, key: str, callback: StateCallback) -> None:
        self._subscribers.setdefault(key, []).append(callback)

    def unsubscribe(self, key: str, callback: StateCallback) -> None:
        cbs = self._subscribers.get(key, [])
        try:
            cbs.remove(callback)
        except ValueError:
            pass

    def set_value(self, key: str, value: Any) -> None:
        self._values[key] = value

    def set_entity_state(self, entity_id: str, state: dict[str, Any]) -> None:
        self._entity_states[entity_id] = state


# ---------------------------------------------------------------------------
# Mock CommandBus
# ---------------------------------------------------------------------------


class MockCommandBus(CommandBus):
    """Records executed actions for assertion."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, Action]] = []

    async def execute(self, binding_key: str, action: Action) -> None:
        self.executed.append((binding_key, action))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_state_provider() -> MockStateProvider:
    return MockStateProvider()


@pytest.fixture
def mock_command_bus() -> MockCommandBus:
    return MockCommandBus()
