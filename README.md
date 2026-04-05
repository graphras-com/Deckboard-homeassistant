# Deckboard Home Assistant

Standalone Home Assistant integration for the [Deckboard](https://github.com/graphras-com/Deckboard) Stream Deck UI library. Control your smart home -- lights, media players, climate, and more -- using an Elgato Stream Deck+ connected to a Raspberry Pi.

## Architecture

```
┌─────────────────────────────┐          ┌──────────────────────┐
│  Raspberry Pi               │          │  Home Assistant       │
│                             │  network │  (separate machine)   │
│  Stream Deck+ ←USB→ Deckboard ←──WS──→ WebSocket API        │
│                             │          │                      │
│  main.py (asyncio daemon)   │          │  Entities / Services │
│   ├─ HomeAssistantClient    │          └──────────────────────┘
│   ├─ HomeAssistantBridge    │
│   ├─ BindingManager         │
│   ├─ DeckboardController    │
│   └─ Adapters (light, media,│
│      climate)               │
└─────────────────────────────┘
```

The application runs as a standalone asyncio service on the Raspberry Pi. It opens the Stream Deck device locally via USB, connects to Home Assistant over the network via WebSocket, and keeps the UI synchronized with HA entity state in real time.

## Features

- **Standalone edge device** -- runs directly on a Raspberry Pi, no AppDaemon or HA add-ons required.
- **WebSocket API** -- authenticates with a long-lived access token, subscribes to state changes, calls services.
- **Automatic reconnect** -- handles HA restarts, network interruptions, and unavailability at startup.
- **Bidirectional sync** -- HA state changes update the Stream Deck display; physical interactions trigger HA service calls.
- **YAML-driven configuration** -- declaratively map HA entities to keys, rotary encoders, and touchscreen cards.
- **Domain adapters** -- built-in adapters for lights, media players, and climate normalize state and resolve actions. Extensible to new domains.
- **Clean architecture** -- abstract interfaces (`StateProvider`, `CommandBus`) decouple the HA backend from the UI layer.
- **systemd ready** -- ships with a service unit for production deployment.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- Elgato Stream Deck+ connected via USB
- System libraries: `libcairo`, `libusb`/`hidapi` (for SVG rendering and Stream Deck communication)
- A running [Home Assistant](https://www.home-assistant.io/) instance accessible over the network
- A Home Assistant [long-lived access token](https://developers.home-assistant.io/docs/auth_api/#long-lived-access-token)

## Installation

```bash
git clone git@github.com:graphras-com/Deckboard-homeassistant.git
cd Deckboard-homeassistant
uv sync
```

### Raspberry Pi system dependencies

```bash
sudo apt install libcairo2-dev libusb-1.0-0-dev libhidapi-hidraw0
```

### USB permissions (Raspberry Pi)

Create a udev rule so the service can access the Stream Deck without root:

```bash
sudo tee /etc/udev/rules.d/99-streamdeck.rules << 'EOF'
SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", MODE="0660", GROUP="input"
EOF
sudo udevadm control --reload-rules
sudo usermod -aG input pi
```

Log out and back in for the group change to take effect.

## Configuration

Create a `deckboard.yaml` configuration file. See [`examples/deckboard.yaml`](examples/deckboard.yaml) for a complete example.

### Home Assistant connection

```yaml
homeassistant:
  url: "http://homeassistant.local:8123"
  token_env: "DECKBOARD_HA_TOKEN"       # reads token from this env var
  reconnect_delay_seconds: 5
```

The token is read from the environment variable named by `token_env`. You can also set `token:` directly in the YAML, but environment variables are preferred for secrets.

### Device

```yaml
device:
  type: "Stream Deck +"
  index: 0
  brightness: 80
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

  thermostat.main:
    entity: climate.living_room
    adapter: climate
```

### Screens

Define UI layouts with keys, encoders, and touchscreen cards:

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

**Climate** (`adapter: climate`)
- State: `is_on`, `hvac_mode`, `current_temperature`, `target_temperature`, `fan_mode`, `humidity`
- Actions: `toggle`, `turn_on`, `turn_off`, `set_temperature`, `temperature_up`, `temperature_down`, `set_hvac_mode`, `set_fan_mode`

## Usage

### Running directly

```bash
# Set your HA token
export DECKBOARD_HA_TOKEN="your_long_lived_access_token"

# Run with default config path (deckboard.yaml)
uv run python main.py

# Or specify a config path
uv run python main.py /path/to/deckboard.yaml
```

### Running as a systemd service

1. Copy the example environment file and fill in your token:

```bash
cp examples/env.example .env
# Edit .env and set DECKBOARD_HA_TOKEN
```

2. Install the systemd unit:

```bash
sudo cp examples/deckboard-ha.service /etc/systemd/system/
# Edit the service file to match your paths and user
sudo systemctl daemon-reload
sudo systemctl enable --now deckboard-ha
```

3. Check logs:

```bash
journalctl -u deckboard-ha -f
```

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `DECKBOARD_HA_TOKEN` | *(required)* | Home Assistant long-lived access token |
| `DECKBOARD_CONFIG` | `deckboard.yaml` | Config file path |
| `DECKBOARD_LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

## Project structure

```
deckboard_homeassistant/
    __init__.py          # Package exports
    __main__.py          # python -m support
    client.py            # HA WebSocket client (auth, reconnect, state, services)
    bridge.py            # StateProvider + CommandBus backed by the WS client
    bindings.py          # Logical name -> entity wiring with normalized state
    controller.py        # Config -> Deckboard UI orchestration
    config.py            # YAML config loader and dataclasses
    interfaces.py        # Abstract interfaces (Action, StateProvider, CommandBus)
    adapters/
        __init__.py      # Adapter registry
        base.py          # DomainAdapter ABC + ResolvedAction
        light.py         # Light adapter
        media_player.py  # Media player adapter
        climate.py       # Climate adapter
main.py                  # Standalone asyncio entrypoint
examples/
    deckboard.yaml       # Full config example
    deckboard-ha.service # systemd unit
    env.example          # Environment variable template
```

## Runtime behavior

- **HA unavailable at startup** -- the service retries connection on a configurable interval until HA is reachable.
- **HA restart / network interruption** -- the WebSocket client detects the drop, clears pending requests, waits, then reconnects and rebuilds the state cache.
- **State cache rebuild** -- after every reconnect, all entity states are re-fetched and pushed to the UI.
- **Graceful shutdown** -- SIGINT/SIGTERM closes the Stream Deck device and WebSocket connection cleanly.

## Running tests

```bash
uv sync --extra dev
uv run pytest
```

## License

See [LICENSE](LICENSE) for details.
