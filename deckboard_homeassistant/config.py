"""Configuration system -- loads and validates YAML configuration.

The configuration defines:
  * **Bindings** -- logical names mapped to HA entities and adapter domains.
  * **Screens** -- named layouts with keys, encoders, and cards.
  * **Keys** -- icon, label, state binding, and press/release actions.
  * **Encoders** -- turn and press actions bound to entities.
  * **Cards** -- touchscreen zone content (preset cards or status cards).

The config is the single source of truth for how the UI connects to HA.
No HA logic is embedded in UI code; everything is declared here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Config dataclasses
# ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ActionConfig:
    """A configured action reference.

    Attributes:
        binding: Logical binding key (e.g. ``"lights.kitchen"``).
        action: Action name (e.g. ``"toggle"``).
        args: Extra arguments passed to the adapter.
    """

    binding: str
    action: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StateBindConfig:
    """A state binding reference for a UI element.

    Attributes:
        binding: Logical binding key.
        attribute: Normalized attribute name (e.g. ``"is_on"``).
    """

    binding: str
    attribute: str


@dataclass(frozen=True, slots=True)
class KeyConfig:
    """Configuration for a single key (button) slot."""

    index: int
    icon: str = ""
    label: str = ""
    state_bind: StateBindConfig | None = None
    on_press: ActionConfig | None = None
    on_release: ActionConfig | None = None


@dataclass(frozen=True, slots=True)
class EncoderConfig:
    """Configuration for a single encoder (dial) slot."""

    index: int
    on_turn: ActionConfig | None = None
    on_press: ActionConfig | None = None


@dataclass(frozen=True, slots=True)
class CardConfig:
    """Configuration for a single touchscreen card zone."""

    index: int
    type: str = "status"  # "status", "light", "media", "equalizer"
    binding: str = ""
    icon: str = ""
    label: str = ""
    # For status cards: optional state bindings for label/value.
    value_bind: StateBindConfig | None = None
    # On-tap action for status/light cards.
    on_tap: ActionConfig | None = None


@dataclass(frozen=True, slots=True)
class ScreenConfig:
    """Configuration for a named screen."""

    name: str
    keys: list[KeyConfig] = field(default_factory=list)
    encoders: list[EncoderConfig] = field(default_factory=list)
    cards: list[CardConfig] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class BindingConfig:
    """Configuration for a single binding."""

    key: str
    entity_id: str
    adapter: str


@dataclass(frozen=True, slots=True)
class DeckConfig:
    """Top-level configuration."""

    bindings: list[BindingConfig] = field(default_factory=list)
    screens: list[ScreenConfig] = field(default_factory=list)
    device_type: str = "Stream Deck +"
    device_index: int = 0
    brightness: int = 80


# ------------------------------------------------------------------
# Parsing
# ------------------------------------------------------------------


def _parse_action(raw: str | dict[str, Any] | None) -> ActionConfig | None:
    """Parse an action from config.

    Accepted formats:
        ``"lights.kitchen.toggle"``  -- shorthand string
        ``{"binding": "lights.kitchen", "action": "toggle", "step": 10}``
    """
    if raw is None:
        return None

    if isinstance(raw, str):
        # Split "binding_key.action_name" on last dot.
        parts = raw.rsplit(".", 1)
        if len(parts) != 2:
            log.warning("Invalid action shorthand: %r", raw)
            return None
        return ActionConfig(binding=parts[0], action=parts[1])

    if isinstance(raw, dict):
        binding = raw.get("binding", "")
        action = raw.get("action", "")
        args = {k: v for k, v in raw.items() if k not in ("binding", "action")}
        return ActionConfig(binding=binding, action=action, args=args)

    return None


def _parse_state_bind(raw: str | dict[str, Any] | None) -> StateBindConfig | None:
    """Parse a state binding.

    Accepted formats:
        ``"lights.kitchen.is_on"``  -- shorthand
        ``{"binding": "lights.kitchen", "attribute": "is_on"}``
    """
    if raw is None:
        return None

    if isinstance(raw, str):
        parts = raw.rsplit(".", 1)
        if len(parts) != 2:
            log.warning("Invalid state bind shorthand: %r", raw)
            return None
        return StateBindConfig(binding=parts[0], attribute=parts[1])

    if isinstance(raw, dict):
        return StateBindConfig(
            binding=raw.get("binding", ""),
            attribute=raw.get("attribute", ""),
        )

    return None


def _parse_key(index: int, raw: dict[str, Any]) -> KeyConfig:
    return KeyConfig(
        index=index,
        icon=raw.get("icon", ""),
        label=raw.get("label", ""),
        state_bind=_parse_state_bind(raw.get("bind", {}).get("state")),
        on_press=_parse_action(raw.get("actions", {}).get("press")),
        on_release=_parse_action(raw.get("actions", {}).get("release")),
    )


def _parse_encoder(index: int, raw: dict[str, Any]) -> EncoderConfig:
    return EncoderConfig(
        index=index,
        on_turn=_parse_action(raw.get("actions", {}).get("turn")),
        on_press=_parse_action(raw.get("actions", {}).get("press")),
    )


def _parse_card(index: int, raw: dict[str, Any]) -> CardConfig:
    return CardConfig(
        index=index,
        type=raw.get("type", "status"),
        binding=raw.get("binding", ""),
        icon=raw.get("icon", ""),
        label=raw.get("label", ""),
        value_bind=_parse_state_bind(raw.get("bind", {}).get("value")),
        on_tap=_parse_action(raw.get("actions", {}).get("tap")),
    )


def _parse_screen(name: str, raw: dict[str, Any]) -> ScreenConfig:
    keys = [_parse_key(int(idx), cfg) for idx, cfg in raw.get("keys", {}).items()]
    encoders = [
        _parse_encoder(int(idx), cfg) for idx, cfg in raw.get("encoders", {}).items()
    ]
    cards = [_parse_card(int(idx), cfg) for idx, cfg in raw.get("cards", {}).items()]
    return ScreenConfig(name=name, keys=keys, encoders=encoders, cards=cards)


def _parse_binding(key: str, raw: dict[str, Any]) -> BindingConfig:
    return BindingConfig(
        key=key,
        entity_id=raw.get("entity", ""),
        adapter=raw.get("adapter", ""),
    )


def load_config(path: str | Path) -> DeckConfig:
    """Load and parse a YAML configuration file.

    Parameters:
        path: Path to the YAML config file.

    Returns:
        Parsed :class:`DeckConfig`.
    """
    path = Path(path)
    with path.open() as f:
        raw = yaml.safe_load(f) or {}

    bindings = [
        _parse_binding(key, cfg) for key, cfg in raw.get("bindings", {}).items()
    ]

    screens = [_parse_screen(name, cfg) for name, cfg in raw.get("screens", {}).items()]

    device = raw.get("device", {})

    return DeckConfig(
        bindings=bindings,
        screens=screens,
        device_type=device.get("type", "Stream Deck +"),
        device_index=device.get("index", 0),
        brightness=device.get("brightness", 80),
    )
