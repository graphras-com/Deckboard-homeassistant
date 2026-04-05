"""AppDaemon entry point for the Deckboard Home Assistant integration.

This module provides :class:`DeckboardApp`, an AppDaemon app that initializes
the bridge, loads configuration, builds the controller, and starts the
Deckboard runtime.

AppDaemon Configuration (apps.yaml):
    deckboard:
      module: deckboard_homeassistant.app
      class: DeckboardApp
      config_path: /config/appdaemon/apps/deckboard.yaml
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import hassapi as hass

from deckboard import Deck

from deckboard_homeassistant.bindings import BindingManager
from deckboard_homeassistant.bridge import HomeAssistantBridge
from deckboard_homeassistant.config import load_config
from deckboard_homeassistant.controller import DeckboardController

log = logging.getLogger(__name__)


class DeckboardApp(hass.Hass):
    """AppDaemon app that bridges Home Assistant to Deckboard.

    This is the single entry point.  It:
      1. Creates the HomeAssistantBridge (sole HA integration point).
      2. Loads the YAML configuration.
      3. Creates the BindingManager and DeckboardController.
      4. Starts the Deckboard Deck and wires everything together.
    """

    def initialize(self) -> None:
        """Called by AppDaemon when the app is loaded."""
        config_path = self.args.get("config_path", "deckboard.yaml")
        log.info("Deckboard HA integration starting (config: %s)", config_path)

        # Schedule the async setup on the event loop.
        self._task = self.create_task(self._async_initialize(config_path))

    async def _async_initialize(self, config_path: str) -> None:
        """Async initialization -- sets up all components."""
        loop = asyncio.get_running_loop()

        # 1. Load configuration.
        config = load_config(config_path)
        log.info(
            "Loaded config: %d bindings, %d screens",
            len(config.bindings),
            len(config.screens),
        )

        # 2. Create the bridge -- the only layer that touches HA.
        bridge = HomeAssistantBridge(self, loop)

        # 3. Create the binding manager.
        binding_manager = BindingManager(bridge, bridge, loop)

        # 4. Create and start the Deck.
        self._deck = Deck(
            device_type=config.device_type,
            device_index=config.device_index,
            brightness=config.brightness,
        )
        await self._deck.start()
        log.info("Deck started: %s", self._deck.info.deck_type)

        # 5. Create the controller and wire everything.
        controller = DeckboardController(self._deck, binding_manager, config, loop)
        await controller.setup()

        log.info("Deckboard HA integration ready")

    def terminate(self) -> None:
        """Called by AppDaemon when the app is stopped."""
        log.info("Deckboard HA integration stopping")
        if hasattr(self, "_deck"):
            # Schedule cleanup.
            self.create_task(self._async_terminate())

    async def _async_terminate(self) -> None:
        """Async cleanup."""
        if hasattr(self, "_deck"):
            await self._deck.stop()
            log.info("Deck stopped")
