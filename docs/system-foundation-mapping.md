# System Foundation 对照边界

本仓库不内置 System Foundation V1.8 外部候选基线，也不声称已实现其完整 90 项业务 API、12 模块 README、PRD/HLD/LLD、RTM 或外部 ADR。

外部候选文档如果需要在评审中使用，应以受控来源、版本标识和校验和引用；不得把未随仓库交付的外部路径或旧 Redis/Scheduler ADR 写成可验证仓库路径。

## 当前仓库可核验范围

- 当前 HTTP 契约以 `docs/openapi.json` 和应用源码为准。
- 当前 OpenAPI 版本为 `3.4.0`，静态可见 15 个 operation。
- 当前真实迁移链为 `0_baseline -> 1_quality_remediation`。
- `GET /health/live` 与 `GET /health/ready` 是工程探针，不计入外部候选的 90 个业务 API。
- 当前已实现 Auth、IAM 最小查询、Files 与 Audit 的有限纵切。
- `dashboard`、`dictionary`、`foundation`、`notification`、`observability`、`preferences`、`scheduler`、`session_monitor` 是预留业务边界，不代表实现。

## 架构对照

- 本仓库采用模块化单体和单一 FastAPI API 进程。
- PostgreSQL 是唯一必需的外部数据基础设施。
- 不使用 Redis、消息代理、KMS、独立 Worker 或自动清理任务。
- 文件清理由 `scripts/reconcile_files.py` 显式触发。
- Cookie 会话和 CSRF 决策见 `docs/adr/0002-cookie-auth-csrf.md`。

在外部候选基线正式签审并进入仓库前，本仓库不得声称 System Foundation API、数据库或模块范围已完全对齐。
