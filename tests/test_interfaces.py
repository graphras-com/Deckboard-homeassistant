"""Tests for deckboard_homeassistant.interfaces."""

from __future__ import annotations

import pytest

from deckboard_homeassistant.interfaces import Action, CommandBus, StateProvider


class TestAction:
    """Tests for the Action frozen dataclass."""

    def test_basic_construction(self) -> None:
        a = Action("toggle")
        assert a.name == "toggle"
        assert a.args == {}

    def test_construction_with_args(self) -> None:
        a = Action("set_brightness", args={"brightness": 80})
        assert a.name == "set_brightness"
        assert a.args == {"brightness": 80}

    def test_default_args_are_independent(self) -> None:
        a1 = Action("a")
        a2 = Action("b")
        assert a1.args is not a2.args

    def test_frozen_immutability(self) -> None:
        a = Action("toggle")
        with pytest.raises(AttributeError):
            a.name = "other"  # type: ignore[misc]

    def test_equality(self) -> None:
        a1 = Action("toggle", args={"x": 1})
        a2 = Action("toggle", args={"x": 1})
        assert a1 == a2

    def test_inequality(self) -> None:
        a1 = Action("toggle")
        a2 = Action("turn_on")
        assert a1 != a2


class TestAbstractInterfaces:
    """Verify that StateProvider and CommandBus cannot be instantiated directly."""

    def test_state_provider_is_abstract(self) -> None:
        with pytest.raises(TypeError):
            StateProvider()  # type: ignore[abstract]

    def test_command_bus_is_abstract(self) -> None:
        with pytest.raises(TypeError):
            CommandBus()  # type: ignore[abstract]
