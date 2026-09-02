from __future__ import annotations

import asyncio
from dataclasses import dataclass

from lob_mcp.transport.base import TransportClosed

_CLOSED = object()


@dataclass(slots=True)
class MemoryTransport:
    _incoming: asyncio.Queue[bytes | object]
    _outgoing: asyncio.Queue[bytes | object]
    _closed: bool = False

    async def send(self, payload: bytes) -> None:
        if self._closed:
            raise TransportClosed("transport is closed")
        await self._outgoing.put(payload)

    async def receive(self) -> bytes:
        payload = await self._incoming.get()
        if payload is _CLOSED:
            raise TransportClosed("peer transport is closed")
        if not isinstance(payload, bytes):
            raise RuntimeError("memory transport received an invalid payload")
        return payload

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            await self._outgoing.put(_CLOSED)


def create_memory_transport_pair() -> tuple[MemoryTransport, MemoryTransport]:
    client_incoming: asyncio.Queue[bytes | object] = asyncio.Queue()
    server_incoming: asyncio.Queue[bytes | object] = asyncio.Queue()
    return (
        MemoryTransport(client_incoming, server_incoming),
        MemoryTransport(server_incoming, client_incoming),
    )

