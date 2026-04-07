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
from deckboard_homeassistant.adapters.base import DomainAdapter, MultiEntityAdapter
from deckboard_homeassistant.interfaces import Action, CommandBus, StateProvider

log = logging.getLogger(__name__)

# Callback: async (normalized_key, value) -> None
NormalizedCallback = Callable[[str, Any], Coroutine[Any, Any, None]]


@dataclass
class Binding:
    """A resolved binding between a logical name and one or more HA entities.

    Attributes:
        key: Logical name (e.g. ``"lights.kitchen"``).
        entity_id: Primary HA entity identifier (single-entity adapters).
        adapter: Domain adapter instance.
        entities: Named entity slots for multi-entity adapters.
            Empty for single-entity bindings.
    """

    key: str
    entity_id: str
    adapter: DomainAdapter
    entities: dict[str, str] = field(default_factory=dict)

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

    async def notify(self, attr: str, value: Any) -> None:
        """Push a normalized value to all subscribers of *attr*."""
        for cb in self._subscribers.get(attr, []):
            try:
                await cb(attr, value)
            except Exception:
                log.exception("Error in subscriber callback for %s.%s", self.key, attr)


class BindingManager:
    """Creates and manages bindings, wiring state and actions.

    Parameters:
        state_provider: For subscribing to raw HA state changes.
        command_bus: For executing resolved actions.
    """

    def __init__(
        self,
        state_provider: StateProvider,
        command_bus: CommandBus,
    ) -> None:
        self._state_provider = state_provider
        self._command_bus = command_bus
        self._bindings: dict[str, Binding] = {}

    def register(
        self,
        key: str,
        entity_id: str,
        adapter_name: str,
        entities: dict[str, str] | None = None,
    ) -> Binding:
        """Create and register a binding.

        Parameters:
            key: Logical binding name (e.g. ``"lights.kitchen"``).
            entity_id: HA entity ID (e.g. ``"light.kitchen"``).
                May be empty for multi-entity bindings.
            adapter_name: Adapter domain name (e.g. ``"light"``).
            entities: Optional ``{slot_name: entity_id}`` mapping for
                multi-entity adapters.

        Returns:
            The created :class:`Binding`.
        """
        adapter = get_adapter(adapter_name)
        entities = entities or {}
        binding = Binding(
            key=key,
            entity_id=entity_id,
            adapter=adapter,
            entities=entities,
        )
        self._bindings[key] = binding

        if isinstance(adapter, MultiEntityAdapter) and entities:
            # Multi-entity: wire adapter context and subscribe to each slot.
            adapter._entities = entities
            for slot, eid in entities.items():
                self._state_provider.subscribe(
                    eid, self._make_multi_state_handler(binding, slot)
                )
            log.info(
                "Registered multi-entity binding %s -> %s [%s]",
                key,
                entities,
                adapter_name,
            )
        else:
            # Single-entity: subscribe to the one entity.
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

        if isinstance(binding.adapter, MultiEntityAdapter) and binding.entities:
            # Multi-entity: enrich with all slot states.
            try:
                for slot, eid in binding.entities.items():
                    raw = self._get_entity_state(eid)
                    args.setdefault(f"current_{slot}", raw.get("state"))
            except Exception:
                log.debug(
                    "Could not enrich multi-entity action args",
                    exc_info=True,
                )

            resolved = binding.adapter.resolve_action_multi(
                binding.entities,
                action_name,
                args,
            )
        else:
            # Single-entity: existing behavior.
            try:
                raw_state = self._get_entity_state(binding.entity_id)
                normalized = binding.adapter.normalize(binding.entity_id, raw_state)
                args.setdefault(
                    "current_brightness", normalized.get("brightness_pct", 50)
                )
                args.setdefault("current_volume", normalized.get("volume_pct", 50))
                args.setdefault("is_muted", normalized.get("is_muted", False))
            except Exception:
                log.debug(
                    "Could not enrich action args with current state", exc_info=True
                )

            resolved = binding.adapter.resolve_action(
                binding.entity_id, action_name, args
            )

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

        if isinstance(binding.adapter, MultiEntityAdapter) and binding.entities:
            # Multi-entity: refresh each slot and rebuild full state.
            for slot, eid in binding.entities.items():
                raw_state = self._get_entity_state(eid)
                binding.adapter._slot_states[slot] = raw_state
            # Now normalize with all states present -- use first slot
            # to trigger a full normalized push.
            for slot, eid in binding.entities.items():
                raw_state = binding.adapter._slot_states[slot]
                normalized = binding.adapter.normalize_multi(
                    slot,
                    eid,
                    raw_state,
                    binding.adapter._slot_states,
                )
                for attr, value in normalized.items():
                    await binding.notify(attr, value)
                break  # One normalize_multi call produces all keys.
        else:
            raw_state = self._get_entity_state(binding.entity_id)
            normalized = binding.adapter.normalize(binding.entity_id, raw_state)
            for attr, value in normalized.items():
                await binding.notify(attr, value)

    async def refresh_all(self) -> None:
        """Refresh all registered bindings."""
        for key in self._bindings:
            await self.refresh_binding(key)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_entity_state(self, entity_id: str) -> dict[str, Any]:
        """Get the full cached state dict for an entity via the bridge.

        The bridge exposes ``get_entity_state()`` which returns the full
        flattened attribute dict from its cache. This avoids the need
        for async fetches during action resolution.
        """
        if hasattr(self._state_provider, "get_entity_state"):
            return self._state_provider.get_entity_state(entity_id)  # type: ignore[attr-defined]
        # Fallback for mock providers without get_entity_state.
        return {}

    def _make_state_handler(
        self, binding: Binding
    ) -> Callable[[str, Any], Coroutine[Any, Any, None]]:
        """Create a raw state change callback that normalizes and dispatches.

        The bridge calls this with ``(entity_id, full_state_dict)`` when
        an entity's state changes.
        """

        async def _on_raw_state_change(entity_id: str, raw_state: Any) -> None:
            if not isinstance(raw_state, dict):
                raw_state = {"state": raw_state}
            normalized = binding.adapter.normalize(binding.entity_id, raw_state)

            for attr, value in normalized.items():
                await binding.notify(attr, value)

        return _on_raw_state_change

    def _make_multi_state_handler(
        self, binding: Binding, slot: str
    ) -> Callable[[str, Any], Coroutine[Any, Any, None]]:
        """Create a state handler for one slot of a multi-entity binding.

        When any slot's entity changes, we update the adapter's cached
        slot states and re-normalize.
        """
        adapter = binding.adapter
        assert isinstance(adapter, MultiEntityAdapter)

        async def _on_slot_state_change(entity_id: str, raw_state: Any) -> None:
            if not isinstance(raw_state, dict):
                raw_state = {"state": raw_state}

            # Update the adapter's view of all slot states.
            adapter._slot_states[slot] = raw_state

            # Normalize and push.
            normalized = adapter.normalize_multi(
                slot,
                entity_id,
                raw_state,
                adapter._slot_states,
            )
            for attr, value in normalized.items():
                await binding.notify(attr, value)

        return _on_slot_state_change
