"""Domain adapters for normalizing Home Assistant state and actions.

Each adapter translates between HA's raw entity state/services and clean,
UI-friendly values and action names.  The adapter registry maps domain names
(e.g. ``"light"``, ``"media_player"``, ``"climate"``) to adapter instances.

Multi-entity adapters (subclasses of :class:`MultiEntityAdapter`) handle
bindings that map multiple named entity slots to a single adapter.
"""

from deckboard_homeassistant.adapters.base import DomainAdapter, MultiEntityAdapter
from deckboard_homeassistant.adapters.climate import ClimateAdapter
from deckboard_homeassistant.adapters.equalizer import EqualizerAdapter
from deckboard_homeassistant.adapters.light import LightAdapter
from deckboard_homeassistant.adapters.media_player import MediaPlayerAdapter

_REGISTRY: dict[str, type[DomainAdapter]] = {
    "light": LightAdapter,
    "media_player": MediaPlayerAdapter,
    "climate": ClimateAdapter,
    "equalizer": EqualizerAdapter,
}


def get_adapter(domain: str) -> DomainAdapter:
    """Return an adapter instance for *domain*.

    Raises ``KeyError`` if no adapter is registered for the domain.
    """
    cls = _REGISTRY[domain]
    return cls()


def register_adapter(domain: str, adapter_cls: type[DomainAdapter]) -> None:
    """Register a custom adapter for *domain*."""
    _REGISTRY[domain] = adapter_cls


__all__ = [
    "ClimateAdapter",
    "DomainAdapter",
    "EqualizerAdapter",
    "LightAdapter",
    "MediaPlayerAdapter",
    "MultiEntityAdapter",
    "get_adapter",
    "register_adapter",
]
