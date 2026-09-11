from __future__ import annotations

import asyncio
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
from lob_mcp.governance import PersistentCredentialStore
from lob_mcp.persistence import MCPRepository, create_pool
from lob_mcp.runtime import ServerRuntimeManager


class ServerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    transport: str = Field(pattern="^(stdio|http)$")
    endpoint: str | None = None
    command: list[str] | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    credential_reference: str | None = None
    enabled: bool = True


class ToolCallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    server_id: uuid.UUID | None = None
    wait: bool = True


class ApprovalDecision(BaseModel):
    approved: bool
    operator: str = Field(min_length=1, max_length=100)
    revised_arguments: dict[str, Any] | None = None


class CredentialInput(BaseModel):
    secret: str = Field(min_length=1)


def create_management_app(
    database_url: str, *, master_key: str, run_migrations: bool = True
) -> FastAPI:
    pool = create_pool(database_url)
    built_in_tools = create_order_tool_registry()
    project_root = Path(__file__).resolve().parents[2]

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await pool.open()
        repository = MCPRepository(pool)
        if run_migrations:
            for migration in sorted((project_root / "migrations").glob("[0-9][0-9][1-9]_*.sql")):
                await repository.migrate(migration)
        credentials = PersistentCredentialStore(repository, master_key)
        runtime = ServerRuntimeManager(repository, credentials)
        app.state.repository = repository
        app.state.credentials = credentials
        app.state.runtime = runtime
        app.state.invocation_tasks = {}
        await runtime.load_enabled()
        yield
        for task in app.state.invocation_tasks.values():
            task.cancel()
        await runtime.close()
        await pool.close()

    app = FastAPI(title="LOB MCP Management API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["*"], allow_headers=["*"],
    )

    def repository() -> MCPRepository:
        return app.state.repository

    def runtime() -> ServerRuntimeManager:
        return app.state.runtime

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "pool": pool.get_stats()}

    @app.get("/api/servers")
    async def list_servers() -> list[dict[str, Any]]:
        return await repository().list_servers()

    @app.post("/api/servers", status_code=201)
    async def create_server(data: ServerInput) -> dict[str, Any]:
        try:
            server = await repository().create_server(data.model_dump())
            if server["enabled"]:
                try:
                    await runtime().connect(server)
                except Exception:
                    pass
            return await repository().get_server(uuid.UUID(server["id"])) or server
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.put("/api/servers/{server_id}")
    async def update_server(server_id: uuid.UUID, data: ServerInput) -> dict[str, Any]:
        server = await repository().update_server(server_id, data.model_dump())
        if server is None:
            raise HTTPException(status_code=404, detail="server not found")
        try:
            await runtime().refresh(server_id)
        except Exception:
            pass
        return await repository().get_server(server_id) or server

    @app.post("/api/servers/{server_id}/enabled")
    async def enable_server(server_id: uuid.UUID, enabled: bool) -> dict[str, Any]:
        if not await repository().set_server_enabled(server_id, enabled):
            raise HTTPException(status_code=404, detail="server not found")
        try:
            await runtime().refresh(server_id)
        except Exception:
            pass
        return await repository().get_server(server_id) or {}

    @app.post("/api/servers/{server_id}/refresh")
    async def refresh_server(server_id: uuid.UUID) -> dict[str, Any]:
        try:
            await runtime().refresh(server_id)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return await repository().get_server(server_id) or {}

    @app.get("/api/servers/{server_id}/capabilities")
    async def server_capabilities(server_id: uuid.UUID) -> dict[str, Any]:
        snapshot = await repository().latest_capability_snapshot(server_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="capability snapshot not found")
        return snapshot

    @app.delete("/api/servers/{server_id}", status_code=204)
    async def delete_server(server_id: uuid.UUID) -> None:
        await runtime().disconnect(server_id)
        if not await repository().soft_delete_server(server_id):
            raise HTTPException(status_code=404, detail="server not found")

    @app.post("/api/credentials", status_code=201)
    async def create_credential(data: CredentialInput) -> dict[str, str]:
        return {"reference": await app.state.credentials.put(data.secret)}

    @app.get("/api/tools")
    async def list_tools() -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for server in await repository().list_servers():
            snapshot = await repository().latest_capability_snapshot(uuid.UUID(server["id"]))
            if snapshot:
                result.extend({**tool, "serverId": server["id"], "server": server["name"]}
                              for tool in snapshot["tools"])
        return result or built_in_tools.list_tools()

    async def execute_invocation(invocation_id: uuid.UUID, data: ToolCallRequest) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            result = (await runtime().call_tool(data.server_id, data.name, data.arguments)
                      if data.server_id else await built_in_tools.call(data.name, data.arguments))
            status = "failed" if result.get("isError") else "succeeded"
            error = result.get("content", [{}])[0].get("text") if status == "failed" else None
        except asyncio.CancelledError:
            await repository().mark_cancelled(invocation_id)
            raise
        except Exception as exc:
            result, status, error = {"isError": True, "error": str(exc)}, "failed", str(exc)
        await repository().complete_invocation(
            invocation_id, status=status, result=result, error=error,
            duration_ms=(time.perf_counter() - started) * 1000,
        )
        return {"invocationId": str(invocation_id), "status": status, "result": result}

    @app.post("/api/tools/call")
    async def call_tool(data: ToolCallRequest) -> dict[str, Any]:
        trace_id = uuid.uuid4().hex
        invocation_id = await repository().start_invocation(
            capability_name=data.name, arguments=data.arguments, trace_id=trace_id,
            server_id=data.server_id,
        )
        if data.name.endswith("order.cancel"):
            approval_id = await repository().create_approval(
                invocation_id, data.name, "high", data.arguments
            )
            return {"invocationId": str(invocation_id), "traceId": trace_id,
                    "status": "awaiting_approval", "approvalId": str(approval_id)}
        task = asyncio.create_task(execute_invocation(invocation_id, data))
        app.state.invocation_tasks[invocation_id] = task
        task.add_done_callback(lambda _: app.state.invocation_tasks.pop(invocation_id, None))
        if not data.wait:
            return {"invocationId": str(invocation_id), "traceId": trace_id, "status": "running"}
        result = await task
        result["traceId"] = trace_id
        return result

    @app.post("/api/invocations/{invocation_id}/cancel")
    async def cancel_invocation(invocation_id: uuid.UUID) -> dict[str, str]:
        if not await repository().request_cancellation(invocation_id):
            raise HTTPException(status_code=409, detail="invocation is not cancellable")
        task = app.state.invocation_tasks.get(invocation_id)
        if task is not None:
            task.cancel()
        else:
            await repository().mark_cancelled(invocation_id)
        return {"status": "cancelled"}

    @app.get("/api/invocations")
    async def list_invocations(
        limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
        status: str | None = None, capability: str | None = None,
    ) -> list[dict[str, Any]]:
        return await repository().list_invocations(limit, offset, status, capability)

    @app.get("/api/invocations/{invocation_id}")
    async def invocation_detail(invocation_id: uuid.UUID) -> dict[str, Any]:
        invocation = await repository().get_invocation(invocation_id)
        if invocation is None:
            raise HTTPException(status_code=404, detail="invocation not found")
        invocation["events"] = await repository().invocation_events(invocation_id)
        return invocation

    @app.get("/api/invocations/{invocation_id}/events")
    async def invocation_events(invocation_id: uuid.UUID) -> list[dict[str, Any]]:
        return await repository().invocation_events(invocation_id)

    @app.get("/api/approvals")
    async def list_approvals(status: str | None = None) -> list[dict[str, Any]]:
        return await repository().list_approvals(status)

    @app.post("/api/approvals/{approval_id}/decision")
    async def decide_approval(approval_id: uuid.UUID, data: ApprovalDecision) -> dict[str, Any]:
        existing = next((item for item in await repository().list_approvals("pending")
                         if item["id"] == str(approval_id)), None)
        if existing is None:
            raise HTTPException(status_code=404, detail="pending approval not found")
        arguments = data.revised_arguments or existing["requested_arguments"]
        decision = "approved" if data.approved else "rejected"
        approval = await repository().decide_approval(
            approval_id, decision, arguments, data.operator
        )
        invocation_id = uuid.UUID(existing["invocation_id"])
        if not data.approved:
            await repository().complete_invocation(
                invocation_id, status="rejected", result={"decision": "rejected"},
                error="rejected by operator", duration_ms=0,
            )
            return approval or {}
        invocation = await repository().get_invocation(invocation_id)
        request = ToolCallRequest(
            name=existing["tool_name"], arguments=arguments,
            server_id=uuid.UUID(invocation["server_id"]) if invocation and invocation["server_id"] else None,
        )
        return {"approval": approval, "execution": await execute_invocation(invocation_id, request)}

    web_dist = project_root / "web" / "dist"
    if web_dist.exists():
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")
    return app
