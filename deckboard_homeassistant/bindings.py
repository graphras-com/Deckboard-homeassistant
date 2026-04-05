"""Binding system -- maps logical keys to HA entities and wires events.

A *binding* connects a logical name (e.g. ``lights.kitchen``) to a
concrete HA entity through a domain adapter.  It provides:

  * **State subscriptions** -- normalized attribute values pushed to callbacks.
  * **Action dispatch** -- logical action names resolved via the adapter and
    executed through the bridge.

The binding layer is the glue between configuration-declared intent and the
runtime behavior of the system.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from deckboard_homeassistant.adapters import get_adapter
from deckboard_homeassistant.adapters.base import DomainAdapter
from deckboard_homeassistant.interfaces import Action, CommandBus, StateProvider

log = logging.getLogger(__name__)

# Callback: async (normalized_key, value) -> None
NormalizedCallback = Callable[[str, Any], Coroutine[Any, Any, None]]


@dataclass
class Binding:
    """A resolved binding between a logical name and an HA entity.

    Attributes:
        key: Logical name (e.g. ``"lights.kitchen"``).
        entity_id: HA entity identifier (e.g. ``"light.kitchen"``).
        adapter: Domain adapter instance.
    """

    key: str
    entity_id: str
    adapter: DomainAdapter

    # Subscribers for normalized state: { normalized_attr -> [callback] }
    _subscribers: dict[str, list[NormalizedCallback]] = field(
        default_factory=dict, repr=False
    )

    def subscribe(self, attr: str, callback: NormalizedCallback) -> None:
        """Subscribe to normalized attribute *attr* on this binding."""
        self._subscribers.setdefault(attr, []).append(callback)

    def unsubscribe(self, attr: str, callback: NormalizedCallback) -> None:
        """Remove a callback for *attr*."""
        cbs = self._subscribers.get(attr, [])
        try:
            cbs.remove(callback)
        except ValueError:
            pass

    def notify(self, attr: str, value: Any, loop: asyncio.AbstractEventLoop) -> None:
        """Push a normalized value to all subscribers of *attr*."""
        for cb in self._subscribers.get(attr, []):
            asyncio.run_coroutine_threadsafe(cb(attr, value), loop)


class BindingManager:
    """Creates and manages bindings, wiring state and actions.

    Parameters:
        state_provider: For subscribing to raw HA state changes.
        command_bus: For executing resolved actions.
        loop: Event loop for scheduling callbacks.
    """

    def __init__(
        self,
        state_provider: StateProvider,
        command_bus: CommandBus,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._state_provider = state_provider
        self._command_bus = command_bus
        self._loop = loop
        self._bindings: dict[str, Binding] = {}

    def register(
        self,
        key: str,
        entity_id: str,
        adapter_name: str,
    ) -> Binding:
        """Create and register a binding.

        Parameters:
            key: Logical binding name (e.g. ``"lights.kitchen"``).
            entity_id: HA entity ID (e.g. ``"light.kitchen"``).
            adapter_name: Adapter domain name (e.g. ``"light"``).

        Returns:
            The created :class:`Binding`.
        """
        adapter = get_adapter(adapter_name)
        binding = Binding(key=key, entity_id=entity_id, adapter=adapter)
        self._bindings[key] = binding

        # Subscribe to raw state changes on the entity.
        self._state_provider.subscribe(entity_id, self._make_state_handler(binding))

        log.info("Registered binding %s -> %s [%s]", key, entity_id, adapter_name)
        return binding

    def get(self, key: str) -> Binding | None:
        """Look up a binding by its logical key."""
        return self._bindings.get(key)

    async def execute_action(
        self,
        binding_key: str,
        action_name: str,
        extra_args: dict[str, Any] | None = None,
    ) -> None:
        """Resolve and execute an action on a binding.

        The adapter translates the logical action name into a concrete HA
        service call, which is then dispatched through the command bus.
        """
        binding = self._bindings.get(binding_key)
        if binding is None:
            log.error("No binding found for key %r", binding_key)
            return

        args = dict(extra_args or {})

        # Enrich with current normalized state so adapters can compute
        # relative changes (e.g. brightness_up needs current brightness).
        try:
            raw_state = await self._get_raw_state(binding.entity_id)
            normalized = binding.adapter.normalize(binding.entity_id, raw_state)
            args.setdefault("current_brightness", normalized.get("brightness_pct", 50))
            args.setdefault("current_volume", normalized.get("volume_pct", 50))
            args.setdefault("is_muted", normalized.get("is_muted", False))
        except Exception:
            log.debug("Could not enrich action args with current state", exc_info=True)

        resolved = binding.adapter.resolve_action(binding.entity_id, action_name, args)

        # Execute through the bridge (CommandBus).
        action = Action(
            name=resolved.service,
            args={
                "entity_id": resolved.data.get("entity_id", binding.entity_id),
                "domain": resolved.domain,
                **{k: v for k, v in resolved.data.items() if k != "entity_id"},
            },
        )
        await self._command_bus.execute(binding_key, action)

    async def refresh_binding(self, key: str) -> None:
        """Force-fetch current state for a binding and push to subscribers."""
        binding = self._bindings.get(key)
        if binding is None:
            return
        raw_state = await self._get_raw_state(binding.entity_id)
        normalized = binding.adapter.normalize(binding.entity_id, raw_state)
        for attr, value in normalized.items():
            binding.notify(attr, value, self._loop)

    async def refresh_all(self) -> None:
        """Refresh all registered bindings."""
        for key in self._bindings:
            await self.refresh_binding(key)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _get_raw_state(self, entity_id: str) -> dict[str, Any]:
        """Fetch full raw state dict from the state provider."""
        # We need the full attribute dict. The bridge caches it keyed by
        # entity_id; fetching "entity_id" returns the "state" attribute,
        # but we need everything. We'll fetch attributes individually.
        #
        # The bridge stores the full cache internally. For now, we fetch
        # the main state and construct what we can.
        state_val = await self._state_provider.get_value(entity_id)
        # The bridge actually caches a full dict keyed by entity_id.
        # get_value with just entity_id returns the "state" string.
        # We need a way to get the full dict. We'll access the bridge
        # cache directly if available (it implements StateProvider).
        from deckboard_homeassistant.bridge import HomeAssistantBridge

        if isinstance(self._state_provider, HomeAssistantBridge):
            cached = self._state_provider._cache.get(entity_id, {})
            if cached:
                return dict(cached)

        # Fallback: return minimal state.
        return {"state": state_val}

    def _make_state_handler(
        self, binding: Binding
    ) -> Callable[[str, Any], Coroutine[Any, Any, None]]:
        """Create a raw state change callback that normalizes and dispatches."""

        async def _on_raw_state_change(key: str, new_value: Any) -> None:
            # Fetch full state for normalization.
            raw_state = await self._get_raw_state(binding.entity_id)
            normalized = binding.adapter.normalize(binding.entity_id, raw_state)

            for attr, value in normalized.items():
                binding.notify(attr, value, self._loop)

        return _on_raw_state_change
