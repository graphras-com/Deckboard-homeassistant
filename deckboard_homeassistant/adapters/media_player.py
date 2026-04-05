"""Media player domain adapter.

Normalizes HA media_player entity state and resolves transport/volume
actions into HA service calls.

Normalized keys:
    is_playing      bool    Whether the media player is actively playing.
    is_on           bool    Whether the entity is not ``"off"`` / ``"unavailable"``.
    volume_pct      int     Volume as 0-100 percentage (HA uses 0.0-1.0).
    is_muted        bool    Whether the player is muted.
    title           str     Current media title (or "No Media").
    artist          str     Current media artist (or "").
    media_type      str     Content type (music, video, etc.).
    source          str     Active input source.

Supported actions:
    play_pause          Toggle play/pause.
    play                Start playback.
    pause               Pause playback.
    stop                Stop playback.
    next_track          Skip to next track.
    previous_track      Skip to previous track.
    volume_up           Increase volume by ``step`` (default 5).
    volume_down         Decrease volume by ``step`` (default 5).
    set_volume          Set volume to a specific percentage.
    mute_toggle         Toggle mute.
    set_source          Set the input source.
"""

from __future__ import annotations

from typing import Any

from deckboard_homeassistant.adapters.base import DomainAdapter, ResolvedAction


class MediaPlayerAdapter(DomainAdapter):
    """Adapter for ``media_player.*`` entities."""

    @property
    def domain(self) -> str:
        return "media_player"

    def normalize(self, entity_id: str, state: dict[str, Any]) -> dict[str, Any]:
        raw_state = state.get("state", "unavailable")
        is_playing = raw_state == "playing"
        is_on = raw_state not in ("off", "unavailable", "unknown")

        # Volume: HA uses 0.0-1.0 float.
        volume_raw = state.get("volume_level")
        volume_pct = round(float(volume_raw) * 100) if volume_raw is not None else 0

        is_muted = bool(state.get("is_volume_muted", False))
        title = state.get("media_title") or "No Media"
        artist = state.get("media_artist") or ""
        media_type = state.get("media_content_type") or ""
        source = state.get("source") or ""

        return {
            "is_playing": is_playing,
            "is_on": is_on,
            "volume_pct": volume_pct,
            "is_muted": is_muted,
            "title": title,
            "artist": artist,
            "media_type": media_type,
            "source": source,
        }

    def resolve_action(
        self, entity_id: str, action_name: str, action_args: dict[str, Any]
    ) -> ResolvedAction:
        domain = "media_player"
        data: dict[str, Any] = {"entity_id": entity_id}

        match action_name:
            case "play_pause":
                return ResolvedAction(domain, "media_play_pause", data)

            case "play":
                return ResolvedAction(domain, "media_play", data)

            case "pause":
                return ResolvedAction(domain, "media_pause", data)

            case "stop":
                return ResolvedAction(domain, "media_stop", data)

            case "next_track":
                return ResolvedAction(domain, "media_next_track", data)

            case "previous_track":
                return ResolvedAction(domain, "media_previous_track", data)

            case "volume_up":
                step = int(action_args.get("step", 5))
                current = int(action_args.get("current_volume", 50))
                target = min(100, current + step)
                data["volume_level"] = target / 100.0
                return ResolvedAction(domain, "volume_set", data)

            case "volume_down":
                step = int(action_args.get("step", 5))
                current = int(action_args.get("current_volume", 50))
                target = max(0, current - step)
                data["volume_level"] = target / 100.0
                return ResolvedAction(domain, "volume_set", data)

            case "set_volume":
                pct = int(action_args.get("volume", 50))
                data["volume_level"] = max(0, min(100, pct)) / 100.0
                return ResolvedAction(domain, "volume_set", data)

            case "mute_toggle":
                data["is_volume_muted"] = not action_args.get("is_muted", False)
                return ResolvedAction(domain, "volume_mute", data)

            case "set_source":
                data["source"] = action_args.get("source", "")
                return ResolvedAction(domain, "select_source", data)

            case _:
                raise ValueError(f"MediaPlayerAdapter: unknown action {action_name!r}")

    def default_state_keys(self) -> list[str]:
        return ["is_playing", "volume_pct", "is_muted", "title"]
