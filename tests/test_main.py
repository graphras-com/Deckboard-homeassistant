"""Tests for main.py."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from main import _load_env_file, main, run


# ---------------------------------------------------------------------------
# _load_env_file
# ---------------------------------------------------------------------------


class TestLoadEnvFile:
    def test_loads_env_file_from_config_dir(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_VAR_LOAD=hello\n")
        config_path = str(tmp_path / "config.yaml")
        os.environ.pop("TEST_VAR_LOAD", None)
        _load_env_file(config_path)
        assert os.environ.get("TEST_VAR_LOAD") == "hello"
        os.environ.pop("TEST_VAR_LOAD", None)

    def test_does_not_override_existing_env(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("EXISTING_VAR=new_value\n")
        config_path = str(tmp_path / "config.yaml")
        os.environ["EXISTING_VAR"] = "original"
        try:
            _load_env_file(config_path)
            assert os.environ["EXISTING_VAR"] == "original"
        finally:
            os.environ.pop("EXISTING_VAR", None)

    def test_skips_comments_and_blanks(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("# Comment\n\nVALID_VAR=yes\n")
        config_path = str(tmp_path / "config.yaml")
        os.environ.pop("VALID_VAR", None)
        _load_env_file(config_path)
        assert os.environ.get("VALID_VAR") == "yes"
        os.environ.pop("VALID_VAR", None)

    def test_skips_lines_without_equals(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("NOEQUALSSIGN\nGOOD_VAR=value\n")
        config_path = str(tmp_path / "config.yaml")
        os.environ.pop("GOOD_VAR", None)
        _load_env_file(config_path)
        assert os.environ.get("GOOD_VAR") == "value"
        assert "NOEQUALSSIGN" not in os.environ
        os.environ.pop("GOOD_VAR", None)

    def test_strips_quotes(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("QUOTED_VAR=\"hello world\"\nSINGLE_Q='value'\n")
        config_path = str(tmp_path / "config.yaml")
        os.environ.pop("QUOTED_VAR", None)
        os.environ.pop("SINGLE_Q", None)
        _load_env_file(config_path)
        assert os.environ.get("QUOTED_VAR") == "hello world"
        assert os.environ.get("SINGLE_Q") == "value"
        os.environ.pop("QUOTED_VAR", None)
        os.environ.pop("SINGLE_Q", None)

    def test_no_env_file(self, tmp_path: Path) -> None:
        config_path = str(tmp_path / "config.yaml")
        with patch.object(Path, "cwd", return_value=tmp_path / "nonexistent"):
            _load_env_file(config_path)

    def test_falls_back_to_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_dir = tmp_path / "config_dir"
        config_dir.mkdir()
        config_path = str(config_dir / "config.yaml")
        cwd_env = tmp_path / ".env"
        cwd_env.write_text("CWD_VAR=from_cwd\n")
        os.environ.pop("CWD_VAR", None)
        monkeypatch.chdir(tmp_path)
        _load_env_file(config_path)
        assert os.environ.get("CWD_VAR") == "from_cwd"
        os.environ.pop("CWD_VAR", None)

    def test_only_loads_first_env_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("FIRST_ENV=config_dir\n")
        config_path = str(tmp_path / "config.yaml")
        monkeypatch.chdir(tmp_path)
        os.environ.pop("FIRST_ENV", None)
        _load_env_file(config_path)
        assert os.environ.get("FIRST_ENV") == "config_dir"
        os.environ.pop("FIRST_ENV", None)

    def test_empty_key_skipped(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("=value\nGOOD=yes\n")
        config_path = str(tmp_path / "config.yaml")
        os.environ.pop("GOOD", None)
        _load_env_file(config_path)
        assert "" not in os.environ
        assert os.environ.get("GOOD") == "yes"
        os.environ.pop("GOOD", None)


# ---------------------------------------------------------------------------
# main() function
# ---------------------------------------------------------------------------


class TestMain:
    def test_main_no_config_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["deckboard-ha"])
        monkeypatch.delenv("DECKBOARD_CONFIG", raising=False)
        # No deckboard.yaml exists -> should call sys.exit(1).
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    def test_main_with_argv_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg_file = tmp_path / "test.yaml"
        cfg_file.write_text(yaml.dump({"homeassistant": {"token": "my-token"}}))
        monkeypatch.setattr(sys, "argv", ["deckboard-ha", str(cfg_file)])
        monkeypatch.chdir(tmp_path)

        # Mock asyncio.run to avoid actually running the event loop.
        with patch("main.asyncio.run") as mock_run:
            main()
            mock_run.assert_called_once()

    def test_main_env_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg_file = tmp_path / "custom.yaml"
        cfg_file.write_text(yaml.dump({"homeassistant": {"token": "my-token"}}))
        monkeypatch.setattr(sys, "argv", ["deckboard-ha"])
        monkeypatch.setenv("DECKBOARD_CONFIG", str(cfg_file))
        monkeypatch.chdir(tmp_path)

        with patch("main.asyncio.run") as mock_run:
            main()
            mock_run.assert_called_once()

    def test_main_custom_log_level(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg_file = tmp_path / "test.yaml"
        cfg_file.write_text(yaml.dump({"homeassistant": {"token": "t"}}))
        monkeypatch.setattr(sys, "argv", ["deckboard-ha", str(cfg_file)])
        monkeypatch.setenv("DECKBOARD_LOG_LEVEL", "DEBUG")

        with patch("main.asyncio.run"):
            main()


# ---------------------------------------------------------------------------
# run() function
# ---------------------------------------------------------------------------


class TestRun:
    async def test_run_no_token_exits(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DECKBOARD_HA_TOKEN", raising=False)
        cfg_file = tmp_path / "test.yaml"
        cfg_file.write_text(yaml.dump({}))

        with pytest.raises(SystemExit) as exc_info:
            await run(str(cfg_file))
        assert exc_info.value.code == 1

    async def test_run_full_lifecycle(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DECKBOARD_HA_TOKEN", "test-token")
        config = {
            "homeassistant": {"url": "http://ha:8123"},
            "bindings": {
                "lights.kitchen": {"entity": "light.kitchen", "adapter": "light"},
            },
            "screens": {
                "main": {
                    "keys": {
                        "0": {
                            "icon": "mdi:bulb",
                            "actions": {"press": "lights.kitchen.toggle"},
                        }
                    }
                }
            },
        }
        cfg_file = tmp_path / "test.yaml"
        cfg_file.write_text(yaml.dump(config))

        # Mock all the heavy components.
        mock_client = MagicMock()
        mock_client.connect = AsyncMock()
        mock_client._receiver_task = None
        mock_client.disconnect = AsyncMock()
        mock_client.on_state_changed = MagicMock()
        mock_client.connected = True
        mock_client.get_states = AsyncMock(return_value=[])
        mock_client.call_service = AsyncMock()

        mock_deck = MagicMock()
        mock_deck.__aenter__ = AsyncMock(return_value=mock_deck)
        mock_deck.__aexit__ = AsyncMock(return_value=None)
        mock_deck.set_screen = AsyncMock()
        mock_deck.refresh = AsyncMock()

        # Create minimal screen/key mocks.
        mock_screen = MagicMock()
        mock_key = MagicMock()
        mock_key.set_icon = MagicMock()
        mock_key.set_label = MagicMock()
        mock_key.on_press = MagicMock(side_effect=lambda fn: fn)
        mock_screen.key = MagicMock(return_value=mock_key)
        mock_screen.encoder = MagicMock(return_value=MagicMock())
        mock_screen.card = MagicMock(return_value=MagicMock())
        mock_deck.screen = MagicMock(return_value=mock_screen)

        with (
            patch("main.HomeAssistantClient", return_value=mock_client),
            patch("main.Deck", return_value=mock_deck),
        ):
            # Set shutdown_event immediately so run() finishes.
            original_run = run

            async def patched_run(config_path: str) -> None:
                # Override to set shutdown early.
                import main as main_module

                original_event_class = asyncio.Event

                class AutoSetEvent(asyncio.Event):
                    def __init__(self):
                        super().__init__()

                    async def wait(self):
                        self.set()  # Immediately signal shutdown.

                with patch.object(asyncio, "Event", AutoSetEvent):
                    # We can't easily replace the shutdown_event inside run().
                    # Instead, patch signal handlers to immediately fire.
                    pass

                await original_run(config_path)

            # Just test that run() goes through the lifecycle path.
            # We'll simulate an immediate shutdown by connecting then cancelling.
            run_task = asyncio.create_task(run(str(cfg_file)))
            await asyncio.sleep(0.05)
            run_task.cancel()
            try:
                await run_task
            except asyncio.CancelledError:
                pass

    async def test_run_connection_error_then_shutdown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DECKBOARD_HA_TOKEN", "test-token")
        cfg_file = tmp_path / "test.yaml"
        cfg_file.write_text(yaml.dump({"homeassistant": {"url": "http://ha:8123"}}))

        mock_client = MagicMock()
        mock_client.connect = AsyncMock(side_effect=ConnectionError("refused"))
        mock_client.disconnect = AsyncMock()
        mock_client.on_state_changed = MagicMock()
        mock_client.connected = False
        mock_client._receiver_task = None
        mock_client.get_states = AsyncMock(return_value=[])

        mock_deck = MagicMock()
        mock_deck.__aenter__ = AsyncMock(return_value=mock_deck)
        mock_deck.__aexit__ = AsyncMock(return_value=None)
        mock_deck.set_screen = AsyncMock()
        mock_deck.refresh = AsyncMock()
        mock_deck.screen = MagicMock(return_value=MagicMock())

        with (
            patch("main.HomeAssistantClient", return_value=mock_client),
            patch("main.Deck", return_value=mock_deck),
        ):
            run_task = asyncio.create_task(run(str(cfg_file)))
            await asyncio.sleep(0.05)
            run_task.cancel()
            try:
                await run_task
            except asyncio.CancelledError:
                pass
