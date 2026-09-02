# LOB MCP

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](./LICENSE)

从零掌握 MCP 的核心协议与工程链路，并参考 FastMCP 分阶段实现 MCP Client、MCP Server、能力协商、工具网关和企业系统接入。

本项目属于 [LOB AI 源码研究系列](../README.md)。目标不是只会配置一个现成 MCP Server，而是从协议初始化开始，理解 Agent 如何发现外部能力、校验参数、执行工具、读取资源，并在权限、凭据和审计边界内连接真实业务系统。

## 核心问题

- MCP 解决了什么问题，它与普通 Function Calling 有什么区别？
- Client 与 Server 如何初始化、协商协议版本和声明能力？
- Tools、Resources、Prompts 分别适合表达什么？
- stdio、Streamable HTTP 等传输方式如何选择？
- 一个 Agent 如何连接多个 Server，并解决工具命名冲突？
- 参数校验、超时、取消、审批、凭据和审计应该放在哪一层？
- 企业数据库和内部 API 如何通过 MCP 安全开放，而不是直接暴露给模型？

## 学习主链路

```text
用户自然语言请求
  → Agent / MCP Client
  → initialize 与能力协商
  → tools/list 能力发现
  → 模型选择 Tool
  → 参数 Schema 校验
  → tools/call
  → MCP Server
  → 数据库 / HTTP API / 企业系统
  → 结构化结果
  → Trace 与调用审计
```

## 首个业务演示

以“查询订单”为固定场景：

1. Agent 只知道用户希望查询订单状态。
2. MCP Client 连接订单 MCP Server，并发现 `order.query` 工具。
3. 模型根据工具 Schema 提取订单号并发起调用。
4. Server 在服务端读取凭据，访问模拟订单系统。
5. 调用结果以结构化内容返回，Agent 继续组织答案。
6. 管理页面展示初始化、能力发现、工具调用、耗时和错误。

后续增加知识资源、Prompt 模板、数据库查询和受审批的写操作，形成从只读查询到企业工具网关的完整演进。

## 阶段路线

- [x] 阶段 0：协议模型、JSON-RPC 与离线最小闭环
- [x] 阶段 1：stdio Client/Server 与生命周期
- [x] 阶段 2：Tools、Schema 校验和订单查询演示
- [ ] 阶段 3：Resources、Prompts 与订阅通知
- [ ] 阶段 4：Streamable HTTP、会话与断线恢复
- [ ] 阶段 5：多 Server 注册、能力聚合与工具路由
- [ ] 阶段 6：凭据隔离、审批、限流和调用审计
- [ ] 阶段 7：PostgreSQL、React 管理台与在线调试
- [ ] 阶段 8：FastMCP 源码映射、兼容性与最终差异清单

详细范围、交付物和验收标准见 [实施计划](./docs/IMPLEMENTATION_PLAN.md)。

## 首期技术基线

- Python 3.12+
- `uv` 管理环境、依赖与锁文件
- Pydantic 定义协议消息与业务 Schema
- FastAPI 承载管理 API 和后续 HTTP Transport
- PostgreSQL 保存 Server 配置、能力快照和调用审计
- React + TypeScript + Vite 实现管理与调试页面
- OpenAI-compatible 模型接口用于 Agent 演示

首阶段优先手写 JSON-RPC、生命周期和 stdio Transport，再引入 FastMCP 做兼容性对照，避免只会调用框架装饰器而不理解协议。

## 快速开始

安装依赖并运行离线最小闭环：

```bash
uv sync
uv run lob-mcp demo
```

演示通过内存双向 Transport 完成 `initialize → initialized → ping`，并逐行输出结构化协议事件，不需要模型、数据库或网络服务。

启动独立 Server 子进程并通过 stdin/stdout 完成相同协议流程：

```bash
uv run lob-mcp stdio-demo
```

stdio 的 stdout 只传输 JSON-RPC 消息，Server 事件写入 stderr，由 Client 独立读取，避免业务日志污染协议数据。

发现并调用订单查询工具：

```bash
uv run lob-mcp tools-demo
```

演示先通过 `tools/list` 动态发现 `order.query`，再通过 `tools/call` 查询固定订单 `ORD-20250902-001`。参数在工具执行前根据 Pydantic 生成的 JSON Schema 对应模型完成校验。

## 实施原则

1. 先完成无模型、可重复的协议闭环，再接入 Agent。
2. 协议层、传输层、能力层、业务 Adapter 和 UI 分开建模。
3. Server 持有业务凭据，Client 和模型不得收到密钥明文。
4. 只读能力优先；写操作必须声明风险等级并支持人工审批。
5. 每次调用保存 Server、Tool、参数摘要、状态、耗时和错误类型。
6. 固定成功、参数错误、超时、取消、断连和权限拒绝样例。
7. 对照 FastMCP 源码入口和调用链，明确记录自研实现的差异。

## 项目定位

LOB MCP 是教学与工程研究实现，不应直接宣称为未经验证的生产级 MCP 网关。项目关注协议可读性、运行过程可观察性和企业接入边界，为后续 `lob-graph`、`lob-hands` 与最终统一观测提供外部能力层。

## 许可证

本项目使用 Apache License 2.0 开源。
