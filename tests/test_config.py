"""Tests for deckboard_homeassistant.config."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import pytest
import yaml

from deckboard_homeassistant.config import (
    ActionConfig,
    BindingConfig,
    CardConfig,
    DeckConfig,
    EncoderConfig,
    HomeAssistantConfig,
    KeyConfig,
    ScreenConfig,
    StateBindConfig,
    _parse_action,
    _parse_binding,
    _parse_card,
    _parse_encoder,
    _parse_homeassistant,
    _parse_key,
    _parse_screen,
    _parse_state_bind,
    load_config,
)


# ------------------------------------------------------------------
# _parse_action
# ------------------------------------------------------------------


class TestParseAction:
    def test_none_returns_none(self) -> None:
        assert _parse_action(None) is None

    def test_shorthand_string(self) -> None:
        result = _parse_action("lights.kitchen.toggle")
        assert result == ActionConfig(binding="lights.kitchen", action="toggle")

    def test_shorthand_no_dot_returns_none(self) -> None:
        result = _parse_action("invalid")
        assert result is None

    def test_dict_format(self) -> None:
        result = _parse_action(
            {
                "binding": "lights.kitchen",
                "action": "set_brightness",
                "step": 10,
            }
        )
        assert result == ActionConfig(
            binding="lights.kitchen",
            action="set_brightness",
            args={"step": 10},
        )

    def test_dict_no_extra_args(self) -> None:
        result = _parse_action({"binding": "x", "action": "y"})
        assert result == ActionConfig(binding="x", action="y", args={})

    def test_unsupported_type_returns_none(self) -> None:
        assert _parse_action(42) is None  # type: ignore[arg-type]

    def test_dict_missing_keys_defaults(self) -> None:
        result = _parse_action({})
        assert result == ActionConfig(binding="", action="", args={})


# ------------------------------------------------------------------
# _parse_state_bind
# ------------------------------------------------------------------


class TestParseStateBind:
    def test_none_returns_none(self) -> None:
        assert _parse_state_bind(None) is None

    def test_shorthand_string(self) -> None:
        result = _parse_state_bind("lights.kitchen.is_on")
        assert result == StateBindConfig(binding="lights.kitchen", attribute="is_on")

    def test_shorthand_no_dot_returns_none(self) -> None:
        result = _parse_state_bind("invalid")
        assert result is None

    def test_dict_format(self) -> None:
        result = _parse_state_bind(
            {
                "binding": "lights.kitchen",
                "attribute": "brightness_pct",
            }
        )
        assert result == StateBindConfig(
            binding="lights.kitchen", attribute="brightness_pct"
        )

    def test_unsupported_type_returns_none(self) -> None:
        assert _parse_state_bind(42) is None  # type: ignore[arg-type]

    def test_dict_missing_keys_defaults(self) -> None:
        result = _parse_state_bind({})
        assert result == StateBindConfig(binding="", attribute="")


# ------------------------------------------------------------------
# _parse_key
# ------------------------------------------------------------------


class TestParseKey:
    def test_minimal(self) -> None:
        result = _parse_key(0, {})
        assert result == KeyConfig(index=0)

    def test_full_config(self) -> None:
        raw = {
            "icon": "mdi:lightbulb",
            "label": "Kitchen",
            "bind": {"state": "lights.kitchen.is_on"},
            "actions": {
                "press": "lights.kitchen.toggle",
                "release": {"binding": "lights.kitchen", "action": "turn_off"},
            },
        }
        result = _parse_key(3, raw)
        assert result.index == 3
        assert result.icon == "mdi:lightbulb"
        assert result.label == "Kitchen"
        assert result.state_bind == StateBindConfig(
            binding="lights.kitchen", attribute="is_on"
        )
        assert result.on_press == ActionConfig(
            binding="lights.kitchen", action="toggle"
        )
        assert result.on_release == ActionConfig(
            binding="lights.kitchen", action="turn_off"
        )

    def test_no_actions_no_bind(self) -> None:
        result = _parse_key(1, {"icon": "x", "label": "y"})
        assert result.on_press is None
        assert result.on_release is None
        assert result.state_bind is None


# ------------------------------------------------------------------
# _parse_encoder
# ------------------------------------------------------------------


class TestParseEncoder:
    def test_minimal(self) -> None:
        result = _parse_encoder(0, {})
        assert result == EncoderConfig(index=0)

    def test_full_config(self) -> None:
        raw = {
            "actions": {
                "turn": "lights.kitchen.brightness_up",
                "press": "lights.kitchen.toggle",
            }
        }
        result = _parse_encoder(2, raw)
        assert result.on_turn == ActionConfig(
            binding="lights.kitchen", action="brightness_up"
        )
        assert result.on_press == ActionConfig(
            binding="lights.kitchen", action="toggle"
        )


# ------------------------------------------------------------------
# _parse_card
# ------------------------------------------------------------------


class TestParseCard:
    def test_minimal(self) -> None:
        result = _parse_card(0, {})
        assert result.index == 0
        assert result.type == "status"
        assert result.binding == ""

    def test_full_config(self) -> None:
        raw = {
            "type": "light",
            "binding": "lights.kitchen",
            "icon": "mdi:bulb",
            "label": "Kitchen Light",
            "bind": {"value": "lights.kitchen.brightness_pct"},
            "actions": {"tap": "lights.kitchen.toggle"},
        }
        result = _parse_card(1, raw)
        assert result.type == "light"
        assert result.binding == "lights.kitchen"
        assert result.icon == "mdi:bulb"
        assert result.label == "Kitchen Light"
        assert result.value_bind == StateBindConfig(
            binding="lights.kitchen", attribute="brightness_pct"
        )
        assert result.on_tap == ActionConfig(binding="lights.kitchen", action="toggle")


# ------------------------------------------------------------------
# _parse_screen
# ------------------------------------------------------------------


class TestParseScreen:
    def test_empty_screen(self) -> None:
        result = _parse_screen("main", {})
        assert result.name == "main"
        assert result.keys == []
        assert result.encoders == []
        assert result.cards == []

    def test_screen_with_keys_encoders_cards(self) -> None:
        raw = {
            "keys": {
                "0": {"icon": "mdi:a", "label": "A"},
                "1": {"icon": "mdi:b"},
            },
            "encoders": {"0": {}},
            "cards": {"0": {"type": "status"}},
        }
        result = _parse_screen("home", raw)
        assert len(result.keys) == 2
        assert len(result.encoders) == 1
        assert len(result.cards) == 1
        assert result.keys[0].index == 0
        assert result.keys[1].index == 1


# ------------------------------------------------------------------
# _parse_binding
# ------------------------------------------------------------------


class TestParseBinding:
    def test_single_entity(self) -> None:
        result = _parse_binding(
            "lights.kitchen",
            {
                "entity": "light.kitchen",
                "adapter": "light",
            },
        )
        assert result == BindingConfig(
            key="lights.kitchen",
            entity_id="light.kitchen",
            adapter="light",
            entities={},
        )

    def test_multi_entity(self) -> None:
        result = _parse_binding(
            "audio.eq",
            {
                "adapter": "equalizer",
                "entities": {"bass": "number.bass", "treble": "number.treble"},
            },
        )
        assert result.entities == {"bass": "number.bass", "treble": "number.treble"}
        assert result.entity_id == ""

    def test_missing_fields_default(self) -> None:
        result = _parse_binding("x", {})
        assert result.entity_id == ""
        assert result.adapter == ""
        assert result.entities == {}


# ------------------------------------------------------------------
# _parse_homeassistant
# ------------------------------------------------------------------


class TestParseHomeAssistant:
    def test_defaults(self) -> None:
        result = _parse_homeassistant({})
        assert result.url == "http://homeassistant.local:8123"
        assert result.reconnect_delay == 5.0

    def test_inline_token(self) -> None:
        result = _parse_homeassistant({"token": "my-secret"})
        assert result.token == "my-secret"

    def test_token_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_TOKEN", "from-env")
        result = _parse_homeassistant({"token_env": "MY_TOKEN"})
        assert result.token == "from-env"

    def test_default_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DECKBOARD_HA_TOKEN", "default-env-token")
        result = _parse_homeassistant({})
        assert result.token == "default-env-token"

    def test_token_missing_env_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DECKBOARD_HA_TOKEN", raising=False)
        result = _parse_homeassistant({})
        assert result.token == ""

    def test_inline_token_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DECKBOARD_HA_TOKEN", "env-token")
        result = _parse_homeassistant({"token": "inline-token"})
        assert result.token == "inline-token"

    def test_custom_url_and_reconnect(self) -> None:
        result = _parse_homeassistant(
            {
                "url": "http://myha:8123",
                "reconnect_delay_seconds": 10.0,
            }
        )
        assert result.url == "http://myha:8123"
        assert result.reconnect_delay == 10.0


# ------------------------------------------------------------------
# load_config
# ------------------------------------------------------------------


class TestLoadConfig:
    def test_minimal_config(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "test.yaml"
        cfg_file.write_text(yaml.dump({}))
        result = load_config(cfg_file)
        assert isinstance(result, DeckConfig)
        assert result.device_type == "Stream Deck +"
        assert result.brightness == 80

    def test_full_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DECKBOARD_HA_TOKEN", "test-token")
        config = {
            "homeassistant": {"url": "http://ha:8123"},
            "device": {"type": "Stream Deck XL", "index": 1, "brightness": 60},
            "bindings": {
                "lights.kitchen": {
                    "entity": "light.kitchen",
                    "adapter": "light",
                }
            },
            "screens": {
                "main": {
                    "keys": {
                        "0": {
                            "icon": "mdi:lightbulb",
                            "label": "Kitchen",
                            "actions": {"press": "lights.kitchen.toggle"},
                        }
                    }
                }
            },
        }
        cfg_file = tmp_path / "test.yaml"
        cfg_file.write_text(yaml.dump(config))

        result = load_config(cfg_file)
        assert result.device_type == "Stream Deck XL"
        assert result.device_index == 1
        assert result.brightness == 60
        assert len(result.bindings) == 1
        assert result.bindings[0].key == "lights.kitchen"
        assert len(result.screens) == 1
        assert result.screens[0].name == "main"

    def test_empty_yaml_file(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "empty.yaml"
        cfg_file.write_text("")
        result = load_config(cfg_file)
        assert isinstance(result, DeckConfig)


# ------------------------------------------------------------------
# Dataclass frozen checks
# ------------------------------------------------------------------


class TestDataclassFrozen:
    def test_action_config_frozen(self) -> None:
        ac = ActionConfig(binding="x", action="y")
        with pytest.raises(AttributeError):
            ac.binding = "z"  # type: ignore[misc]

    def test_state_bind_config_frozen(self) -> None:
        sbc = StateBindConfig(binding="x", attribute="y")
        with pytest.raises(AttributeError):
            sbc.binding = "z"  # type: ignore[misc]

    def test_key_config_frozen(self) -> None:
        kc = KeyConfig(index=0)
        with pytest.raises(AttributeError):
            kc.index = 1  # type: ignore[misc]

    def test_encoder_config_frozen(self) -> None:
        ec = EncoderConfig(index=0)
        with pytest.raises(AttributeError):
            ec.index = 1  # type: ignore[misc]

    def test_card_config_frozen(self) -> None:
        cc = CardConfig(index=0)
        with pytest.raises(AttributeError):
            cc.index = 1  # type: ignore[misc]

    def test_screen_config_frozen(self) -> None:
        sc = ScreenConfig(name="x")
        with pytest.raises(AttributeError):
            sc.name = "y"  # type: ignore[misc]

    def test_binding_config_frozen(self) -> None:
        bc = BindingConfig(key="x", entity_id="y", adapter="z")
        with pytest.raises(AttributeError):
            bc.key = "w"  # type: ignore[misc]

    def test_ha_config_frozen(self) -> None:
        hc = HomeAssistantConfig()
        with pytest.raises(AttributeError):
            hc.url = "x"  # type: ignore[misc]

    def test_deck_config_frozen(self) -> None:
        dc = DeckConfig()
        with pytest.raises(AttributeError):
            dc.brightness = 50  # type: ignore[misc]
