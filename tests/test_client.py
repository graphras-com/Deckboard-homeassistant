"""Tests for deckboard_homeassistant.client."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from deckboard_homeassistant.client import HomeAssistantClient


# ---------------------------------------------------------------------------
# Constructor / properties
# ---------------------------------------------------------------------------


class TestClientInit:
    def test_defaults(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "token123")
        assert client._base_url == "http://ha:8123"
        assert client._token == "token123"
        assert client._reconnect_delay == 5.0
        assert client.connected is False

    def test_custom_reconnect(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t", reconnect_delay=10.0)
        assert client._reconnect_delay == 10.0

    def test_url_trailing_slash_stripped(self) -> None:
        client = HomeAssistantClient("http://ha:8123/", "t")
        assert client._base_url == "http://ha:8123"


# ---------------------------------------------------------------------------
# on_state_changed
# ---------------------------------------------------------------------------


class TestOnStateChanged:
    def test_registers_callback(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        cb = AsyncMock()
        client.on_state_changed(cb)
        assert cb in client._state_callbacks


# ---------------------------------------------------------------------------
# _next_id
# ---------------------------------------------------------------------------


class TestNextId:
    def test_auto_increment(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        assert client._next_id() == 1
        assert client._next_id() == 2
        assert client._next_id() == 3


# ---------------------------------------------------------------------------
# _dispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    async def test_result_success(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        client._pending[1] = fut

        await client._dispatch(
            {
                "type": "result",
                "id": 1,
                "success": True,
                "result": [{"entity_id": "light.kitchen"}],
            }
        )

        assert fut.done()
        assert fut.result() == [{"entity_id": "light.kitchen"}]

    async def test_result_failure(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        client._pending[1] = fut

        await client._dispatch(
            {
                "type": "result",
                "id": 1,
                "success": False,
                "error": {"code": "not_found", "message": "Entity not found"},
            }
        )

        assert fut.done()
        with pytest.raises(RuntimeError, match="HA error"):
            fut.result()

    async def test_result_unknown_id(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        # Should not raise.
        await client._dispatch(
            {
                "type": "result",
                "id": 999,
                "success": True,
                "result": None,
            }
        )

    async def test_result_already_done(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        fut.set_result("already")
        client._pending[1] = fut

        # Should not raise (future already resolved).
        await client._dispatch(
            {
                "type": "result",
                "id": 1,
                "success": True,
                "result": "new",
            }
        )
        assert fut.result() == "already"

    async def test_event_state_changed(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        cb = AsyncMock()
        client.on_state_changed(cb)

        await client._dispatch(
            {
                "type": "event",
                "event": {
                    "event_type": "state_changed",
                    "data": {
                        "entity_id": "light.kitchen",
                        "new_state": {"state": "on", "attributes": {}},
                    },
                },
            }
        )

        # The dispatch creates a task; let it run.
        await asyncio.sleep(0.01)
        cb.assert_called_once()

    async def test_event_non_state_changed(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        cb = AsyncMock()
        client.on_state_changed(cb)

        await client._dispatch(
            {
                "type": "event",
                "event": {
                    "event_type": "timer_finished",
                    "data": {},
                },
            }
        )

        await asyncio.sleep(0.01)
        cb.assert_not_called()

    async def test_pong(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        client._pending[5] = fut

        await client._dispatch({"type": "pong", "id": 5})

        assert fut.done()
        assert fut.result() is None

    async def test_pong_unknown_id(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        # Should not raise.
        await client._dispatch({"type": "pong", "id": 999})

    async def test_unknown_type(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        # Should not raise.
        await client._dispatch({"type": "unknown_msg_type"})


# ---------------------------------------------------------------------------
# _handle_state_changed
# ---------------------------------------------------------------------------


class TestHandleStateChanged:
    async def test_invokes_callbacks(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        cb = AsyncMock()
        client.on_state_changed(cb)

        new_state = {"state": "on", "attributes": {}}
        await client._handle_state_changed(
            {
                "entity_id": "light.kitchen",
                "new_state": new_state,
            }
        )

        cb.assert_called_once_with("light.kitchen", new_state)

    async def test_no_new_state(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        cb = AsyncMock()
        client.on_state_changed(cb)

        await client._handle_state_changed(
            {
                "entity_id": "light.kitchen",
                "new_state": None,
            }
        )

        cb.assert_not_called()

    async def test_handles_callback_error(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        cb = AsyncMock(side_effect=RuntimeError("boom"))
        client.on_state_changed(cb)

        # Should not raise.
        await client._handle_state_changed(
            {
                "entity_id": "light.kitchen",
                "new_state": {"state": "on"},
            }
        )

    async def test_empty_entity_id(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        cb = AsyncMock()
        client.on_state_changed(cb)

        await client._handle_state_changed(
            {
                "entity_id": "",
                "new_state": {"state": "on"},
            }
        )
        # Should still call with empty string.
        cb.assert_called_once()


# ---------------------------------------------------------------------------
# get_states / call_service / subscribe_events (require connection)
# ---------------------------------------------------------------------------


class TestRequiresConnection:
    async def test_get_states_not_connected(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        with pytest.raises(ConnectionError):
            await client.get_states()

    async def test_call_service_not_connected(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        with pytest.raises(ConnectionError):
            await client.call_service("light", "toggle")

    async def test_subscribe_events_not_connected(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        with pytest.raises(ConnectionError):
            await client.subscribe_events()


# ---------------------------------------------------------------------------
# _send_command_raw
# ---------------------------------------------------------------------------


class TestSendCommandRaw:
    async def test_not_connected_raises(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        client._ws = None
        with pytest.raises(ConnectionError, match="Not connected"):
            await client._send_command_raw({"type": "test"})

    async def test_ws_closed_raises(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        ws_mock = MagicMock()
        ws_mock.closed = True
        client._ws = ws_mock
        with pytest.raises(ConnectionError, match="Not connected"):
            await client._send_command_raw({"type": "test"})

    async def test_sends_and_receives(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        ws_mock = MagicMock()
        ws_mock.closed = False
        ws_mock.send_json = AsyncMock()
        client._ws = ws_mock

        async def resolve_result():
            await asyncio.sleep(0.01)
            fut = client._pending.get(1)
            if fut and not fut.done():
                fut.set_result("ok")

        task = asyncio.create_task(resolve_result())
        result = await client._send_command_raw({"type": "test"}, timeout=5.0)

        assert result == "ok"
        ws_mock.send_json.assert_called_once()
        sent_msg = ws_mock.send_json.call_args[0][0]
        assert sent_msg["id"] == 1
        assert sent_msg["type"] == "test"
        await task

    async def test_timeout_cleans_up_pending(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        ws_mock = MagicMock()
        ws_mock.closed = False
        ws_mock.send_json = AsyncMock()
        client._ws = ws_mock

        with pytest.raises(asyncio.TimeoutError):
            await client._send_command_raw({"type": "test"}, timeout=0.01)

        # Pending should be cleaned up.
        assert 1 not in client._pending


# ---------------------------------------------------------------------------
# disconnect
# ---------------------------------------------------------------------------


class TestDisconnect:
    async def test_disconnect_rejects_pending(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        client._pending[1] = fut

        await client.disconnect()

        assert fut.done()
        with pytest.raises(ConnectionError, match="disconnected"):
            fut.result()
        assert client._shutting_down is True
        assert client.connected is False

    async def test_disconnect_closes_ws(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        ws_mock = MagicMock()
        ws_mock.closed = False
        ws_mock.close = AsyncMock()
        client._ws = ws_mock

        session_mock = MagicMock()
        session_mock.closed = False
        session_mock.close = AsyncMock()
        client._session = session_mock

        await client.disconnect()

        ws_mock.close.assert_called_once()
        session_mock.close.assert_called_once()

    async def test_disconnect_cancels_receiver(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")

        async def long_running():
            await asyncio.sleep(999)

        client._receiver_task = asyncio.create_task(long_running())

        await client.disconnect()
        assert client._receiver_task.cancelled() or client._receiver_task.done()

    async def test_disconnect_handles_ws_close_error(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        ws_mock = MagicMock()
        ws_mock.closed = False
        ws_mock.close = AsyncMock(side_effect=Exception("close error"))
        client._ws = ws_mock

        # Should not raise.
        await client.disconnect()

    async def test_disconnect_handles_session_close_error(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        session_mock = MagicMock()
        session_mock.closed = False
        session_mock.close = AsyncMock(side_effect=Exception("session error"))
        client._session = session_mock

        # Should not raise.
        await client.disconnect()

    async def test_disconnect_already_done_pending(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        fut.set_result("already done")
        client._pending[1] = fut

        # Should not raise -- pending future already resolved.
        await client.disconnect()


# ---------------------------------------------------------------------------
# _establish_connection
# ---------------------------------------------------------------------------


class TestEstablishConnection:
    async def test_successful_auth(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "my-token")

        ws_mock = AsyncMock()
        ws_mock.receive_json = AsyncMock(
            side_effect=[
                {"type": "auth_required"},
                {"type": "auth_ok", "ha_version": "2024.1.0"},
            ]
        )
        ws_mock.send_json = AsyncMock()
        ws_mock.__aiter__ = MagicMock(return_value=iter([]))

        session_mock = MagicMock()
        session_mock.closed = False
        session_mock.ws_connect = AsyncMock(return_value=ws_mock)

        with patch(
            "deckboard_homeassistant.client.aiohttp.ClientSession",
            return_value=session_mock,
        ):
            # We need to mock subscribe_events too since it's called after auth.
            client._send_command_raw = AsyncMock(return_value=42)
            await client._establish_connection()

        assert client.connected is True
        assert client._state_sub_id == 42

    async def test_auth_required_not_received(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")

        ws_mock = AsyncMock()
        ws_mock.receive_json = AsyncMock(return_value={"type": "other"})

        session_mock = MagicMock()
        session_mock.closed = False
        session_mock.ws_connect = AsyncMock(return_value=ws_mock)

        with patch(
            "deckboard_homeassistant.client.aiohttp.ClientSession",
            return_value=session_mock,
        ):
            with pytest.raises(ConnectionError, match="Expected auth_required"):
                await client._establish_connection()

    async def test_auth_failed(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "bad-token")

        ws_mock = AsyncMock()
        ws_mock.receive_json = AsyncMock(
            side_effect=[
                {"type": "auth_required"},
                {"type": "auth_invalid", "message": "Invalid token"},
            ]
        )
        ws_mock.send_json = AsyncMock()

        session_mock = MagicMock()
        session_mock.closed = False
        session_mock.ws_connect = AsyncMock(return_value=ws_mock)

        with patch(
            "deckboard_homeassistant.client.aiohttp.ClientSession",
            return_value=session_mock,
        ):
            with pytest.raises(ConnectionError, match="Authentication failed"):
                await client._establish_connection()


# ---------------------------------------------------------------------------
# call_service
# ---------------------------------------------------------------------------


class TestCallService:
    async def test_call_service_message(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        client._connected.set()
        client._send_command_raw = AsyncMock(return_value=None)

        await client.call_service(
            "light",
            "toggle",
            service_data={"brightness": 200},
            target={"entity_id": "light.kitchen"},
        )

        client._send_command_raw.assert_called_once()
        msg = client._send_command_raw.call_args[0][0]
        assert msg["type"] == "call_service"
        assert msg["domain"] == "light"
        assert msg["service"] == "toggle"
        assert msg["service_data"] == {"brightness": 200}
        assert msg["target"] == {"entity_id": "light.kitchen"}

    async def test_call_service_no_data(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        client._connected.set()
        client._send_command_raw = AsyncMock(return_value=None)

        await client.call_service("light", "toggle")

        msg = client._send_command_raw.call_args[0][0]
        assert "service_data" not in msg
        assert "target" not in msg


# ---------------------------------------------------------------------------
# subscribe_events
# ---------------------------------------------------------------------------


class TestSubscribeEvents:
    async def test_subscribe_events(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        client._connected.set()
        client._send_command_raw = AsyncMock(return_value=42)

        result = await client.subscribe_events("state_changed")
        assert result == 42

        msg = client._send_command_raw.call_args[0][0]
        assert msg["type"] == "subscribe_events"
        assert msg["event_type"] == "state_changed"


# ---------------------------------------------------------------------------
# wait_connected
# ---------------------------------------------------------------------------


class TestWaitConnected:
    async def test_wait_connected(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")

        async def set_connected():
            await asyncio.sleep(0.01)
            client._connected.set()

        task = asyncio.create_task(set_connected())
        await asyncio.wait_for(client.wait_connected(), timeout=1.0)
        assert client.connected
        await task


# ---------------------------------------------------------------------------
# run_forever
# ---------------------------------------------------------------------------


class TestRunForever:
    async def test_stops_on_shutdown(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t", reconnect_delay=0.01)

        # Simulate: establish_connection -> receiver done -> shutdown.
        call_count = 0

        async def fake_establish():
            nonlocal call_count
            call_count += 1
            client._connected.set()
            client._receiver_task = asyncio.create_task(asyncio.sleep(0))

        client._establish_connection = AsyncMock(side_effect=fake_establish)

        async def shutdown_after_delay():
            await asyncio.sleep(0.05)
            client._shutting_down = True

        task = asyncio.create_task(shutdown_after_delay())
        await asyncio.wait_for(client.run_forever(), timeout=2.0)
        await task

    async def test_reconnect_on_connection_error(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t", reconnect_delay=0.01)
        call_count = 0

        async def fake_establish():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise ConnectionError("refused")
            client._shutting_down = True

        client._establish_connection = AsyncMock(side_effect=fake_establish)

        await asyncio.wait_for(client.run_forever(), timeout=2.0)
        assert call_count == 3

    async def test_reconnect_on_unexpected_error(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t", reconnect_delay=0.01)
        call_count = 0

        async def fake_establish():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("unexpected")
            client._shutting_down = True

        client._establish_connection = AsyncMock(side_effect=fake_establish)

        await asyncio.wait_for(client.run_forever(), timeout=2.0)
        assert call_count == 2

    async def test_cancelled_error_breaks_loop(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t", reconnect_delay=0.01)

        client._establish_connection = AsyncMock(side_effect=asyncio.CancelledError())

        await asyncio.wait_for(client.run_forever(), timeout=2.0)

    async def test_shutting_down_during_error(self) -> None:
        """Test run_forever exits when shutting_down is set during error handling."""
        client = HomeAssistantClient("http://ha:8123", "t", reconnect_delay=0.01)

        async def fake_establish():
            client._shutting_down = True
            raise ConnectionError("refused")

        client._establish_connection = AsyncMock(side_effect=fake_establish)
        await asyncio.wait_for(client.run_forever(), timeout=2.0)

    async def test_shutting_down_during_unexpected_error(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t", reconnect_delay=0.01)

        async def fake_establish():
            client._shutting_down = True
            raise RuntimeError("unexpected")

        client._establish_connection = AsyncMock(side_effect=fake_establish)
        await asyncio.wait_for(client.run_forever(), timeout=2.0)

    async def test_run_forever_reconnects_after_receiver_ends(self) -> None:
        """Test the path where receiver task ends (connection dropped) then reconnect."""
        client = HomeAssistantClient("http://ha:8123", "t", reconnect_delay=0.01)
        call_count = 0

        async def fake_establish():
            nonlocal call_count
            call_count += 1
            client._connected.set()
            # Create a receiver that finishes immediately.
            client._receiver_task = asyncio.create_task(asyncio.sleep(0))
            if call_count >= 2:
                client._shutting_down = True

        client._establish_connection = AsyncMock(side_effect=fake_establish)
        await asyncio.wait_for(client.run_forever(), timeout=2.0)
        assert call_count >= 2


# ---------------------------------------------------------------------------
# connect
# ---------------------------------------------------------------------------


class TestConnect:
    async def test_connect_sets_not_shutting_down(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        client._shutting_down = True
        client._establish_connection = AsyncMock()

        await client.connect()
        assert client._shutting_down is False
        client._establish_connection.assert_called_once()


# ---------------------------------------------------------------------------
# _send_command
# ---------------------------------------------------------------------------


class TestSendCommand:
    async def test_send_command_delegates(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        client._send_command_raw = AsyncMock(return_value="states_list")

        result = await client._send_command("get_states")
        assert result == "states_list"
        msg = client._send_command_raw.call_args[0][0]
        assert msg == {"type": "get_states"}


# ---------------------------------------------------------------------------
# _receiver_loop
# ---------------------------------------------------------------------------


class _AsyncIterator:
    """Helper to make a list of items behave as an async iterator."""

    def __init__(self, items: list[Any]) -> None:
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration


class TestReceiverLoop:
    async def test_receiver_loop_text_messages(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        client._dispatch = AsyncMock()

        import aiohttp

        msg1 = MagicMock()
        msg1.type = aiohttp.WSMsgType.TEXT
        msg1.json = MagicMock(
            return_value={"type": "result", "id": 1, "success": True, "result": None}
        )

        msg2 = MagicMock()
        msg2.type = aiohttp.WSMsgType.CLOSE

        client._ws = _AsyncIterator([msg1, msg2])

        await client._receiver_loop()
        client._dispatch.assert_called_once()

    async def test_receiver_loop_error(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")

        import aiohttp

        msg = MagicMock()
        msg.type = aiohttp.WSMsgType.ERROR

        ws_mock = _AsyncIterator([msg])
        ws_mock.exception = MagicMock(return_value=Exception("ws error"))
        client._ws = ws_mock

        await client._receiver_loop()

    async def test_receiver_loop_closing(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")

        import aiohttp

        msg = MagicMock()
        msg.type = aiohttp.WSMsgType.CLOSING

        client._ws = _AsyncIterator([msg])

        await client._receiver_loop()

    async def test_receiver_loop_closed(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")

        import aiohttp

        msg = MagicMock()
        msg.type = aiohttp.WSMsgType.CLOSED

        client._ws = _AsyncIterator([msg])

        await client._receiver_loop()
        client._dispatch.assert_called_once()

    async def test_receiver_loop_error(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")

        import aiohttp

        msg = MagicMock()
        msg.type = aiohttp.WSMsgType.ERROR

        ws = _AsyncIterator([msg])
        ws.exception = MagicMock(return_value=Exception("ws error"))
        client._ws = ws

        await client._receiver_loop()

    async def test_receiver_loop_closing(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")

        import aiohttp

        msg = MagicMock()
        msg.type = aiohttp.WSMsgType.CLOSING

        client._ws = _AsyncIterator([msg])

        await client._receiver_loop()

    async def test_receiver_loop_closed(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")

        import aiohttp

        msg = MagicMock()
        msg.type = aiohttp.WSMsgType.CLOSED

        client._ws = _AsyncIterator([msg])

        await client._receiver_loop()


# ---------------------------------------------------------------------------
# get_states (connected)
# ---------------------------------------------------------------------------


class TestGetStatesConnected:
    async def test_get_states_returns_result(self) -> None:
        client = HomeAssistantClient("http://ha:8123", "t")
        client._connected.set()
        client._send_command = AsyncMock(return_value=[{"entity_id": "light.a"}])

        result = await client.get_states()
        assert result == [{"entity_id": "light.a"}]
        client._send_command.assert_called_once_with("get_states")
