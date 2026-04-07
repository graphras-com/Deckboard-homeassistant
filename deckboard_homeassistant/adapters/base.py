"""Base class for domain adapters.

An adapter normalizes raw HA entity state into UI-friendly values and
resolves logical action names into concrete HA service calls.

Subclasses implement two responsibilities:
  1. **State normalization** -- convert raw HA attributes into a dict of
     clean, typed values the UI can consume without HA knowledge.
  2. **Action resolution** -- translate a logical action name (e.g.
     ``"toggle"``) into the HA domain/service and service_data needed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ResolvedAction:
    """A fully-resolved HA service call ready to dispatch.

    Attributes:
        domain: HA domain (e.g. ``"light"``).
        service: HA service name (e.g. ``"toggle"``).
        data: Service call data dict (always includes ``entity_id``).
    """

    domain: str
    service: str
    data: dict[str, Any]


class DomainAdapter(ABC):
    """Abstract base for all domain adapters."""

    @property
    @abstractmethod
    def domain(self) -> str:
        """The HA domain this adapter handles (e.g. ``"light"``)."""

    @abstractmethod
    def normalize(self, entity_id: str, state: dict[str, Any]) -> dict[str, Any]:
        """Convert raw HA state dict into normalized UI-friendly values.

        Parameters:
            entity_id: The HA entity identifier.
            state: Raw state dict -- keys are attribute names, ``"state"``
                holds the main state string.

        Returns:
            Flat dict of normalized values. Keys are logical attribute names
            (e.g. ``"is_on"``, ``"brightness_pct"``).
        """

    @abstractmethod
    def resolve_action(
        self, entity_id: str, action_name: str, action_args: dict[str, Any]
    ) -> ResolvedAction:
        """Resolve a logical action into a concrete HA service call.

        Parameters:
            entity_id: Target entity.
            action_name: Logical action (e.g. ``"toggle"``, ``"brightness_up"``).
            action_args: Additional arguments from the UI event.

        Returns:
            A :class:`ResolvedAction` with domain, service, and data.

        Raises:
            ValueError: If the action name is not recognized.
        """

    def default_state_keys(self) -> list[str]:
        """Return the default list of normalized state keys this adapter produces.

        Used by the binding system to auto-wire state subscriptions when no
        explicit ``bind`` is configured.
        """
        return []


class MultiEntityAdapter(DomainAdapter):
    """Base class for adapters that operate on multiple named entity slots.

    Where a regular :class:`DomainAdapter` maps 1:1 to a single HA entity,
    a *multi-entity* adapter receives a named set of entities (slots) and
    can normalize / dispatch actions across all of them.

    Subclasses must implement :meth:`normalize_multi` and
    :meth:`resolve_action_multi`.  The single-entity ``normalize`` /
    ``resolve_action`` methods delegate to these so the adapter can be
    used uniformly by the binding system.

    Slot names are defined by the YAML config, e.g.::

        bindings:
          audio.entertainment:
            adapter: equalizer
            entities:
              bass: number.entertainment_bass
              treble: number.entertainment_treble
    """

    # The binding manager injects slot states here before calling
    # normalize / resolve_action.  Adapters should treat this as
    # read-only context.
    _slot_states: dict[str, dict[str, Any]]
    _entities: dict[str, str]  # slot_name -> entity_id

    def __init__(self) -> None:
        self._slot_states = {}
        self._entities = {}

    # -- Single-entity interface (delegates to multi) -------------------

    def normalize(self, entity_id: str, state: dict[str, Any]) -> dict[str, Any]:
        """Delegate to :meth:`normalize_multi`.

        Called by the binding system's state handler.  By the time this is
        invoked the binding manager has already updated ``_slot_states``
        with the latest raw state for the changed slot.
        """
        # Determine which slot this entity_id belongs to.
        slot = self._slot_for_entity(entity_id)
        return self.normalize_multi(slot, entity_id, state, self._slot_states)

    def resolve_action(
        self, entity_id: str, action_name: str, action_args: dict[str, Any]
    ) -> ResolvedAction:
        """Delegate to :meth:`resolve_action_multi`."""
        return self.resolve_action_multi(self._entities, action_name, action_args)

    # -- Multi-entity interface (implement in subclasses) ---------------

    @abstractmethod
    def normalize_multi(
        self,
        slot: str,
        entity_id: str,
        state: dict[str, Any],
        all_states: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Normalize state when a specific slot changes.

        Parameters:
            slot: The slot name that triggered the update (e.g. ``"bass"``).
            entity_id: The HA entity for that slot.
            state: Raw state dict for the changed entity.
            all_states: ``{slot_name: raw_state}`` for **all** slots.

        Returns:
            Flat dict of normalized values.
        """

    @abstractmethod
    def resolve_action_multi(
        self,
        entities: dict[str, str],
        action_name: str,
        action_args: dict[str, Any],
    ) -> ResolvedAction:
        """Resolve an action with access to all entity slots.

        Parameters:
            entities: ``{slot_name: entity_id}`` mapping.
            action_name: Logical action name.
            action_args: Extra arguments from the UI event.

        Returns:
            A :class:`ResolvedAction` targeting the appropriate entity.
        """

    # -- Helpers --------------------------------------------------------

    def _slot_for_entity(self, entity_id: str) -> str:
        """Return the slot name for *entity_id*, or ``"unknown"``."""
        for slot, eid in self._entities.items():
            if eid == entity_id:
                return slot
        return "unknown"
