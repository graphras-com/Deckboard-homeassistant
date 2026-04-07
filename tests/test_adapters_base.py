"""Tests for deckboard_homeassistant.adapters.base."""

from __future__ import annotations

from typing import Any

import pytest

from deckboard_homeassistant.adapters.base import (
    DomainAdapter,
    MultiEntityAdapter,
    ResolvedAction,
)


class TestResolvedAction:
    def test_basic_construction(self) -> None:
        ra = ResolvedAction("light", "toggle", {"entity_id": "light.kitchen"})
        assert ra.domain == "light"
        assert ra.service == "toggle"
        assert ra.data == {"entity_id": "light.kitchen"}

    def test_frozen(self) -> None:
        ra = ResolvedAction("light", "toggle", {})
        with pytest.raises(AttributeError):
            ra.domain = "x"  # type: ignore[misc]

    def test_equality(self) -> None:
        ra1 = ResolvedAction("a", "b", {"c": 1})
        ra2 = ResolvedAction("a", "b", {"c": 1})
        assert ra1 == ra2


class TestDomainAdapterABC:
    def test_cannot_instantiate_directly(self) -> None:
        with pytest.raises(TypeError):
            DomainAdapter()  # type: ignore[abstract]

    def test_default_state_keys_returns_empty(self) -> None:
        # Create a minimal concrete subclass to test default_state_keys.
        class MinimalAdapter(DomainAdapter):
            @property
            def domain(self) -> str:
                return "test"

            def normalize(
                self, entity_id: str, state: dict[str, Any]
            ) -> dict[str, Any]:
                return {}

            def resolve_action(
                self, entity_id: str, action_name: str, action_args: dict[str, Any]
            ) -> ResolvedAction:
                return ResolvedAction("test", action_name, {})

        adapter = MinimalAdapter()
        assert adapter.default_state_keys() == []


class TestMultiEntityAdapter:
    def test_cannot_instantiate_directly(self) -> None:
        with pytest.raises(TypeError):
            MultiEntityAdapter()  # type: ignore[abstract]

    def test_slot_for_entity_found(self) -> None:
        class ConcreteMulti(MultiEntityAdapter):
            @property
            def domain(self) -> str:
                return "test"

            def normalize_multi(self, slot, entity_id, state, all_states):
                return {}

            def resolve_action_multi(self, entities, action_name, action_args):
                return ResolvedAction("test", action_name, {})

        adapter = ConcreteMulti()
        adapter._entities = {"bass": "number.bass", "treble": "number.treble"}
        assert adapter._slot_for_entity("number.bass") == "bass"
        assert adapter._slot_for_entity("number.treble") == "treble"

    def test_slot_for_entity_not_found(self) -> None:
        class ConcreteMulti(MultiEntityAdapter):
            @property
            def domain(self) -> str:
                return "test"

            def normalize_multi(self, slot, entity_id, state, all_states):
                return {}

            def resolve_action_multi(self, entities, action_name, action_args):
                return ResolvedAction("test", action_name, {})

        adapter = ConcreteMulti()
        adapter._entities = {"bass": "number.bass"}
        assert adapter._slot_for_entity("number.unknown") == "unknown"

    def test_normalize_delegates_to_multi(self) -> None:
        class ConcreteMulti(MultiEntityAdapter):
            @property
            def domain(self) -> str:
                return "test"

            def normalize_multi(self, slot, entity_id, state, all_states):
                return {"slot": slot, "entity": entity_id}

            def resolve_action_multi(self, entities, action_name, action_args):
                return ResolvedAction("test", action_name, {})

        adapter = ConcreteMulti()
        adapter._entities = {"bass": "number.bass"}
        adapter._slot_states = {"bass": {"state": "50"}}

        result = adapter.normalize("number.bass", {"state": "50"})
        assert result == {"slot": "bass", "entity": "number.bass"}

    def test_resolve_action_delegates_to_multi(self) -> None:
        class ConcreteMulti(MultiEntityAdapter):
            @property
            def domain(self) -> str:
                return "test"

            def normalize_multi(self, slot, entity_id, state, all_states):
                return {}

            def resolve_action_multi(self, entities, action_name, action_args):
                return ResolvedAction("test", action_name, {"entities": entities})

        adapter = ConcreteMulti()
        adapter._entities = {"bass": "number.bass"}

        result = adapter.resolve_action("number.bass", "set_bass", {})
        assert result.data == {"entities": {"bass": "number.bass"}}
