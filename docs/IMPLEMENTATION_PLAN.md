# LOB MCP 实施计划

## 1. 目标与边界

LOB MCP 参考 FastMCP 与 MCP 官方协议，等价实现一条可以解释、运行、验证的主链路：Client 与 Server 建立连接，完成初始化和能力协商，发现并调用工具，最终把结构化结果返回 Agent。

首期不追求完整生态市场、远程多租户托管、任意代码执行或生产级高可用。浏览器自动化留在 `lob-browser`，状态图与 Checkpoint 留在 `lob-graph`，远程沙箱留在 `lob-hands`，跨项目统一观测留在最后的 `lob-observe`。

## 2. 核心领域模型

```text
ServerDefinition
  ├── transport / endpoint / command
  ├── credential_reference
  └── enabled

Connection
  ├── protocol_version
  ├── client_capabilities
  ├── server_capabilities
  └── lifecycle_state

CapabilitySnapshot
  ├── tools
  ├── resources
  └── prompts

Invocation
  ├── server_id / capability_name
  ├── arguments / result
  ├── status / error
  ├── started_at / completed_at
  └── approval / trace_id
```

生命周期必须明确表达：`disconnected → connecting → initializing → ready → closing → closed`。调用状态至少包含 `pending、awaiting_approval、running、succeeded、failed、cancelled、timed_out`。

## 3. 分阶段实施

### 阶段 0：协议模型与离线闭环

实现：

- JSON-RPC Request、Response、Notification 和 Error
- ID 关联、错误码、未知消息与非法消息处理
- 内存 Transport 和固定 Fake Server
- 协议事件日志与命令行演示

验收：

- 无网络完成一次 request/response 和 notification
- 并发请求不会串联响应
- 非法 JSON、未知 method 和取消均返回明确结果

### 阶段 1：stdio 与生命周期

实现：

- 子进程启动与 stdin/stdout 消息帧
- initialize、initialized、ping 和关闭流程
- stderr 隔离、进程退出、超时与协作式取消
- ClientInfo、ServerInfo、版本和能力协商

验收：

- 一条命令启动本地 Server 并进入 ready
- Server 异常退出后 Client 能给出结构化错误
- stdout 协议数据不被业务日志污染

### 阶段 2：Tools 与订单查询

实现：

- tools/list、tools/call 与 list_changed 通知
- JSON Schema 参数验证和结构化结果
- 订单查询示例 Server
- Agent Tool Adapter

验收：

- Agent 能发现并调用此前未知的 `order.query`
- 缺少订单号时在执行前阻断
- 工具异常、超时和取消能返回模型可理解的错误

### 阶段 3：Resources 与 Prompts

实现：

- resources/list、read、templates 和订阅
- prompts/list、get 与参数模板
- URI、MIME Type 和文本/二进制内容
- 资源变更通知和缓存失效

验收：

- Client 可读取订单状态说明资源
- Prompt 参数经过 Schema 校验
- 资源更新后能力快照可刷新

### 阶段 4：Streamable HTTP

实现：

- HTTP Transport、会话标识和协议版本 Header
- 流式消息、重连和服务端通知
- Origin 校验、认证失败和会话过期
- stdio/HTTP 共用相同协议核心

验收：

- 本地与远程 Transport 通过同一组协议样例
- 断线、重复消息和会话失效行为明确
- 不允许未授权来源调用 Server

### 阶段 5：多 Server 与能力路由

实现：

- Server Registry 和连接池
- 能力聚合、命名空间与冲突处理
- 健康检查、启停和能力快照
- 路由策略与结果归一化

验收：

- 同时连接订单、知识和 HTTP 三个 Server
- 同名工具不会静默覆盖
- 单个 Server 失败不影响其他连接

### 阶段 6：安全与治理

实现：

- 凭据引用和服务端加密存储
- 只读、写入、高风险三级工具策略
- 人工审批、参数修订和拒绝
- 域名白名单、超时、限流和结果裁剪
- 调用审计与敏感字段脱敏

验收：

- API Key 不进入浏览器、模型上下文和日志
- 高风险工具未经批准无法执行
- 审批决定和最终参数可追溯

### 阶段 7：持久化与管理台

实现：

- PostgreSQL Migration
- Server 配置、能力快照和 Invocation 表
- React Server 列表、能力浏览、在线调用
- 调用时间线、筛选、错误详情和取消

验收：

- 页面刷新后 Server 和调用记录仍存在
- UI 能区分连接、初始化、调用和结果状态
- 删除 Server 不级联删除历史审计

### 阶段 8：源码映射与兼容性

实现：

- FastMCP 核心入口与完整调用链映射
- 官方 Inspector 或兼容 Client 验证
- 功能、错误语义和生命周期差异清单
- 性能、并发、取消和故障样例报告

验收：

- 文档能够从一个 API 入口追踪到 Transport 与业务函数
- 固定兼容性矩阵可重复运行
- 明确列出未实现能力和生产化风险

## 4. 数据库设计草案

- `mcp_servers`：名称、Transport、端点、命令、状态和凭据引用
- `mcp_capability_snapshots`：协议版本、Server 信息和能力 JSON
- `mcp_invocations`：调用类型、能力名、参数摘要、结果摘要、状态和耗时
- `mcp_approvals`：风险级别、待执行动作、决定、修订参数和操作者
- `mcp_events`：连接与调用生命周期事件

历史 Invocation 和 Event 属于审计事实。删除 Server 时只标记配置失效，不级联删除历史调用。

## 5. 目录规划

```text
lob-mcp/
├── src/lob_mcp/
│   ├── protocol/
│   ├── transport/
│   ├── client/
│   ├── server/
│   ├── registry/
│   ├── gateway/
│   └── web/
├── examples/
│   ├── order_server/
│   ├── resource_server/
│   └── http_server/
├── web/
├── migrations/
├── docs/
└── tests/
```

测试目录属于规划，不要求首阶段为了凑覆盖率引入额外依赖；每阶段只增加对应协议和生命周期的定向验证。

## 6. 首个迭代任务

1. 建立 `pyproject.toml`、包结构和 CLI。
2. 定义 JSON-RPC 强类型消息。
3. 实现内存双向 Transport。
4. 实现 Client 请求关联和 Server method 分发。
5. 完成 initialize、ping、tools/list、tools/call。
6. 添加固定订单查询 Server。
7. 输出结构化事件，证明完整调用链。
8. 记录 FastMCP 对应入口和首轮差异。

## 7. 完成标准

最终项目应同时回答“协议如何工作”“框架如何封装”“企业系统如何安全接入”三个问题，并具备可运行代码、源码映射、差异清单、业务演示、持久化管理页面和定向验证结果。
