"""Core interfaces for the integration layer.

These define the abstraction boundary between the UI (Deckboard) and the
backend (Home Assistant). Neither side imports the other directly; they
communicate exclusively through these contracts.

A different backend (MQTT, REST, mock) can be substituted by implementing
StateProvider and CommandBus without touching any UI code.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine


@dataclass(frozen=True, slots=True)
class Action:
    """A named command with arguments.

    Actions are the unit of intent flowing from UI to backend.
    They carry no HA-specific types -- just a name and keyword arguments.

    Examples:
        Action("toggle")
        Action("set_brightness", args={"brightness": 80})
        Action("media_next_track")
    """

    name: str
    args: dict[str, Any] = field(default_factory=dict)


# Callback types used by the state system.
StateCallback = Callable[[str, Any], Coroutine[Any, Any, None]]


class StateProvider(ABC):
    """Read and subscribe to state values by logical key.

    Logical keys are dot-separated paths like ``lights.kitchen.is_on``.
    The provider resolves them to concrete backend entities and attributes.
    """

    @abstractmethod
    async def get_value(self, key: str) -> Any:
        """Return the current value for *key*, or None if unavailable."""

    @abstractmethod
    def subscribe(self, key: str, callback: StateCallback) -> None:
        """Register *callback* to be called when *key* changes.

        The callback signature is ``async callback(key, new_value)``.
        """

    @abstractmethod
    def unsubscribe(self, key: str, callback: StateCallback) -> None:
        """Remove a previously registered callback for *key*."""


class CommandBus(ABC):
    """Execute actions dispatched by the UI layer.

    The bus resolves action names to concrete backend service calls.
    """

    @abstractmethod
    async def execute(self, binding_key: str, action: Action) -> None:
        """Execute *action* in the context of *binding_key*.

        Parameters:
            binding_key: The logical binding (e.g. ``lights.kitchen``) that
                provides entity context for the action.
            action: The action to perform.
        """
