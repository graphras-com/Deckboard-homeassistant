"""Climate domain adapter.

Normalizes HA climate entity state into clean values and resolves climate
actions into HA service calls.

Normalized keys:
    is_on               bool    Whether the climate device is not ``"off"``.
    hvac_mode           str     Current HVAC mode (heat, cool, auto, off, etc.).
    current_temperature float   Current measured temperature.
    target_temperature  float   Target temperature setpoint.
    fan_mode            str     Current fan mode (auto, low, medium, high, etc.).
    humidity            float   Current humidity (if available).

Supported actions:
    set_temperature     Set target temperature.
    temperature_up      Increase target temperature by ``step`` (default 0.5).
    temperature_down    Decrease target temperature by ``step`` (default 0.5).
    set_hvac_mode       Set HVAC mode (heat, cool, auto, off, etc.).
    set_fan_mode        Set fan mode.
    toggle              Toggle the climate device on/off.
    turn_on             Turn on.
    turn_off            Turn off.
"""

from __future__ import annotations

from typing import Any

from deckboard_homeassistant.adapters.base import DomainAdapter, ResolvedAction


class ClimateAdapter(DomainAdapter):
    """Adapter for ``climate.*`` entities."""

    @property
    def domain(self) -> str:
        return "climate"

    def normalize(self, entity_id: str, state: dict[str, Any]) -> dict[str, Any]:
        raw_state = state.get("state", "unavailable")
        is_on = raw_state not in ("off", "unavailable", "unknown")

        current_temp = state.get("current_temperature")
        try:
            current_temp = float(current_temp) if current_temp is not None else 0.0
        except (TypeError, ValueError):
            current_temp = 0.0

        target_temp = state.get("temperature")
        try:
            target_temp = float(target_temp) if target_temp is not None else 0.0
        except (TypeError, ValueError):
            target_temp = 0.0

        humidity = state.get("current_humidity")
        try:
            humidity = float(humidity) if humidity is not None else 0.0
        except (TypeError, ValueError):
            humidity = 0.0

        return {
            "is_on": is_on,
            "hvac_mode": raw_state,
            "current_temperature": current_temp,
            "target_temperature": target_temp,
            "fan_mode": state.get("fan_mode", ""),
            "humidity": humidity,
        }

    def resolve_action(
        self, entity_id: str, action_name: str, action_args: dict[str, Any]
    ) -> ResolvedAction:
        domain = "climate"
        data: dict[str, Any] = {"entity_id": entity_id}

        match action_name:
            case "toggle":
                # HA doesn't have climate.toggle natively; use turn_on/turn_off
                # based on current state. Caller should supply ``is_on``.
                if action_args.get("is_on", True):
                    return ResolvedAction(domain, "turn_off", data)
                return ResolvedAction(domain, "turn_on", data)
            case "turn_on":
                return ResolvedAction(domain, "turn_on", data)
            case "turn_off":
                return ResolvedAction(domain, "turn_off", data)
            case "set_temperature":
                temp = float(action_args.get("temperature", 21.0))
                data["temperature"] = temp
                return ResolvedAction(domain, "set_temperature", data)
            case "temperature_up":
                step = float(action_args.get("step", 0.5))
                current = float(action_args.get("current_target", 21.0))
                data["temperature"] = current + step
                return ResolvedAction(domain, "set_temperature", data)
            case "temperature_down":
                step = float(action_args.get("step", 0.5))
                current = float(action_args.get("current_target", 21.0))
                data["temperature"] = current - step
                return ResolvedAction(domain, "set_temperature", data)
            case "set_hvac_mode":
                data["hvac_mode"] = action_args.get("hvac_mode", "auto")
                return ResolvedAction(domain, "set_hvac_mode", data)
            case "set_fan_mode":
                data["fan_mode"] = action_args.get("fan_mode", "auto")
                return ResolvedAction(domain, "set_fan_mode", data)
            case _:
                raise ValueError(f"ClimateAdapter: unknown action {action_name!r}")

    def default_state_keys(self) -> list[str]:
        return ["is_on", "hvac_mode", "current_temperature", "target_temperature"]
