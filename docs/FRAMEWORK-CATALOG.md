# Python Framework 真实模块目录及用途

本清单以当前工作区源码文件存在为准。文件存在不等于功能已经生产验收。

## 应用装配与 API

- `app/main.py`：唯一 FastAPI 应用装配入口。
- `app/api/router.py`：健康检查、Auth、IAM V1/V2 和 Files 路由装配。
- `app/api/iam_router.py`：IAM 模块路由的兼容导出面。

## 公共契约

- `app/common/i18n.py`
- `app/common/responses.py`
- `app/common/pagination.py`
- `app/common/files.py`
- `app/common/redaction.py`
- `app/common/openapi.py`

## 核心运行时

- `app/core/config.py`
- `app/core/database.py`
- `app/core/errors.py`
- `app/core/codes.py`
- `app/core/health.py`
- `app/core/middleware/context.py`
- `app/core/middleware/limits.py`

## 基础设施

- `app/infrastructure/storage.py`：私有本地对象存储与安全路径约束。
- `app/infrastructure/logging.py`：结构化日志。
- `app/infrastructure/malware.py`：本地 ClamAV/clamd 扫描适配。
- `app/infrastructure/upload_failures.py`：失败补偿日志。

## 业务模块

- `app/modules/auth/`：Cookie 会话、CSRF、登录限流、密码安全、认证服务和路由。
- `app/modules/iam/`：用户列表 V1/V2、菜单、模型、权限策略和查询。
- `app/modules/files/`：上传、列表、元数据、下载、Range/ETag、删除、清理 intent、查询和策略。
- `app/modules/audit/`：审计模型和事务内写入服务。
- `app/modules/dashboard/`、`dictionary/`、`foundation/`、`notification/`、`observability/`、`preferences/`、`scheduler/`、`session_monitor/`：预留业务边界，当前无业务实现。

`app/modules/scheduler/` 不是 Worker 或调度进程；基线不包含独立 Worker、Redis 或消息代理。

## 迁移

- `migrations/env.py`：Alembic 异步迁移环境。
- `migrations/preflight.py`：用户名大小写唯一性预检。
- `migrations/versions/0_baseline.py`：基线 revision。
- `migrations/versions/1_quality_remediation.py`：当前 head，增加约束与索引。

真实迁移链：`0_baseline -> 1_quality_remediation`。

## 脚本

- `scripts/init_database.py`：Alembic 初始化和幂等 Seed。
- `scripts/reconcile_files.py`：显式文件清理运维 CLI，不是定时任务。

## 测试

- `tests/test_api_contract.py`
- `tests/test_auth_and_iam.py`
- `tests/test_errors_and_i18n.py`
- `tests/test_file_cleanup.py`
- `tests/test_file_download_semantics.py`
- `tests/test_files_validation.py`
- `tests/test_http_contracts.py`
- `tests/test_middleware.py`
- `tests/test_migrations.py`
- `tests/test_postgres_integration.py`
- `tests/test_storage.py`
- `tests/test_upload_safety.py`

`tests/test_postgres_integration.py` 在未设置 `TEST_DATABASE_URL` 时会 skip，不能据此宣称真实 PostgreSQL 验证通过。配置真实数据库后，该文件覆盖空库安装、升级/回滚、约束、并发登录限流和清理 lease 互斥。`invalidate_user_authorization()` 相关测试仅为保留服务的回归保护，不是验收项。

## 文档

- `README.md`
- `docs/architecture.md`
- `docs/engineering-contract.md`
- `docs/ENGINEERING-STANDARDS.md`
- `docs/USER-GUIDE.md`
- `docs/BUSINESS-OPERATIONS.md`
- `docs/FRAMEWORK-CATALOG.md`
- `docs/VALIDATION.md`
- `docs/openapi.json`
- `docs/system-foundation-mapping.md`
- `docs/adr/0001-modular-monolith.md`
- `docs/adr/0002-cookie-auth-csrf.md`
