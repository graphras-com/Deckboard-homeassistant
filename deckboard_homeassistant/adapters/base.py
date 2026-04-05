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
