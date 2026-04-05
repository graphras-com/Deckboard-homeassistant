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

import logging
from typing import Any

from deckboard import (
    Deck,
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
            self._bindings.register(b.key, b.entity_id, b.adapter)

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

        binding_obj.subscribe("brightness_pct", _on_brightness)
        binding_obj.subscribe("kelvin", _on_kelvin)

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
