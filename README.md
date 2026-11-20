# Python Framework 3.4.0

Python 3.11–3.13 · FastAPI · SQLAlchemy 2.x async · PostgreSQL · Alembic。

本项目是模块化单体，采用单一 FastAPI API 进程。PostgreSQL 是唯一必需的外部数据基础设施；文件内容保存在配置的私有本地存储根目录中。基线**不要求 Redis、消息代理、Docker、KMS、独立 Worker 或自动清理任务**。

当前 OpenAPI 版本与应用版本均为 `3.4.0`。OpenAPI 快照位于 `docs/openapi.json`，一致性测试已随 2026-11-20 全量 pytest 通过。

## 安装（空 PostgreSQL 数据库）

1. 创建空 PostgreSQL 15+ 数据库，并设置 `DATABASE_URL=postgresql+asyncpg://...`（参考 `.env.example`）。
2. 先升级构建与审计工具：`python -m pip install --upgrade "pip>=26.2" "setuptools>=84.1"`。
3. 安装依赖：`python -m pip install -e '.[dev]'`。
4. 初始化结构和内置数据：`python -m scripts.init_database`。
5. 需要首次管理员时，显式设置 `FRAMEWORK_ADMIN_PASSWORD`（不少于 12 字符），执行 `python -m scripts.init_database --admin-user admin`。不存在默认管理员密码。
6. 升级既有数据库前先备份，核查 `alembic_version` 和存量数据，再执行 `alembic upgrade head` 与 `python -m scripts.init_database --seed-only`。

`schema.sql` 是当前 Alembic 链的离线 SQL 审阅快照，包含迁移历史中的中间状态，不是第二套建表入口。正常安装只使用 Alembic；不要在 Alembic 之后再次执行 `schema.sql`。

## 数据库与迁移

- 当前真实迁移链：`0_baseline -> 1_quality_remediation`。
- `0_baseline` 建立 13 张 `sf_*` 基础表及 `alembic_version`。
- `1_quality_remediation` 增加数据约束、查询索引和用户名大小写唯一索引。
- 新迁移必须追加到当前 head，禁止改写已应用 revision。
- `schema.sql` 已包含上述两版迁移的 DDL；它只用于离线审阅，不作为运行时初始化入口。
- ORM 字段修改必须同时提供迁移和真实 PostgreSQL 验证证据；未执行时必须标为 `NOT_RUN`。

## IAM 双契约

IAM users 存在两个不同且必须同时保持的 API 契约：

- `GET /api/v1/iam/users`：固定返回 capped array，最多 100 条；不得在同一路径协商为分页对象。
- `GET /api/v2/iam/users`：固定返回 `Page[UserSummaryResponse]`。
- `/api/v1/iam/users/legacy` 是兼容别名，仍返回 V1 数组。
- 任何新增文档、测试或客户端适配都不得把这两个契约合并。

## Seed 数据

`scripts/init_database.py` 是唯一 Seed 入口，当前 `SEED_VERSION` 为 `2026.11.20.2`。内置权限包括：

- `system:user:list`
- `file:upload`
- `file:read:all`
- `file:delete:all`

Seed 还会创建 `framework_admin` 角色和 `/iam/users` 菜单；不会覆盖已有账号、角色或授权。

## 文件授权与清理

- 文件访问必须先做服务端授权，再访问私有本地存储。
- 本地对象键不得包含路径穿越，不得通过符号链接访问配置根目录之外的路径。
- 删除采用持久化数据库 intent、PostgreSQL lease claim、live-record recheck 和孤儿扫描 grace period。
- `sf_file_cleanup_jobs.file_id` 故意不设外键，以便文件元数据删除后仍保留补偿记录。
- 文件清理由运维人员显式执行，**不得增加自动清理、定时任务或独立 Worker**。

### 显式运维流程

先以只读方式扫描超过宽限期的孤儿对象：

```bash
python -m scripts.reconcile_files scan-orphans --grace-seconds 3600
```

确认结果后，再写入持久化清理 intent：

```bash
python -m scripts.reconcile_files scan-orphans --grace-seconds 3600 --apply
```

随后显式领取并重试清理：

```bash
python -m scripts.reconcile_files retry-cleanup --limit 100 --lease-seconds 300
```

执行该命令的运维环境必须与 API 服务使用同一 PostgreSQL 和同一私有 `FILE_STORAGE_ROOT`。`--apply` 只写清理 intent；物理删除仍由 `retry-cleanup` 在 lease、live-record recheck 和对象存储状态复核后执行。

## 质量检查

以下命令是发布前应执行的门禁；2026-11-20 本地已验证结果见 `docs/VALIDATION.md`：

```bash
python -m pytest -q
python -m ruff format --check .
python -m ruff check app scripts migrations tests
python -m mypy app scripts migrations tests
python -m bandit -r app scripts migrations
python -m pip_audit
python -m compileall -q app scripts migrations tests
```

真实 PostgreSQL 集成测试需要设置 `TEST_DATABASE_URL`；未设置时相关测试会 skip。2026-11-20 已在临时 PostgreSQL 16 上通过全量测试、迁移生命周期、事务回滚、并发限流与清理租约，并完成 wheel 独立安装、空库初始化和 Uvicorn 启动验证。详细证据见 `docs/VALIDATION.md`；生产备份/恢复、容量与故障恢复、真实 clamd 扫描及安全审批永久排除于代码开发验证，不阻断代码交付验收。

## 文档入口

- `docs/USER-GUIDE.md`：安装、启动、认证、API 调用与故障排查。
- `docs/architecture.md`：架构、目录和依赖方向。
- `docs/engineering-contract.md`：工程边界和基础设施约束。
- `docs/ENGINEERING-STANDARDS.md`：命名、API、数据库和安全规范。
- `docs/BUSINESS-OPERATIONS.md`：当前业务操作矩阵。
- `docs/FRAMEWORK-CATALOG.md`：真实源码目录清单。
- `docs/VALIDATION.md`：当前验证状态与证据；未执行项保持 `NOT_RUN`。
- `docs/adr/0001-modular-monolith.md`：模块化单体 ADR。
- `docs/adr/0002-cookie-auth-csrf.md`：Cookie 会话与 CSRF ADR。
