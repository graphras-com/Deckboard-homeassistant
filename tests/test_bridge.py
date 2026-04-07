"""Tests for deckboard_homeassistant.bridge."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deckboard_homeassistant.bridge import HomeAssistantBridge
from deckboard_homeassistant.interfaces import Action


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_client(
    connected: bool = True,
    states: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """Return a mock HomeAssistantClient."""
    client = MagicMock()
    client.connected = connected
    client.on_state_changed = MagicMock()
    client.get_states = AsyncMock(return_value=states or [])
    client.call_service = AsyncMock(return_value=None)
    return client


# ---------------------------------------------------------------------------
# _parse_key
# ---------------------------------------------------------------------------


class TestParseKey:
    def test_bare_entity_id(self) -> None:
        eid, attr = HomeAssistantBridge._parse_key("light.kitchen")
        assert eid == "light.kitchen"
        assert attr == "state"

    def test_entity_with_attribute(self) -> None:
        eid, attr = HomeAssistantBridge._parse_key("light.kitchen.brightness")
        assert eid == "light.kitchen"
        assert attr == "brightness"

    def test_deep_attribute(self) -> None:
        eid, attr = HomeAssistantBridge._parse_key("light.kitchen.deep.nested")
        assert eid == "light.kitchen"
        assert attr == "deep.nested"

    def test_single_part(self) -> None:
        eid, attr = HomeAssistantBridge._parse_key("something")
        assert eid == "something"
        assert attr == "state"


# ---------------------------------------------------------------------------
# _update_cache
# ---------------------------------------------------------------------------


class TestUpdateCache:
    def test_flattens_state(self) -> None:
        client = _make_mock_client()
        bridge = HomeAssistantBridge(client)

        bridge._update_cache(
            "light.kitchen",
            {
                "state": "on",
                "attributes": {"brightness": 200, "friendly_name": "Kitchen"},
            },
        )

        cached = bridge._cache["light.kitchen"]
        assert cached["state"] == "on"
        assert cached["brightness"] == 200
        assert cached["friendly_name"] == "Kitchen"

    def test_missing_attributes(self) -> None:
        client = _make_mock_client()
        bridge = HomeAssistantBridge(client)

        bridge._update_cache("light.kitchen", {"state": "off"})
        cached = bridge._cache["light.kitchen"]
        assert cached["state"] == "off"

    def test_missing_state(self) -> None:
        client = _make_mock_client()
        bridge = HomeAssistantBridge(client)

        bridge._update_cache("light.kitchen", {})
        cached = bridge._cache["light.kitchen"]
        assert cached["state"] == "unavailable"


# ---------------------------------------------------------------------------
# get_value / get_entity_state
# ---------------------------------------------------------------------------


class TestGetValue:
    async def test_get_value_state(self) -> None:
        client = _make_mock_client()
        bridge = HomeAssistantBridge(client)
        bridge._update_cache(
            "light.kitchen",
            {
                "state": "on",
                "attributes": {"brightness": 200},
            },
        )

        value = await bridge.get_value("light.kitchen")
        assert value == "on"

    async def test_get_value_attribute(self) -> None:
        client = _make_mock_client()
        bridge = HomeAssistantBridge(client)
        bridge._update_cache(
            "light.kitchen",
            {
                "state": "on",
                "attributes": {"brightness": 200},
            },
        )

        value = await bridge.get_value("light.kitchen.brightness")
        assert value == 200

    async def test_get_value_missing_entity(self) -> None:
        client = _make_mock_client()
        bridge = HomeAssistantBridge(client)
        value = await bridge.get_value("light.nonexistent")
        assert value is None

    def test_get_entity_state(self) -> None:
        client = _make_mock_client()
        bridge = HomeAssistantBridge(client)
        bridge._update_cache(
            "light.kitchen",
            {
                "state": "on",
                "attributes": {"brightness": 200},
            },
        )

        state = bridge.get_entity_state("light.kitchen")
        assert state["state"] == "on"
        assert state["brightness"] == 200

    def test_get_entity_state_missing(self) -> None:
        client = _make_mock_client()
        bridge = HomeAssistantBridge(client)
        state = bridge.get_entity_state("light.nonexistent")
        assert state == {}

    def test_get_entity_state_returns_copy(self) -> None:
        client = _make_mock_client()
        bridge = HomeAssistantBridge(client)
        bridge._update_cache(
            "light.kitchen",
            {
                "state": "on",
                "attributes": {},
            },
        )
        state = bridge.get_entity_state("light.kitchen")
        state["mutated"] = True
        assert "mutated" not in bridge._cache["light.kitchen"]


# ---------------------------------------------------------------------------
# subscribe / unsubscribe
# ---------------------------------------------------------------------------


class TestSubscription:
    def test_subscribe_and_unsubscribe(self) -> None:
        client = _make_mock_client()
        bridge = HomeAssistantBridge(client)

        cb = AsyncMock()
        bridge.subscribe("light.kitchen", cb)
        assert cb in bridge._subscribers["light.kitchen"]

        bridge.unsubscribe("light.kitchen", cb)
        assert cb not in bridge._subscribers["light.kitchen"]

    def test_unsubscribe_nonexistent(self) -> None:
        client = _make_mock_client()
        bridge = HomeAssistantBridge(client)
        cb = AsyncMock()
        # Should not raise.
        bridge.unsubscribe("light.kitchen", cb)

    def test_subscribe_with_attribute_key(self) -> None:
        client = _make_mock_client()
        bridge = HomeAssistantBridge(client)
        cb = AsyncMock()
        bridge.subscribe("light.kitchen.brightness", cb)
        # Should be subscribed to the entity_id.
        assert cb in bridge._subscribers["light.kitchen"]


# ---------------------------------------------------------------------------
# load_initial_states
# ---------------------------------------------------------------------------


class TestLoadInitialStates:
    async def test_populates_cache(self) -> None:
        states = [
            {
                "entity_id": "light.kitchen",
                "state": "on",
                "attributes": {"brightness": 200},
            },
            {
                "entity_id": "light.bedroom",
                "state": "off",
                "attributes": {},
            },
        ]
        client = _make_mock_client(states=states)
        bridge = HomeAssistantBridge(client)

        await bridge.load_initial_states()

        assert "light.kitchen" in bridge._cache
        assert bridge._cache["light.kitchen"]["state"] == "on"
        assert "light.bedroom" in bridge._cache

    async def test_skips_empty_entity_id(self) -> None:
        states = [{"entity_id": "", "state": "on", "attributes": {}}]
        client = _make_mock_client(states=states)
        bridge = HomeAssistantBridge(client)

        await bridge.load_initial_states()
        assert "" not in bridge._cache

    async def test_handles_exception(self) -> None:
        client = _make_mock_client()
        client.get_states = AsyncMock(side_effect=Exception("Connection failed"))
        bridge = HomeAssistantBridge(client)

        # Should not raise.
        await bridge.load_initial_states()
        assert bridge._cache == {}


# ---------------------------------------------------------------------------
# reload_states
# ---------------------------------------------------------------------------


class TestReloadStates:
    async def test_notifies_subscribers(self) -> None:
        states = [
            {
                "entity_id": "light.kitchen",
                "state": "on",
                "attributes": {"brightness": 200},
            }
        ]
        client = _make_mock_client(states=states)
        bridge = HomeAssistantBridge(client)

        cb = AsyncMock()
        bridge.subscribe("light.kitchen", cb)

        await bridge.reload_states()

        cb.assert_called_once()
        call_args = cb.call_args
        assert call_args[0][0] == "light.kitchen"

    async def test_handles_subscriber_error(self) -> None:
        states = [{"entity_id": "light.kitchen", "state": "on", "attributes": {}}]
        client = _make_mock_client(states=states)
        bridge = HomeAssistantBridge(client)

        cb = AsyncMock(side_effect=Exception("Subscriber error"))
        bridge.subscribe("light.kitchen", cb)

        # Should not raise.
        await bridge.reload_states()

    async def test_skips_entities_not_in_cache(self) -> None:
        client = _make_mock_client(states=[])
        bridge = HomeAssistantBridge(client)
        cb = AsyncMock()
        bridge.subscribe("light.unknown", cb)

        await bridge.reload_states()
        cb.assert_not_called()


# ---------------------------------------------------------------------------
# _on_state_changed
# ---------------------------------------------------------------------------


class TestOnStateChanged:
    async def test_updates_cache_and_notifies(self) -> None:
        client = _make_mock_client()
        bridge = HomeAssistantBridge(client)

        cb = AsyncMock()
        bridge.subscribe("light.kitchen", cb)

        await bridge._on_state_changed(
            "light.kitchen",
            {
                "state": "on",
                "attributes": {"brightness": 255},
            },
        )

        assert bridge._cache["light.kitchen"]["state"] == "on"
        assert bridge._cache["light.kitchen"]["brightness"] == 255
        cb.assert_called_once()

    async def test_handles_callback_error(self) -> None:
        client = _make_mock_client()
        bridge = HomeAssistantBridge(client)

        cb = AsyncMock(side_effect=RuntimeError("boom"))
        bridge.subscribe("light.kitchen", cb)

        # Should not raise.
        await bridge._on_state_changed(
            "light.kitchen",
            {
                "state": "on",
                "attributes": {},
            },
        )


# ---------------------------------------------------------------------------
# execute (CommandBus)
# ---------------------------------------------------------------------------


class TestExecute:
    async def test_calls_service(self) -> None:
        client = _make_mock_client(connected=True)
        bridge = HomeAssistantBridge(client)

        action = Action(
            name="toggle",
            args={
                "entity_id": "light.kitchen",
                "domain": "light",
            },
        )

        await bridge.execute("lights.kitchen", action)

        client.call_service.assert_called_once_with(
            "light",
            "toggle",
            service_data={},
            target={"entity_id": "light.kitchen"},
        )

    async def test_not_connected(self) -> None:
        client = _make_mock_client(connected=False)
        bridge = HomeAssistantBridge(client)

        action = Action(name="toggle", args={"entity_id": "x", "domain": "light"})
        await bridge.execute("lights.kitchen", action)

        client.call_service.assert_not_called()

    async def test_missing_entity_id(self) -> None:
        client = _make_mock_client(connected=True)
        bridge = HomeAssistantBridge(client)

        action = Action(name="toggle", args={"domain": "light"})
        await bridge.execute("lights.kitchen", action)

        client.call_service.assert_not_called()

    async def test_missing_domain(self) -> None:
        client = _make_mock_client(connected=True)
        bridge = HomeAssistantBridge(client)

        action = Action(name="toggle", args={"entity_id": "light.kitchen"})
        await bridge.execute("lights.kitchen", action)

        client.call_service.assert_not_called()

    async def test_timeout_error(self) -> None:
        client = _make_mock_client(connected=True)
        client.call_service = AsyncMock(side_effect=asyncio.TimeoutError())
        bridge = HomeAssistantBridge(client)

        action = Action(name="toggle", args={"entity_id": "x", "domain": "light"})
        # Should not raise.
        await bridge.execute("lights.kitchen", action)

    async def test_connection_error(self) -> None:
        client = _make_mock_client(connected=True)
        client.call_service = AsyncMock(side_effect=ConnectionError())
        bridge = HomeAssistantBridge(client)

        action = Action(name="toggle", args={"entity_id": "x", "domain": "light"})
        await bridge.execute("lights.kitchen", action)

    async def test_generic_error(self) -> None:
        client = _make_mock_client(connected=True)
        client.call_service = AsyncMock(side_effect=RuntimeError("boom"))
        bridge = HomeAssistantBridge(client)

        action = Action(name="toggle", args={"entity_id": "x", "domain": "light"})
        await bridge.execute("lights.kitchen", action)

    async def test_service_data_excludes_entity_and_domain(self) -> None:
        client = _make_mock_client(connected=True)
        bridge = HomeAssistantBridge(client)

        action = Action(
            name="turn_on",
            args={
                "entity_id": "light.kitchen",
                "domain": "light",
                "brightness": 200,
            },
        )
        await bridge.execute("lights.kitchen", action)

        call_args = client.call_service.call_args
        assert call_args[1]["service_data"] == {"brightness": 200}
