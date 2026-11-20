# 当前验证状态

验证日期：2026-11-20 17:14 CST。工作目录：`/Users/kyle/Documents/AI-Innovation-RD/python-framework`。解释器：Python 3.11.9。工作区不是 Git 仓库，因此没有 commit hash；wheel 校验和见下文。

本轮使用临时 PostgreSQL 16.2 实例执行真实数据库测试，数据库连接通过 `TEST_DATABASE_URL` 注入。该实例只用于验证，不是项目运行时依赖，也不改变“PostgreSQL 15+”的部署基线。

## 无效代码清理后复核

同日完成无效代码清理后，在未配置 `TEST_DATABASE_URL` 的环境重新执行门禁：

| 项目 | 状态 | 证据 |
|---|---|---|
| pytest 全量（未配置 PostgreSQL） | PASS | `105 passed, 7 skipped, 1 warning` |
| Ruff format / lint | PASS | `83 files already formatted`；`All checks passed!` |
| mypy / `--warn-unreachable` | PASS | `Success: no issues found in 85 source files` |
| Bandit | PASS | `bandit -r app scripts migrations -q` 无输出，退出码 0 |
| pip-audit | PASS | `No known vulnerabilities found`；本地包按预期跳过 |
| compileall | PASS | `app scripts migrations tests` 编译通过 |
| pip check | PASS | `No broken requirements found.` |
| wheel 构建与依赖元数据 | PASS | `python_framework-3.4.0-py3-none-any.whl` 构建成功；`httpx`、`openpyxl` 仅出现在 `dev` extra，`cryptography`、`PyYAML` 不再出现 |
| 真实 PostgreSQL | NOT_RUN | 清理后未配置 `TEST_DATABASE_URL`；上方历史矩阵不替代当前快照证据 |

本次删除的无调用文件为 `app/infrastructure/contracts.py`、`app/common/crypto.py` 和 `app/common/excel.py`；同时移除未使用的运行时依赖，并将测试夹具所需依赖调整到开发依赖。

## 关键修复

真实迁移测试发现并修复了一个离线 SQL 无法暴露的 P0 缺陷：

- 修复前：`alembic upgrade head` 打印升级成功，但异步连接退出时外层 SQLAlchemy 事务回滚，表实际不存在。
- 修复位置：`migrations/env.py` 在同步迁移入口完成后显式 `await connection.commit()`。
- 修复后：`0_baseline -> 1_quality_remediation`、downgrade、空库重建和 wheel 内置初始化都真实持久化。

同时将 `scripts/init_database.py` 改为以编程方式构造 Alembic `Config`，使安装后的 wheel 不再依赖源码树中的 `alembic.ini`。

## 验证矩阵

| 项目 | 状态 | 证据与说明 |
|---|---|---|
| pytest 全量（含真实 PostgreSQL） | PASS | `104 passed, 1 warning` |
| pytest 全量（未配置 PostgreSQL） | PASS | `97 passed, 7 skipped`；真实 PostgreSQL 用例按设计 skip，skip 不视为数据库 PASS |
| OpenAPI snapshot 精确 diff | PASS | `tests/test_api_contract.py::test_openapi_snapshot_matches_checked_in_contract` 随全量 pytest 通过 |
| Ruff format | PASS | `86 files already formatted` |
| Ruff lint | PASS | `All checks passed!` |
| mypy | PASS | `Success: no issues found in 88 source files` |
| Bandit | PASS | `bandit -r app scripts migrations -q` 无输出，退出码 0 |
| pip-audit | PASS | `No known vulnerabilities found`；本地包不在 PyPI，按预期跳过 |
| compileall | PASS | `app scripts migrations tests` 编译通过，退出码 0 |
| pip check | PASS | `No broken requirements found.` |
| wheel build | PASS | 生成 `python_framework-3.4.0-py3-none-any.whl`，SHA-256 `431f135a4fdfd32619936484feb1a092b8c007cbeea0b62e421049e5cb8b66ab` |
| wheel 独立安装 | PASS | 在全新 `/tmp/pf-wheel-smoke` 虚拟环境安装 wheel 及全部运行时依赖 |
| wheel 空库初始化 | PASS | 从 `/tmp` 运行 `python -m scripts.init_database`，迁移与 Seed 成功 |
| wheel Uvicorn 启动 | PASS | 从 `/tmp` 启动，确认导入路径为 venv 的 `site-packages` |
| `/health/live` | PASS | `{"status":"alive"}`，HTTP 200 |
| `/health/ready` | PASS | `{"status":"ready"}`，HTTP 200 |
| Alembic upgrade（真实数据库） | PASS | `0_baseline -> 1_quality_remediation` 持久化，`alembic_version` 为 head |
| Alembic downgrade / re-upgrade | PASS | `head -> 0_baseline -> head -> base -> head` 全部成功 |
| 真实 PostgreSQL 空库安装 | PASS | 独立临时数据库从空库升级到 head |
| 真实 PostgreSQL 旧库升级 | PASS | 先迁移到 `0_baseline`，再升级到 head |
| PostgreSQL schema/约束集成断言 | PASS | 大小写唯一索引、4 个 CHECK 约束和大小写重复用户名拒绝均通过 |
| 登录失败计数并发 | PASS | 5 个并发写入最终计数为 5，并正确设置锁定时间 |
| 文件清理 lease 并发 | PASS | 两个并发清理者只有一个获得 claim，对象只删除一次 |
| 本次代码与交付验收 | PASS | 用户明确将生产备份/恢复、目标环境负载/容量/故障恢复、真实 clamd 扫描、生产密钥与安全审批移出本次验证范围 |

