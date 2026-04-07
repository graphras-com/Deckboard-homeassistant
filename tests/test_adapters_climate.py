"""Tests for deckboard_homeassistant.adapters.climate."""

from __future__ import annotations

import pytest

from deckboard_homeassistant.adapters.climate import ClimateAdapter


class TestClimateNormalize:
    def setup_method(self) -> None:
        self.adapter = ClimateAdapter()
        self.eid = "climate.living_room"

    def test_domain(self) -> None:
        assert self.adapter.domain == "climate"

    def test_heating(self) -> None:
        state = {
            "state": "heat",
            "current_temperature": 21.5,
            "temperature": 23.0,
            "min_temp": 7.0,
            "max_temp": 35.0,
            "fan_mode": "auto",
            "current_humidity": 45.0,
        }
        result = self.adapter.normalize(self.eid, state)
        assert result["is_on"] is True
        assert result["hvac_mode"] == "heat"
        assert result["current_temperature"] == 21.5
        assert result["target_temperature"] == 23.0
        assert result["target_temp_min"] == 7.0
        assert result["target_temp_max"] == 35.0
        assert result["fan_mode"] == "auto"
        assert result["humidity"] == 45.0

    def test_off(self) -> None:
        state = {"state": "off"}
        result = self.adapter.normalize(self.eid, state)
        assert result["is_on"] is False
        assert result["hvac_mode"] == "off"

    def test_unavailable(self) -> None:
        state = {"state": "unavailable"}
        result = self.adapter.normalize(self.eid, state)
        assert result["is_on"] is False

    def test_unknown(self) -> None:
        state = {"state": "unknown"}
        result = self.adapter.normalize(self.eid, state)
        assert result["is_on"] is False

    def test_cool_mode(self) -> None:
        state = {"state": "cool"}
        result = self.adapter.normalize(self.eid, state)
        assert result["is_on"] is True
        assert result["hvac_mode"] == "cool"

    def test_missing_temperatures_default(self) -> None:
        state = {"state": "heat"}
        result = self.adapter.normalize(self.eid, state)
        assert result["current_temperature"] == 0.0
        assert result["target_temperature"] == 0.0
        assert result["target_temp_min"] == 7.0
        assert result["target_temp_max"] == 35.0
        assert result["humidity"] == 0.0

    def test_invalid_temperature_values(self) -> None:
        state = {
            "state": "heat",
            "current_temperature": "invalid",
            "temperature": "bad",
            "min_temp": "oops",
            "max_temp": "nope",
            "current_humidity": "wat",
        }
        result = self.adapter.normalize(self.eid, state)
        assert result["current_temperature"] == 0.0
        assert result["target_temperature"] == 0.0
        assert result["target_temp_min"] == 7.0
        assert result["target_temp_max"] == 35.0
        assert result["humidity"] == 0.0

    def test_no_fan_mode(self) -> None:
        state = {"state": "heat"}
        result = self.adapter.normalize(self.eid, state)
        assert result["fan_mode"] == ""

    def test_default_state_keys(self) -> None:
        assert self.adapter.default_state_keys() == [
            "is_on",
            "hvac_mode",
            "current_temperature",
            "target_temperature",
        ]


class TestClimateResolveAction:
    def setup_method(self) -> None:
        self.adapter = ClimateAdapter()
        self.eid = "climate.living_room"

    def test_toggle_when_on(self) -> None:
        r = self.adapter.resolve_action(self.eid, "toggle", {"is_on": True})
        assert r.service == "turn_off"

    def test_toggle_when_off(self) -> None:
        r = self.adapter.resolve_action(self.eid, "toggle", {"is_on": False})
        assert r.service == "turn_on"

    def test_toggle_default_is_on(self) -> None:
        # Default is_on=True -> turn_off
        r = self.adapter.resolve_action(self.eid, "toggle", {})
        assert r.service == "turn_off"

    def test_turn_on(self) -> None:
        r = self.adapter.resolve_action(self.eid, "turn_on", {})
        assert r.service == "turn_on"
        assert r.domain == "climate"

    def test_turn_off(self) -> None:
        r = self.adapter.resolve_action(self.eid, "turn_off", {})
        assert r.service == "turn_off"

    def test_set_temperature(self) -> None:
        r = self.adapter.resolve_action(
            self.eid, "set_temperature", {"temperature": 25.0}
        )
        assert r.service == "set_temperature"
        assert r.data["temperature"] == 25.0

    def test_set_temperature_default(self) -> None:
        r = self.adapter.resolve_action(self.eid, "set_temperature", {})
        assert r.data["temperature"] == 21.0

    def test_temperature_up(self) -> None:
        r = self.adapter.resolve_action(
            self.eid, "temperature_up", {"step": 1.0, "current_target": 22.0}
        )
        assert r.data["temperature"] == 23.0

    def test_temperature_up_defaults(self) -> None:
        r = self.adapter.resolve_action(self.eid, "temperature_up", {})
        assert r.data["temperature"] == 21.5

    def test_temperature_down(self) -> None:
        r = self.adapter.resolve_action(
            self.eid, "temperature_down", {"step": 1.0, "current_target": 22.0}
        )
        assert r.data["temperature"] == 21.0

    def test_temperature_down_defaults(self) -> None:
        r = self.adapter.resolve_action(self.eid, "temperature_down", {})
        assert r.data["temperature"] == 20.5

    def test_set_hvac_mode(self) -> None:
        r = self.adapter.resolve_action(
            self.eid, "set_hvac_mode", {"hvac_mode": "cool"}
        )
        assert r.service == "set_hvac_mode"
        assert r.data["hvac_mode"] == "cool"

    def test_set_hvac_mode_default(self) -> None:
        r = self.adapter.resolve_action(self.eid, "set_hvac_mode", {})
        assert r.data["hvac_mode"] == "auto"

    def test_set_fan_mode(self) -> None:
        r = self.adapter.resolve_action(self.eid, "set_fan_mode", {"fan_mode": "high"})
        assert r.service == "set_fan_mode"
        assert r.data["fan_mode"] == "high"

    def test_set_fan_mode_default(self) -> None:
        r = self.adapter.resolve_action(self.eid, "set_fan_mode", {})
        assert r.data["fan_mode"] == "auto"

    def test_unknown_action_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown action"):
            self.adapter.resolve_action(self.eid, "defrost", {})
