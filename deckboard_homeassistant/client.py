"""Standalone Home Assistant WebSocket client.

Connects to Home Assistant over the network using its native WebSocket API.
Handles authentication (long-lived access token), state subscriptions,
service calls, and automatic reconnection.

This is a production-oriented async client designed to run on an edge device
(e.g. Raspberry Pi) that talks to HA remotely. It is NOT an AppDaemon component.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine

import aiohttp

log = logging.getLogger(__name__)

# Callback type for state change events.
StateChangeCallback = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]


class HomeAssistantClient:
    """Async WebSocket client for Home Assistant.

    Parameters:
        url: Base URL of the HA instance (e.g. ``http://homeassistant.local:8123``).
        token: Long-lived access token.
        reconnect_delay: Seconds to wait before reconnecting after a drop.
    """

    def __init__(
        self,
        url: str,
        token: str,
        *,
        reconnect_delay: float = 5.0,
    ) -> None:
        self._base_url = url.rstrip("/")
        self._token = token
        self._reconnect_delay = reconnect_delay

        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._msg_id: int = 0
        self._connected = asyncio.Event()
        self._shutting_down = False

        # Pending request futures: msg_id -> Future[result]
        self._pending: dict[int, asyncio.Future[Any]] = {}

        # State change callbacks.
        self._state_callbacks: list[StateChangeCallback] = []

        # Subscription ID for state_changed events (from HA).
        self._state_sub_id: int | None = None

        # Receiver task.
        self._receiver_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        """Whether the client is currently connected and authenticated."""
        return self._connected.is_set()

    async def connect(self) -> None:
        """Connect to HA, authenticate, and start the message receiver."""
        self._shutting_down = False
        await self._establish_connection()

    async def disconnect(self) -> None:
        """Gracefully close the WebSocket and HTTP session."""
        self._shutting_down = True
        self._connected.clear()

        # Reject pending requests first -- unblocks any coroutines
        # waiting on service call / get_states results.
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError("Client disconnected"))
        self._pending.clear()

        if self._receiver_task and not self._receiver_task.done():
            self._receiver_task.cancel()
            try:
                await self._receiver_task
            except asyncio.CancelledError:
                pass

        if self._ws and not self._ws.closed:
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._session and not self._session.closed:
            try:
                await self._session.close()
            except Exception:
                pass

        log.info("Disconnected from Home Assistant")

    async def wait_connected(self) -> None:
        """Block until the client is connected and authenticated."""
        await self._connected.wait()

    def on_state_changed(self, callback: StateChangeCallback) -> None:
        """Register a callback for entity state changes.

        Callback signature: ``async callback(entity_id, new_state_dict)``
        where ``new_state_dict`` includes ``state``, ``attributes``, etc.
        """
        self._state_callbacks.append(callback)

    async def get_states(self) -> list[dict[str, Any]]:
        """Fetch all entity states from HA.

        Returns a list of state objects, each containing ``entity_id``,
        ``state``, ``attributes``, ``last_changed``, etc.
        """
        if not self._connected.is_set():
            raise ConnectionError("Not connected to Home Assistant")
        return await self._send_command("get_states")

    async def call_service(
        self,
        domain: str,
        service: str,
        service_data: dict[str, Any] | None = None,
        target: dict[str, Any] | None = None,
    ) -> Any:
        """Call a Home Assistant service.

        Parameters:
            domain: Service domain (e.g. ``"light"``).
            service: Service name (e.g. ``"toggle"``).
            service_data: Service call data.
            target: Target dict (``entity_id``, ``device_id``, or ``area_id``).

        Returns the result from HA, or None on timeout/error.
        Service calls are best-effort -- a timeout does not mean the
        call failed on the HA side.
        """
        if not self._connected.is_set():
            raise ConnectionError("Not connected to Home Assistant")

        msg: dict[str, Any] = {
            "type": "call_service",
            "domain": domain,
            "service": service,
        }
        if service_data:
            msg["service_data"] = service_data
        if target:
            msg["target"] = target

        return await self._send_command_raw(msg, timeout=10.0)

    async def subscribe_events(self, event_type: str = "state_changed") -> int:
        """Subscribe to events of a given type.

        Returns the subscription ID.
        """
        if not self._connected.is_set():
            raise ConnectionError("Not connected to Home Assistant")
        result = await self._send_command_raw(
            {"type": "subscribe_events", "event_type": event_type}
        )
        return result

    async def run_forever(self) -> None:
        """Main loop: connect, receive, reconnect on failure.

        Runs until ``disconnect()`` is called. Suitable as the top-level
        coroutine for a standalone daemon.
        """
        while not self._shutting_down:
            try:
                if not self.connected:
                    await self._establish_connection()

                # Wait for the receiver to finish (it only finishes on error/close).
                if self._receiver_task:
                    await self._receiver_task
            except (
                aiohttp.ClientError,
                ConnectionError,
                OSError,
                asyncio.TimeoutError,
            ) as exc:
                if self._shutting_down:
                    break
                log.warning(
                    "Connection lost: %s. Reconnecting in %.0fs...",
                    exc,
                    self._reconnect_delay,
                )
            except asyncio.CancelledError:
                break
            except Exception:
                if self._shutting_down:
                    break
                log.exception(
                    "Unexpected error. Reconnecting in %.0fs...",
                    self._reconnect_delay,
                )
            finally:
                self._connected.clear()
                self._state_sub_id = None
                # Reject pending requests.
                for fut in self._pending.values():
                    if not fut.done():
                        fut.set_exception(ConnectionError("Connection lost"))
                self._pending.clear()

            if not self._shutting_down:
                await asyncio.sleep(self._reconnect_delay)

    # ------------------------------------------------------------------
    # Connection internals
    # ------------------------------------------------------------------

    async def _establish_connection(self) -> None:
        """Open WebSocket, authenticate, subscribe to state changes."""
        ws_url = self._base_url.replace("http", "ws", 1) + "/api/websocket"
        log.info("Connecting to %s", ws_url)

        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

        self._ws = await self._session.ws_connect(ws_url, heartbeat=30, compress=15)
        self._msg_id = 0

        # HA sends auth_required on connect.
        auth_req = await self._ws.receive_json()
        if auth_req.get("type") != "auth_required":
            raise ConnectionError(f"Expected auth_required, got: {auth_req}")

        # Send auth.
        await self._ws.send_json({"type": "auth", "access_token": self._token})
        auth_resp = await self._ws.receive_json()
        if auth_resp.get("type") != "auth_ok":
            msg = auth_resp.get("message", "Unknown auth error")
            raise ConnectionError(f"Authentication failed: {msg}")

        log.info("Authenticated with HA %s", auth_resp.get("ha_version", "unknown"))
        self._connected.set()

        # Start receiver loop BEFORE subscribing -- the receiver must be
        # running to process the subscribe_events result message.
        self._receiver_task = asyncio.create_task(
            self._receiver_loop(), name="ha-ws-receiver"
        )

        # Subscribe to state_changed events.
        sub_id = await self.subscribe_events("state_changed")
        self._state_sub_id = sub_id
        log.debug("Subscribed to state_changed (id=%s)", sub_id)

    async def _receiver_loop(self) -> None:
        """Read messages from the WebSocket and dispatch them."""
        assert self._ws is not None
        async for msg in self._ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = msg.json()
                await self._dispatch(data)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                log.error("WebSocket error: %s", self._ws.exception())
                break
            elif msg.type in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSING,
                aiohttp.WSMsgType.CLOSED,
            ):
                break

        log.debug("Receiver loop ended")

    async def _dispatch(self, data: dict[str, Any]) -> None:
        """Route an incoming message to the correct handler."""
        msg_type = data.get("type")

        if msg_type == "result":
            msg_id = data.get("id")
            fut = self._pending.pop(msg_id, None)
            if fut and not fut.done():
                if data.get("success"):
                    fut.set_result(data.get("result"))
                else:
                    error = data.get("error", {})
                    fut.set_exception(
                        RuntimeError(
                            f"HA error: {error.get('code')} - {error.get('message')}"
                        )
                    )

        elif msg_type == "event":
            event = data.get("event", {})
            event_type = event.get("event_type")
            if event_type == "state_changed":
                # Dispatch as a separate task so the receiver loop is never
                # blocked by callback processing (which may call deck.refresh
                # or even trigger further service calls that need the receiver
                # to resolve their response futures).
                asyncio.create_task(
                    self._handle_state_changed(event.get("data", {})),
                    name="ha-state-changed",
                )

        elif msg_type == "pong":
            msg_id = data.get("id")
            fut = self._pending.pop(msg_id, None)
            if fut and not fut.done():
                fut.set_result(None)

    async def _handle_state_changed(self, data: dict[str, Any]) -> None:
        """Process a state_changed event and invoke callbacks."""
        entity_id = data.get("entity_id", "")
        new_state = data.get("new_state")
        if not new_state:
            return

        for cb in self._state_callbacks:
            try:
                await cb(entity_id, new_state)
            except Exception:
                log.exception("Error in state callback for %s", entity_id)

    # ------------------------------------------------------------------
    # Message sending
    # ------------------------------------------------------------------

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    async def _send_command(self, cmd_type: str) -> Any:
        """Send a simple command and wait for the result."""
        return await self._send_command_raw({"type": cmd_type})

    async def _send_command_raw(
        self, msg: dict[str, Any], *, timeout: float = 30.0
    ) -> Any:
        """Send a command message with an auto-assigned ID and await result."""
        if self._ws is None or self._ws.closed:
            raise ConnectionError("Not connected")

        msg_id = self._next_id()
        msg["id"] = msg_id

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        self._pending[msg_id] = fut

        await self._ws.send_json(msg)

        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            raise
