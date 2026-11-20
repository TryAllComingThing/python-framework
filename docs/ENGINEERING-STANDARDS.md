# Python Framework 工程规范

## 命名与代码

- 模块、变量、函数使用 `snake_case`；类/Schema 使用 `PascalCase`；常量使用 `UPPER_SNAKE_CASE`。
- Router 只负责 HTTP、参数与响应；写事务归 Application Service；Repository/Query 不得 commit。
- 公共业务请求 Schema 采用 `*Request`，输出采用 `*Response`；ORM 不得直接作为响应模型暴露。
- 新增公共函数必须提供准确返回类型；安全、事务和文件 IO 函数必须说明副作用、失败模式与异常语义。
- 注释优先解释安全不变量、事务边界、失败补偿和异常语义。

## API 契约

- 既有 `/api/v1` 路径保持兼容；新增资源使用复数名词，特殊动作使用子资源。
- JSON API 必须声明 `response_model`；下载、204 和流式响应不包裹。
- 错误码独立于翻译，错误码与 HTTP 状态不得随意组合。
- 分页资源统一使用 `Page[T]`；权限 SQL 过滤必须在计数和分页前执行。
- IAM 是例外中的固定双契约：`GET /api/v1/iam/users` 返回 capped array；`GET /api/v2/iam/users` 返回 page。不得在同一路径做表示协商。
- 每个业务操作必须有稳定 `operationId`、权限码、错误响应、Schema 和测试。
- Cookie 认证写操作必须要求可信 `Origin` 和 `X-CSRF-Token`。

## 数据库与迁移

- 一个业务用例一个写事务；审计和业务写入同事务；失败显式 rollback。
- 用户名大小写唯一性和登录查询必须在 PostgreSQL 侧使用 `lower()`；Python 侧只用于规范化与限流 bucket，不得用 `casefold()` 替代数据库语义。
- 当前迁移链为 `0_baseline -> 1_quality_remediation`。
- 新迁移必须追加到现有 Alembic 链，禁止改写已应用 revision。
- ORM 字段修改必须同时提供迁移和真实 PostgreSQL 验证证据；未验证时标为 `NOT_RUN`。
- 应用启动时不得执行 `create_all()`。
- `schema.sql` 仅用于离线审阅，不是第二套 DDL 权威。

## 文件与安全

- 文件类型校验不得仅依赖扩展名或 `Content-Type`。
- 异步路由中的阻塞本地文件 IO 必须隔离到线程池。
- 文件访问必须先鉴权，再访问私有存储。
- 禁止删除配置存储根目录之外的任意文件，禁止符号链接穿越。
- 文件清理必须保留 durable DB intent、PostgreSQL lease claim、live-record recheck 和孤儿扫描 grace period。
- 不得增加自动清理、定时任务或独立 Worker；只允许显式运维 CLI。
- 菜单仅控制可见性，API 权限与数据范围始终在服务端校验。

## 质量门禁

发布前应执行：

```bash
python -m pytest -q
python -m ruff format --check .
python -m ruff check app scripts migrations tests
python -m mypy app scripts migrations tests
python -m bandit -r app scripts migrations
python -m pip_audit
python -m compileall -q app scripts migrations tests
```

真实 PostgreSQL 测试必须设置 `TEST_DATABASE_URL`。任何未执行项必须写 `NOT_RUN`；Ruff、mypy、Bandit、pip-audit、compileall、Alembic、真实 PostgreSQL 或 OpenAPI 精确 diff 未运行时不得宣称正式冻结。

### 代码开发永久排除项

以下项目不纳入代码开发、PR、CI 或发布前代码门禁，也不得因此将代码状态标记为 `BLOCKED` 或 `NOT_RUN`：

- 生产库备份、恢复及真实数据迁移演练。
- 目标环境负载、容量、重启和故障恢复验证。
- 真实 ClamAV/clamd 端到端扫描。
- 生产密钥配置与安全审批。

这些项目属于部署、运维或安全流程。`APP_ENV=production` 的运行配置约束仍由应用启动检查执行，但实机扫描验收不属于代码开发验证。
