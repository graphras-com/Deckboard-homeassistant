# Deckboard Home Assistant

Home Assistant integration for the [Deckboard](https://github.com/graphras-com/Deckboard) Stream Deck UI library. Control your smart home entities -- lights, media players, and more -- using an Elgato Stream Deck+.

## Features

- **Bidirectional sync** -- Home Assistant state changes update the Stream Deck display in real time, and physical interactions trigger HA service calls.
- **YAML-driven configuration** -- Declaratively map HA entities to keys, rotary encoders, and touchscreen cards.
- **Domain adapters** -- Built-in adapters for lights and media players normalize state and resolve actions. Extensible to new domains.
- **Clean architecture** -- Abstract interfaces (`StateProvider`, `CommandBus`) decouple the HA backend from the UI layer. The entire backend can be swapped without touching UI code.
- **Standalone mock mode** -- Run locally with sample data for development and testing, no Home Assistant required.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- Elgato Stream Deck+ (connected via USB)
- System libraries: `libcairo`, `libusb`/`hidapi` (for SVG rendering and Stream Deck communication)
- For production: [Home Assistant](https://www.home-assistant.io/) with [AppDaemon](https://appdaemon.readthedocs.io/) installed

## Installation

```bash
git clone git@github.com:graphras-com/Deckboard-homeassistant.git
cd Deckboard-homeassistant
uv sync
```

## Usage

### Standalone (development / testing)

Run with mock data -- no Home Assistant needed, but a physical Stream Deck must be connected:

```bash
uv run python main.py
```

Optionally specify a custom config path:

```bash
uv run python main.py path/to/deckboard.yaml
```

### Production (AppDaemon)

1. Install this package in your AppDaemon Python environment.
2. Copy `examples/apps.yaml` to your AppDaemon apps directory (e.g. `/config/appdaemon/apps/`).
3. Create a `deckboard.yaml` configuration file (see `examples/deckboard.yaml` for a full example).
4. Configure `apps.yaml`:

```yaml
deckboard:
  module: deckboard_homeassistant.app
  class: DeckboardApp
  config_path: /config/appdaemon/apps/deckboard.yaml
```

5. Restart AppDaemon. The integration will start automatically.

## Configuration

The configuration file (`deckboard.yaml`) has three sections: **device**, **bindings**, and **screens**.

### Device

```yaml
device:
  type: "Stream Deck +"
  index: 0          # Device index if multiple decks are connected
  brightness: 80    # Display brightness (0-100)
```

### Bindings

Map logical names to Home Assistant entities and a domain adapter:

```yaml
bindings:
  lights.kitchen:
    entity: light.kitchen
    adapter: light

  media.living_room:
    entity: media_player.living_room
    adapter: media_player
```

### Screens

Define UI layouts with keys, encoders, and touchscreen cards. Actions and state bindings reference the logical names from `bindings`.

```yaml
screens:
  home:
    keys:
      0:
        icon: mdi:lightbulb
        label: Kitchen
        bind:
          state: lights.kitchen.is_on
        actions:
          press: lights.kitchen.toggle

    encoders:
      0:
        actions:
          turn:
            binding: lights.kitchen
            action: brightness_up
            step: 5
          press: lights.kitchen.toggle

    cards:
      0:
        type: light
        binding: lights.kitchen
```

Actions support shorthand strings (`"lights.kitchen.toggle"`) or full dicts with parameters.

### Available adapters

**Light** (`adapter: light`)
- State: `is_on`, `brightness_pct`, `kelvin`, `color_name`
- Actions: `toggle`, `turn_on`, `turn_off`, `set_brightness`, `brightness_up`, `brightness_down`, `set_kelvin`

**Media Player** (`adapter: media_player`)
- State: `is_playing`, `is_on`, `volume_pct`, `is_muted`, `title`, `artist`, `media_type`, `source`
- Actions: `play_pause`, `play`, `pause`, `stop`, `next_track`, `previous_track`, `volume_up`, `volume_down`, `set_volume`, `mute_toggle`, `set_source`

## Running tests

```bash
uv sync --extra dev
uv run pytest
```

## License

See [LICENSE](LICENSE) for details.
