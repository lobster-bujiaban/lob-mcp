# 生产化风险与后续边界

LOB MCP 是教学和工程研究实现，当前不能直接宣称为生产级 MCP 网关。

## 上线前必须补强

- 将固定 Bearer Token 升级为 OAuth 2.1 / OIDC，并实现租户、用户和 Scope 授权。
- 将主密钥交给 KMS 或 Secret Manager，支持密钥版本、轮换和审计；`.env` 只适合本地运行。
- 将会话、SSE Event Store、限流器和审批锁迁移至 Redis/数据库，支持多副本部署。
- 对 Management API 增加认证、CSRF、防暴力请求、操作权限和管理员审计。
- 对 stdio command 使用命令白名单和沙箱，禁止用户任意配置可执行程序。
- 对远程 endpoint 实施 DNS/IP 校验、私网阻断和重绑定防护，防止 SSRF。
- 审计参数和结果需要字段级策略、保留周期、访问控制与合规删除。
- 增加 Migration 版本表和事务化迁移工具；当前 SQL 文件适合研究阶段。
- 增加 PostgreSQL、Redis、Server Process、HTTP Client 的指标、告警和容量限制。
- 为写操作设计幂等键、补偿事务和业务侧最终状态核验。

## 当前安全边界

- 浏览器只接触凭据引用，不返回凭据明文。
- Server 持有并解密业务凭据；模型上下文、调用参数和审计记录不保存密钥。
- 高风险工具必须经过持久化审批，审批前不会执行。
- Server 删除为软删除，Invocation 和 Event 作为审计事实保留。

