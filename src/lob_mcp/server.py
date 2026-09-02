from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from lob_mcp.events import EventSink, ProtocolEvent, discard_event
from lob_mcp.protocol import (
    JSONRPCError,
    JSONRPCErrorResponse,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    decode_message,
    encode_message,
)
from lob_mcp.prompts import PromptRegistry
from lob_mcp.resources import ResourceRegistry
from lob_mcp.transport import Transport, TransportClosed
from lob_mcp.tools import ToolRegistry

MethodHandler = Callable[[dict[str, Any] | list[Any] | None], Awaitable[Any]]


class MCPServer:
    def __init__(
        self,
        transport: Transport,
        event_sink: EventSink = discard_event,
        name: str = "lob-mcp-memory-server",
        tool_registry: ToolRegistry | None = None,
        resource_registry: ResourceRegistry | None = None,
        prompt_registry: PromptRegistry | None = None,
    ) -> None:
        self._transport = transport
        self._event_sink = event_sink
        self._initialized = False
        self._name = name
        self._tools = tool_registry or ToolRegistry()
        self._resources = resource_registry or ResourceRegistry()
        self._prompts = prompt_registry or PromptRegistry()
        self._resource_subscriptions: set[str] = set()
        self._handlers: dict[str, MethodHandler] = {
            "initialize": self._initialize,
            "ping": self._ping,
            "tools/list": self._list_tools,
            "tools/call": self._call_tool,
            "resources/list": self._list_resources,
            "resources/read": self._read_resource,
            "resources/templates/list": self._list_resource_templates,
            "resources/subscribe": self._subscribe_resource,
            "prompts/list": self._list_prompts,
            "prompts/get": self._get_prompt,
        }

    async def serve(self) -> None:
        try:
            while True:
                payload = await self._transport.receive()
                try:
                    message = decode_message(payload)
                except ValueError as exc:
                    await self._send_error(None, -32700, "Parse error", str(exc))
                    continue

                if isinstance(message, JSONRPCRequest):
                    self._emit("receive", "request", message.method, message.id)
                    await self._handle_request(message)
                elif isinstance(message, JSONRPCNotification):
                    self._emit("receive", "notification", message.method)
                    self._handle_notification(message)
                else:
                    await self._send_error(None, -32600, "Invalid Request")
        except TransportClosed:
            return

    async def close(self) -> None:
        await self._transport.close()

    async def _handle_request(self, request: JSONRPCRequest) -> None:
        handler = self._handlers.get(request.method)
        if handler is None:
            await self._send_error(request.id, -32601, "Method not found", request.method)
            return
        try:
            result = await handler(request.params)
        except Exception as exc:
            await self._send_error(request.id, -32603, "Internal error", str(exc))
            return
        response = JSONRPCResponse(id=request.id, result=result)
        self._emit("send", "response", request_id=request.id)
        await self._transport.send(encode_message(response))

    def _handle_notification(self, notification: JSONRPCNotification) -> None:
        if notification.method == "notifications/initialized":
            self._initialized = True

    async def _initialize(self, params: dict[str, Any] | list[Any] | None) -> dict[str, Any]:
        if not isinstance(params, dict):
            raise ValueError("initialize params must be an object")
        return {
            "protocolVersion": params.get("protocolVersion", "2025-06-18"),
            "capabilities": {
                "tools": {"listChanged": True},
                "resources": {"subscribe": True, "listChanged": True},
                "prompts": {"listChanged": True},
            },
            "serverInfo": {"name": self._name, "version": "0.1.0"},
        }

    async def _ping(self, params: dict[str, Any] | list[Any] | None) -> dict[str, Any]:
        del params
        if not self._initialized:
            raise RuntimeError("server has not received initialized notification")
        return {}

    async def _list_tools(self, params: dict[str, Any] | list[Any] | None) -> dict[str, Any]:
        del params
        self._require_initialized()
        return {"tools": self._tools.list_tools()}

    async def _call_tool(self, params: dict[str, Any] | list[Any] | None) -> dict[str, Any]:
        self._require_initialized()
        if not isinstance(params, dict):
            raise ValueError("tools/call params must be an object")
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            raise ValueError("tools/call requires string name and object arguments")
        return await self._tools.call(name, arguments)

    async def _list_resources(self, params: Any) -> dict[str, Any]:
        del params
        self._require_initialized()
        return {"resources": self._resources.list_resources()}

    async def _read_resource(self, params: Any) -> dict[str, Any]:
        self._require_initialized()
        uri = self._string_param(params, "uri")
        return self._resources.read(uri)

    async def _list_resource_templates(self, params: Any) -> dict[str, Any]:
        del params
        self._require_initialized()
        return {"resourceTemplates": self._resources.list_templates()}

    async def _subscribe_resource(self, params: Any) -> dict[str, Any]:
        self._require_initialized()
        uri = self._string_param(params, "uri")
        self._resources.read(uri)
        self._resource_subscriptions.add(uri)
        return {}

    async def _list_prompts(self, params: Any) -> dict[str, Any]:
        del params
        self._require_initialized()
        return {"prompts": self._prompts.list_prompts()}

    async def _get_prompt(self, params: Any) -> dict[str, Any]:
        self._require_initialized()
        if not isinstance(params, dict):
            raise ValueError("prompts/get params must be an object")
        name = self._string_param(params, "name")
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ValueError("prompt arguments must be an object")
        return self._prompts.get(name, arguments)

    async def notify_resource_updated(self, uri: str) -> None:
        if uri not in self._resource_subscriptions:
            return
        notification = JSONRPCNotification(
            method="notifications/resources/updated", params={"uri": uri}
        )
        self._emit("send", "notification", method=notification.method)
        await self._transport.send(encode_message(notification))

    @staticmethod
    def _string_param(params: Any, name: str) -> str:
        if not isinstance(params, dict) or not isinstance(params.get(name), str):
            raise ValueError(f"{name} must be a string")
        return params[name]

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("server has not received initialized notification")

    async def _send_error(
        self,
        request_id: int | str | None,
        code: int,
        message: str,
        data: Any = None,
    ) -> None:
        response = JSONRPCErrorResponse(
            id=request_id,
            error=JSONRPCError(code=code, message=message, data=data),
        )
        self._emit("send", "error", request_id=request_id)
        await self._transport.send(encode_message(response))

    def _emit(
        self,
        direction: str,
        message_type: str,
        method: str | None = None,
        request_id: int | str | None = None,
    ) -> None:
        self._event_sink(
            ProtocolEvent.create(
                actor="server",
                direction=direction,
                message_type=message_type,
                method=method,
                request_id=request_id,
            )
        )
