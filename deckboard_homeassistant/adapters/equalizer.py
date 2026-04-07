"""Equalizer domain adapter (multi-entity).

Combines multiple HA ``number.*`` entities (e.g. bass, treble, sub-gain,
balance) into a single adapter that exposes each slot as a normalized
attribute and can dispatch ``set_<slot>`` / ``<slot>_up`` / ``<slot>_down``
actions to the correct entity.

Normalized keys (per slot):
    <slot>           float   Current value of that slot's entity.
    <slot>_min       float   Minimum value (from HA ``min`` attribute).
    <slot>_max       float   Maximum value (from HA ``max`` attribute).

Supported actions:
    set_<slot>       Set a slot to a specific value (``value`` arg).
    <slot>_up        Increase a slot by ``step`` (default 1).
    <slot>_down      Decrease a slot by ``step`` (default 1).

Example config::

    bindings:
      audio.entertainment:
        adapter: equalizer
        entities:
          sub:      number.entertainment_sub_gain
          treble:   number.entertainment_treble
          bass:     number.entertainment_bass
          balance:  number.entertainment_balance
"""

from __future__ import annotations

from typing import Any

from deckboard_homeassistant.adapters.base import MultiEntityAdapter, ResolvedAction


def _parse_number(raw: Any, default: float = 0.0) -> float:
    """Safely parse a numeric value from HA state."""
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


class EqualizerAdapter(MultiEntityAdapter):
    """Multi-entity adapter for ``number.*`` equalizer controls."""

    @property
    def domain(self) -> str:
        return "equalizer"

    def normalize_multi(
        self,
        slot: str,
        entity_id: str,
        state: dict[str, Any],
        all_states: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Return value, min, and max for every slot."""
        result: dict[str, Any] = {}
        for s, s_state in all_states.items():
            result[s] = _parse_number(s_state.get("state"))
            result[f"{s}_min"] = _parse_number(s_state.get("min"), 0.0)
            result[f"{s}_max"] = _parse_number(s_state.get("max"), 100.0)
        return result

    def resolve_action_multi(
        self,
        entities: dict[str, str],
        action_name: str,
        action_args: dict[str, Any],
    ) -> ResolvedAction:
        # Supported patterns:
        #   set_<slot>   -- set absolute value
        #   <slot>_up    -- increment by step
        #   <slot>_down  -- decrement by step

        for slot, entity_id in entities.items():
            if action_name == f"set_{slot}":
                value = float(action_args.get("value", 0))
                return ResolvedAction(
                    "number",
                    "set_value",
                    {"entity_id": entity_id, "value": value},
                )

            if action_name == f"{slot}_up":
                step = float(action_args.get("step", 1))
                current = _parse_number(action_args.get(f"current_{slot}"))
                target = current + step
                return ResolvedAction(
                    "number",
                    "set_value",
                    {"entity_id": entity_id, "value": target},
                )

            if action_name == f"{slot}_down":
                step = float(action_args.get("step", 1))
                current = _parse_number(action_args.get(f"current_{slot}"))
                target = current - step
                return ResolvedAction(
                    "number",
                    "set_value",
                    {"entity_id": entity_id, "value": target},
                )

        raise ValueError(f"EqualizerAdapter: unknown action {action_name!r}")

    def default_state_keys(self) -> list[str]:
        # Slot names are dynamic; return empty -- the binding system
        # discovers keys from normalize_multi output.
        return []
