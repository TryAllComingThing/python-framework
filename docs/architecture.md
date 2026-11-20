# Python Framework 架构与目录规范

## 1. 定位与原则

- 采用模块化单体，部署为单一 FastAPI API 进程，初期不拆微服务。
- PostgreSQL 是唯一必需的外部数据基础设施，也是事务、审计、会话、限流和文件清理 intent 的事实源。
- 文件内容保存在配置的私有本地存储根目录；不得访问根目录之外的任意文件，不得通过符号链接逃逸。
- 基线不要求 Redis、消息代理、Docker、KMS、独立 Worker 或自动清理任务。
- API 层只负责 HTTP、Schema、依赖注入和响应；应用服务负责用例编排和事务边界；Repository/Query 层负责持久化查询；Policy 层负责权限决策。
- OpenAPI 是 HTTP 契约权威。IAM V1 capped array 与 V2 page 是两个独立契约，不能在同一路径做表示协商。

## 2. 实际目录

```text
python-framework/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── alembic.ini
├── schema.sql
├── app/
│   ├── main.py                  # 唯一应用装配入口
│   ├── api/                     # 路由装配与 IAM 兼容导出
│   ├── common/                  # 业务无关通用契约与工具
│   ├── core/                    # 配置、数据库、错误、健康检查、中间件
│   ├── infrastructure/          # 存储、日志、恶意文件扫描、失败补偿日志
│   ├── models/                  # SQLAlchemy Base
│   └── modules/                 # 领域模块
│       ├── auth/
│       ├── iam/
│       ├── files/
│       ├── audit/
│       ├── dashboard/           # 预留边界
│       ├── dictionary/          # 预留边界
│       ├── foundation/          # 预留边界
│       ├── notification/        # 预留边界
│       ├── observability/       # 预留边界
│       ├── preferences/         # 预留边界
│       ├── scheduler/           # 预留边界；不是 Worker
│       └── session_monitor/     # 预留边界
├── migrations/
│   ├── env.py
│   ├── preflight.py
│   └── versions/
│       ├── 0_baseline.py
│       └── 1_quality_remediation.py
├── scripts/
│   ├── init_database.py
│   └── reconcile_files.py
├── tests/
└── docs/
```

外部技术适配统一放在 `app/infrastructure/`。基线没有独立执行进程目录；`app/modules/scheduler/` 只是预留业务边界，不包含调度器、队列或 Worker。

## 3. 领域模块内部结构

模块可按实际需要建立 `router.py`、`schemas.py`、`service.py`、`query.py`、`models.py`、`policy.py`、`errors.py` 和 `dependencies.py`，但不要机械创建空文件。路由不得直接执行 SQL；事务提交点由 service 统一管理；Repository/Query 不得自行 commit。

## 4. 依赖方向与事务

依赖方向为 `router -> service/query -> SQLAlchemy`，`service -> policy`。`core` 不依赖业务模块，跨模块协作通过公开 service 接口完成，禁止直接读取其他模块的 repository/query 私有实现。

一个 HTTP 用例的写事务由 service 或 Unit of Work 统一管理。数据库业务写入与审计必须共享同一个 service-owned transaction；失败时显式 rollback。异步路由中的阻塞文件 IO 必须通过线程池隔离。

## 5. 认证、授权与审计

认证采用数据库会话与 HttpOnly Cookie。Cookie 名称为 `sf_session`；登录要求可信 `Origin`，写操作要求可信 `Origin` 与 `X-CSRF-Token`。原始 session token 和 CSRF token 不落库，只保存 SHA-256 digest。

IAM 是单租户；停用角色不授予权限或数据范围。用户授权版本、会话撤销和审计必须保持事务一致。详细决策见 `docs/adr/0002-cookie-auth-csrf.md`。

## 6. PostgreSQL、迁移与文件清理

SQLAlchemy 2 使用 `AsyncSession`，每请求创建独立 session，使用 `asyncpg` 和受控连接池。迁移使用 Alembic，禁止在应用启动时 `create_all()`。

当前迁移链固定为：

```text
0_baseline -> 1_quality_remediation
```

新迁移只能追加到现有 head，不得改写已应用 revision。`schema.sql` 是离线 SQL 审阅快照，不是第二套建表入口。

文件清理使用持久化 DB intent、PostgreSQL lease claim、live-record recheck 和孤儿扫描 grace period。清理只通过显式运维 CLI 执行，不得增加自动清理、定时任务或独立 Worker。详细命令见 `README.md`。

## 7. API 契约与治理

- `GET /api/v1/iam/users`：固定 capped array，最多 100 条。
- `GET /api/v1/iam/users/legacy`：兼容数组别名。
- `GET /api/v2/iam/users`：固定分页 `Page[UserSummaryResponse]`。
- 每个业务操作应有稳定 `operationId`、权限码、错误响应、Schema 和测试。
- 下载接口支持单段 Range、ETag 和 `If-None-Match`；下载审计表示服务端内容已准备，不表示客户端完整接收。
- 健康检查区分 liveness 与 PostgreSQL readiness。

## 8. 质量门禁

发布前应执行 pytest、Ruff、mypy、Bandit、pip-audit、compileall、Alembic upgrade/offline SQL、真实 PostgreSQL 集成测试和 OpenAPI 精确 diff。没有命令输出和可追溯记录时一律标为 `NOT_RUN`，不得标记 PASS。
