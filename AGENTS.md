# 说明

# Development contract — Python Framework

- Preserve the modular monolith and the existing Auth/IAM/file authorization boundaries.
- Treat users default array and users pagination as distinct API contracts; do not silently change them.
- All file cleanup changes must retain durable DB intents, PostgreSQL lease claims, live-record rechecks, and a grace period for orphan scanning.
- Never delete arbitrary files outside the private configured local storage root; no symlink traversal.
- No Redis, message broker, Docker, KMS or standalone worker is required by this baseline.
- New migrations must append to the existing Alembic chain; never rewrite applied revisions.
- Run pytest, dependency checks, compileall, and real PostgreSQL integration tests where available. Clearly distinguish NOT_RUN from PASS.

## Contracts
- IAM users must return the capped array; IAM users must return a page. No same-path representation negotiation.
- IAM is single-tenant; inactive roles never grant permissions or scopes.
- Database writes and audit must share a service-owned transaction.
- Do not add automatic file cleanup or scheduled workers.

## 开发约束
- 文件类型校验不得仅凭扩展名或 Content-Type；所有阻塞本地文件 IO 在异步路由中必须隔离。
- ORM 字段修改必须同时提供迁移与真实 PostgreSQL 验证证据。
- 新增公共函数使用准确的返回类型；安全/事务相关函数解释副作用、失败模式与异常语义。
