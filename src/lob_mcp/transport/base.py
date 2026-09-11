from __future__ import annotations

from typing import Protocol


class TransportClosed(Exception):
    """Raised when reading from or writing to a closed transport."""


class Transport(Protocol):
    async def send(self, payload: bytes) -> None: ...

    async def receive(self) -> bytes: ...

    async def close(self) -> None: ...

