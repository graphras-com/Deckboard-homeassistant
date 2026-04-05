"""Home Assistant bridge -- the sole HA integration point.

This module is the ONLY place that imports ``hassapi`` or calls Home Assistant
APIs.  Every other module communicates through :class:`StateProvider` and
:class:`CommandBus` interfaces.

The bridge:
  * Maintains an in-memory state cache.
  * Uses ``listen_state`` for real-time subscriptions.
  * Exposes ``call_service`` for outbound commands.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from deckboard_homeassistant.interfaces import (
    Action,
    CommandBus,
    StateCallback,
    StateProvider,
)

log = logging.getLogger(__name__)


class HomeAssistantBridge(StateProvider, CommandBus):
    """Wraps an AppDaemon ``hass.Hass`` instance.

    Parameters:
        hass: The AppDaemon Hass app instance.
        loop: The asyncio event loop for scheduling async callbacks.
    """

    def __init__(self, hass: Any, loop: asyncio.AbstractEventLoop) -> None:
        self._hass = hass
        self._loop = loop

        # entity_id -> {attribute -> value}
        self._cache: dict[str, dict[str, Any]] = {}

        # "entity_id.attribute" -> list[StateCallback]
        self._subscribers: dict[str, list[StateCallback]] = {}

        # entity_id -> listen_state handle (so we register at most once per entity)
        self._listeners: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # StateProvider
    # ------------------------------------------------------------------

    async def get_value(self, key: str) -> Any:
        """Return current value for a logical state key.

        Keys are ``entity_id`` (returns main state) or
        ``entity_id.attribute`` (returns that attribute).
        """
        entity_id, attribute = self._parse_key(key)

        # Populate cache on first access.
        if entity_id not in self._cache:
            await self._fetch_entity(entity_id)

        cached = self._cache.get(entity_id, {})
        return cached.get(attribute)

    def subscribe(self, key: str, callback: StateCallback) -> None:
        entity_id, _attribute = self._parse_key(key)
        self._subscribers.setdefault(key, []).append(callback)
        self._ensure_listener(entity_id)

    def unsubscribe(self, key: str, callback: StateCallback) -> None:
        cbs = self._subscribers.get(key, [])
        try:
            cbs.remove(callback)
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # CommandBus
    # ------------------------------------------------------------------

    async def execute(self, binding_key: str, action: Action) -> None:
        """Execute *action* using the entity associated with *binding_key*.

        The binding system resolves the binding_key to an entity_id and domain
        before calling this method.  The action name is mapped to an HA service.
        """
        # The controller attaches entity metadata to the action args before
        # dispatching.  See ``controller.py`` for the wiring.
        entity_id: str | None = action.args.get("entity_id")
        domain: str | None = action.args.get("domain")

        if not entity_id or not domain:
            log.error("Action %s missing entity_id or domain", action.name)
            return

        service = action.name
        service_data: dict[str, Any] = {
            k: v for k, v in action.args.items() if k not in ("entity_id", "domain")
        }
        service_data["entity_id"] = entity_id

        log.info(
            "Calling %s/%s with %s",
            domain,
            service,
            service_data,
        )
        await self._call_service(domain, service, service_data)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_key(key: str) -> tuple[str, str]:
        """Split ``entity_id.attribute`` into parts.

        If no attribute is specified, defaults to ``"state"``.
        """
        # Entity IDs already contain one dot (e.g. light.kitchen).
        # An attribute key looks like light.kitchen.brightness -- three parts.
        parts = key.split(".")
        if len(parts) <= 2:
            return key, "state"
        entity_id = f"{parts[0]}.{parts[1]}"
        attribute = ".".join(parts[2:])
        return entity_id, attribute

    async def _fetch_entity(self, entity_id: str) -> None:
        """Pull full state for *entity_id* into the cache."""
        try:
            state = self._hass.get_state(entity_id, attribute="all")
            if state is None:
                log.warning("Entity %s not found in HA", entity_id)
                return
            attrs = dict(state.get("attributes", {}))
            attrs["state"] = state.get("state")
            self._cache[entity_id] = attrs
        except Exception:
            log.exception("Failed to fetch state for %s", entity_id)

    def _ensure_listener(self, entity_id: str) -> None:
        """Register a ``listen_state`` callback for *entity_id* if not already listening."""
        if entity_id in self._listeners:
            return

        def _on_state_change(
            _entity: str, attribute: str, old: Any, new: Any, kwargs: Any
        ) -> None:
            self._handle_state_change(entity_id, attribute, new)

        handle = self._hass.listen_state(
            _on_state_change,
            entity_id,
            attribute="all",
        )
        self._listeners[entity_id] = handle
        log.debug("Registered listener for %s", entity_id)

    def _handle_state_change(
        self, entity_id: str, attribute: str, new_state: Any
    ) -> None:
        """Process an incoming state change from AppDaemon.

        Updates the cache, then fires matching subscriber callbacks.
        ``listen_state`` with ``attribute='all'`` delivers the full state dict
        on every change.
        """
        if isinstance(new_state, dict):
            # Full state dict from attribute="all".
            attrs = dict(new_state.get("attributes", {}))
            attrs["state"] = new_state.get("state")
            self._cache[entity_id] = attrs
        else:
            # Single attribute change.
            self._cache.setdefault(entity_id, {})["state"] = new_state

        cached = self._cache.get(entity_id, {})

        # Notify subscribers whose key matches this entity.
        for sub_key, callbacks in self._subscribers.items():
            sub_entity, sub_attr = self._parse_key(sub_key)
            if sub_entity != entity_id:
                continue
            value = cached.get(sub_attr)
            for cb in callbacks:
                asyncio.run_coroutine_threadsafe(cb(sub_key, value), self._loop)

    async def _call_service(
        self, domain: str, service: str, data: dict[str, Any]
    ) -> None:
        """Call an HA service through AppDaemon."""
        try:
            self._hass.call_service(f"{domain}/{service}", **data)
        except Exception:
            log.exception("Failed to call service %s/%s", domain, service)
