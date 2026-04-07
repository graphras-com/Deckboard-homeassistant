"""Tests for deckboard_homeassistant.controller."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from deckboard_homeassistant.bindings import Binding, BindingManager
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
)
from deckboard_homeassistant.controller import DeckboardController


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_deck() -> MagicMock:
    """Create a mock Deck with standard screen/key/encoder/card support."""
    deck = MagicMock()
    deck.set_screen = AsyncMock()
    deck.refresh = AsyncMock()

    key_mock = MagicMock()
    key_mock.set_icon = MagicMock()
    key_mock.set_label = MagicMock()
    key_mock.on_press = MagicMock(side_effect=lambda fn: fn)
    key_mock.on_release = MagicMock(side_effect=lambda fn: fn)

    encoder_mock = MagicMock()
    encoder_mock.on_turn = MagicMock(side_effect=lambda fn: fn)
    encoder_mock.on_press = MagicMock(side_effect=lambda fn: fn)

    card_mock = MagicMock()
    card_mock.set_icon = MagicMock()
    card_mock.set_label = MagicMock()
    card_mock.set_value = MagicMock()
    card_mock.on_tap = MagicMock(side_effect=lambda fn: fn)

    screen_mock = MagicMock()
    screen_mock.key = MagicMock(return_value=key_mock)
    screen_mock.encoder = MagicMock(return_value=encoder_mock)
    screen_mock.card = MagicMock(return_value=card_mock)
    screen_mock.set_card = MagicMock()

    deck.screen = MagicMock(return_value=screen_mock)
    return deck


def _make_mock_binding_manager() -> MagicMock:
    """Create a mock BindingManager."""
    mgr = MagicMock(spec=BindingManager)
    mgr.register = MagicMock()
    mgr.get = MagicMock(return_value=None)
    mgr.execute_action = AsyncMock()
    mgr.refresh_all = AsyncMock()
    return mgr


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------


class TestControllerSetup:
    async def test_registers_bindings(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        config = DeckConfig(
            bindings=[
                BindingConfig(
                    key="lights.kitchen", entity_id="light.kitchen", adapter="light"
                ),
            ],
            screens=[],
        )
        controller = DeckboardController(deck, mgr, config)
        await controller.setup()
        mgr.register.assert_called_once_with(
            "lights.kitchen", "light.kitchen", "light", entities=None
        )

    async def test_registers_multi_entity_binding(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        config = DeckConfig(
            bindings=[
                BindingConfig(
                    key="audio.eq",
                    entity_id="",
                    adapter="equalizer",
                    entities={"bass": "number.bass", "treble": "number.treble"},
                ),
            ],
            screens=[],
        )
        controller = DeckboardController(deck, mgr, config)
        await controller.setup()
        mgr.register.assert_called_once_with(
            "audio.eq",
            "",
            "equalizer",
            entities={"bass": "number.bass", "treble": "number.treble"},
        )

    async def test_builds_screens(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        config = DeckConfig(
            screens=[
                ScreenConfig(name="main", keys=[KeyConfig(index=0, icon="mdi:a")]),
                ScreenConfig(name="second"),
            ],
        )
        controller = DeckboardController(deck, mgr, config)
        await controller.setup()
        assert deck.screen.call_count == 2
        deck.set_screen.assert_called_once_with("main")

    async def test_no_screens(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        config = DeckConfig(screens=[])
        controller = DeckboardController(deck, mgr, config)
        await controller.setup()
        deck.set_screen.assert_not_called()

    async def test_refreshes_after_setup(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        config = DeckConfig(screens=[ScreenConfig(name="main")])
        controller = DeckboardController(deck, mgr, config)
        await controller.setup()
        mgr.refresh_all.assert_called_once()
        deck.refresh.assert_called()


# ---------------------------------------------------------------------------
# Key building and callbacks
# ---------------------------------------------------------------------------


class TestBuildKey:
    async def test_key_with_icon_and_label(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        config = DeckConfig(
            screens=[
                ScreenConfig(
                    name="main",
                    keys=[
                        KeyConfig(index=0, icon="mdi:bulb", label="Kitchen"),
                    ],
                )
            ],
        )
        controller = DeckboardController(deck, mgr, config)
        await controller.setup()
        key = deck.screen.return_value.key.return_value
        key.set_icon.assert_called_with("mdi:bulb")
        key.set_label.assert_called_with("Kitchen")

    async def test_key_press_callback_invoked(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        # Capture the registered callback.
        captured_fn = {}
        deck.screen.return_value.key.return_value.on_press = MagicMock(
            side_effect=lambda fn: captured_fn.__setitem__("press", fn)
        )
        config = DeckConfig(
            screens=[
                ScreenConfig(
                    name="main",
                    keys=[
                        KeyConfig(
                            index=0,
                            on_press=ActionConfig(
                                binding="lights.kitchen", action="toggle", args={"x": 1}
                            ),
                        ),
                    ],
                )
            ],
        )
        controller = DeckboardController(deck, mgr, config)
        await controller.setup()

        # Invoke the captured callback.
        fn = captured_fn["press"]
        await fn()
        mgr.execute_action.assert_called_with("lights.kitchen", "toggle", {"x": 1})

    async def test_key_release_callback_invoked(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        captured_fn = {}
        deck.screen.return_value.key.return_value.on_release = MagicMock(
            side_effect=lambda fn: captured_fn.__setitem__("release", fn)
        )
        config = DeckConfig(
            screens=[
                ScreenConfig(
                    name="main",
                    keys=[
                        KeyConfig(
                            index=0,
                            on_release=ActionConfig(
                                binding="lights.kitchen", action="turn_off"
                            ),
                        ),
                    ],
                )
            ],
        )
        controller = DeckboardController(deck, mgr, config)
        await controller.setup()

        fn = captured_fn["release"]
        await fn()
        mgr.execute_action.assert_called_with("lights.kitchen", "turn_off", {})


# ---------------------------------------------------------------------------
# Key state wiring
# ---------------------------------------------------------------------------


class TestWireKeyState:
    async def test_key_state_bind_with_binding(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        from deckboard_homeassistant.adapters.light import LightAdapter

        mock_binding = Binding(
            key="lights.kitchen", entity_id="light.kitchen", adapter=LightAdapter()
        )
        mgr.get = MagicMock(return_value=mock_binding)
        config = DeckConfig(
            screens=[
                ScreenConfig(
                    name="main",
                    keys=[
                        KeyConfig(
                            index=0,
                            icon="mdi:bulb",
                            state_bind=StateBindConfig(
                                binding="lights.kitchen", attribute="is_on"
                            ),
                        ),
                    ],
                )
            ],
        )
        controller = DeckboardController(deck, mgr, config)
        await controller.setup()
        assert "is_on" in mock_binding._subscribers
        assert len(mock_binding._subscribers["is_on"]) == 1

    async def test_key_state_bind_missing_binding(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        mgr.get = MagicMock(return_value=None)
        config = DeckConfig(
            screens=[
                ScreenConfig(
                    name="main",
                    keys=[
                        KeyConfig(
                            index=0,
                            state_bind=StateBindConfig(
                                binding="nonexistent", attribute="is_on"
                            ),
                        ),
                    ],
                )
            ],
        )
        controller = DeckboardController(deck, mgr, config)
        await controller.setup()

    async def test_key_state_callback_bool(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        from deckboard_homeassistant.adapters.light import LightAdapter

        mock_binding = Binding(
            key="lights.kitchen", entity_id="light.kitchen", adapter=LightAdapter()
        )
        mgr.get = MagicMock(return_value=mock_binding)
        config = DeckConfig(
            screens=[
                ScreenConfig(
                    name="main",
                    keys=[
                        KeyConfig(
                            index=0,
                            icon="mdi:bulb",
                            state_bind=StateBindConfig(
                                binding="lights.kitchen", attribute="is_on"
                            ),
                        ),
                    ],
                )
            ],
        )
        controller = DeckboardController(deck, mgr, config)
        await controller.setup()
        callback = mock_binding._subscribers["is_on"][0]
        await callback("is_on", True)
        key = deck.screen.return_value.key.return_value
        key.set_icon.assert_called_with("mdi:bulb", color="#FFD700")
        await callback("is_on", False)
        key.set_icon.assert_called_with("mdi:bulb", color="#555555")

    async def test_key_state_callback_number(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        from deckboard_homeassistant.adapters.light import LightAdapter

        mock_binding = Binding(
            key="lights.kitchen", entity_id="light.kitchen", adapter=LightAdapter()
        )
        mgr.get = MagicMock(return_value=mock_binding)
        config = DeckConfig(
            screens=[
                ScreenConfig(
                    name="main",
                    keys=[
                        KeyConfig(
                            index=0,
                            label="Brightness",
                            state_bind=StateBindConfig(
                                binding="lights.kitchen", attribute="brightness_pct"
                            ),
                        ),
                    ],
                )
            ],
        )
        controller = DeckboardController(deck, mgr, config)
        await controller.setup()
        callback = mock_binding._subscribers["brightness_pct"][0]
        await callback("brightness_pct", 75)
        key = deck.screen.return_value.key.return_value
        key.set_label.assert_called_with("Brightness\n75")

    async def test_key_state_callback_string_value(self) -> None:
        """String values should just call refresh without set_icon or set_label changes."""
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        from deckboard_homeassistant.adapters.light import LightAdapter

        mock_binding = Binding(
            key="lights.kitchen", entity_id="light.kitchen", adapter=LightAdapter()
        )
        mgr.get = MagicMock(return_value=mock_binding)
        config = DeckConfig(
            screens=[
                ScreenConfig(
                    name="main",
                    keys=[
                        KeyConfig(
                            index=0,
                            icon="mdi:bulb",
                            state_bind=StateBindConfig(
                                binding="lights.kitchen", attribute="is_on"
                            ),
                        ),
                    ],
                )
            ],
        )
        controller = DeckboardController(deck, mgr, config)
        await controller.setup()
        callback = mock_binding._subscribers["is_on"][0]
        # Pass a string -- neither bool nor number branch.
        await callback("is_on", "string_value")
        deck.refresh.assert_called()

    async def test_key_no_icon_defaults_to_mdi_circle(self) -> None:
        """When icon is empty, should use mdi:circle as the icon."""
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        from deckboard_homeassistant.adapters.light import LightAdapter

        mock_binding = Binding(
            key="lights.kitchen", entity_id="light.kitchen", adapter=LightAdapter()
        )
        mgr.get = MagicMock(return_value=mock_binding)
        config = DeckConfig(
            screens=[
                ScreenConfig(
                    name="main",
                    keys=[
                        KeyConfig(
                            index=0,
                            icon="",
                            state_bind=StateBindConfig(
                                binding="lights.kitchen", attribute="is_on"
                            ),
                        ),
                    ],
                )
            ],
        )
        controller = DeckboardController(deck, mgr, config)
        await controller.setup()
        callback = mock_binding._subscribers["is_on"][0]
        await callback("is_on", True)
        key = deck.screen.return_value.key.return_value
        key.set_icon.assert_called_with("mdi:circle", color="#FFD700")


# ---------------------------------------------------------------------------
# Encoder building and callbacks
# ---------------------------------------------------------------------------


class TestBuildEncoder:
    async def test_encoder_with_turn_and_press(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        config = DeckConfig(
            screens=[
                ScreenConfig(
                    name="main",
                    encoders=[
                        EncoderConfig(
                            index=0,
                            on_turn=ActionConfig(
                                binding="lights.kitchen", action="brightness_up"
                            ),
                            on_press=ActionConfig(
                                binding="lights.kitchen", action="toggle"
                            ),
                        ),
                    ],
                )
            ],
        )
        controller = DeckboardController(deck, mgr, config)
        await controller.setup()
        screen = deck.screen.return_value
        encoder = screen.encoder.return_value
        encoder.on_turn.assert_called_once()
        encoder.on_press.assert_called_once()

    async def test_encoder_turn_callback_up(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        captured = {}
        enc = deck.screen.return_value.encoder.return_value
        enc.on_turn = MagicMock(side_effect=lambda fn: captured.__setitem__("turn", fn))
        config = DeckConfig(
            screens=[
                ScreenConfig(
                    name="main",
                    encoders=[
                        EncoderConfig(
                            index=0,
                            on_turn=ActionConfig(
                                binding="lights.kitchen", action="brightness_up"
                            ),
                        ),
                    ],
                )
            ],
        )
        controller = DeckboardController(deck, mgr, config)
        await controller.setup()
        fn = captured["turn"]
        # Positive direction with _up -> stays _up
        await fn(1)
        mgr.execute_action.assert_called_with(
            "lights.kitchen", "brightness_up", {"direction": 1}
        )

    async def test_encoder_turn_callback_down_swaps(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        captured = {}
        enc = deck.screen.return_value.encoder.return_value
        enc.on_turn = MagicMock(side_effect=lambda fn: captured.__setitem__("turn", fn))
        config = DeckConfig(
            screens=[
                ScreenConfig(
                    name="main",
                    encoders=[
                        EncoderConfig(
                            index=0,
                            on_turn=ActionConfig(
                                binding="lights.kitchen", action="brightness_up"
                            ),
                        ),
                    ],
                )
            ],
        )
        controller = DeckboardController(deck, mgr, config)
        await controller.setup()
        fn = captured["turn"]
        # Negative direction with _up -> swaps to _down
        await fn(-1)
        mgr.execute_action.assert_called_with(
            "lights.kitchen", "brightness_down", {"direction": -1}
        )

    async def test_encoder_turn_callback_down_to_up_swap(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        captured = {}
        enc = deck.screen.return_value.encoder.return_value
        enc.on_turn = MagicMock(side_effect=lambda fn: captured.__setitem__("turn", fn))
        config = DeckConfig(
            screens=[
                ScreenConfig(
                    name="main",
                    encoders=[
                        EncoderConfig(
                            index=0,
                            on_turn=ActionConfig(
                                binding="lights.kitchen", action="brightness_down"
                            ),
                        ),
                    ],
                )
            ],
        )
        controller = DeckboardController(deck, mgr, config)
        await controller.setup()
        fn = captured["turn"]
        # Positive direction with _down -> swaps to _up
        await fn(1)
        mgr.execute_action.assert_called_with(
            "lights.kitchen", "brightness_up", {"direction": 1}
        )

    async def test_encoder_turn_no_swap_neutral(self) -> None:
        """Action name without _up or _down should remain unchanged."""
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        captured = {}
        enc = deck.screen.return_value.encoder.return_value
        enc.on_turn = MagicMock(side_effect=lambda fn: captured.__setitem__("turn", fn))
        config = DeckConfig(
            screens=[
                ScreenConfig(
                    name="main",
                    encoders=[
                        EncoderConfig(
                            index=0,
                            on_turn=ActionConfig(
                                binding="lights.kitchen", action="toggle"
                            ),
                        ),
                    ],
                )
            ],
        )
        controller = DeckboardController(deck, mgr, config)
        await controller.setup()
        fn = captured["turn"]
        await fn(-1)
        mgr.execute_action.assert_called_with(
            "lights.kitchen", "toggle", {"direction": -1}
        )

    async def test_encoder_press_callback(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        captured = {}
        enc = deck.screen.return_value.encoder.return_value
        enc.on_press = MagicMock(
            side_effect=lambda fn: captured.__setitem__("press", fn)
        )
        config = DeckConfig(
            screens=[
                ScreenConfig(
                    name="main",
                    encoders=[
                        EncoderConfig(
                            index=0,
                            on_press=ActionConfig(
                                binding="lights.kitchen", action="toggle"
                            ),
                        ),
                    ],
                )
            ],
        )
        controller = DeckboardController(deck, mgr, config)
        await controller.setup()
        fn = captured["press"]
        await fn()
        mgr.execute_action.assert_called_with("lights.kitchen", "toggle", {})


# ---------------------------------------------------------------------------
# Card building and callbacks
# ---------------------------------------------------------------------------


class TestBuildCard:
    async def test_status_card(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        config = DeckConfig(
            screens=[
                ScreenConfig(
                    name="main",
                    cards=[
                        CardConfig(
                            index=0, type="status", icon="mdi:info", label="Status"
                        ),
                    ],
                )
            ],
        )
        controller = DeckboardController(deck, mgr, config)
        await controller.setup()
        card = deck.screen.return_value.card.return_value
        card.set_icon.assert_called_with("mdi:info")
        card.set_label.assert_called_with("Status")

    async def test_status_card_value_bind_callback(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        from deckboard_homeassistant.adapters.light import LightAdapter

        mock_binding = Binding(
            key="lights.kitchen", entity_id="light.kitchen", adapter=LightAdapter()
        )
        mgr.get = MagicMock(return_value=mock_binding)
        config = DeckConfig(
            screens=[
                ScreenConfig(
                    name="main",
                    cards=[
                        CardConfig(
                            index=0,
                            type="status",
                            value_bind=StateBindConfig(
                                binding="lights.kitchen", attribute="brightness_pct"
                            ),
                        ),
                    ],
                )
            ],
        )
        controller = DeckboardController(deck, mgr, config)
        await controller.setup()

        callback = mock_binding._subscribers["brightness_pct"][0]
        card = deck.screen.return_value.card.return_value

        await callback("brightness_pct", 75)
        card.set_value.assert_called_with("75")

        await callback("brightness_pct", None)
        card.set_value.assert_called_with("")

    async def test_status_card_tap_callback(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        captured = {}
        card = deck.screen.return_value.card.return_value
        card.on_tap = MagicMock(side_effect=lambda fn: captured.__setitem__("tap", fn))
        config = DeckConfig(
            screens=[
                ScreenConfig(
                    name="main",
                    cards=[
                        CardConfig(
                            index=0,
                            type="status",
                            on_tap=ActionConfig(
                                binding="lights.kitchen", action="toggle"
                            ),
                        ),
                    ],
                )
            ],
        )
        controller = DeckboardController(deck, mgr, config)
        await controller.setup()
        fn = captured["tap"]
        await fn()
        mgr.execute_action.assert_called_with("lights.kitchen", "toggle", {})

    async def test_light_card_callbacks(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        from deckboard_homeassistant.adapters.light import LightAdapter

        mock_binding = Binding(
            key="lights.kitchen", entity_id="light.kitchen", adapter=LightAdapter()
        )
        mgr.get = MagicMock(return_value=mock_binding)
        config = DeckConfig(
            screens=[
                ScreenConfig(
                    name="main",
                    cards=[
                        CardConfig(index=0, type="light", binding="lights.kitchen"),
                    ],
                )
            ],
        )
        with patch("deckboard_homeassistant.controller.LightCard") as MockLC:
            mock_lc = MagicMock()
            mock_lc.brightness = MagicMock()
            mock_lc.brightness.on_change = MagicMock(side_effect=lambda fn: fn)
            mock_lc.kelvin = MagicMock()
            mock_lc.kelvin.on_change = MagicMock(side_effect=lambda fn: fn)
            mock_lc.kelvin.max_value = 6500.0
            mock_lc.kelvin.min_value = 2000.0
            mock_lc.on_tap = MagicMock(side_effect=lambda fn: fn)
            MockLC.return_value = mock_lc

            controller = DeckboardController(deck, mgr, config)
            await controller.setup()

            # Test state callbacks.
            brightness_cb = mock_binding._subscribers["brightness_pct"][0]
            await brightness_cb("brightness_pct", 50)
            mock_lc.brightness.set_value.assert_called_with(50)

            await brightness_cb(
                "brightness_pct", "not_a_number"
            )  # not int/float -> skip

            kelvin_cb = mock_binding._subscribers["kelvin"][0]
            await kelvin_cb("kelvin", 3500)
            mock_lc.kelvin.set_value.assert_called_with(3500)

            kelvin_min_cb = mock_binding._subscribers["kelvin_min"][0]
            await kelvin_min_cb("kelvin_min", 2200)
            mock_lc.set_kelvin_range.assert_called_with(
                2200.0, mock_lc.kelvin.max_value
            )

            kelvin_max_cb = mock_binding._subscribers["kelvin_max"][0]
            await kelvin_max_cb("kelvin_max", 6000)
            mock_lc.set_kelvin_range.assert_called_with(
                mock_lc.kelvin.min_value, 6000.0
            )

            # Not numeric => skip
            await kelvin_min_cb("kelvin_min", "bad")
            await kelvin_max_cb("kelvin_max", "bad")

    async def test_light_card_ui_callbacks(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        from deckboard_homeassistant.adapters.light import LightAdapter

        mock_binding = Binding(
            key="lights.kitchen", entity_id="light.kitchen", adapter=LightAdapter()
        )
        mgr.get = MagicMock(return_value=mock_binding)
        config = DeckConfig(
            screens=[
                ScreenConfig(
                    name="main",
                    cards=[
                        CardConfig(index=0, type="light", binding="lights.kitchen"),
                    ],
                )
            ],
        )
        captured_brightness = {}
        captured_kelvin = {}
        captured_tap = {}

        with patch("deckboard_homeassistant.controller.LightCard") as MockLC:
            mock_lc = MagicMock()
            mock_lc.brightness = MagicMock()
            mock_lc.brightness.on_change = MagicMock(
                side_effect=lambda fn: captured_brightness.__setitem__("fn", fn)
            )
            mock_lc.kelvin = MagicMock()
            mock_lc.kelvin.on_change = MagicMock(
                side_effect=lambda fn: captured_kelvin.__setitem__("fn", fn)
            )
            mock_lc.on_tap = MagicMock(
                side_effect=lambda fn: captured_tap.__setitem__("fn", fn)
            )
            MockLC.return_value = mock_lc

            controller = DeckboardController(deck, mgr, config)
            await controller.setup()

            # Brightness change callback.
            await captured_brightness["fn"](80.0)
            mgr.execute_action.assert_called_with(
                "lights.kitchen", "set_brightness", {"brightness": 80}
            )

            # Kelvin change callback.
            mgr.execute_action.reset_mock()
            await captured_kelvin["fn"](4000.0)
            mgr.execute_action.assert_called_with(
                "lights.kitchen", "set_kelvin", {"kelvin": 4000}
            )

            # Tap callback.
            mgr.execute_action.reset_mock()
            await captured_tap["fn"]()
            mgr.execute_action.assert_called_with("lights.kitchen", "toggle")

    async def test_light_card_missing_binding(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        mgr.get = MagicMock(return_value=None)
        config = DeckConfig(
            screens=[
                ScreenConfig(
                    name="main",
                    cards=[
                        CardConfig(index=0, type="light", binding="nonexistent"),
                    ],
                )
            ],
        )
        with patch("deckboard_homeassistant.controller.LightCard"):
            controller = DeckboardController(deck, mgr, config)
            await controller.setup()

    async def test_media_card_callbacks(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        from deckboard_homeassistant.adapters.media_player import MediaPlayerAdapter

        mock_binding = Binding(
            key="media.lr", entity_id="media_player.lr", adapter=MediaPlayerAdapter()
        )
        mgr.get = MagicMock(return_value=mock_binding)
        config = DeckConfig(
            screens=[
                ScreenConfig(
                    name="main",
                    cards=[
                        CardConfig(index=0, type="media", binding="media.lr"),
                    ],
                )
            ],
        )
        captured_vol = {}
        captured_tap = {}

        with patch("deckboard_homeassistant.controller.MediaCard") as MockMC:
            mock_mc = MagicMock()
            mock_mc.title_text = MagicMock()
            mock_mc.volume = MagicMock()
            mock_mc.volume.on_change = MagicMock(
                side_effect=lambda fn: captured_vol.__setitem__("fn", fn)
            )
            mock_mc.muted = False
            mock_mc.toggle_mute = MagicMock()
            mock_mc.on_tap = MagicMock(
                side_effect=lambda fn: captured_tap.__setitem__("fn", fn)
            )
            MockMC.return_value = mock_mc

            controller = DeckboardController(deck, mgr, config)
            await controller.setup()

            # Title callback.
            title_cb = mock_binding._subscribers["title"][0]
            await title_cb("title", "Song Name")
            mock_mc.title_text.set_text.assert_called_with("Song Name")

            await title_cb("title", "")
            mock_mc.title_text.set_text.assert_called_with("No Media")

            # Volume callback.
            vol_cb = mock_binding._subscribers["volume_pct"][0]
            await vol_cb("volume_pct", 65)
            mock_mc.volume.set_value.assert_called_with(65)

            await vol_cb("volume_pct", "bad")  # non-numeric: skip

            # Mute callback.
            mute_cb = mock_binding._subscribers["is_muted"][0]
            await mute_cb("is_muted", True)  # value != mock_mc.muted (False)
            mock_mc.toggle_mute.assert_called_once()

            mock_mc.toggle_mute.reset_mock()
            await mute_cb(
                "is_muted", False
            )  # value == mock_mc.muted (False) -> no toggle
            mock_mc.toggle_mute.assert_not_called()

            await mute_cb("is_muted", "not_bool")  # not bool -> skip

            # UI -> HA: volume change.
            await captured_vol["fn"](80.0)
            mgr.execute_action.assert_called_with(
                "media.lr", "set_volume", {"volume": 80}
            )

            # UI -> HA: tap.
            mgr.execute_action.reset_mock()
            await captured_tap["fn"]()
            mgr.execute_action.assert_called_with("media.lr", "play_pause")

    async def test_media_card_missing_binding(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        mgr.get = MagicMock(return_value=None)
        config = DeckConfig(
            screens=[
                ScreenConfig(
                    name="main",
                    cards=[
                        CardConfig(index=0, type="media", binding="nonexistent"),
                    ],
                )
            ],
        )
        with patch("deckboard_homeassistant.controller.MediaCard"):
            controller = DeckboardController(deck, mgr, config)
            await controller.setup()

    async def test_equalizer_card_callbacks(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        from deckboard_homeassistant.adapters.equalizer import EqualizerAdapter

        adapter = EqualizerAdapter()
        adapter._entities = {
            "sub": "n.s",
            "bass": "n.b",
            "treble": "n.t",
            "balance": "n.ba",
        }
        mock_binding = Binding(
            key="audio.eq", entity_id="", adapter=adapter, entities=adapter._entities
        )
        mgr.get = MagicMock(return_value=mock_binding)
        config = DeckConfig(
            screens=[
                ScreenConfig(
                    name="main",
                    cards=[
                        CardConfig(index=0, type="equalizer", binding="audio.eq"),
                    ],
                )
            ],
        )
        captured_slider = {}

        with patch("deckboard_homeassistant.controller.EqualizerCard") as MockEQ:
            mock_eq = MagicMock()
            for attr in ("sub", "bass", "treble", "balance"):
                slider = MagicMock()
                slider.on_change = MagicMock(
                    side_effect=lambda fn, _n=attr: captured_slider.__setitem__(_n, fn)
                )
                slider.max_value = 100.0
                slider.min_value = 0.0
                setattr(mock_eq, attr, slider)
            mock_eq.set_sub_range = MagicMock()
            mock_eq.set_bass_range = MagicMock()
            mock_eq.set_treble_range = MagicMock()
            mock_eq.set_balance_range = MagicMock()
            MockEQ.return_value = mock_eq

            controller = DeckboardController(deck, mgr, config)
            await controller.setup()

            # Test state -> UI callbacks for value/min/max.
            for slot in ("sub", "bass", "treble", "balance"):
                val_cb = mock_binding._subscribers[slot][0]
                await val_cb(slot, 50.0)
                getattr(mock_eq, slot).set_value.assert_called_with(50.0)

                await val_cb(slot, "bad")  # non-numeric, skip

                min_cb = mock_binding._subscribers[f"{slot}_min"][0]
                await min_cb(f"{slot}_min", 10.0)

                max_cb = mock_binding._subscribers[f"{slot}_max"][0]
                await max_cb(f"{slot}_max", 90.0)

                await min_cb(f"{slot}_min", "bad")  # non-numeric, skip
                await max_cb(f"{slot}_max", "bad")  # non-numeric, skip

            # Test UI -> HA slider change.
            await captured_slider["sub"](25.0)
            mgr.execute_action.assert_called_with(
                "audio.eq", "set_sub", {"value": 25.0}
            )

    async def test_equalizer_card_missing_binding(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        mgr.get = MagicMock(return_value=None)
        config = DeckConfig(
            screens=[
                ScreenConfig(
                    name="main",
                    cards=[
                        CardConfig(index=0, type="equalizer", binding="nonexistent"),
                    ],
                )
            ],
        )
        with patch("deckboard_homeassistant.controller.EqualizerCard"):
            controller = DeckboardController(deck, mgr, config)
            await controller.setup()

    async def test_ha_media_card_callbacks(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        from deckboard_homeassistant.adapters.media_player import MediaPlayerAdapter

        mock_binding = Binding(
            key="media.lr", entity_id="media_player.lr", adapter=MediaPlayerAdapter()
        )
        mgr.get = MagicMock(return_value=mock_binding)
        config = DeckConfig(
            homeassistant=HomeAssistantConfig(url="http://ha:8123", token="test-token"),
            screens=[
                ScreenConfig(
                    name="main",
                    cards=[
                        CardConfig(index=0, type="ha_media", binding="media.lr"),
                    ],
                )
            ],
        )
        captured_vol = {}
        captured_mute = {}
        captured_play = {}
        captured_tap = {}

        with patch("deckboard_homeassistant.controller.HaMediaCard") as MockHMC:
            mock_hmc = MagicMock()
            mock_hmc.muted = False
            mock_hmc.entity_picture = None
            mock_hmc.set_artist = MagicMock()
            mock_hmc.set_title = MagicMock()
            mock_hmc.set_state = MagicMock()
            mock_hmc.set_volume = MagicMock()
            mock_hmc.set_muted = MagicMock()
            mock_hmc.set_entity_picture = MagicMock()
            mock_hmc.on_volume_change = MagicMock(
                side_effect=lambda fn: captured_vol.__setitem__("fn", fn)
            )
            mock_hmc.on_mute_toggle = MagicMock(
                side_effect=lambda fn: captured_mute.__setitem__("fn", fn)
            )
            mock_hmc.on_play_pause_toggle = MagicMock(
                side_effect=lambda fn: captured_play.__setitem__("fn", fn)
            )
            mock_hmc.on_tap = MagicMock(
                side_effect=lambda fn: captured_tap.__setitem__("fn", fn)
            )
            MockHMC.return_value = mock_hmc

            controller = DeckboardController(deck, mgr, config)
            await controller.setup()

            # Test state -> UI callbacks.
            artist_cb = mock_binding._subscribers["artist"][0]
            await artist_cb("artist", "Artist Name")
            mock_hmc.set_artist.assert_called_with("Artist Name")
            await artist_cb("artist", "")
            mock_hmc.set_artist.assert_called_with("")

            title_cb = mock_binding._subscribers["title"][0]
            await title_cb("title", "Song")
            mock_hmc.set_title.assert_called_with("Song")
            await title_cb("title", "")
            mock_hmc.set_title.assert_called_with("No Media")

            playing_cb = mock_binding._subscribers["is_playing"][0]
            await playing_cb("is_playing", True)
            mock_hmc.set_state.assert_called_with("Playing")
            await playing_cb("is_playing", False)
            mock_hmc.set_state.assert_called_with("Paused")
            await playing_cb("is_playing", "not_bool")  # skip

            vol_cb = mock_binding._subscribers["volume_pct"][0]
            await vol_cb("volume_pct", 65)
            mock_hmc.set_volume.assert_called_with(65.0)
            await vol_cb("volume_pct", "bad")  # skip

            mute_cb = mock_binding._subscribers["is_muted"][0]
            await mute_cb("is_muted", True)  # value != muted (False)
            mock_hmc.set_muted.assert_called_with(True)
            mock_hmc.set_muted.reset_mock()
            await mute_cb("is_muted", False)  # value == muted (False) -> skip
            mock_hmc.set_muted.assert_not_called()
            await mute_cb("is_muted", "not_bool")  # not bool -> skip

            # Test entity_picture callback.
            pic_cb = mock_binding._subscribers["entity_picture"][0]

            with patch(
                "deckboard_homeassistant.controller.aiohttp.ClientSession"
            ) as MockSession:
                mock_resp = AsyncMock()
                mock_resp.status = 200
                mock_resp.read = AsyncMock(
                    return_value=b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
                )
                mock_ctx = AsyncMock()
                mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
                mock_ctx.__aexit__ = AsyncMock(return_value=None)
                mock_session_inst = AsyncMock()
                mock_session_inst.get = MagicMock(return_value=mock_ctx)
                mock_session_inst.__aenter__ = AsyncMock(return_value=mock_session_inst)
                mock_session_inst.__aexit__ = AsyncMock(return_value=None)
                MockSession.return_value = mock_session_inst

                with patch("deckboard_homeassistant.controller.Image.open") as MockOpen:
                    mock_image = MagicMock()
                    MockOpen.return_value = mock_image

                    await pic_cb("entity_picture", "/api/media/art.jpg")
                    mock_hmc.set_entity_picture.assert_called_with(mock_image)

                    # Same URL -> skip
                    mock_hmc.set_entity_picture.reset_mock()
                    await pic_cb("entity_picture", "/api/media/art.jpg")
                    mock_hmc.set_entity_picture.assert_not_called()

            # Empty URL with existing picture -> clear
            mock_hmc.entity_picture = MagicMock()  # non-None
            await pic_cb("entity_picture", "")
            mock_hmc.set_entity_picture.assert_called_with(None)

            # Empty URL with no picture -> skip
            mock_hmc.entity_picture = None
            mock_hmc.set_entity_picture.reset_mock()
            await pic_cb("entity_picture", "")
            # Should have been called (to set None) only if entity_picture was not None.
            # Already None => skip.

            # Test UI -> HA callbacks.
            await captured_vol["fn"](70.0)
            mgr.execute_action.assert_called_with(
                "media.lr", "set_volume", {"volume": 70}
            )

            mgr.execute_action.reset_mock()
            await captured_mute["fn"](True)
            mgr.execute_action.assert_called_with("media.lr", "mute_toggle")

            mgr.execute_action.reset_mock()
            await captured_play["fn"](True)
            mgr.execute_action.assert_called_with("media.lr", "play_pause")

            mgr.execute_action.reset_mock()
            await captured_tap["fn"]()
            mgr.execute_action.assert_called_with("media.lr", "play_pause")

    async def test_ha_media_card_fetch_error(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        from deckboard_homeassistant.adapters.media_player import MediaPlayerAdapter

        mock_binding = Binding(
            key="media.lr", entity_id="media_player.lr", adapter=MediaPlayerAdapter()
        )
        mgr.get = MagicMock(return_value=mock_binding)
        config = DeckConfig(
            homeassistant=HomeAssistantConfig(url="http://ha:8123", token="test-token"),
            screens=[
                ScreenConfig(
                    name="main",
                    cards=[
                        CardConfig(index=0, type="ha_media", binding="media.lr"),
                    ],
                )
            ],
        )
        with patch("deckboard_homeassistant.controller.HaMediaCard") as MockHMC:
            mock_hmc = MagicMock()
            mock_hmc.muted = False
            mock_hmc.entity_picture = None
            mock_hmc.set_entity_picture = MagicMock()
            mock_hmc.on_volume_change = MagicMock(side_effect=lambda fn: fn)
            mock_hmc.on_mute_toggle = MagicMock(side_effect=lambda fn: fn)
            mock_hmc.on_play_pause_toggle = MagicMock(side_effect=lambda fn: fn)
            mock_hmc.on_tap = MagicMock(side_effect=lambda fn: fn)
            MockHMC.return_value = mock_hmc

            controller = DeckboardController(deck, mgr, config)
            await controller.setup()

            pic_cb = mock_binding._subscribers["entity_picture"][0]

            # Test HTTP error (non-200 status).
            with patch(
                "deckboard_homeassistant.controller.aiohttp.ClientSession"
            ) as MockSession:
                mock_resp = AsyncMock()
                mock_resp.status = 404
                mock_ctx = AsyncMock()
                mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
                mock_ctx.__aexit__ = AsyncMock(return_value=None)
                mock_session_inst = AsyncMock()
                mock_session_inst.get = MagicMock(return_value=mock_ctx)
                mock_session_inst.__aenter__ = AsyncMock(return_value=mock_session_inst)
                mock_session_inst.__aexit__ = AsyncMock(return_value=None)
                MockSession.return_value = mock_session_inst

                await pic_cb("entity_picture", "/api/media/missing.jpg")
                mock_hmc.set_entity_picture.assert_called_with(None)

    async def test_ha_media_card_fetch_exception(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        from deckboard_homeassistant.adapters.media_player import MediaPlayerAdapter

        mock_binding = Binding(
            key="media.lr", entity_id="media_player.lr", adapter=MediaPlayerAdapter()
        )
        mgr.get = MagicMock(return_value=mock_binding)
        config = DeckConfig(
            homeassistant=HomeAssistantConfig(url="http://ha:8123", token="test-token"),
            screens=[
                ScreenConfig(
                    name="main",
                    cards=[
                        CardConfig(index=0, type="ha_media", binding="media.lr"),
                    ],
                )
            ],
        )
        with patch("deckboard_homeassistant.controller.HaMediaCard") as MockHMC:
            mock_hmc = MagicMock()
            mock_hmc.muted = False
            mock_hmc.entity_picture = None
            mock_hmc.set_entity_picture = MagicMock()
            mock_hmc.on_volume_change = MagicMock(side_effect=lambda fn: fn)
            mock_hmc.on_mute_toggle = MagicMock(side_effect=lambda fn: fn)
            mock_hmc.on_play_pause_toggle = MagicMock(side_effect=lambda fn: fn)
            mock_hmc.on_tap = MagicMock(side_effect=lambda fn: fn)
            MockHMC.return_value = mock_hmc

            controller = DeckboardController(deck, mgr, config)
            await controller.setup()

            pic_cb = mock_binding._subscribers["entity_picture"][0]

            # Test exception during fetch.
            with patch(
                "deckboard_homeassistant.controller.aiohttp.ClientSession"
            ) as MockSession:
                MockSession.side_effect = Exception("Network error")
                await pic_cb("entity_picture", "/api/media/err.jpg")
                mock_hmc.set_entity_picture.assert_called_with(None)

    async def test_ha_media_card_missing_binding(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        mgr.get = MagicMock(return_value=None)
        config = DeckConfig(
            screens=[
                ScreenConfig(
                    name="main",
                    cards=[
                        CardConfig(index=0, type="ha_media", binding="nonexistent"),
                    ],
                )
            ],
        )
        with patch("deckboard_homeassistant.controller.HaMediaCard"):
            controller = DeckboardController(deck, mgr, config)
            await controller.setup()

    async def test_unknown_card_type_falls_to_status(self) -> None:
        deck = _make_mock_deck()
        mgr = _make_mock_binding_manager()
        config = DeckConfig(
            screens=[
                ScreenConfig(
                    name="main",
                    cards=[
                        CardConfig(index=0, type="unknown_type"),
                    ],
                )
            ],
        )
        controller = DeckboardController(deck, mgr, config)
        await controller.setup()
        screen = deck.screen.return_value
        screen.card.assert_called_once_with(0)
