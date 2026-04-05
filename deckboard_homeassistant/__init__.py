"""Deckboard Home Assistant integration.

Connects Home Assistant entities to the Deckboard Stream Deck UI library
through a clean abstraction layer. All HA-specific logic is isolated here;
Deckboard remains unmodified and unaware of Home Assistant concepts.
"""

from deckboard_homeassistant.interfaces import Action, CommandBus, StateProvider

__all__ = ["Action", "CommandBus", "StateProvider"]