## 代码开发永久排除项

以下项目不得作为代码开发、PR、CI 或发布前代码门禁的验证条件：

- 生产库备份、恢复及真实数据迁移演练。
- 目标环境负载、容量、重启和故障恢复验证。
- 真实 ClamAV/clamd 端到端扫描。`APP_ENV=production` 时应用要求 `FILE_MALWARE_SCAN_ENABLED=true`，否则拒绝启动；该运行配置策略保持不变。
- 生产密钥配置与安全审批。

上述项目只由生产部署、运维或安全流程处理，不得据此将代码开发状态标记为 `BLOCKED` 或 `NOT_RUN`。

## 已执行命令

```bash
env TEST_DATABASE_URL='postgresql+asyncpg://...' /tmp/python-framework-review-venv/bin/python -m pytest -q
/tmp/python-framework-review-venv/bin/ruff format --check .
/tmp/python-framework-review-venv/bin/ruff check .
/tmp/python-framework-review-venv/bin/mypy app scripts migrations tests
/tmp/python-framework-review-venv/bin/bandit -r app scripts migrations -q
env XDG_CACHE_HOME=/tmp/pip-audit-cache /tmp/python-framework-review-venv/bin/python -m pip_audit
/tmp/python-framework-review-venv/bin/python -m compileall -q app scripts migrations tests
/tmp/python-framework-review-venv/bin/python -m pip check
/tmp/python-framework-review-venv/bin/python -m pip wheel . --no-deps --no-build-isolation -w /tmp/pf-dist-smoke
env DATABASE_URL='postgresql+asyncpg://...' /tmp/pf-wheel-smoke/bin/python -m scripts.init_database
env DATABASE_URL='postgresql+asyncpg://...' FILE_STORAGE_ROOT=/tmp/pf-wheel-storage /tmp/pf-wheel-smoke/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

真实 PostgreSQL 集成测试覆盖以下场景：

- `tests/test_postgres_integration.py::test_postgres_empty_install_upgrade_downgrade_and_reupgrade`
- `tests/test_postgres_integration.py::test_login_failure_counter_is_atomic_under_concurrent_writers`
- `tests/test_postgres_integration.py::test_cleanup_lease_allows_only_one_concurrent_claim`

## 依赖与供应链

认证查询已在 SQL 中使用 PostgreSQL 双侧 `lower()`，无效用户名不会进入数据库查询；下载流已通过锁串行化 `next()` 与 `close()`。此前 `pip-audit` 发现的 `cryptography 46.0.7`、`pip 24.0`、`setuptools 65.5.0` 漏洞已整改：

- 无调用的 `crypto.py` 已删除，`cryptography` 已移出运行时依赖。
- 无调用的 `excel.py` 已删除；`openpyxl` 仅保留为测试开发依赖。
- 未直接使用的 `PyYAML` 已移除；`httpx` 调整为测试开发依赖。
- 构建后端约束为 `setuptools>=84.1`。
- README 要求安装前升级 `pip>=26.2` 和 `setuptools>=84.1`。
- 清理后 `pip-audit` 未发现已知漏洞。

## 已知告警与残余事项

- 全量 pytest 仍有一条 Starlette/FastAPI 测试客户端弃用告警：`httpx` 与 `starlette.testclient` 组合提示未来迁移到 `httpx2`。该告警不影响本轮结果，但应纳入后续依赖升级跟踪。
- `invalidate_user_authorization()` 作为未来 IAM 写接口的安全能力保留，其现有测试仅用于回归保护；该服务不是验收项，也不作为当前交付的验收证据。
- 历史登录限流 bucket 兼容只在从旧版本升级且保留旧 `sf_login_attempts` 数据时有意义；新库或清空该表后不需要处理，不是当前阻断项。

## 结论边界

本次历史快照中的本地静态质量门禁、全量单元/契约测试、真实 PostgreSQL 16 迁移生命周期、事务回滚、并发限流与清理租约、wheel 独立安装、空库初始化和 Uvicorn 启动均已通过。无效代码清理后的当前快照已完成 pytest、Ruff、mypy、Bandit、pip-audit、compileall 和 pip check；真实 PostgreSQL 为 `NOT_RUN`。

本次不声明生产运维、容量、真实 clamd 扫描或安全审批已经通过；这些项目已按要求移出本次验证范围，不构成 `BLOCKED`。
