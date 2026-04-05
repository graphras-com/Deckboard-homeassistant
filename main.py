"""Standalone entry point for the Deckboard Home Assistant service.

Runs as an asyncio daemon on a Raspberry Pi (or any Linux host) with a
Stream Deck connected via USB.  Connects to Home Assistant over the network
using the WebSocket API.

Usage:
    python main.py [config_path]
    python -m deckboard_homeassistant [config_path]

Environment variables:
    DECKBOARD_HA_TOKEN  -- HA long-lived access token (preferred over YAML).
    DECKBOARD_CONFIG    -- Config file path (default: deckboard.yaml).
    DECKBOARD_LOG_LEVEL -- Logging level (default: INFO).

Suitable for running under systemd.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from deckboard import Deck

from deckboard_homeassistant.bindings import BindingManager
from deckboard_homeassistant.bridge import HomeAssistantBridge
from deckboard_homeassistant.client import HomeAssistantClient
from deckboard_homeassistant.config import load_config
from deckboard_homeassistant.controller import DeckboardController

log = logging.getLogger("deckboard_homeassistant")


async def run(config_path: str) -> None:
    """Main application lifecycle."""
    # ------------------------------------------------------------------
    # 1. Load configuration.
    # ------------------------------------------------------------------
    config = load_config(config_path)
    ha = config.homeassistant

    if not ha.token:
        log.error(
            "No HA access token configured. Set DECKBOARD_HA_TOKEN or "
            "configure homeassistant.token_env in %s",
            config_path,
        )
        sys.exit(1)

    log.info(
        "Config loaded: %d bindings, %d screens, HA @ %s",
        len(config.bindings),
        len(config.screens),
        ha.url,
    )

    # ------------------------------------------------------------------
    # 2. Create the HA WebSocket client.
    # ------------------------------------------------------------------
    client = HomeAssistantClient(
        url=ha.url,
        token=ha.token,
        reconnect_delay=ha.reconnect_delay,
    )

    # ------------------------------------------------------------------
    # 3. Create the bridge (StateProvider + CommandBus).
    # ------------------------------------------------------------------
    bridge = HomeAssistantBridge(client)

    # ------------------------------------------------------------------
    # 4. Create the binding manager.
    # ------------------------------------------------------------------
    binding_manager = BindingManager(bridge, bridge)

    # ------------------------------------------------------------------
    # 5. Open the Stream Deck device.
    # ------------------------------------------------------------------
    shutdown_event = asyncio.Event()

    # Wire OS signals for graceful shutdown.
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown_event.set)

    async with Deck(
        device_type=config.device_type,
        device_index=config.device_index,
        brightness=config.brightness,
    ) as deck:
        # ------------------------------------------------------------------
        # 6. Build the controller and wire UI.
        # ------------------------------------------------------------------
        controller = DeckboardController(deck, binding_manager, config)
        await controller.setup()

        # ------------------------------------------------------------------
        # 7. Connect to HA and start the event loop.
        # ------------------------------------------------------------------
        async def _on_connected() -> None:
            """Called after each (re)connect to HA."""
            await bridge.load_initial_states()
            await binding_manager.refresh_all()
            await deck.refresh()
            log.info("UI synchronized with Home Assistant")

        async def _connection_lifecycle() -> None:
            """Manage the HA connection with automatic reconnect."""
            while not shutdown_event.is_set():
                try:
                    await client.connect()
                    await _on_connected()

                    # Run until disconnected or shutdown.
                    if client._receiver_task:
                        done, _ = await asyncio.wait(
                            [
                                client._receiver_task,
                                asyncio.create_task(shutdown_event.wait()),
                            ],
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        # If shutdown was triggered, break out.
                        if shutdown_event.is_set():
                            break
                except (
                    ConnectionError,
                    OSError,
                    asyncio.TimeoutError,
                ) as exc:
                    log.warning("HA connection failed: %s", exc)
                except Exception:
                    log.exception("Unexpected error in HA connection")

                if not shutdown_event.is_set():
                    log.info("Reconnecting in %.0fs...", ha.reconnect_delay)
                    try:
                        await asyncio.wait_for(
                            shutdown_event.wait(), timeout=ha.reconnect_delay
                        )
                    except asyncio.TimeoutError:
                        pass  # Timeout means we should reconnect.
                    if shutdown_event.is_set():
                        break

        # Run the connection lifecycle alongside the deck.
        connection_task = asyncio.create_task(
            _connection_lifecycle(), name="ha-connection"
        )

        log.info("Deckboard HA service running. Waiting for shutdown signal.")

        # Wait for shutdown signal.
        await shutdown_event.wait()

        log.info("Shutting down...")

        # Cancel the connection lifecycle.
        connection_task.cancel()
        try:
            await connection_task
        except asyncio.CancelledError:
            pass

        # Disconnect from HA.
        await client.disconnect()

    log.info("Deck closed. Goodbye.")


def _load_env_file(config_path: str) -> None:
    """Load a .env file into os.environ if it exists.

    Searches for ``.env`` in the same directory as the config file,
    then falls back to the current working directory.  Only sets
    variables that are not already defined in the environment (so real
    env vars always win).
    """
    candidates = [
        Path(config_path).parent / ".env",
        Path.cwd() / ".env",
    ]
    for env_path in candidates:
        if env_path.is_file():
            with env_path.open() as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip("\"'")
                    if key and key not in os.environ:
                        os.environ[key] = value
            log.debug("Loaded env file: %s", env_path)
            return  # Only load the first one found.


def main() -> None:
    """CLI entrypoint."""
    config_path = (
        sys.argv[1]
        if len(sys.argv) > 1
        else os.environ.get("DECKBOARD_CONFIG", "deckboard.yaml")
    )

    # Load .env before reading log level or config (token may be in .env).
    _load_env_file(config_path)

    log_level = os.environ.get("DECKBOARD_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not Path(config_path).exists():
        log.error("Config file not found: %s", config_path)
        sys.exit(1)

    asyncio.run(run(config_path))


if __name__ == "__main__":
    main()
