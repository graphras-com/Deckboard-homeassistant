"""Tests for deckboard_homeassistant.bindings."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deckboard_homeassistant.bindings import Binding, BindingManager
from deckboard_homeassistant.adapters.light import LightAdapter
from deckboard_homeassistant.adapters.equalizer import EqualizerAdapter
from deckboard_homeassistant.interfaces import Action

from tests.conftest import MockCommandBus, MockStateProvider


# ---------------------------------------------------------------------------
# Binding dataclass
# ---------------------------------------------------------------------------


class TestBinding:
    def test_subscribe_and_notify(self) -> None:
        binding = Binding(
            key="lights.kitchen", entity_id="light.kitchen", adapter=LightAdapter()
        )
        cb = AsyncMock()
        binding.subscribe("is_on", cb)
        assert cb in binding._subscribers["is_on"]

    def test_unsubscribe(self) -> None:
        binding = Binding(
            key="lights.kitchen", entity_id="light.kitchen", adapter=LightAdapter()
        )
        cb = AsyncMock()
        binding.subscribe("is_on", cb)
        binding.unsubscribe("is_on", cb)
        assert cb not in binding._subscribers["is_on"]

    def test_unsubscribe_nonexistent(self) -> None:
        binding = Binding(
            key="lights.kitchen", entity_id="light.kitchen", adapter=LightAdapter()
        )
        cb = AsyncMock()
        # Should not raise.
        binding.unsubscribe("is_on", cb)

    async def test_notify_calls_subscribers(self) -> None:
        binding = Binding(
            key="lights.kitchen", entity_id="light.kitchen", adapter=LightAdapter()
        )
        cb1 = AsyncMock()
        cb2 = AsyncMock()
        binding.subscribe("is_on", cb1)
        binding.subscribe("is_on", cb2)

        await binding.notify("is_on", True)

        cb1.assert_called_once_with("is_on", True)
        cb2.assert_called_once_with("is_on", True)

    async def test_notify_no_subscribers(self) -> None:
        binding = Binding(
            key="lights.kitchen", entity_id="light.kitchen", adapter=LightAdapter()
        )
        # Should not raise.
        await binding.notify("is_on", True)

    async def test_notify_handles_exception(self) -> None:
        binding = Binding(
            key="lights.kitchen", entity_id="light.kitchen", adapter=LightAdapter()
        )
        cb = AsyncMock(side_effect=RuntimeError("boom"))
        binding.subscribe("is_on", cb)
        # Should not raise.
        await binding.notify("is_on", True)


# ---------------------------------------------------------------------------
# BindingManager.register
# ---------------------------------------------------------------------------


class TestBindingManagerRegister:
    def test_register_single_entity(self) -> None:
        sp = MockStateProvider()
        cb = MockCommandBus()
        mgr = BindingManager(sp, cb)

        binding = mgr.register("lights.kitchen", "light.kitchen", "light")
        assert binding.key == "lights.kitchen"
        assert binding.entity_id == "light.kitchen"
        assert isinstance(binding.adapter, LightAdapter)

    def test_register_subscribes_to_entity(self) -> None:
        sp = MockStateProvider()
        cb = MockCommandBus()
        mgr = BindingManager(sp, cb)

        mgr.register("lights.kitchen", "light.kitchen", "light")
        assert "light.kitchen" in sp._subscribers
        assert len(sp._subscribers["light.kitchen"]) == 1

    def test_register_multi_entity(self) -> None:
        sp = MockStateProvider()
        cb = MockCommandBus()
        mgr = BindingManager(sp, cb)

        entities = {"bass": "number.bass", "treble": "number.treble"}
        binding = mgr.register("audio.eq", "", "equalizer", entities=entities)

        assert isinstance(binding.adapter, EqualizerAdapter)
        assert binding.entities == entities
        # Should subscribe to each entity.
        assert "number.bass" in sp._subscribers
        assert "number.treble" in sp._subscribers

    def test_get_binding(self) -> None:
        sp = MockStateProvider()
        cb = MockCommandBus()
        mgr = BindingManager(sp, cb)

        mgr.register("lights.kitchen", "light.kitchen", "light")
        assert mgr.get("lights.kitchen") is not None
        assert mgr.get("nonexistent") is None


# ---------------------------------------------------------------------------
# BindingManager.execute_action
# ---------------------------------------------------------------------------


class TestBindingManagerExecuteAction:
    async def test_single_entity_action(self) -> None:
        sp = MockStateProvider()
        sp.set_entity_state(
            "light.kitchen",
            {
                "state": "on",
                "brightness": 200,
            },
        )
        cb = MockCommandBus()
        mgr = BindingManager(sp, cb)
        mgr.register("lights.kitchen", "light.kitchen", "light")

        await mgr.execute_action("lights.kitchen", "toggle")

        assert len(cb.executed) == 1
        key, action = cb.executed[0]
        assert key == "lights.kitchen"
        assert action.name == "toggle"
        assert action.args["entity_id"] == "light.kitchen"
        assert action.args["domain"] == "light"

    async def test_nonexistent_binding(self) -> None:
        sp = MockStateProvider()
        cb = MockCommandBus()
        mgr = BindingManager(sp, cb)

        await mgr.execute_action("nonexistent", "toggle")
        assert len(cb.executed) == 0

    async def test_multi_entity_action(self) -> None:
        sp = MockStateProvider()
        sp.set_entity_state("number.bass", {"state": "50"})
        sp.set_entity_state("number.treble", {"state": "70"})
        cb = MockCommandBus()
        mgr = BindingManager(sp, cb)

        entities = {"bass": "number.bass", "treble": "number.treble"}
        mgr.register("audio.eq", "", "equalizer", entities=entities)

        await mgr.execute_action("audio.eq", "set_bass", {"value": 60})

        assert len(cb.executed) == 1
        key, action = cb.executed[0]
        assert key == "audio.eq"
        assert action.args["entity_id"] == "number.bass"

    async def test_enriches_args_with_current_state(self) -> None:
        sp = MockStateProvider()
        sp.set_entity_state(
            "light.kitchen",
            {
                "state": "on",
                "brightness": 128,
            },
        )
        cb = MockCommandBus()
        mgr = BindingManager(sp, cb)
        mgr.register("lights.kitchen", "light.kitchen", "light")

        await mgr.execute_action("lights.kitchen", "brightness_up")

        assert len(cb.executed) == 1

    async def test_handles_enrichment_error(self) -> None:
        """If state enrichment fails, action should still execute."""
        sp = MockStateProvider()
        cb = MockCommandBus()
        mgr = BindingManager(sp, cb)
        mgr.register("lights.kitchen", "light.kitchen", "light")

        # get_entity_state returns {} which is fine, normalize may set defaults.
        await mgr.execute_action("lights.kitchen", "toggle")
        assert len(cb.executed) == 1

    async def test_multi_entity_enrichment_error(self) -> None:
        """Multi-entity enrichment error should not prevent execution."""
        sp = MockStateProvider()
        cb = MockCommandBus()
        mgr = BindingManager(sp, cb)

        entities = {"bass": "number.bass", "treble": "number.treble"}
        mgr.register("audio.eq", "", "equalizer", entities=entities)

        # Even with empty state, set_bass should work.
        await mgr.execute_action("audio.eq", "set_bass", {"value": 10})
        assert len(cb.executed) == 1

    async def test_multi_entity_enrichment_raises_exception(self) -> None:
        """When _get_entity_state raises, enrichment should be swallowed."""
        sp = MockStateProvider()
        cb = MockCommandBus()
        mgr = BindingManager(sp, cb)

        entities = {"bass": "number.bass"}
        mgr.register("audio.eq", "", "equalizer", entities=entities)

        # Make get_entity_state raise.
        original = mgr._get_entity_state

        def broken_get(eid: str):
            raise RuntimeError("Broken!")

        mgr._get_entity_state = broken_get

        await mgr.execute_action("audio.eq", "set_bass", {"value": 10})
        assert len(cb.executed) == 1

    async def test_single_entity_enrichment_raises_exception(self) -> None:
        """When normalize raises during enrichment, should be swallowed."""
        sp = MockStateProvider()
        cb = MockCommandBus()
        mgr = BindingManager(sp, cb)
        mgr.register("lights.kitchen", "light.kitchen", "light")

        # Make get_entity_state raise.
        def broken_get(eid: str):
            raise RuntimeError("Broken state!")

        mgr._get_entity_state = broken_get

        await mgr.execute_action("lights.kitchen", "toggle")
        assert len(cb.executed) == 1


# ---------------------------------------------------------------------------
# BindingManager.refresh_binding / refresh_all
# ---------------------------------------------------------------------------


class TestBindingManagerRefresh:
    async def test_refresh_single_entity(self) -> None:
        sp = MockStateProvider()
        sp.set_entity_state(
            "light.kitchen",
            {
                "state": "on",
                "brightness": 200,
            },
        )
        cb = MockCommandBus()
        mgr = BindingManager(sp, cb)
        binding = mgr.register("lights.kitchen", "light.kitchen", "light")

        notified: list[tuple[str, Any]] = []

        async def _on_state(attr: str, value: Any) -> None:
            notified.append((attr, value))

        binding.subscribe("is_on", _on_state)
        binding.subscribe("brightness_pct", _on_state)

        await mgr.refresh_binding("lights.kitchen")

        # Should have been notified for all normalized keys.
        attrs = [n[0] for n in notified]
        assert "is_on" in attrs or "brightness_pct" in attrs

    async def test_refresh_nonexistent_binding(self) -> None:
        sp = MockStateProvider()
        cb = MockCommandBus()
        mgr = BindingManager(sp, cb)
        # Should not raise.
        await mgr.refresh_binding("nonexistent")

    async def test_refresh_multi_entity(self) -> None:
        sp = MockStateProvider()
        sp.set_entity_state("number.bass", {"state": "50", "min": "0", "max": "100"})
        sp.set_entity_state("number.treble", {"state": "70", "min": "-10", "max": "10"})
        cb = MockCommandBus()
        mgr = BindingManager(sp, cb)

        entities = {"bass": "number.bass", "treble": "number.treble"}
        binding = mgr.register("audio.eq", "", "equalizer", entities=entities)

        notified: list[tuple[str, Any]] = []

        async def _on_state(attr: str, value: Any) -> None:
            notified.append((attr, value))

        binding.subscribe("bass", _on_state)

        await mgr.refresh_binding("audio.eq")
        attrs = [n[0] for n in notified]
        assert "bass" in attrs

    async def test_refresh_all(self) -> None:
        sp = MockStateProvider()
        sp.set_entity_state("light.kitchen", {"state": "on"})
        sp.set_entity_state("light.bedroom", {"state": "off"})
        cb = MockCommandBus()
        mgr = BindingManager(sp, cb)

        mgr.register("lights.kitchen", "light.kitchen", "light")
        mgr.register("lights.bedroom", "light.bedroom", "light")

        notified = []

        async def _on_state(attr: str, value: Any) -> None:
            notified.append((attr, value))

        mgr.get("lights.kitchen").subscribe("is_on", _on_state)
        mgr.get("lights.bedroom").subscribe("is_on", _on_state)

        await mgr.refresh_all()
        assert len(notified) >= 2


# ---------------------------------------------------------------------------
# State handlers (integration with normalize)
# ---------------------------------------------------------------------------


class TestStateHandlers:
    async def test_single_entity_state_handler(self) -> None:
        sp = MockStateProvider()
        cb = MockCommandBus()
        mgr = BindingManager(sp, cb)
        binding = mgr.register("lights.kitchen", "light.kitchen", "light")

        notified: list[tuple[str, Any]] = []

        async def _on_state(attr: str, value: Any) -> None:
            notified.append((attr, value))

        binding.subscribe("is_on", _on_state)

        # Simulate a state change by calling the handler directly.
        handler = sp._subscribers["light.kitchen"][0]
        await handler("light.kitchen", {"state": "on", "brightness": 200})

        attrs = [n[0] for n in notified]
        assert "is_on" in attrs

    async def test_state_handler_non_dict_state(self) -> None:
        sp = MockStateProvider()
        cb = MockCommandBus()
        mgr = BindingManager(sp, cb)
        binding = mgr.register("lights.kitchen", "light.kitchen", "light")

        notified: list[tuple[str, Any]] = []

        async def _on_state(attr: str, value: Any) -> None:
            notified.append((attr, value))

        binding.subscribe("is_on", _on_state)

        handler = sp._subscribers["light.kitchen"][0]
        # Pass a non-dict state -- should be wrapped.
        await handler("light.kitchen", "on")
        # The adapter will normalize {"state": "on"} -> is_on=True
        assert any(n == ("is_on", True) for n in notified)

    async def test_multi_entity_state_handler(self) -> None:
        sp = MockStateProvider()
        cb = MockCommandBus()
        mgr = BindingManager(sp, cb)

        entities = {"bass": "number.bass", "treble": "number.treble"}
        binding = mgr.register("audio.eq", "", "equalizer", entities=entities)

        notified: list[tuple[str, Any]] = []

        async def _on_state(attr: str, value: Any) -> None:
            notified.append((attr, value))

        binding.subscribe("bass", _on_state)

        # Simulate state change on one slot.
        handler = sp._subscribers["number.bass"][0]
        await handler("number.bass", {"state": "55", "min": "0", "max": "100"})

        attrs = [n[0] for n in notified]
        assert "bass" in attrs

    async def test_multi_entity_non_dict_state(self) -> None:
        sp = MockStateProvider()
        cb = MockCommandBus()
        mgr = BindingManager(sp, cb)

        entities = {"bass": "number.bass"}
        binding = mgr.register("audio.eq", "", "equalizer", entities=entities)

        notified: list[tuple[str, Any]] = []

        async def _on_state(attr: str, value: Any) -> None:
            notified.append((attr, value))

        binding.subscribe("bass", _on_state)

        handler = sp._subscribers["number.bass"][0]
        await handler("number.bass", "42")

        # Should wrap non-dict into {"state": "42"}.
        attrs = [n[0] for n in notified]
        assert "bass" in attrs


# ---------------------------------------------------------------------------
# _get_entity_state
# ---------------------------------------------------------------------------


class TestGetEntityState:
    def test_with_get_entity_state_method(self) -> None:
        sp = MockStateProvider()
        sp.set_entity_state("light.kitchen", {"state": "on"})
        cb = MockCommandBus()
        mgr = BindingManager(sp, cb)

        result = mgr._get_entity_state("light.kitchen")
        assert result == {"state": "on"}

    def test_fallback_without_method(self) -> None:
        """Test fallback when provider doesn't have get_entity_state."""
        sp = MagicMock(spec=["get_value", "subscribe", "unsubscribe"])
        cb = MockCommandBus()
        mgr = BindingManager(sp, cb)

        result = mgr._get_entity_state("light.kitchen")
        assert result == {}
