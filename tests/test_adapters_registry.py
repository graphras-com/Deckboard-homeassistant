"""Tests for deckboard_homeassistant.adapters registry."""

from __future__ import annotations

from typing import Any

import pytest

from deckboard_homeassistant.adapters import (
    ClimateAdapter,
    DomainAdapter,
    EqualizerAdapter,
    LightAdapter,
    MediaPlayerAdapter,
    get_adapter,
    register_adapter,
)
from deckboard_homeassistant.adapters.base import ResolvedAction


class TestGetAdapter:
    def test_light(self) -> None:
        adapter = get_adapter("light")
        assert isinstance(adapter, LightAdapter)

    def test_media_player(self) -> None:
        adapter = get_adapter("media_player")
        assert isinstance(adapter, MediaPlayerAdapter)

    def test_climate(self) -> None:
        adapter = get_adapter("climate")
        assert isinstance(adapter, ClimateAdapter)

    def test_equalizer(self) -> None:
        adapter = get_adapter("equalizer")
        assert isinstance(adapter, EqualizerAdapter)

    def test_unknown_raises_key_error(self) -> None:
        with pytest.raises(KeyError):
            get_adapter("nonexistent")

    def test_returns_new_instance_each_time(self) -> None:
        a1 = get_adapter("light")
        a2 = get_adapter("light")
        assert a1 is not a2


class TestRegisterAdapter:
    def test_register_and_retrieve_custom(self) -> None:
        class CustomAdapter(DomainAdapter):
            @property
            def domain(self) -> str:
                return "custom"

            def normalize(
                self, entity_id: str, state: dict[str, Any]
            ) -> dict[str, Any]:
                return {"custom": True}

            def resolve_action(
                self, entity_id: str, action_name: str, action_args: dict[str, Any]
            ) -> ResolvedAction:
                return ResolvedAction("custom", action_name, {})

        register_adapter("custom", CustomAdapter)
        adapter = get_adapter("custom")
        assert isinstance(adapter, CustomAdapter)
        assert adapter.domain == "custom"

    def test_override_existing(self) -> None:
        class FakeLight(DomainAdapter):
            @property
            def domain(self) -> str:
                return "light"

            def normalize(
                self, entity_id: str, state: dict[str, Any]
            ) -> dict[str, Any]:
                return {"fake": True}

            def resolve_action(
                self, entity_id: str, action_name: str, action_args: dict[str, Any]
            ) -> ResolvedAction:
                return ResolvedAction("light", action_name, {})

        register_adapter("light", FakeLight)
        adapter = get_adapter("light")
        assert isinstance(adapter, FakeLight)

        # Restore the original.
        register_adapter("light", LightAdapter)
