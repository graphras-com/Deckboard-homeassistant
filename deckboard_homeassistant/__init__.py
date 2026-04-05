"""Deckboard Home Assistant integration.

Connects Home Assistant entities to the Deckboard Stream Deck UI library
through a clean abstraction layer. All HA-specific logic is isolated in
the client and bridge modules; Deckboard remains unmodified and unaware
of Home Assistant concepts.

This package is designed to run as a standalone asyncio service on a
Raspberry Pi (or similar device) with a Stream Deck connected via USB.
"""

from deckboard_homeassistant.interfaces import Action, CommandBus, StateProvider

__all__ = ["Action", "CommandBus", "StateProvider"]
