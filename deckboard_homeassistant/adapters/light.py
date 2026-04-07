"""Light domain adapter.

Normalizes HA light entity state into clean values and resolves light
actions into HA service calls.

Normalized keys:
    is_on              bool     Whether the light is on.
    brightness_pct     int      Brightness as 0-100 percentage (HA uses 0-255).
    kelvin             int      Color temperature in Kelvin.
    kelvin_min         int      Minimum supported Kelvin (from HA).
    kelvin_max         int      Maximum supported Kelvin (from HA).
    color_name         str      Friendly name of the current color mode.

Supported actions:
    toggle           Toggle the light on/off.
    turn_on          Turn the light on.
    turn_off         Turn the light off.
    set_brightness   Set brightness to a specific percentage.
    brightness_up    Increase brightness by ``step`` (default 10).
    brightness_down  Decrease brightness by ``step`` (default 10).
    set_kelvin       Set color temperature to a specific Kelvin value.
"""

from __future__ import annotations

from typing import Any

from deckboard_homeassistant.adapters.base import DomainAdapter, ResolvedAction


def _brightness_ha_to_pct(value: Any) -> int:
    """Convert HA brightness (0-255) to percentage (0-100)."""
    if value is None:
        return 0
    return round(int(value) / 255 * 100)


def _brightness_pct_to_ha(pct: int) -> int:
    """Convert percentage (0-100) to HA brightness (0-255)."""
    return round(max(0, min(100, pct)) / 100 * 255)


class LightAdapter(DomainAdapter):
    """Adapter for ``light.*`` entities."""

    @property
    def domain(self) -> str:
        return "light"

    def normalize(self, entity_id: str, state: dict[str, Any]) -> dict[str, Any]:
        is_on = state.get("state") == "on"
        brightness_pct = _brightness_ha_to_pct(state.get("brightness"))
        kelvin = state.get("color_temp_kelvin") or state.get("color_temp", 4000)
        color_mode = state.get("color_mode", "unknown")

        # Ensure kelvin is an int.
        try:
            kelvin = int(kelvin)
        except (TypeError, ValueError):
            kelvin = 4000

        # Kelvin range from HA attributes.
        kelvin_min = state.get("min_color_temp_kelvin")
        kelvin_max = state.get("max_color_temp_kelvin")
        try:
            kelvin_min = int(kelvin_min) if kelvin_min is not None else 2000
        except (TypeError, ValueError):
            kelvin_min = 2000
        try:
            kelvin_max = int(kelvin_max) if kelvin_max is not None else 6500
        except (TypeError, ValueError):
            kelvin_max = 6500

        return {
            "is_on": is_on,
            "brightness_pct": brightness_pct if is_on else 0,
            "kelvin": kelvin,
            "kelvin_min": kelvin_min,
            "kelvin_max": kelvin_max,
            "color_name": color_mode,
        }

    def resolve_action(
        self, entity_id: str, action_name: str, action_args: dict[str, Any]
    ) -> ResolvedAction:
        match action_name:
            case "toggle":
                return ResolvedAction("light", "toggle", {"entity_id": entity_id})

            case "turn_on":
                return ResolvedAction("light", "turn_on", {"entity_id": entity_id})

            case "turn_off":
                return ResolvedAction("light", "turn_off", {"entity_id": entity_id})

            case "set_brightness":
                pct = int(action_args.get("brightness", 100))
                return ResolvedAction(
                    "light",
                    "turn_on",
                    {
                        "entity_id": entity_id,
                        "brightness": _brightness_pct_to_ha(pct),
                    },
                )

            case "brightness_up":
                step = int(action_args.get("step", 10))
                current = int(action_args.get("current_brightness", 50))
                target = min(100, current + step)
                return ResolvedAction(
                    "light",
                    "turn_on",
                    {
                        "entity_id": entity_id,
                        "brightness": _brightness_pct_to_ha(target),
                    },
                )

            case "brightness_down":
                step = int(action_args.get("step", 10))
                current = int(action_args.get("current_brightness", 50))
                target = max(0, current - step)
                if target == 0:
                    return ResolvedAction("light", "turn_off", {"entity_id": entity_id})
                return ResolvedAction(
                    "light",
                    "turn_on",
                    {
                        "entity_id": entity_id,
                        "brightness": _brightness_pct_to_ha(target),
                    },
                )

            case "set_kelvin":
                kelvin = int(action_args.get("kelvin", 4000))
                return ResolvedAction(
                    "light",
                    "turn_on",
                    {
                        "entity_id": entity_id,
                        "color_temp_kelvin": kelvin,
                    },
                )

            case _:
                raise ValueError(f"LightAdapter: unknown action {action_name!r}")

    def default_state_keys(self) -> list[str]:
        return ["is_on", "brightness_pct", "kelvin"]
