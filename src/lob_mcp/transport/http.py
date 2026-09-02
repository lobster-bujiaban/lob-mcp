from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import suppress

import httpx

from lob_mcp.protocol import JSONRPCNotification, decode_message
from lob_mcp.transport.base import TransportClosed


class StreamableHTTPTransport:
    def __init__(
        self,
        endpoint: str,
        *,
        token: str,
        origin: str = "http://localhost",
        protocol_version: str = "2025-06-18",
    ) -> None:
        self._endpoint = endpoint
        self._token = token
        self._origin = origin
        self._protocol_version = protocol_version
        self._client = httpx.AsyncClient(timeout=15, trust_env=False)
        self._incoming: asyncio.Queue[bytes] = asyncio.Queue()
        self._session_id: str | None = None
        self._poll_task: asyncio.Task[None] | None = None
        self._initialize_payload: bytes | None = None
        self._reconnect_count = 0
        self._reconnect_lock = asyncio.Lock()
        self._closed = False

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def reconnect_count(self) -> int:
        return self._reconnect_count

    async def send(self, payload: bytes) -> None:
        if self._closed:
            raise TransportClosed("HTTP transport is closed")
        message = decode_message(payload)
        if getattr(message, "method", None) == "initialize":
            self._initialize_payload = payload
        response = await self._post(payload)
        if response.status_code == 404 and self._session_id is not None:
            await self._reconnect()
            response = await self._post(payload)
        if response.status_code not in (200, 202):
            raise TransportClosed(
                f"HTTP server rejected request: {response.status_code} {response.text}"
            )
        session_id = response.headers.get("mcp-session-id")
        if session_id is not None and self._session_id is None:
            self._session_id = session_id
            self._poll_task = asyncio.create_task(self._poll_notifications())
        if response.status_code == 200 and response.content:
            await self._incoming.put(response.content)

    async def receive(self) -> bytes:
        if self._closed:
            raise TransportClosed("HTTP transport is closed")
        return await self._incoming.get()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._poll_task is not None:
            self._poll_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._poll_task
        if self._session_id is not None:
            with suppress(httpx.HTTPError):
                await self._client.delete(self._endpoint, headers=self._headers())
        await self._client.aclose()

    async def _poll_notifications(self) -> None:
        try:
            while not self._closed:
                response = await self._client.get(
                    self._endpoint, headers=self._headers(), timeout=15
                )
                if response.status_code == 200 and response.content:
                    message = decode_message(response.content)
                    if isinstance(message, JSONRPCNotification):
                        await self._incoming.put(response.content)
                elif response.status_code not in (204, 404):
                    raise TransportClosed(
                        f"notification stream failed: {response.status_code}"
                    )
        except asyncio.CancelledError:
            raise
        except (httpx.HTTPError, TransportClosed):
            return

    async def _post(self, payload: bytes) -> httpx.Response:
        try:
            return await self._client.post(
                self._endpoint, content=payload, headers=self._headers()
            )
        except httpx.HTTPError as exc:
            raise TransportClosed(f"HTTP request failed: {exc}") from exc

    async def _reconnect(self) -> None:
        async with self._reconnect_lock:
            if self._initialize_payload is None:
                raise TransportClosed("cannot restore session before initialize")
            old_session_id = self._session_id
            self._session_id = None
            raw = json.loads(self._initialize_payload)
            raw["id"] = f"reconnect-{uuid.uuid4().hex}"
            response = await self._post(json.dumps(raw).encode())
            if response.status_code != 200:
                self._session_id = old_session_id
                raise TransportClosed("failed to reinitialize HTTP session")
            self._session_id = response.headers.get("mcp-session-id")
            if self._session_id is None:
                raise TransportClosed("reinitialized session has no session id")
            initialized = json.dumps(
                {"jsonrpc": "2.0", "method": "notifications/initialized"}
            ).encode()
            acknowledged = await self._post(initialized)
            if acknowledged.status_code != 202:
                raise TransportClosed("failed to restore initialized state")
            if self._poll_task is not None:
                self._poll_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._poll_task
            self._poll_task = asyncio.create_task(self._poll_notifications())
            self._reconnect_count += 1

    def _headers(self) -> dict[str, str]:
        headers = {
            "authorization": f"Bearer {self._token}",
            "origin": self._origin,
            "mcp-protocol-version": self._protocol_version,
            "content-type": "application/json",
        }
        if self._session_id is not None:
            headers["mcp-session-id"] = self._session_id
        return headers
