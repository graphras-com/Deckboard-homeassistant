"""Standalone entry point for testing without AppDaemon.

This demonstrates the controller wiring with a mock bridge.
For production use, deploy via AppDaemon (see examples/apps.yaml).
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from deckboard import Deck

from deckboard_homeassistant.bindings import BindingManager
from deckboard_homeassistant.config import load_config
from deckboard_homeassistant.controller import DeckboardController
from deckboard_homeassistant.interfaces import (
    Action,
    CommandBus,
    StateCallback,
    StateProvider,
)

logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


class MockBridge(StateProvider, CommandBus):
    """In-memory mock for testing without Home Assistant."""

    def __init__(self) -> None:
        self._state: dict[str, dict[str, Any]] = {}
        self._cache: dict[str, dict[str, Any]] = {}
        self._subscribers: dict[str, list[StateCallback]] = {}

    def set_entity_state(self, entity_id: str, attrs: dict[str, Any]) -> None:
        """Inject mock entity state."""
        self._cache[entity_id] = dict(attrs)

    async def get_value(self, key: str) -> Any:
        entity_id, attribute = self._parse_key(key)
        cached = self._cache.get(entity_id, {})
        return cached.get(attribute)

    def subscribe(self, key: str, callback: StateCallback) -> None:
        self._subscribers.setdefault(key, []).append(callback)

    def unsubscribe(self, key: str, callback: StateCallback) -> None:
        cbs = self._subscribers.get(key, [])
        try:
            cbs.remove(callback)
        except ValueError:
            pass

    async def execute(self, binding_key: str, action: Action) -> None:
        log.info("MOCK EXECUTE: %s -> %s %s", binding_key, action.name, action.args)

    @staticmethod
    def _parse_key(key: str) -> tuple[str, str]:
        parts = key.split(".")
        if len(parts) <= 2:
            return key, "state"
        return f"{parts[0]}.{parts[1]}", ".".join(parts[2:])


async def main() -> None:
    config_path = sys.argv[1] if len(sys.argv) > 1 else "examples/deckboard.yaml"

    if not Path(config_path).exists():
        log.error("Config file not found: %s", config_path)
        sys.exit(1)

    config = load_config(config_path)
    log.info(
        "Loaded %d bindings, %d screens", len(config.bindings), len(config.screens)
    )

    loop = asyncio.get_running_loop()

    # Create mock bridge with sample state.
    bridge = MockBridge()
    bridge.set_entity_state(
        "light.kitchen",
        {
            "state": "on",
            "brightness": 200,
            "color_temp_kelvin": 3500,
            "color_mode": "color_temp",
        },
    )
    bridge.set_entity_state(
        "light.living_room",
        {
            "state": "off",
            "brightness": 0,
            "color_temp_kelvin": 4000,
            "color_mode": "color_temp",
        },
    )
    bridge.set_entity_state(
        "media_player.living_room",
        {
            "state": "playing",
            "volume_level": 0.65,
            "is_volume_muted": False,
            "media_title": "Bohemian Rhapsody",
            "media_artist": "Queen",
        },
    )
    bridge.set_entity_state(
        "media_player.bedroom_speaker",
        {
            "state": "idle",
            "volume_level": 0.40,
            "is_volume_muted": False,
            "media_title": "",
        },
    )

    binding_manager = BindingManager(bridge, bridge, loop)

    async with Deck(
        device_type=config.device_type,
        device_index=config.device_index,
        brightness=config.brightness,
    ) as deck:
        controller = DeckboardController(deck, binding_manager, config, loop)
        await controller.setup()
        log.info("Ready. Press Ctrl+C to exit.")
        await deck.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
