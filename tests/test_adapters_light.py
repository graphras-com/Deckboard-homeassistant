"""Tests for deckboard_homeassistant.adapters.light."""

from __future__ import annotations

import pytest

from deckboard_homeassistant.adapters.light import (
    LightAdapter,
    _brightness_ha_to_pct,
    _brightness_pct_to_ha,
)


class TestBrightnessHaToPct:
    def test_zero(self) -> None:
        assert _brightness_ha_to_pct(0) == 0

    def test_max(self) -> None:
        assert _brightness_ha_to_pct(255) == 100

    def test_mid(self) -> None:
        assert _brightness_ha_to_pct(128) == 50

    def test_none_returns_zero(self) -> None:
        assert _brightness_ha_to_pct(None) == 0

    def test_string_number(self) -> None:
        assert _brightness_ha_to_pct("200") == 78


class TestBrightnessPctToHa:
    def test_zero(self) -> None:
        assert _brightness_pct_to_ha(0) == 0

    def test_max(self) -> None:
        assert _brightness_pct_to_ha(100) == 255

    def test_mid(self) -> None:
        assert _brightness_pct_to_ha(50) == 128

    def test_clamp_below(self) -> None:
        assert _brightness_pct_to_ha(-10) == 0

    def test_clamp_above(self) -> None:
        assert _brightness_pct_to_ha(150) == 255


class TestLightAdapterNormalize:
    def setup_method(self) -> None:
        self.adapter = LightAdapter()

    def test_domain(self) -> None:
        assert self.adapter.domain == "light"

    def test_light_on(self) -> None:
        state = {
            "state": "on",
            "brightness": 200,
            "color_temp_kelvin": 3500,
            "color_mode": "color_temp",
            "min_color_temp_kelvin": 2000,
            "max_color_temp_kelvin": 6500,
        }
        result = self.adapter.normalize("light.kitchen", state)
        assert result["is_on"] is True
        assert result["brightness_pct"] == 78
        assert result["kelvin"] == 3500
        assert result["kelvin_min"] == 2000
        assert result["kelvin_max"] == 6500
        assert result["color_name"] == "color_temp"

    def test_light_off(self) -> None:
        state = {"state": "off", "brightness": 100}
        result = self.adapter.normalize("light.kitchen", state)
        assert result["is_on"] is False
        assert result["brightness_pct"] == 0  # Off -> brightness is 0

    def test_no_brightness(self) -> None:
        state = {"state": "on"}
        result = self.adapter.normalize("light.kitchen", state)
        assert result["brightness_pct"] == 0  # None brightness -> 0

    def test_kelvin_fallback_to_color_temp(self) -> None:
        state = {"state": "on", "color_temp": 4500}
        result = self.adapter.normalize("light.kitchen", state)
        assert result["kelvin"] == 4500

    def test_kelvin_fallback_to_default(self) -> None:
        state = {"state": "on"}
        result = self.adapter.normalize("light.kitchen", state)
        assert result["kelvin"] == 4000

    def test_kelvin_invalid_type(self) -> None:
        state = {"state": "on", "color_temp_kelvin": "invalid"}
        result = self.adapter.normalize("light.kitchen", state)
        assert result["kelvin"] == 4000

    def test_kelvin_min_max_invalid(self) -> None:
        state = {
            "state": "on",
            "min_color_temp_kelvin": "bad",
            "max_color_temp_kelvin": "bad",
        }
        result = self.adapter.normalize("light.kitchen", state)
        assert result["kelvin_min"] == 2000
        assert result["kelvin_max"] == 6500

    def test_kelvin_min_max_none_defaults(self) -> None:
        state = {"state": "on"}
        result = self.adapter.normalize("light.kitchen", state)
        assert result["kelvin_min"] == 2000
        assert result["kelvin_max"] == 6500

    def test_default_state_keys(self) -> None:
        assert self.adapter.default_state_keys() == [
            "is_on",
            "brightness_pct",
            "kelvin",
        ]


class TestLightAdapterResolveAction:
    def setup_method(self) -> None:
        self.adapter = LightAdapter()
        self.eid = "light.kitchen"

    def test_toggle(self) -> None:
        r = self.adapter.resolve_action(self.eid, "toggle", {})
        assert r.domain == "light"
        assert r.service == "toggle"
        assert r.data["entity_id"] == self.eid

    def test_turn_on(self) -> None:
        r = self.adapter.resolve_action(self.eid, "turn_on", {})
        assert r.service == "turn_on"

    def test_turn_off(self) -> None:
        r = self.adapter.resolve_action(self.eid, "turn_off", {})
        assert r.service == "turn_off"

    def test_set_brightness(self) -> None:
        r = self.adapter.resolve_action(self.eid, "set_brightness", {"brightness": 75})
        assert r.service == "turn_on"
        assert r.data["brightness"] == _brightness_pct_to_ha(75)

    def test_set_brightness_default(self) -> None:
        r = self.adapter.resolve_action(self.eid, "set_brightness", {})
        assert r.data["brightness"] == _brightness_pct_to_ha(100)

    def test_brightness_up(self) -> None:
        r = self.adapter.resolve_action(
            self.eid, "brightness_up", {"step": 20, "current_brightness": 60}
        )
        assert r.service == "turn_on"
        assert r.data["brightness"] == _brightness_pct_to_ha(80)

    def test_brightness_up_clamped(self) -> None:
        r = self.adapter.resolve_action(
            self.eid, "brightness_up", {"step": 20, "current_brightness": 90}
        )
        assert r.data["brightness"] == _brightness_pct_to_ha(100)

    def test_brightness_up_defaults(self) -> None:
        r = self.adapter.resolve_action(self.eid, "brightness_up", {})
        # defaults: step=10, current=50 -> target=60
        assert r.data["brightness"] == _brightness_pct_to_ha(60)

    def test_brightness_down(self) -> None:
        r = self.adapter.resolve_action(
            self.eid, "brightness_down", {"step": 20, "current_brightness": 60}
        )
        assert r.service == "turn_on"
        assert r.data["brightness"] == _brightness_pct_to_ha(40)

    def test_brightness_down_to_zero_turns_off(self) -> None:
        r = self.adapter.resolve_action(
            self.eid, "brightness_down", {"step": 50, "current_brightness": 50}
        )
        assert r.service == "turn_off"

    def test_brightness_down_clamped(self) -> None:
        r = self.adapter.resolve_action(
            self.eid, "brightness_down", {"step": 100, "current_brightness": 10}
        )
        assert r.service == "turn_off"

    def test_set_kelvin(self) -> None:
        r = self.adapter.resolve_action(self.eid, "set_kelvin", {"kelvin": 3000})
        assert r.service == "turn_on"
        assert r.data["color_temp_kelvin"] == 3000

    def test_set_kelvin_default(self) -> None:
        r = self.adapter.resolve_action(self.eid, "set_kelvin", {})
        assert r.data["color_temp_kelvin"] == 4000

    def test_unknown_action_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown action"):
            self.adapter.resolve_action(self.eid, "do_magic", {})
