from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from lob_mcp.client import MCPClient


class ServerStatus(StrEnum):
    DISABLED = "disabled"
    CONNECTING = "connecting"
    READY = "ready"
    FAILED = "failed"
    CLOSED = "closed"


@dataclass(slots=True)
class ServerConnection:
    name: str
    client: MCPClient
    enabled: bool = True
    status: ServerStatus = ServerStatus.CLOSED
    error: str | None = None


class MultiServerGateway:
    SEPARATOR = "::"

    def __init__(self) -> None:
        self._servers: dict[str, ServerConnection] = {}

    def register(self, name: str, client: MCPClient, *, enabled: bool = True) -> None:
        if not name or self.SEPARATOR in name:
            raise ValueError("server name is empty or contains reserved separator")
        if name in self._servers:
            raise ValueError(f"server already registered: {name}")
        status = ServerStatus.CLOSED if enabled else ServerStatus.DISABLED
        self._servers[name] = ServerConnection(name, client, enabled, status)

    async def connect_all(self) -> None:
        await asyncio.gather(
            *(self._connect(server) for server in self._servers.values() if server.enabled)
        )

    async def list_tools(self) -> list[dict[str, Any]]:
        results = await asyncio.gather(
            *(
                self._list_server_tools(server)
                for server in self._servers.values()
                if server.status is ServerStatus.READY
            )
        )
        return [tool for server_tools in results for tool in server_tools]

    async def call_tool(self, qualified_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        server_name, separator, tool_name = qualified_name.partition(self.SEPARATOR)
        if not separator or not server_name or not tool_name:
            raise ValueError(
                f"tool name must use <server>{self.SEPARATOR}<tool> format"
            )
        server = self._servers.get(server_name)
        if server is None:
            raise ValueError(f"unknown server: {server_name}")
        if server.status is not ServerStatus.READY:
            raise RuntimeError(f"server is not ready: {server_name} ({server.status})")
        return await server.client.call_tool(tool_name, arguments)

    def set_enabled(self, name: str, enabled: bool) -> None:
        server = self._require_server(name)
        server.enabled = enabled
        if not enabled:
            server.status = ServerStatus.DISABLED
            server.error = None
        elif server.status is ServerStatus.DISABLED:
            server.status = ServerStatus.CLOSED

    def health(self) -> list[dict[str, Any]]:
        return [
            {
                "name": server.name,
                "enabled": server.enabled,
                "status": server.status,
                **({"error": server.error} if server.error else {}),
            }
            for server in self._servers.values()
        ]

    async def close(self) -> None:
        await asyncio.gather(
            *(server.client.close() for server in self._servers.values()),
            return_exceptions=True,
        )
        for server in self._servers.values():
            server.status = ServerStatus.CLOSED

    async def _connect(self, server: ServerConnection) -> None:
        server.status = ServerStatus.CONNECTING
        server.error = None
        try:
            await server.client.connect()
        except Exception as exc:
            server.status = ServerStatus.FAILED
            server.error = str(exc)
        else:
            server.status = ServerStatus.READY

    async def _list_server_tools(self, server: ServerConnection) -> list[dict[str, Any]]:
        try:
            tools = await server.client.list_tools()
        except Exception as exc:
            server.status = ServerStatus.FAILED
            server.error = str(exc)
            return []
        return [
            {
                **tool,
                "name": f"{server.name}{self.SEPARATOR}{tool['name']}",
                "originalName": tool["name"],
                "server": server.name,
            }
            for tool in tools
        ]

    def _require_server(self, name: str) -> ServerConnection:
        server = self._servers.get(name)
        if server is None:
            raise ValueError(f"unknown server: {name}")
        return server

