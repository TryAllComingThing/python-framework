# 业务操作矩阵（当前源码）

| 资源 | 已实现 | 待实现或待权威需求确认 |
|---|---|---|
| Auth | 登录、当前用户、退出、会话凭据轮换 | 会话列表、管理员强制退出、更多管理操作 |
| IAM User V1 | `GET /api/v1/iam/users` 固定 capped array，最多 100 条 | 详情、创建、更新、删除、状态与角色授权 |
| IAM User V1 legacy | `GET /api/v1/iam/users/legacy` 兼容数组别名 | 不新增功能，仅保持兼容 |
| IAM User V2 | `GET /api/v2/iam/users` 固定分页 `Page[UserSummaryResponse]` | 详情、创建、更新、删除、状态与角色授权 |
| IAM Menu | 当前用户可见菜单 | 菜单管理 CRUD 与树约束 |
| Files | 上传、分页列表、元数据、下载、Range/ETag、删除 | 更复杂的共享策略、外部对象存储等 |
| Audit | 业务事务内写入；文件下载准备事件写入 | 查询、过滤、导出 |
| 预留模块 | 无业务实现 | dashboard、dictionary、foundation、notification、observability、preferences、scheduler、session_monitor |

## 契约说明

- IAM V1 数组与 V2 page 是两个独立 API 契约，必须同时保持。
- 文件下载审计事件为 `file.content_prepared`，表示服务端已准备内容，不表示客户端完整接收。
- 文件清理不是自动业务操作，只能通过 `scripts/reconcile_files.py` 由运维人员显式执行。
- 每个新增操作必须定义：权限码、Request、Response、HTTP 状态、数据范围、审计、异常和测试。
