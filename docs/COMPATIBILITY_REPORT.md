# MCP 兼容性与故障验证报告

验证日期：2026-09-02。协议基线：MCP `2025-06-18`。官方兼容客户端：`@modelcontextprotocol/inspector`。

## 官方 Inspector 结果

| Transport / 方法 | 结果 | 说明 |
|---|---|---|
| stdio initialize | 通过 | 协议版本、ServerInfo、Capabilities 正常 |
| stdio tools/list | 通过 | Inspector 正确识别 Pydantic JSON Schema |
| stdio tools/call | 通过 | 文本和 structuredContent 均可识别 |
| stdio resources/list | 通过 | 正确识别 URI、名称和 MIME Type |
| stdio prompts/list | 通过 | 正确识别必填 Prompt 参数 |
| Streamable HTTP POST | 通过 | JSON 响应、Session ID、协议 Header |
| Streamable HTTP GET SSE | 通过（定向验证） | `text/event-stream`、事件 ID、Last-Event-ID |
| DELETE 会话 | 通过 | Client 主动终止会话 |

复现命令：

```bash
npx -y @modelcontextprotocol/inspector --cli \
  --config inspector.mcp.json --server lob-mcp --method tools/list
```

## 故障和治理验证

| 场景 | 预期 | 结果 |
|---|---|---|
| 非法 JSON | JSON-RPC Parse error | 通过 |
| 未知 method | `-32601` | 通过 |
| 未知工具 / 参数错误 | `-32602` | 通过 |
| stdio Server 退出 | 待处理请求失败且状态隔离 | 通过 |
| Client 超时 | 发送 cancelled notification | 通过 |
| 后台调用取消 | Invocation `cancelled`，事件 `started → cancelled` | 通过 |
| HTTP 无 Token | 401 | 通过 |
| HTTP 非法 Origin | 403 | 通过 |
| HTTP 非法协议版本 | 400 | 通过 |
| HTTP 会话过期 | 404 后自动重新 initialize | 通过，`reconnectCount=1` |
| 相同 ID 同内容重放 | 返回缓存响应 | 通过 |
| 相同 ID 不同内容 | 409 | 通过 |
| 多 Server 同名工具 | 命名空间隔离 | 通过 |
| 单 Server 失败 | 其他 Server 继续工作 | 通过 |
| 高风险调用 | 审批前不执行 | 通过 |
| 审批参数修订 | 以最终参数执行并审计 | 通过 |
| 敏感字段 | 日志和审计脱敏 | 通过 |
| 域名白名单 / 限流 | 拒绝越权调用 | 通过 |

## 已知兼容边界

- 列表接口接受 cursor，但当前数据量小，尚未返回 nextCursor 分页。
- 不支持 Roots、Sampling、Elicitation、Logging、Completion 和 MCP Tasks。
- 不支持工具图片、音频、ResourceLink、EmbeddedResource 等全部内容类型。
- HTTP 使用固定 Bearer Token，不是 MCP OAuth 2.1 授权流程。
- SSE 事件历史保存在进程内，重启后不能继续重放；生产环境应使用 Redis 或数据库事件存储。
- 管理 API 的取消可终止本进程 Task，并触发 MCP cancelled notification；已启动的第三方业务副作用不能自动回滚。

