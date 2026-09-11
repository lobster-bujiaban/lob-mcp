[English](README.md) | 中文

# LOB MCP

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](./LICENSE)

**状态：研究** — 可读的 MCP Client/Server 与网关。演示订单是进程内字典；管理台需要 PostgreSQL。不是生产网关。

CLI：`src/lob_mcp/cli.py`（`uv run lob-mcp <command>`）。

## What

JSON-RPC MCP：initialize、tools / resources / prompts，memory + stdio + Streamable HTTP，`server::tool` 聚合，审批/审计，可选 FastAPI 管理台。

## Run in 3 commands

Python 3.12+ 和 `uv`。

```bash
uv sync
uv run lob-mcp demo
uv run lob-mcp tools-demo
```

`demo` 用 `create_memory_transport_pair()`，无子进程、无库、无模型。  
`tools-demo` 拉起 `python -m lob_mcp.cli serve-stdio`，调用 `order.query`，订单号 `ORD-20250902-001`（`src/lob_mcp/examples/order.py`）。

## Architecture

```text
MCPClient  (src/lob_mcp/client.py)
  ↔ Transport: memory | stdio | Streamable HTTP
MCPServer  (src/lob_mcp/server.py)
  → ToolRegistry / ResourceRegistry / PromptRegistry
  → 示例 order + knowledge 注册表

MultiServerGateway  (gateway.py)  工具名 "{name}::{tool}"
GovernedGateway     (governance.py)  策略、审批、CredentialStore、审计
management.create_management_app  → PostgreSQL + React (./start.sh)
```

协议类型：`src/lob_mcp/protocol/messages.py`。

## 实际存在的命令

| 命令 | 代码在做什么 |
|---|---|
| `demo` | 内存里 `initialize` + `ping` |
| `stdio-demo` | 对着 `serve-stdio` 子进程做同样的事；stdout 是 JSON-RPC，事件在 stderr |
| `tools-demo` | `tools/list` 再 `order.query` |
| `content-demo` | `docs://orders/status-guide`、`order.assistant` prompt |
| `http-demo` | 子进程 `serve-http` 监听 `127.0.0.1:8765`，token `lob-mcp-demo-token`，TTL 过后再重连 |
| `multi-server-demo` | `orders`、`backup`、`knowledge`，外加预先关掉的 `offline`；调用 `orders::order.query` |
| `governance-demo` | `order.cancel` 为 `HIGH` 且要审批；密钥留在 `CredentialStore` |
| `serve-stdio` / `serve-http` | 给演示用的隐藏服务 |
| `serve-admin` | 管理 API；**必须有 `LOB_MCP_MASTER_KEY`** |

管理台：

```bash
./start.sh          # 在 .env 生成 LOB_MCP_MASTER_KEY，构建 web/，跑 serve-admin
./start.sh --port 8090
```

默认库：`postgresql://localhost/lob_mcp` 或 `DATABASE_URL`。

stdio 服务上的示例工具：`order.query`、`order.cancel`（见 `examples/order.py` 的 `ORDERS`）。

## 边界

- 「订单系统」是模块级 dict，不是真实 ERP。
- HTTP demo 的 token 在 `serve_http` 里写死为 `lob-mcp-demo-token`。
- FastMCP 是 **dev extra**，用来对照源码（`pyproject.toml` `dependency-groups.dev`），不是运行时。

## 许可证

Apache License 2.0，见 [LICENSE](LICENSE)。

## 联系

[chishishuan@gmail.com](mailto:chishishuan@gmail.com) · [GitHub Issues](https://github.com/lobster-bujiaban/lob-mcp/issues)
