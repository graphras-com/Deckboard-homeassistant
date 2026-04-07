"""Tests for deckboard_homeassistant.adapters.media_player."""

from __future__ import annotations

import pytest

from deckboard_homeassistant.adapters.media_player import MediaPlayerAdapter


class TestMediaPlayerNormalize:
    def setup_method(self) -> None:
        self.adapter = MediaPlayerAdapter()
        self.eid = "media_player.living_room"

    def test_domain(self) -> None:
        assert self.adapter.domain == "media_player"

    def test_playing(self) -> None:
        state = {
            "state": "playing",
            "volume_level": 0.65,
            "is_volume_muted": False,
            "media_title": "Song Title",
            "media_artist": "Artist Name",
            "media_content_type": "music",
            "source": "Spotify",
            "entity_picture": "/api/media/image.jpg",
        }
        result = self.adapter.normalize(self.eid, state)
        assert result["is_playing"] is True
        assert result["is_on"] is True
        assert result["volume_pct"] == 65
        assert result["is_muted"] is False
        assert result["title"] == "Song Title"
        assert result["artist"] == "Artist Name"
        assert result["media_type"] == "music"
        assert result["source"] == "Spotify"
        assert result["entity_picture"] == "/api/media/image.jpg"

    def test_off(self) -> None:
        state = {"state": "off"}
        result = self.adapter.normalize(self.eid, state)
        assert result["is_playing"] is False
        assert result["is_on"] is False
        assert result["volume_pct"] == 0
        assert result["title"] == "No Media"
        assert result["artist"] == ""
        assert result["entity_picture"] == ""

    def test_unavailable(self) -> None:
        state = {"state": "unavailable"}
        result = self.adapter.normalize(self.eid, state)
        assert result["is_on"] is False

    def test_unknown(self) -> None:
        state = {"state": "unknown"}
        result = self.adapter.normalize(self.eid, state)
        assert result["is_on"] is False

    def test_idle(self) -> None:
        state = {"state": "idle", "volume_level": 0.5}
        result = self.adapter.normalize(self.eid, state)
        assert result["is_playing"] is False
        assert result["is_on"] is True
        assert result["volume_pct"] == 50

    def test_paused(self) -> None:
        state = {"state": "paused"}
        result = self.adapter.normalize(self.eid, state)
        assert result["is_playing"] is False
        assert result["is_on"] is True

    def test_muted(self) -> None:
        state = {"state": "playing", "is_volume_muted": True}
        result = self.adapter.normalize(self.eid, state)
        assert result["is_muted"] is True

    def test_no_volume(self) -> None:
        state = {"state": "playing"}
        result = self.adapter.normalize(self.eid, state)
        assert result["volume_pct"] == 0

    def test_default_state_keys(self) -> None:
        assert self.adapter.default_state_keys() == [
            "is_playing",
            "volume_pct",
            "is_muted",
            "title",
            "artist",
            "entity_picture",
        ]


class TestMediaPlayerResolveAction:
    def setup_method(self) -> None:
        self.adapter = MediaPlayerAdapter()
        self.eid = "media_player.living_room"

    def test_play_pause(self) -> None:
        r = self.adapter.resolve_action(self.eid, "play_pause", {})
        assert r.service == "media_play_pause"
        assert r.domain == "media_player"

    def test_play(self) -> None:
        r = self.adapter.resolve_action(self.eid, "play", {})
        assert r.service == "media_play"

    def test_pause(self) -> None:
        r = self.adapter.resolve_action(self.eid, "pause", {})
        assert r.service == "media_pause"

    def test_stop(self) -> None:
        r = self.adapter.resolve_action(self.eid, "stop", {})
        assert r.service == "media_stop"

    def test_next_track(self) -> None:
        r = self.adapter.resolve_action(self.eid, "next_track", {})
        assert r.service == "media_next_track"

    def test_previous_track(self) -> None:
        r = self.adapter.resolve_action(self.eid, "previous_track", {})
        assert r.service == "media_previous_track"

    def test_volume_up(self) -> None:
        r = self.adapter.resolve_action(
            self.eid, "volume_up", {"step": 10, "current_volume": 50}
        )
        assert r.service == "volume_set"
        assert r.data["volume_level"] == 0.60

    def test_volume_up_clamped(self) -> None:
        r = self.adapter.resolve_action(
            self.eid, "volume_up", {"step": 20, "current_volume": 90}
        )
        assert r.data["volume_level"] == 1.0

    def test_volume_up_defaults(self) -> None:
        r = self.adapter.resolve_action(self.eid, "volume_up", {})
        # step=5, current=50 -> 55
        assert r.data["volume_level"] == 0.55

    def test_volume_down(self) -> None:
        r = self.adapter.resolve_action(
            self.eid, "volume_down", {"step": 10, "current_volume": 50}
        )
        assert r.data["volume_level"] == 0.40

    def test_volume_down_clamped(self) -> None:
        r = self.adapter.resolve_action(
            self.eid, "volume_down", {"step": 100, "current_volume": 10}
        )
        assert r.data["volume_level"] == 0.0

    def test_set_volume(self) -> None:
        r = self.adapter.resolve_action(self.eid, "set_volume", {"volume": 75})
        assert r.service == "volume_set"
        assert r.data["volume_level"] == 0.75

    def test_set_volume_clamped(self) -> None:
        r = self.adapter.resolve_action(self.eid, "set_volume", {"volume": 150})
        assert r.data["volume_level"] == 1.0

    def test_mute_toggle(self) -> None:
        r = self.adapter.resolve_action(self.eid, "mute_toggle", {"is_muted": True})
        assert r.service == "volume_mute"
        assert r.data["is_volume_muted"] is False

    def test_mute_toggle_unmuted(self) -> None:
        r = self.adapter.resolve_action(self.eid, "mute_toggle", {"is_muted": False})
        assert r.data["is_volume_muted"] is True

    def test_set_source(self) -> None:
        r = self.adapter.resolve_action(self.eid, "set_source", {"source": "HDMI"})
        assert r.service == "select_source"
        assert r.data["source"] == "HDMI"

    def test_set_source_default(self) -> None:
        r = self.adapter.resolve_action(self.eid, "set_source", {})
        assert r.data["source"] == ""

    def test_unknown_action_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown action"):
            self.adapter.resolve_action(self.eid, "rewind", {})
