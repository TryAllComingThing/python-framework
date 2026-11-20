# ADR-0001 模块化单体

- 状态：ACCEPTED（当前基线）
- 日期：2026-11-20

## 背景

当前框架包含 IAM、Auth、Files、Audit 等相互关联的基础能力，规模不足以证明微服务拆分收益。文件清理需要持久化 intent 和 PostgreSQL lease，但不需要独立 Worker。

## 决策

- 采用单一 FastAPI API 进程的模块化单体。
- PostgreSQL 是唯一必需的外部数据基础设施，也是事务、审计、会话、限流和清理 intent 的事实源。
- 不使用 Redis、消息代理、KMS、独立 Scheduler Worker 或自动清理任务。
- 文件内容保存在配置的私有本地存储根目录。
- 外部技术适配统一放在 `app/infrastructure/`，基线不增加独立执行进程目录。
- 代码按领域模块分组，禁止跨域直接依赖 repository/query 私有实现。
- 数据库业务写入与审计共享 service-owned transaction。

## 收益

- 事务边界清晰。
- 本地 macOS 环境无需 Docker 或 Redis。
- 部署和运维入口简单。
- 模块边界仍可在未来通过 ADR 演进。

## 代价

- 共享部署节奏。
- 模块隔离依赖代码审查。
- 文件清理需要运维人员显式执行 CLI，而不是依赖后台任务。

## 约束

- IAM V1 capped array 与 V2 page 是两个独立契约。
- 新迁移只能追加到 `0_baseline -> 1_quality_remediation`。
- 没有执行证据时，所有验证项必须标为 `NOT_RUN`。
