"""Tests for deckboard_homeassistant.adapters.equalizer."""

from __future__ import annotations

import pytest

from deckboard_homeassistant.adapters.equalizer import EqualizerAdapter, _parse_number


class TestParseNumber:
    def test_valid_int(self) -> None:
        assert _parse_number(42) == 42.0

    def test_valid_float(self) -> None:
        assert _parse_number(3.14) == 3.14

    def test_valid_string(self) -> None:
        assert _parse_number("10.5") == 10.5

    def test_none_returns_default(self) -> None:
        assert _parse_number(None) == 0.0
        assert _parse_number(None, 5.0) == 5.0

    def test_invalid_string_returns_default(self) -> None:
        assert _parse_number("invalid") == 0.0
        assert _parse_number("invalid", -1.0) == -1.0

    def test_empty_string_returns_default(self) -> None:
        assert _parse_number("", 99.0) == 99.0


class TestEqualizerAdapterNormalize:
    def setup_method(self) -> None:
        self.adapter = EqualizerAdapter()
        self.adapter._entities = {
            "bass": "number.bass",
            "treble": "number.treble",
        }

    def test_domain(self) -> None:
        assert self.adapter.domain == "equalizer"

    def test_normalize_multi(self) -> None:
        all_states = {
            "bass": {"state": "50", "min": "0", "max": "100"},
            "treble": {"state": "70", "min": "-10", "max": "10"},
        }
        result = self.adapter.normalize_multi(
            "bass", "number.bass", all_states["bass"], all_states
        )
        assert result["bass"] == 50.0
        assert result["bass_min"] == 0.0
        assert result["bass_max"] == 100.0
        assert result["treble"] == 70.0
        assert result["treble_min"] == -10.0
        assert result["treble_max"] == 10.0

    def test_normalize_multi_missing_values(self) -> None:
        all_states = {
            "bass": {"state": None},
            "treble": {},
        }
        result = self.adapter.normalize_multi(
            "bass", "number.bass", all_states["bass"], all_states
        )
        assert result["bass"] == 0.0
        assert result["bass_min"] == 0.0
        assert result["bass_max"] == 100.0
        assert result["treble"] == 0.0

    def test_normalize_delegates(self) -> None:
        """Test that single-entity normalize delegates to normalize_multi."""
        self.adapter._slot_states = {
            "bass": {"state": "50", "min": "0", "max": "100"},
            "treble": {"state": "70", "min": "-10", "max": "10"},
        }
        result = self.adapter.normalize(
            "number.bass", {"state": "50", "min": "0", "max": "100"}
        )
        assert "bass" in result
        assert "treble" in result

    def test_default_state_keys(self) -> None:
        assert self.adapter.default_state_keys() == []


class TestEqualizerAdapterResolveAction:
    def setup_method(self) -> None:
        self.adapter = EqualizerAdapter()
        self.entities = {
            "bass": "number.bass",
            "treble": "number.treble",
        }
        self.adapter._entities = self.entities

    def test_set_bass(self) -> None:
        r = self.adapter.resolve_action_multi(self.entities, "set_bass", {"value": 75})
        assert r.domain == "number"
        assert r.service == "set_value"
        assert r.data["entity_id"] == "number.bass"
        assert r.data["value"] == 75.0

    def test_set_treble(self) -> None:
        r = self.adapter.resolve_action_multi(self.entities, "set_treble", {"value": 5})
        assert r.data["entity_id"] == "number.treble"
        assert r.data["value"] == 5.0

    def test_bass_up(self) -> None:
        r = self.adapter.resolve_action_multi(
            self.entities, "bass_up", {"step": 5, "current_bass": 50}
        )
        assert r.data["entity_id"] == "number.bass"
        assert r.data["value"] == 55.0

    def test_bass_up_default_step(self) -> None:
        r = self.adapter.resolve_action_multi(
            self.entities, "bass_up", {"current_bass": 50}
        )
        assert r.data["value"] == 51.0

    def test_bass_down(self) -> None:
        r = self.adapter.resolve_action_multi(
            self.entities, "bass_down", {"step": 5, "current_bass": 50}
        )
        assert r.data["entity_id"] == "number.bass"
        assert r.data["value"] == 45.0

    def test_treble_up(self) -> None:
        r = self.adapter.resolve_action_multi(
            self.entities, "treble_up", {"step": 2, "current_treble": 3}
        )
        assert r.data["entity_id"] == "number.treble"
        assert r.data["value"] == 5.0

    def test_treble_down(self) -> None:
        r = self.adapter.resolve_action_multi(
            self.entities, "treble_down", {"step": 2, "current_treble": 3}
        )
        assert r.data["value"] == 1.0

    def test_unknown_action_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown action"):
            self.adapter.resolve_action_multi(self.entities, "wobble", {})

    def test_resolve_action_delegates(self) -> None:
        """Test that single-entity resolve_action delegates to resolve_action_multi."""
        r = self.adapter.resolve_action("number.bass", "set_bass", {"value": 10})
        assert r.data["entity_id"] == "number.bass"
        assert r.data["value"] == 10.0
