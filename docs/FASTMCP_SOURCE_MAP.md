# FastMCP 4.0.1 源码映射

本项目以 FastMCP `4.0.1` 作为 Python 框架对照，以 MCP `2025-06-18` 规范作为协议依据。FastMCP 只作为开发依赖，不参与 LOB MCP 运行链路。

## 主调用链

```text
FastMCP.run()
  → TransportMixin.run_async()
  → stdio / create_streamable_http_app()
  → MCPOperationsMixin 注册 JSON-RPC Handler
  → Provider / LocalProvider 查找组件
  → FunctionTool.run() 校验并执行函数
  → ToolResult 转换为 MCP content / structuredContent
```

LOB MCP 对应链路：

```text
CLI serve-stdio / serve-http
  → StdioServerTransport / HTTPSession
  → MCPServer.serve() 与 method 分发
  → ToolRegistry / ResourceRegistry / PromptRegistry
  → Pydantic 校验并执行 handler
  → JSONRPCResponse 编码
```

## 文件和职责映射

| FastMCP 4.0.1 | LOB MCP | 说明 |
|---|---|---|
| `fastmcp/server/server.py: FastMCP` | `src/lob_mcp/server.py: MCPServer` | Server 聚合入口 |
| `server/mixins/mcp_operations.py` | `src/lob_mcp/server.py` | Tools、Resources、Prompts 协议处理 |
| `server/providers/local_provider/local_provider.py` | `tools.py`、`resources.py`、`prompts.py` | 本地组件注册和查找 |
| `tools/function_tool.py: FunctionTool.run` | `tools.py: ToolRegistry.call` | 参数校验、函数执行和结果转换 |
| `server/mixins/transport.py` | `transport/stdio.py`、`transport/http.py` | Transport 选择和运行 |
| `server/http.py: create_streamable_http_app` | `http_server.py: create_http_app` | Streamable HTTP 会话、SSE 和安全 |
| `client/client.py`、`client/mixins/*` | `client.py: MCPClient` | 初始化、能力发现和调用 |
| `client/group.py`、AggregateProvider | `gateway.py: MultiServerGateway` | 多 Server 聚合和命名空间 |
| Middleware、Transforms | `governance.py` | 审批、限流、脱敏和审计 |

## 关键差异

- FastMCP 支持 Provider、Transform、Middleware、Proxy、OpenAPI、OAuth、Tasks、Sampling、Elicitation 等完整框架能力；LOB MCP 只实现研究主链路。
- FastMCP 使用官方 Python SDK 的强类型协议对象；LOB MCP 保留手写 JSON-RPC 和 Transport，便于观察协议边界。
- FastMCP 支持列表分页、工具 outputSchema、图片/音频/嵌入资源等丰富内容；LOB MCP 当前主要返回文本和结构化 JSON。
- FastMCP 的 Streamable HTTP 复用官方 SDK Session Manager；LOB MCP 自行实现会话、SSE、事件重放和过期恢复。
- LOB MCP 额外实现 PostgreSQL 管理台、审批审计和数据库驱动的动态 Server 连接，属于协议之上的网关能力。

