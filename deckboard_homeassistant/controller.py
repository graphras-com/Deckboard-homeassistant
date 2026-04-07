"""Controller -- orchestrates config, bindings, and Deckboard UI.

The controller is the top-level coordinator.  It:
  1. Registers bindings in the BindingManager.
  2. Creates Deckboard Screen / Key / Card objects from config.
  3. Wires state subscriptions so HA changes update the UI.
  4. Wires UI event callbacks so user input dispatches HA actions.

It does NOT import the HA client or bridge -- it works through the abstract
:class:`StateProvider` and :class:`CommandBus` interfaces via BindingManager.
"""

from __future__ import annotations

import io
import logging
from typing import Any

import aiohttp
from PIL import Image

from deckboard import (
    Deck,
    EqualizerCard,
    HaMediaCard,
    LightCard,
    MediaCard,
    StatusCard,
)

from deckboard_homeassistant.bindings import BindingManager
from deckboard_homeassistant.config import (
    ActionConfig,
    CardConfig,
    DeckConfig,
    EncoderConfig,
    KeyConfig,
    ScreenConfig,
    StateBindConfig,
)

log = logging.getLogger(__name__)


class DeckboardController:
    """Builds and manages the Deckboard UI from configuration.

    Parameters:
        deck: The Deckboard Deck instance.
        binding_manager: Manages entity bindings.
        config: Parsed configuration.
    """

    def __init__(
        self,
        deck: Deck,
        binding_manager: BindingManager,
        config: DeckConfig,
    ) -> None:
        self._deck = deck
        self._bindings = binding_manager
        self._config = config

    async def setup(self) -> None:
        """Build all screens, keys, cards, and wire bindings."""
        # Register all bindings from config.
        for b in self._config.bindings:
            self._bindings.register(
                b.key,
                b.entity_id,
                b.adapter,
                entities=b.entities or None,
            )

        # Build each screen.
        for screen_cfg in self._config.screens:
            await self._build_screen(screen_cfg)

        # Set the first screen as active.
        if self._config.screens:
            first = self._config.screens[0].name
            await self._deck.set_screen(first)

        # Initial state refresh -- push current HA state to the UI.
        await self._bindings.refresh_all()
        await self._deck.refresh()

    # ------------------------------------------------------------------
    # Screen building
    # ------------------------------------------------------------------

    async def _build_screen(self, cfg: ScreenConfig) -> None:
        """Create a Deckboard screen and populate it from config."""
        screen = self._deck.screen(cfg.name)

        for key_cfg in cfg.keys:
            await self._build_key(screen, key_cfg)

        for enc_cfg in cfg.encoders:
            self._build_encoder(screen, enc_cfg)

        for card_cfg in cfg.cards:
            await self._build_card(screen, card_cfg)

    # ------------------------------------------------------------------
    # Keys
    # ------------------------------------------------------------------

    async def _build_key(self, screen: Any, cfg: KeyConfig) -> None:
        """Configure a key slot with icon, label, state, and actions."""
        key = screen.key(cfg.index)

        if cfg.icon:
            key.set_icon(cfg.icon)
        if cfg.label:
            key.set_label(cfg.label)

        # State binding: update key appearance on state change.
        if cfg.state_bind:
            self._wire_key_state(key, cfg)

        # Action bindings.
        if cfg.on_press:
            action_cfg = cfg.on_press

            @key.on_press
            async def _press(*, _action_cfg: ActionConfig = action_cfg) -> None:
                await self._bindings.execute_action(
                    _action_cfg.binding, _action_cfg.action, _action_cfg.args
                )
                await self._deck.refresh()

        if cfg.on_release:
            action_cfg = cfg.on_release

            @key.on_release
            async def _release(*, _action_cfg: ActionConfig = action_cfg) -> None:
                await self._bindings.execute_action(
                    _action_cfg.binding, _action_cfg.action, _action_cfg.args
                )
                await self._deck.refresh()

    def _wire_key_state(self, key: Any, cfg: KeyConfig) -> None:
        """Subscribe a key's appearance to a state binding."""
        bind = cfg.state_bind
        if bind is None:
            return

        binding_obj = self._bindings.get(bind.binding)
        if binding_obj is None:
            log.warning("Key %d: binding %r not found", cfg.index, bind.binding)
            return

        deck = self._deck
        icon_on = cfg.icon or "mdi:circle"
        label_text = cfg.label

        async def _on_state(attr: str, value: Any) -> None:
            # Update key icon color based on boolean state.
            if isinstance(value, bool):
                color = "#FFD700" if value else "#555555"
                key.set_icon(icon_on, color=color)
            elif isinstance(value, (int, float)):
                key.set_label(f"{label_text}\n{value}")
            await deck.refresh()

        binding_obj.subscribe(bind.attribute, _on_state)

    # ------------------------------------------------------------------
    # Encoders
    # ------------------------------------------------------------------

    def _build_encoder(self, screen: Any, cfg: EncoderConfig) -> None:
        """Configure an encoder slot with turn and press actions."""
        encoder = screen.encoder(cfg.index)

        if cfg.on_turn:
            action_cfg = cfg.on_turn

            @encoder.on_turn
            async def _turn(
                direction: int, *, _action_cfg: ActionConfig = action_cfg
            ) -> None:
                action_name = _action_cfg.action
                if direction < 0 and "_up" in action_name:
                    action_name = action_name.replace("_up", "_down")
                elif direction > 0 and "_down" in action_name:
                    action_name = action_name.replace("_down", "_up")

                args = dict(_action_cfg.args)
                args["direction"] = direction
                await self._bindings.execute_action(
                    _action_cfg.binding, action_name, args
                )
                await self._deck.refresh()

        if cfg.on_press:
            action_cfg = cfg.on_press

            @encoder.on_press
            async def _press(*, _action_cfg: ActionConfig = action_cfg) -> None:
                await self._bindings.execute_action(
                    _action_cfg.binding, _action_cfg.action, _action_cfg.args
                )
                await self._deck.refresh()

    # ------------------------------------------------------------------
    # Cards (touchscreen zones)
    # ------------------------------------------------------------------

    async def _build_card(self, screen: Any, cfg: CardConfig) -> None:
        """Create and configure a touchscreen card."""
        match cfg.type:
            case "light":
                await self._build_light_card(screen, cfg)
            case "media":
                await self._build_media_card(screen, cfg)
            case "ha_media":
                await self._build_ha_media_card(screen, cfg)
            case "equalizer":
                await self._build_equalizer_card(screen, cfg)
            case "status" | _:
                await self._build_status_card(screen, cfg)

    async def _build_status_card(self, screen: Any, cfg: CardConfig) -> None:
        """Build a StatusCard (icon + label + value)."""
        card = screen.card(cfg.index)

        if cfg.icon:
            card.set_icon(cfg.icon)
        if cfg.label:
            card.set_label(cfg.label)

        # Wire value display to state.
        if cfg.value_bind:
            bind = cfg.value_bind
            binding_obj = self._bindings.get(bind.binding)
            if binding_obj:
                deck = self._deck

                async def _on_value(attr: str, value: Any) -> None:
                    card.set_value(str(value) if value is not None else "")
                    await deck.refresh()

                binding_obj.subscribe(bind.attribute, _on_value)

        # Wire tap action.
        if cfg.on_tap:
            action_cfg = cfg.on_tap

            @card.on_tap
            async def _tap(*, _action_cfg: ActionConfig = action_cfg) -> None:
                await self._bindings.execute_action(
                    _action_cfg.binding, _action_cfg.action, _action_cfg.args
                )
                await self._deck.refresh()

    async def _build_light_card(self, screen: Any, cfg: CardConfig) -> None:
        """Build a LightCard (brightness + kelvin sliders)."""
        light_card = LightCard(cfg.index)
        screen.set_card(cfg.index, light_card)

        binding_obj = self._bindings.get(cfg.binding)
        if binding_obj is None:
            log.warning("Card %d: binding %r not found", cfg.index, cfg.binding)
            return

        deck = self._deck
        bindings = self._bindings
        binding_key = cfg.binding

        # State -> UI: update sliders when HA state changes.
        async def _on_brightness(attr: str, value: Any) -> None:
            if isinstance(value, (int, float)):
                light_card.brightness.set_value(int(value))
                await deck.refresh()

        async def _on_kelvin(attr: str, value: Any) -> None:
            if isinstance(value, (int, float)):
                light_card.kelvin.set_value(int(value))
                await deck.refresh()

        async def _on_kelvin_min(attr: str, value: Any) -> None:
            if isinstance(value, (int, float)):
                light_card.set_kelvin_range(float(value), light_card.kelvin.max_value)

        async def _on_kelvin_max(attr: str, value: Any) -> None:
            if isinstance(value, (int, float)):
                light_card.set_kelvin_range(light_card.kelvin.min_value, float(value))

        binding_obj.subscribe("brightness_pct", _on_brightness)
        binding_obj.subscribe("kelvin", _on_kelvin)
        binding_obj.subscribe("kelvin_min", _on_kelvin_min)
        binding_obj.subscribe("kelvin_max", _on_kelvin_max)

        # UI -> HA: slider change callbacks.
        @light_card.brightness.on_change
        async def _brightness_changed(value: float) -> None:
            await bindings.execute_action(
                binding_key,
                "set_brightness",
                {"brightness": int(value)},
            )

        @light_card.kelvin.on_change
        async def _kelvin_changed(value: float) -> None:
            await bindings.execute_action(
                binding_key,
                "set_kelvin",
                {"kelvin": int(value)},
            )

        # Tap on card toggles the light.
        @light_card.on_tap
        async def _tap() -> None:
            await bindings.execute_action(binding_key, "toggle")
            await deck.refresh()

    async def _build_media_card(self, screen: Any, cfg: CardConfig) -> None:
        """Build a MediaCard (title + volume slider + mute)."""
        media_card = MediaCard(cfg.index)
        screen.set_card(cfg.index, media_card)

        binding_obj = self._bindings.get(cfg.binding)
        if binding_obj is None:
            log.warning("Card %d: binding %r not found", cfg.index, cfg.binding)
            return

        deck = self._deck
        bindings = self._bindings
        binding_key = cfg.binding

        # State -> UI.
        async def _on_title(attr: str, value: Any) -> None:
            media_card.title_text.set_text(str(value) if value else "No Media")
            await deck.refresh()

        async def _on_volume(attr: str, value: Any) -> None:
            if isinstance(value, (int, float)):
                media_card.volume.set_value(int(value))
                await deck.refresh()

        async def _on_muted(attr: str, value: Any) -> None:
            if isinstance(value, bool) and value != media_card.muted:
                media_card.toggle_mute()
                await deck.refresh()

        binding_obj.subscribe("title", _on_title)
        binding_obj.subscribe("volume_pct", _on_volume)
        binding_obj.subscribe("is_muted", _on_muted)

        # UI -> HA: volume slider.
        @media_card.volume.on_change
        async def _volume_changed(value: float) -> None:
            await bindings.execute_action(
                binding_key,
                "set_volume",
                {"volume": int(value)},
            )

        # Tap toggles play/pause.
        @media_card.on_tap
        async def _tap() -> None:
            await bindings.execute_action(binding_key, "play_pause")
            await deck.refresh()

    async def _build_equalizer_card(self, screen: Any, cfg: CardConfig) -> None:
        """Build an EqualizerCard (sub, bass, treble, balance sliders).

        Expects the binding to be a multi-entity equalizer adapter with
        slots named ``sub``, ``bass``, ``treble``, and ``balance``.
        """
        eq_card = EqualizerCard(cfg.index)
        screen.set_card(cfg.index, eq_card)

        binding_obj = self._bindings.get(cfg.binding)
        if binding_obj is None:
            log.warning("Card %d: binding %r not found", cfg.index, cfg.binding)
            return

        deck = self._deck
        bindings = self._bindings
        binding_key = cfg.binding

        # Map slot names to card-level accessors.
        sliders = {
            "sub": eq_card.sub,
            "bass": eq_card.bass,
            "treble": eq_card.treble,
            "balance": eq_card.balance,
        }
        range_setters = {
            "sub": eq_card.set_sub_range,
            "bass": eq_card.set_bass_range,
            "treble": eq_card.set_treble_range,
            "balance": eq_card.set_balance_range,
        }

        # State -> UI: wire value and range updates per slot.
        for slot_name, slider in sliders.items():
            setter = range_setters[slot_name]

            async def _on_value(
                attr: str, value: Any, *, _slider: Any = slider
            ) -> None:
                if isinstance(value, (int, float)):
                    _slider.set_value(float(value))
                    await deck.refresh()

            async def _on_min(
                attr: str,
                value: Any,
                *,
                _slider: Any = slider,
                _set_range: Any = setter,
            ) -> None:
                if isinstance(value, (int, float)):
                    _set_range(float(value), _slider.max_value)

            async def _on_max(
                attr: str,
                value: Any,
                *,
                _slider: Any = slider,
                _set_range: Any = setter,
            ) -> None:
                if isinstance(value, (int, float)):
                    _set_range(_slider.min_value, float(value))

            binding_obj.subscribe(slot_name, _on_value)
            binding_obj.subscribe(f"{slot_name}_min", _on_min)
            binding_obj.subscribe(f"{slot_name}_max", _on_max)

        # UI -> HA: slider change callbacks.
        for slot_name, slider in sliders.items():

            @slider.on_change
            async def _slider_changed(value: float, *, _slot: str = slot_name) -> None:
                await bindings.execute_action(
                    binding_key,
                    f"set_{_slot}",
                    {"value": value},
                )

    async def _build_ha_media_card(self, screen: Any, cfg: CardConfig) -> None:
        """Build an HaMediaCard (album art + metadata + volume bar).

        The HaMediaCard renders album art with a gradient overlay, artist
        name, title, playback state, and a volume bar.  The card emits
        pure events via callbacks; it does not modify its own state
        directly.  The controller dispatches actions to HA and applies
        confirmed state back to the card via setters.
        """
        ha_card = HaMediaCard(cfg.index)
        screen.set_card(cfg.index, ha_card)

        binding_obj = self._bindings.get(cfg.binding)
        if binding_obj is None:
            log.warning("Card %d: binding %r not found", cfg.index, cfg.binding)
            return

        deck = self._deck
        bindings = self._bindings
        binding_key = cfg.binding
        ha_base_url = self._config.homeassistant.url.rstrip("/")
        ha_token = self._config.homeassistant.token

        # Track the last fetched picture URL to avoid redundant fetches.
        last_picture_url: dict[str, str] = {"url": ""}

        # ── State -> UI (HA pushes confirmed state to the card) ───────

        async def _on_artist(attr: str, value: Any) -> None:
            ha_card.set_artist(str(value) if value else "")
            await deck.refresh()

        async def _on_title(attr: str, value: Any) -> None:
            ha_card.set_title(str(value) if value else "No Media")
            await deck.refresh()

        async def _on_playing(attr: str, value: Any) -> None:
            if isinstance(value, bool):
                ha_card.set_state("Playing" if value else "Paused")
                await deck.refresh()

        async def _on_volume(attr: str, value: Any) -> None:
            if isinstance(value, (int, float)):
                ha_card.set_volume(float(value))
                await deck.refresh()

        async def _on_muted(attr: str, value: Any) -> None:
            if isinstance(value, bool) and value != ha_card.muted:
                ha_card.set_muted(value)
                await deck.refresh()

        async def _on_entity_picture(attr: str, value: Any) -> None:
            url = str(value) if value else ""
            if not url or url == last_picture_url["url"]:
                if not url and ha_card.entity_picture is not None:
                    ha_card.set_entity_picture(None)
                    await deck.refresh()
                return
            last_picture_url["url"] = url
            image = await _fetch_entity_picture(url)
            ha_card.set_entity_picture(image)
            await deck.refresh()

        async def _fetch_entity_picture(path: str) -> Image.Image | None:
            """Fetch album art from HA and return as a PIL Image."""
            full_url = f"{ha_base_url}{path}"
            headers = {"Authorization": f"Bearer {ha_token}"}
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        full_url,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        if resp.status != 200:
                            log.warning(
                                "Failed to fetch entity picture: HTTP %d", resp.status
                            )
                            return None
                        data = await resp.read()
                        return Image.open(io.BytesIO(data))
            except Exception:
                log.exception("Error fetching entity picture from %s", full_url)
                return None

        binding_obj.subscribe("artist", _on_artist)
        binding_obj.subscribe("title", _on_title)
        binding_obj.subscribe("is_playing", _on_playing)
        binding_obj.subscribe("volume_pct", _on_volume)
        binding_obj.subscribe("is_muted", _on_muted)
        binding_obj.subscribe("entity_picture", _on_entity_picture)

        # ── UI -> HA (card emits requests, controller dispatches) ─────

        @ha_card.on_volume_change
        async def _volume_changed(volume: float) -> None:
            await bindings.execute_action(
                binding_key,
                "set_volume",
                {"volume": int(volume)},
            )

        @ha_card.on_mute_toggle
        async def _mute_toggled(muted: bool) -> None:
            await bindings.execute_action(binding_key, "mute_toggle")
            await deck.refresh()

        @ha_card.on_play_pause_toggle
        async def _play_pause_toggled(playing: bool) -> None:
            await bindings.execute_action(binding_key, "play_pause")
            await deck.refresh()

        # Tap toggles play/pause.
        @ha_card.on_tap
        async def _tap() -> None:
            await bindings.execute_action(binding_key, "play_pause")
            await deck.refresh()
