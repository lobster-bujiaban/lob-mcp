from __future__ import annotations

import asyncio
from contextlib import suppress
from enum import StrEnum
from typing import Any

from lob_mcp.events import EventSink, ProtocolEvent, discard_event
from lob_mcp.protocol import (
    JSONRPCErrorResponse,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    decode_message,
    encode_message,
)
from lob_mcp.transport import Transport, TransportClosed


class ClientState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    INITIALIZING = "initializing"
    READY = "ready"
    CLOSING = "closing"
    CLOSED = "closed"


class RemoteError(Exception):
    def __init__(self, response: JSONRPCErrorResponse) -> None:
        self.code = response.error.code
        self.data = response.error.data
        super().__init__(response.error.message)


class MCPClient:
    def __init__(
        self,
        transport: Transport,
        event_sink: EventSink = discard_event,
        request_timeout: float = 10,
    ) -> None:
        self._transport = transport
        self._event_sink = event_sink
        self._next_id = 1
        self._pending: dict[int | str, asyncio.Future[Any]] = {}
        self._notifications: asyncio.Queue[JSONRPCNotification] = asyncio.Queue()
        self._reader_task: asyncio.Task[None] | None = None
        self._request_timeout = request_timeout
        self.state = ClientState.DISCONNECTED
        self.server_info: dict[str, Any] | None = None
        self.server_capabilities: dict[str, Any] = {}

    async def connect(self) -> None:
        if self.state is not ClientState.DISCONNECTED:
            raise RuntimeError(f"cannot connect from state {self.state}")
        self.state = ClientState.CONNECTING
        self._reader_task = asyncio.create_task(self._read_loop())
        self.state = ClientState.INITIALIZING
        result = await self.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "lob-mcp", "version": "0.1.0"},
            },
        )
        self.server_info = result["serverInfo"]
        self.server_capabilities = result["capabilities"]
        await self.notify("notifications/initialized")
        self.state = ClientState.READY

    async def ping(self) -> dict[str, Any]:
        self._require_ready()
        result = await self.request("ping")
        if not isinstance(result, dict):
            raise RuntimeError("ping returned a non-object result")
        return result

    async def list_tools(self) -> list[dict[str, Any]]:
        self._require_ready()
        result = await self.request("tools/list")
        if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            raise RuntimeError("tools/list returned an invalid result")
        return result["tools"]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self._require_ready()
        result = await self.request(
            "tools/call",
            {"name": name, "arguments": arguments},
        )
        if not isinstance(result, dict) or not isinstance(result.get("content"), list):
            raise RuntimeError("tools/call returned an invalid result")
        return result

    async def list_resources(self) -> list[dict[str, Any]]:
        self._require_ready()
        return self._list_result(await self.request("resources/list"), "resources")

    async def read_resource(self, uri: str) -> list[dict[str, Any]]:
        self._require_ready()
        return self._list_result(
            await self.request("resources/read", {"uri": uri}), "contents"
        )

    async def list_resource_templates(self) -> list[dict[str, Any]]:
        self._require_ready()
        return self._list_result(
            await self.request("resources/templates/list"), "resourceTemplates"
        )

    async def subscribe_resource(self, uri: str) -> None:
        self._require_ready()
        await self.request("resources/subscribe", {"uri": uri})

    async def list_prompts(self) -> list[dict[str, Any]]:
        self._require_ready()
        return self._list_result(await self.request("prompts/list"), "prompts")

    async def get_prompt(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self._require_ready()
        result = await self.request("prompts/get", {"name": name, "arguments": arguments})
        if not isinstance(result, dict) or not isinstance(result.get("messages"), list):
            raise RuntimeError("prompts/get returned an invalid result")
        return result

    async def next_notification(self, timeout: float = 10) -> JSONRPCNotification:
        async with asyncio.timeout(timeout):
            return await self._notifications.get()

    async def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        request_id = self._next_id
        self._next_id += 1
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        message = JSONRPCRequest(id=request_id, method=method, params=params)
        self._emit("send", "request", method=method, request_id=request_id)
        try:
            await self._transport.send(encode_message(message))
            try:
                async with asyncio.timeout(self._request_timeout):
                    return await future
            except TimeoutError:
                await self._send_cancellation(request_id, "request timed out")
                raise
            except asyncio.CancelledError:
                await self._send_cancellation(request_id, "request cancelled")
                raise
        finally:
            self._pending.pop(request_id, None)

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        message = JSONRPCNotification(method=method, params=params)
        self._emit("send", "notification", method=method)
        await self._transport.send(encode_message(message))

    async def close(self) -> None:
        if self.state is ClientState.CLOSED:
            return
        self.state = ClientState.CLOSING
        await self._transport.close()
        if self._reader_task is not None:
            self._reader_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._reader_task
        self._fail_pending(TransportClosed("client closed"))
        self.state = ClientState.CLOSED

    async def _read_loop(self) -> None:
        try:
            while True:
                message = decode_message(await self._transport.receive())
                if isinstance(message, JSONRPCResponse):
                    self._emit("receive", "response", request_id=message.id)
                    future = self._pending.get(message.id)
                    if future is not None and not future.done():
                        future.set_result(message.result)
                elif isinstance(message, JSONRPCErrorResponse):
                    self._emit("receive", "error", request_id=message.id)
                    future = self._pending.get(message.id) if message.id is not None else None
                    if future is not None and not future.done():
                        future.set_exception(RemoteError(message))
                elif isinstance(message, JSONRPCNotification):
                    self._emit("receive", "notification", method=message.method)
                    await self._notifications.put(message)
        except TransportClosed as exc:
            self._fail_pending(exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail_pending(exc)

    def _fail_pending(self, error: Exception) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)

    async def _send_cancellation(self, request_id: int | str, reason: str) -> None:
        with suppress(TransportClosed):
            await self.notify(
                "notifications/cancelled",
                {"requestId": request_id, "reason": reason},
            )

    def _require_ready(self) -> None:
        if self.state is not ClientState.READY:
            raise RuntimeError(f"client is not ready: {self.state}")

    def _list_result(self, result: Any, key: str) -> list[dict[str, Any]]:
        if not isinstance(result, dict) or not isinstance(result.get(key), list):
            raise RuntimeError(f"response returned an invalid {key} result")
        return result[key]

    def _emit(
        self,
        direction: str,
        message_type: str,
        *,
        method: str | None = None,
        request_id: int | str | None = None,
    ) -> None:
        self._event_sink(
            ProtocolEvent.create(
                actor="client",
                direction=direction,
                message_type=message_type,
                method=method,
                request_id=request_id,
            )
        )
