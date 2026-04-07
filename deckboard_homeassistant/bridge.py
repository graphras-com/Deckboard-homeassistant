"""Home Assistant bridge -- the sole HA integration point.

This module is the ONLY place that consumes the :class:`HomeAssistantClient`.
Every other module communicates through :class:`StateProvider` and
:class:`CommandBus` interfaces.

The bridge:
  * Maintains a normalized in-memory state cache of all subscribed entities.
  * Receives real-time ``state_changed`` events from the WebSocket client.
  * Exposes ``call_service`` for outbound commands via the client.
  * Rebuilds its cache after a reconnect.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from deckboard_homeassistant.client import HomeAssistantClient
from deckboard_homeassistant.interfaces import (
    Action,
    CommandBus,
    StateCallback,
    StateProvider,
)

log = logging.getLogger(__name__)


class HomeAssistantBridge(StateProvider, CommandBus):
    """Bridges the standalone HA WebSocket client to the abstraction layer.

    Parameters:
        client: A connected (or connecting) :class:`HomeAssistantClient`.
    """

    def __init__(self, client: HomeAssistantClient) -> None:
        self._client = client

        # entity_id -> {attribute -> value}  (flattened: state + attributes)
        self._cache: dict[str, dict[str, Any]] = {}

        # entity_id -> list[StateCallback]
        self._subscribers: dict[str, list[StateCallback]] = {}

        # Wire ourselves into the client's event stream.
        self._client.on_state_changed(self._on_state_changed)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def load_initial_states(self) -> None:
        """Fetch all entity states and populate the cache.

        Call this after the client connects (or reconnects).
        """
        try:
            states = await self._client.get_states()
        except Exception:
            log.exception("Failed to fetch initial states")
            return

        for state_obj in states:
            entity_id = state_obj.get("entity_id", "")
            if not entity_id:
                continue
            self._update_cache(entity_id, state_obj)

        log.info("Cached %d entity states", len(self._cache))

    async def reload_states(self) -> None:
        """Re-fetch all states and notify subscribers.

        Use after a reconnect to bring the cache up to date and push
        fresh values to the UI.
        """
        await self.load_initial_states()

        # Notify all subscribers with refreshed cache values.
        for entity_id, callbacks in self._subscribers.items():
            cached = self._cache.get(entity_id, {})
            if not cached:
                continue
            for cb in callbacks:
                try:
                    await cb(entity_id, cached)
                except Exception:
                    log.exception("Error notifying subscriber for %s", entity_id)

    # ------------------------------------------------------------------
    # StateProvider
    # ------------------------------------------------------------------

    async def get_value(self, key: str) -> Any:
        """Return current value for a logical state key.

        Keys are either bare entity IDs (``light.kitchen`` -> ``state``)
        or dotted paths (``light.kitchen.brightness`` -> ``brightness``).
        """
        entity_id, attribute = self._parse_key(key)

        cached = self._cache.get(entity_id, {})
        return cached.get(attribute)

    def get_entity_state(self, entity_id: str) -> dict[str, Any]:
        """Return the full cached state dict for an entity (or empty)."""
        return dict(self._cache.get(entity_id, {}))

    def subscribe(self, key: str, callback: StateCallback) -> None:
        """Register *callback* for state changes on *key* (entity_id)."""
        entity_id, _attribute = self._parse_key(key)
        self._subscribers.setdefault(entity_id, []).append(callback)

    def unsubscribe(self, key: str, callback: StateCallback) -> None:
        entity_id, _attribute = self._parse_key(key)
        cbs = self._subscribers.get(entity_id, [])
        try:
            cbs.remove(callback)
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # CommandBus
    # ------------------------------------------------------------------

    async def execute(self, binding_key: str, action: Action) -> None:
        """Execute *action* by calling the appropriate HA service.

        Best-effort: logs and swallows errors so a failed service call
        never crashes the UI event loop.
        """
        if not self._client.connected:
            log.warning("Cannot execute %s -- not connected to HA", action.name)
            return

        entity_id: str | None = action.args.get("entity_id")
        domain: str | None = action.args.get("domain")

        if not entity_id or not domain:
            log.error("Action %s missing entity_id or domain", action.name)
            return

        service = action.name
        service_data: dict[str, Any] = {
            k: v for k, v in action.args.items() if k not in ("entity_id", "domain")
        }

        target = {"entity_id": entity_id}

        log.info(
            "Calling %s/%s target=%s data=%s", domain, service, target, service_data
        )

        try:
            await self._client.call_service(
                domain, service, service_data=service_data, target=target
            )
        except asyncio.TimeoutError:
            log.warning("Service call %s/%s timed out", domain, service)
        except ConnectionError:
            log.warning("Service call %s/%s failed -- not connected", domain, service)
        except Exception:
            log.exception("Failed to call service %s/%s", domain, service)

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    async def _on_state_changed(
        self, entity_id: str, new_state: dict[str, Any]
    ) -> None:
        """Handle a state_changed event from the WebSocket client."""
        self._update_cache(entity_id, new_state)

        cached = self._cache.get(entity_id, {})

        # Notify all subscribers for this entity.
        for cb in self._subscribers.get(entity_id, []):
            try:
                await cb(entity_id, cached)
            except Exception:
                log.exception("Error in subscriber callback for %s", entity_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _update_cache(self, entity_id: str, state_obj: dict[str, Any]) -> None:
        """Flatten an HA state object into the cache.

        Stores ``{"state": ..., <attr>: ..., ...}`` so that both the raw
        state string and all attributes are accessible by key.
        """
        attrs = dict(state_obj.get("attributes", {}))
        attrs["state"] = state_obj.get("state", "unavailable")
        self._cache[entity_id] = attrs

    @staticmethod
    def _parse_key(key: str) -> tuple[str, str]:
        """Split ``entity_id.attribute`` into ``(entity_id, attribute)``."""
        parts = key.split(".")
        if len(parts) <= 2:
            return key, "state"
        entity_id = f"{parts[0]}.{parts[1]}"
        attribute = ".".join(parts[2:])
        return entity_id, attribute
