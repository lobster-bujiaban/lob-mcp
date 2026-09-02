from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from lob_mcp.examples.order import create_order_tool_registry
from lob_mcp.persistence import MCPRepository, create_pool


class ServerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    transport: str = Field(pattern="^(stdio|http)$")
    endpoint: str | None = None
    command: list[str] | None = None
    credential_reference: str | None = None
    enabled: bool = True


class ToolCallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    server_id: uuid.UUID | None = None


def create_management_app(database_url: str, *, run_migrations: bool = True) -> FastAPI:
    pool = create_pool(database_url)
    tools = create_order_tool_registry()
    project_root = Path(__file__).resolve().parents[2]

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await pool.open()
        repository = MCPRepository(pool)
        if run_migrations:
            await repository.migrate(project_root / "migrations" / "001_initial.sql")
        app.state.repository = repository
        yield
        await pool.close()

    app = FastAPI(title="LOB MCP Management API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def repository() -> MCPRepository:
        return app.state.repository

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/servers")
    async def list_servers() -> list[dict[str, Any]]:
        return await repository().list_servers()

    @app.post("/api/servers", status_code=201)
    async def create_server(data: ServerCreate) -> dict[str, Any]:
        try:
            return await repository().create_server(data.model_dump())
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.delete("/api/servers/{server_id}", status_code=204)
    async def delete_server(server_id: uuid.UUID) -> None:
        if not await repository().soft_delete_server(server_id):
            raise HTTPException(status_code=404, detail="server not found")

    @app.get("/api/tools")
    async def list_tools() -> list[dict[str, Any]]:
        return tools.list_tools()

    @app.post("/api/tools/call")
    async def call_tool(data: ToolCallRequest) -> dict[str, Any]:
        trace_id = uuid.uuid4().hex
        invocation_id = await repository().start_invocation(
            capability_name=data.name,
            arguments=data.arguments,
            trace_id=trace_id,
            server_id=data.server_id,
        )
        started = time.perf_counter()
        try:
            result = await tools.call(data.name, data.arguments)
            status = "failed" if result.get("isError") else "succeeded"
            error = result["content"][0]["text"] if status == "failed" else None
        except Exception as exc:
            result = {"isError": True, "error": str(exc)}
            status = "failed"
            error = str(exc)
        await repository().complete_invocation(
            invocation_id,
            status=status,
            result=result,
            error=error,
            duration_ms=(time.perf_counter() - started) * 1000,
        )
        return {
            "invocationId": str(invocation_id),
            "traceId": trace_id,
            "status": status,
            "result": result,
        }

    @app.get("/api/invocations")
    async def list_invocations(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return await repository().list_invocations(limit)

    @app.get("/api/invocations/{invocation_id}/events")
    async def invocation_events(invocation_id: uuid.UUID) -> list[dict[str, Any]]:
        return await repository().invocation_events(invocation_id)

    web_dist = project_root / "web" / "dist"
    if web_dist.exists():
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")
    return app

