English | [中文](README.cn.md)

# LOB MCP

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](./LICENSE)

**Status: research** — a readable MCP client/server and gateway. Demo order store is in-process; admin UI needs PostgreSQL. Not a production gateway.

CLI: `src/lob_mcp/cli.py` (`uv run lob-mcp <command>`).

## What

JSON-RPC MCP: initialize, tools / resources / prompts, memory + stdio + Streamable HTTP transports, `server::tool` aggregation, approval/audit, optional FastAPI admin.

## Run in 3 commands

Python 3.12+ and `uv`.

```bash
uv sync
uv run lob-mcp demo
uv run lob-mcp tools-demo
```

`demo` uses `create_memory_transport_pair()` — no child process, no DB, no model.  
`tools-demo` spawns `python -m lob_mcp.cli serve-stdio` and calls `order.query` with `ORD-20250902-001` (`src/lob_mcp/examples/order.py`).

## Architecture

```text
MCPClient  (src/lob_mcp/client.py)
  ↔ Transport: memory | stdio | Streamable HTTP
MCPServer  (src/lob_mcp/server.py)
  → ToolRegistry / ResourceRegistry / PromptRegistry
  → example order + knowledge registries

MultiServerGateway  (gateway.py)  names tools "{name}::{tool}"
GovernedGateway     (governance.py)  policy, approval, CredentialStore, audit
management.create_management_app  → PostgreSQL + React (./start.sh)
```

Protocol types: `src/lob_mcp/protocol/messages.py`.

## Commands that exist

| Command | What the code does |
|---|---|
| `demo` | in-memory `initialize` + `ping` |
| `stdio-demo` | same against a `serve-stdio` child; JSON-RPC on stdout, events on stderr |
| `tools-demo` | `tools/list` then `order.query` |
| `content-demo` | `docs://orders/status-guide`, `order.assistant` prompt |
| `http-demo` | child `serve-http` on `127.0.0.1:8765`, token `lob-mcp-demo-token`, then reconnect after TTL |
| `multi-server-demo` | `orders`, `backup`, `knowledge`, plus a pre-closed `offline` client; call `orders::order.query` |
| `governance-demo` | `order.cancel` is `HIGH` + approval; secret stays in `CredentialStore` |
| `serve-stdio` / `serve-http` | hidden servers used by the demos |
| `serve-admin` | management API; **requires `LOB_MCP_MASTER_KEY`** |

Admin:

```bash
./start.sh          # generates LOB_MCP_MASTER_KEY in .env, builds web/, runs serve-admin
./start.sh --port 8090
```

Default admin DB URL: `postgresql://localhost/lob_mcp` or `DATABASE_URL`.

Example tools on the stdio server: `order.query`, `order.cancel` (see `ORDERS` dict in `examples/order.py`).

## Boundaries

- Order “system” is a module-level dict, not a real ERP.
- HTTP demo token is hardcoded `lob-mcp-demo-token` in `serve_http`.
- FastMCP is a **dev extra** for source comparison (`pyproject.toml` `dependency-groups.dev`), not the runtime.

## License

Apache License 2.0. See [LICENSE](LICENSE).

## Contact

[chishishuan@gmail.com](mailto:chishishuan@gmail.com) · [GitHub Issues](https://github.com/lobster-bujiaban/lob-mcp/issues)
