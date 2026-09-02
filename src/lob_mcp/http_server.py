from __future__ import annotations

import asyncio
import secrets
import time
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, Response

from lob_mcp.events import EventSink, discard_event
from lob_mcp.examples.knowledge import create_prompt_registry, create_resource_registry
from lob_mcp.examples.order import create_order_tool_registry
from lob_mcp.protocol import (
    JSONRPCErrorResponse,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    decode_message,
)
from lob_mcp.server import MCPServer
from lob_mcp.transport import TransportClosed, create_memory_transport_pair


@dataclass(slots=True)
class HTTPSession:
    session_id: str
    event_sink: EventSink
    client_transport: Any = field(init=False)
    server: MCPServer = field(init=False)
    responses: dict[int | str, asyncio.Future[bytes]] = field(default_factory=dict)
    notifications: asyncio.Queue[bytes] = field(default_factory=asyncio.Queue)
    completed_responses: dict[int | str, tuple[bytes, bytes]] = field(default_factory=dict)
    last_activity: float = field(default_factory=time.monotonic)
    server_task: asyncio.Task[None] = field(init=False)
    router_task: asyncio.Task[None] = field(init=False)

    def __post_init__(self) -> None:
        self.client_transport, server_transport = create_memory_transport_pair()
        self.server = MCPServer(
            server_transport,
            self.event_sink,
            name="lob-mcp-http-server",
            tool_registry=create_order_tool_registry(),
            resource_registry=create_resource_registry(),
            prompt_registry=create_prompt_registry(),
        )
        self.server_task = asyncio.create_task(self.server.serve())
        self.router_task = asyncio.create_task(self._route_output())

    async def dispatch(self, payload: bytes) -> bytes | None:
        message = decode_message(payload)
        future: asyncio.Future[bytes] | None = None
        if isinstance(message, JSONRPCRequest):
            completed = self.completed_responses.get(message.id)
            if completed is not None:
                previous_payload, previous_response = completed
                if previous_payload != payload:
                    raise ValueError("request id was reused with different payload")
                return previous_response
            future = asyncio.get_running_loop().create_future()
            self.responses[message.id] = future
        await self.client_transport.send(payload)
        if future is None:
            return None
        try:
            async with asyncio.timeout(15):
                response = await future
                self.completed_responses[message.id] = (payload, response)
                return response
        finally:
            self.responses.pop(message.id, None)

    async def close(self) -> None:
        await self.client_transport.close()
        await self.server.close()
        for task in (self.router_task, self.server_task):
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _route_output(self) -> None:
        try:
            while True:
                payload = await self.client_transport.receive()
                message = decode_message(payload)
                if isinstance(message, (JSONRPCResponse, JSONRPCErrorResponse)):
                    if message.id is not None:
                        future = self.responses.get(message.id)
                        if future is not None and not future.done():
                            future.set_result(payload)
                elif isinstance(message, JSONRPCNotification):
                    await self.notifications.put(payload)
        except TransportClosed:
            return


def create_http_app(
    *,
    token: str,
    allowed_origins: set[str] | None = None,
    event_sink: EventSink = discard_event,
    session_ttl: float = 30,
) -> FastAPI:
    app = FastAPI(title="LOB MCP Streamable HTTP")
    sessions: dict[str, HTTPSession] = {}
    origins = allowed_origins or {"http://localhost"}

    async def find_session(session_id: str | None) -> HTTPSession | None:
        session = sessions.get(session_id or "")
        if session is None:
            return None
        if time.monotonic() - session.last_activity > session_ttl:
            sessions.pop(session.session_id, None)
            await session.close()
            return None
        return session

    def authorize(authorization: str | None, origin: str | None) -> None:
        if authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="invalid bearer token")
        if origin not in origins:
            raise HTTPException(status_code=403, detail="origin is not allowed")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/mcp")
    async def post_mcp(
        request: Request,
        authorization: str | None = Header(default=None),
        origin: str | None = Header(default=None),
        mcp_session_id: str | None = Header(default=None),
        mcp_protocol_version: str | None = Header(default=None),
    ) -> Response:
        authorize(authorization, origin)
        if mcp_protocol_version != "2025-06-18":
            raise HTTPException(status_code=400, detail="unsupported protocol version")
        payload = await request.body()
        try:
            message = decode_message(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        session = await find_session(mcp_session_id)
        if session is None:
            if not isinstance(message, JSONRPCRequest) or message.method != "initialize":
                raise HTTPException(status_code=404, detail="MCP session not found")
            session_id = secrets.token_urlsafe(24)
            session = HTTPSession(session_id, event_sink)
            sessions[session_id] = session
        session.last_activity = time.monotonic()
        try:
            result = await session.dispatch(payload)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        headers = {"Mcp-Session-Id": session.session_id}
        if result is None:
            return Response(status_code=202, headers=headers)
        return Response(result, media_type="application/json", headers=headers)

    @app.get("/mcp")
    async def get_notifications(
        authorization: str | None = Header(default=None),
        origin: str | None = Header(default=None),
        mcp_session_id: str | None = Header(default=None),
    ) -> Response:
        authorize(authorization, origin)
        session = sessions.get(mcp_session_id or "")
        if session is None:
            raise HTTPException(status_code=404, detail="MCP session not found")
        try:
            async with asyncio.timeout(1):
                payload = await session.notifications.get()
        except TimeoutError:
            return Response(status_code=204)
        return Response(payload, media_type="application/json")

    @app.delete("/mcp")
    async def delete_session(
        authorization: str | None = Header(default=None),
        origin: str | None = Header(default=None),
        mcp_session_id: str | None = Header(default=None),
    ) -> Response:
        authorize(authorization, origin)
        session = sessions.pop(mcp_session_id or "", None)
        if session is None:
            raise HTTPException(status_code=404, detail="MCP session not found")
        await session.close()
        return Response(status_code=204)

    return app
