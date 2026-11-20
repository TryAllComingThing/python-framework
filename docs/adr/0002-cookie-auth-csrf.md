# ADR-0002 Cookie 会话与 CSRF

- 状态：ACCEPTED（当前基线）
- 日期：2026-11-20

## 背景

浏览器客户端需要服务端可撤销的登录会话，同时避免把会话令牌暴露给 JavaScript。框架使用 PostgreSQL 保存会话状态，不引入 Redis 或外部会话服务。

## 决策

### 会话存储

- 登录成功后创建数据库会话记录。
- 原始 session token 只写入 HttpOnly Cookie `sf_session`；数据库只保存其 SHA-256 digest。
- CSRF token 返回给客户端；数据库只保存其 SHA-256 digest。
- 会话记录包含 `auth_version`、`expires_at`、`revoked_at` 和创建时间。
- 退出、轮换或授权变更通过 service-owned transaction 更新会话并写入审计。

### Cookie 属性

- `HttpOnly=true`。
- `SameSite=Lax`。
- `Path=/`。
- 本地和测试环境可关闭 `Secure`；其他环境必须启用 `Secure`。
- Cookie 最大年龄与配置的 session TTL 一致。

### 登录与写操作校验

- Cookie 认证关闭时，即使请求携带 `sf_session` 也必须拒绝。
- 登录必须启用 Cookie 认证，并校验可信 `Origin`。
- 登录成功返回 CSRF token。
- 所有 Cookie 认证的写操作必须同时校验可信 `Origin` 和 `X-CSRF-Token`。
- 缺失或错误 CSRF token 统一返回 403，不泄露令牌有效性细节。
- 会话不存在、已撤销、已过期、用户停用或 `auth_version` 不匹配时返回 401。

### 授权失效

- 用户角色、权限或状态变更必须递增 `auth_version` 并撤销现有会话。
- 授权版本更新、会话撤销和审计写入必须处于同一事务。
- 停用角色不授予权限或数据范围。

### OpenAPI

- OpenAPI 安全方案使用 `APIKeyCookie`，Cookie 名称为 `sf_session`。
- 登录、退出、上传和删除等写操作在 OpenAPI 中声明必要的 `Origin` 和 `X-CSRF-Token` 参数。

## 失败模式

- CSRF 校验失败：返回 403，不执行写操作。
- 会话过期或撤销：返回 401。
- 数据库不可用：返回 503。
- 审计提交失败：业务事务回滚，不产生“业务成功但审计缺失”的状态。

## 后果

- 不依赖 Redis 或其他会话缓存。
- 会话撤销依赖 PostgreSQL。
- 客户端必须保存并在写请求中回传 CSRF token。
- 跨域部署必须显式配置 `CORS_ORIGINS` 和 `CSRF_ORIGINS`，禁止通配符。

## 验证状态

相关测试已随 2026-11-20 全量 pytest 和真实 PostgreSQL 集成测试执行，包括授权版本失效、会话撤销与审计同事务回滚。当前证据见 `docs/VALIDATION.md`。
