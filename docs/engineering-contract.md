# 工程开发、依赖与质量门禁

## 本地环境

- Python 3.11–3.13。
- PostgreSQL 15+。
- 采用 venv + pip；Docker 不是必需条件。
- PostgreSQL 是唯一必需的外部数据基础设施。
- 基线不使用 Redis、消息代理、KMS、独立 Worker 或自动清理任务。
- 文件内容保存在应用配置的私有本地存储根目录。

## 依赖边界

运行时：FastAPI、Uvicorn、Pydantic Settings、SQLAlchemy[asyncio]、asyncpg、Alembic、Argon2、python-multipart 和文件类型校验相关依赖。

开发：pytest、pytest-asyncio、httpx、openpyxl、Ruff、mypy、Bandit、pip-audit。

ClamAV/clamd 是可选本地文件扫描集成；启用恶意文件扫描时，扫描器不可用会使上传失败并返回 503。它不是队列、Worker 或后台任务系统。

## 架构约束

- 保持模块化单体和单一 FastAPI API 进程。
- 保持 Auth、IAM、File authorization 边界。
- 数据库业务写入和审计共享 service-owned transaction。
- IAM V1 users 固定返回 capped array；IAM V2 users 固定返回 page，不得合并契约。
- 文件清理必须保留 durable DB intent、PostgreSQL lease claim、live-record recheck 和孤儿扫描 grace period。
- 文件清理只能由显式运维 CLI 触发，不能加入自动清理、定时任务或独立 Worker。
- 新迁移必须追加到 `0_baseline -> 1_quality_remediation` 的现有链，禁止改写已应用 revision。

## 当前实现范围

当前源码包含：

- Auth Cookie 会话、CSRF、登录限流、退出和会话轮换。
- IAM 用户列表双契约与可见菜单。
- 文件上传、列表、元数据、下载、Range/ETag、删除和审计。
- PostgreSQL 登录限流、持久化文件清理 intent 和显式运维 CLI。
- 健康检查、统一错误响应、请求上下文和请求大小限制。

`dashboard`、`dictionary`、`foundation`、`notification`、`observability`、`preferences`、`scheduler`、`session_monitor` 仍为预留边界，不代表已交付业务功能。

## InStar / Codex

先扫描已有代码并复用公共函数与组件；只有存在两个以上真实调用方且无业务耦合时，才将跨模块通用能力提取到 `core` 或 `common`。禁止工具自动批准设计。项目级约束以 `AGENTS.md` 为准。

## 验证状态

2026-11-20 已执行 pytest、Ruff、mypy、Bandit、pip-audit、compileall、Alembic 真实升级/回滚、真实 PostgreSQL 事务与并发、OpenAPI 精确 diff、wheel 独立安装和 Uvicorn 启动。详细矩阵与残余生产验证项见 `docs/VALIDATION.md`。
