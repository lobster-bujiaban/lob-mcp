from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

from lob_mcp.client import MCPClient
from lob_mcp.governance import PersistentCredentialStore
from lob_mcp.persistence import MCPRepository
from lob_mcp.transport import StdioProcessTransport, StreamableHTTPTransport


@dataclass(slots=True)
class RuntimeConnection:
    server_id: uuid.UUID
    client: MCPClient


class ServerRuntimeManager:
    def __init__(
        self, repository: MCPRepository, credentials: PersistentCredentialStore
    ) -> None:
        self._repository = repository
        self._credentials = credentials
        self._connections: dict[uuid.UUID, RuntimeConnection] = {}
        self._locks: dict[uuid.UUID, asyncio.Lock] = {}

    async def load_enabled(self) -> None:
        servers = await self._repository.list_servers()
        await asyncio.gather(
            *(self.connect(server) for server in servers if server["enabled"]),
            return_exceptions=True,
        )

    async def connect(self, server: dict[str, Any]) -> None:
        server_id = uuid.UUID(str(server["id"]))
        lock = self._locks.setdefault(server_id, asyncio.Lock())
        async with lock:
            await self.disconnect(server_id)
            await self._repository.set_server_runtime(server_id, "connecting")
            try:
                client = MCPClient(await self._create_transport(server))
                await client.connect()
                self._connections[server_id] = RuntimeConnection(server_id, client)
                capabilities = client.server_capabilities
                tools = await client.list_tools() if "tools" in capabilities else []
                resources = await client.list_resources() if "resources" in capabilities else []
                prompts = await client.list_prompts() if "prompts" in capabilities else []
                await self._repository.save_capability_snapshot(
                    server_id,
                    protocol_version="2025-06-18",
                    server_info=client.server_info or {},
                    capabilities=capabilities,
                    tools=tools,
                    resources=resources,
                    prompts=prompts,
                )
                await self._repository.set_server_runtime(server_id, "ready")
            except Exception as exc:
                await self._repository.set_server_runtime(server_id, "failed", str(exc))
                raise

    async def disconnect(self, server_id: uuid.UUID) -> None:
        connection = self._connections.pop(server_id, None)
        if connection is not None:
            await connection.client.close()

    async def refresh(self, server_id: uuid.UUID) -> None:
        server = await self._repository.get_server(server_id)
        if server is None:
            raise ValueError("server not found")
        if not server["enabled"]:
            await self.disconnect(server_id)
            await self._repository.set_server_runtime(server_id, "disabled")
            return
        await self.connect(server)

    async def call_tool(
        self, server_id: uuid.UUID, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        connection = self._connections.get(server_id)
        if connection is None:
            await self.refresh(server_id)
            connection = self._connections.get(server_id)
        if connection is None:
            raise RuntimeError("server is not connected")
        return await connection.client.call_tool(name, arguments)

    async def close(self) -> None:
        await asyncio.gather(
            *(connection.client.close() for connection in self._connections.values()),
            return_exceptions=True,
        )
        self._connections.clear()

    async def _create_transport(self, server: dict[str, Any]):
        if server["transport"] == "stdio":
            command = server.get("command")
            if not isinstance(command, list) or not command:
                raise ValueError("stdio server requires a non-empty command")
            return await StdioProcessTransport.start([str(part) for part in command])
        if server["transport"] == "http":
            endpoint = server.get("endpoint")
            if not endpoint:
                raise ValueError("HTTP server requires an endpoint")
            token = ""
            if server.get("credential_reference"):
                token = await self._credentials.resolve(server["credential_reference"])
            headers = server.get("headers") or {}
            return StreamableHTTPTransport(
                endpoint,
                token=token,
                origin=headers.get("Origin", "http://localhost"),
            )
        raise ValueError(f"unsupported transport: {server['transport']}")
