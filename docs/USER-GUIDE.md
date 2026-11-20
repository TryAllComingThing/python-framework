# Python Framework 使用手册

适用版本：`3.4.0`。本手册面向本地开发、联调和后端集成人员，介绍安装、数据库初始化、启动、在线 API 文档、认证与 CSRF、IAM、文件接口、健康检查和常见故障排查。

## 1. 当前能力与边界

当前应用是一个 FastAPI 模块化单体，PostgreSQL 是唯一必需的外部数据基础设施，文件内容保存在服务端配置的私有本地目录。

已实现的 HTTP 能力：

| 能力 | 路径 | 说明 |
|---|---|---|
| 登录 | `POST /api/v1/auth/login` | Cookie 会话登录，返回 CSRF token |
| 当前用户 | `GET /api/v1/auth/me` | 返回用户 ID、用户名和有效权限 |
| 会话轮换 | `POST /api/v1/auth/rotate` | 吊销旧会话并签发新 Cookie/CSRF token |
| 退出 | `POST /api/v1/auth/logout` | 吊销当前会话并清除 Cookie |
| IAM V1 用户 | `GET /api/v1/iam/users` | 固定返回数组，最多 100 条 |
| IAM V1 兼容别名 | `GET /api/v1/iam/users/legacy` | 与 V1 相同的数组契约 |
| IAM V2 用户 | `GET /api/v2/iam/users` | 固定返回分页对象 |
| IAM 菜单 | `GET /api/v1/iam/menus` | 返回当前用户可见菜单 |
| 文件 | `/api/v1/files` | 上传、分页列表、元数据、下载、Range/ETag、删除 |
| 健康检查 | `/health/live`、`/health/ready` | 进程存活与 PostgreSQL 就绪检查 |

当前没有 IAM 用户创建、更新、删除、角色授权或授权撤销 HTTP 写接口。`invalidate_user_authorization()` 是保留在服务层、用于未来 IAM 写接口的安全能力，不是当前 API，也不作为验收项。

当前基线不要求 Redis、消息代理、Docker、KMS、独立 Worker 或自动文件清理任务。`dashboard`、`dictionary`、`foundation`、`notification`、`observability`、`preferences`、`scheduler`、`session_monitor` 等目录是预留边界，不代表已有业务 API。

## 2. 环境要求

- Python `3.11` 至 `3.13`。
- PostgreSQL `15+`。
- 可写的私有本地文件目录，默认 `./var/uploads`。
- 可选：`curl` 和 `jq`，用于执行本手册中的 API 示例。

先确认版本：

```bash
python3 --version
psql --version
```

## 3. 安装依赖

在项目根目录创建虚拟环境。以下命令假定从源码目录运行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade "pip>=26.2" "setuptools>=84.1"
python -m pip install -e '.[dev]'
```

安装完成后可确认导入路径和命令：

```bash
python -c 'import app; print(app.__file__)'
python -m uvicorn --version
```

Windows PowerShell 激活命令为 `.venv\Scripts\Activate.ps1`；后续示例以 macOS/Linux 的已经激活虚拟环境为前提。

## 4. 准备 PostgreSQL 与配置

### 4.1 创建数据库

示例使用本机 PostgreSQL，数据库名为 `python_framework`：

```bash
createdb -h 127.0.0.1 -U postgres python_framework
```

也可以先进入 `psql` 后执行：

```sql
CREATE DATABASE python_framework;
```

数据库账号需要具备建表、建索引和迁移所需的权限。使用已有数据库时，跳过创建步骤。

### 4.2 创建 `.env`

从示例复制配置：

```bash
cp .env.example .env
```

本地开发的最小可用配置如下。请将数据库用户名、密码和主机替换为实际值：

```dotenv
APP_ENV=local
LOG_LEVEL=INFO
DEFAULT_LOCALE=zh-CN

DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/python_framework
COOKIE_AUTH_ENABLED=true
SESSION_TTL_HOURS=8

CORS_ORIGINS=["http://127.0.0.1:8000","http://localhost:8000"]
CSRF_ORIGINS=["http://127.0.0.1:8000","http://localhost:8000"]
TRUSTED_HOSTS=["127.0.0.1","localhost"]

FILE_STORAGE_ROOT=./var/uploads
MAX_REQUEST_BYTES=10485760
FILE_MAX_BYTES=5000000

FILE_MALWARE_SCAN_ENABLED=false
FILE_CLAMD_SOCKET=/run/clamav/clamd.ctl
```

关键配置说明：

| 变量 | 作用 | 注意 |
|---|---|---|
| `DATABASE_URL` | SQLAlchemy asyncpg 连接串 | 必须是 `postgresql+asyncpg://` |
| `COOKIE_AUTH_ENABLED` | 是否启用 Cookie 会话认证 | 本地需要使用 Auth、IAM、Files API 时必须为 `true` |
| `CORS_ORIGINS` | 允许携带凭据的浏览器 Origin | 必须是明确 HTTP(S) Origin，不允许 `*` |
| `CSRF_ORIGINS` | 登录和所有 Cookie 写操作信任的 Origin | 必须是 `CORS_ORIGINS` 的子集 |
| `TRUSTED_HOSTS` | Host 请求头白名单 | 使用局域网 IP 访问时，要加入对应 IP 或主机名 |
| `FILE_STORAGE_ROOT` | 私有文件存储根目录 | 必须是普通目录，不能是符号链接 |
| `MAX_REQUEST_BYTES` | 整个 HTTP 请求的大小上限 | 默认 10 MiB，包含 multipart 开销 |
| `FILE_MAX_BYTES` | 单文件内容上限 | 默认 5,000,000 字节 |
| `FILE_MALWARE_SCAN_ENABLED` | 是否调用本地 clamd 扫描上传 | 扫描器不可用时上传返回 503 |
| `SESSION_TTL_HOURS` | 会话有效小时数 | 默认 8，范围 1 至 720 |

`Origin` 必须与配置完全一致，包括协议、主机和端口，且不能带路径或末尾斜杠。例如，通过 `http://localhost:8000/docs` 访问时，`http://localhost:8000` 必须同时位于 `CORS_ORIGINS` 和 `CSRF_ORIGINS`。

`FRAMEWORK_ADMIN_PASSWORD` 是一次性初始化命令使用的 shell 环境变量，不要写入仓库，也不要依赖 `.env` 自动注入。具体用法见下一节。

`APP_ENV=production` 时，应用启动还会强制检查明确配置的 CORS、`TRUSTED_HOSTS` 和 `FILE_MALWARE_SCAN_ENABLED=true`。这些是运行时配置策略，不代表代码开发阶段执行真实 clamd 扫描或生产安全审批。

## 5. 初始化数据库和首个管理员

推荐使用统一入口完成“迁移到 head + 写入内置 Seed”：

```bash
export FRAMEWORK_ADMIN_PASSWORD='请替换为至少12字符的强密码'
python -m scripts.init_database --admin-user admin
unset FRAMEWORK_ADMIN_PASSWORD
```

该命令会：

- 将 Alembic 迁移升级到当前 head。
- 幂等写入内置权限、`framework_admin` 角色和 `/iam/users` 菜单。
- 在指定用户名不存在时创建一个启用状态的管理员。
- 不提供默认管理员，也不会重置或提升已有账号。

管理员密码至少 12 个字符。若 `admin` 已存在，再次带 `--admin-user admin` 执行会报错，这是为了避免静默覆盖账号；后续账号管理应通过正式 IAM 流程实现。

只初始化内置数据、不创建管理员：

```bash
python -m scripts.init_database
```

已有数据库升级可执行：

```bash
python -m alembic upgrade head
python -m scripts.init_database --seed-only
```

当前迁移链为 `0_baseline -> 1_quality_remediation`。新迁移只能追加到当前 head，不能改写已应用 revision。`schema.sql` 仅用于离线审阅，不是运行时初始化入口，不要在 Alembic 之后再次执行它。

检查迁移状态：

```bash
python -m alembic current
python -m alembic heads
```

## 6. 启动服务

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

`--reload` 仅适合本地开发。生产或联调环境应去掉 `--reload`，并由部署平台管理进程生命周期。

应用启动不会自动执行数据库迁移，也不会自动创建管理员。先完成上一节初始化再启动。当前文件存储目录会在应用启动时创建并校验。

如需从局域网访问，可监听全部接口：

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

此时还必须将实际访问地址加入 `TRUSTED_HOSTS`、`CORS_ORIGINS` 和 `CSRF_ORIGINS`。例如通过 `http://192.168.1.10:8000/docs` 访问，就要加入：

```dotenv
CORS_ORIGINS=["http://127.0.0.1:8000","http://192.168.1.10:8000"]
CSRF_ORIGINS=["http://127.0.0.1:8000","http://192.168.1.10:8000"]
TRUSTED_HOSTS=["127.0.0.1","localhost","192.168.1.10"]
```

## 7. 在线 API 文档

服务启动后可访问：

| 地址 | 内容 |
|---|---|
| `http://127.0.0.1:8000/docs` | Swagger UI，可直接调试接口 |
| `http://127.0.0.1:8000/redoc` | ReDoc 阅读视图 |
| `http://127.0.0.1:8000/openapi.json` | 在线 OpenAPI 3 文档 |

下载在线 OpenAPI：

```bash
curl -sS http://127.0.0.1:8000/openapi.json -o openapi.json
```

仓库内快照 `docs/openapi.json` 由契约测试保护，不应手工修改来绕过契约差异。

在 Swagger UI 中调试时：

1. 使用与 `CSRF_ORIGINS` 完全匹配的地址打开 `/docs`。
2. 调用 `POST /api/v1/auth/login`；若界面显示 `Origin` 参数，请填写与当前访问地址一致的值。浏览器会保存服务端返回的 `sf_session` Cookie。
3. 从登录响应的 `data.csrf_token` 复制 CSRF token。
4. 调用上传、删除、轮换或退出接口时，在 `X-CSRF-Token` 请求头中填写该 token。

`Origin` 由浏览器自动发送，但值必须与应用配置一致；从 `127.0.0.1` 和 `localhost` 打开页面会被视为两个不同 Origin。

## 8. 登录、Cookie 与 CSRF

### 8.1 登录

```bash
curl -sS -c cookies.txt \
  -H 'Origin: http://127.0.0.1:8000' \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"请替换为管理员密码"}' \
  http://127.0.0.1:8000/api/v1/auth/login \
  | tee login.json
```

成功响应结构：

```json
{
  "data": {
    "csrf_token": "一次性返回的会话绑定 token",
    "user_id": 1
  },
  "request_id": "请求追踪 ID"
}
```

响应同时设置 `sf_session` Cookie。该 Cookie 为 `HttpOnly`、`SameSite=Lax`；除 `local` 和 `test` 环境外使用 `Secure`，因此非本地环境必须使用 HTTPS。

提取 CSRF token：

```bash
CSRF_TOKEN=$(jq -r '.data.csrf_token' login.json)
```

没有 `jq` 时，可从 `login.json` 或 Swagger UI 响应中手工复制。不要提交 `cookies.txt`、`login.json` 或 CSRF token 到版本库。

### 8.2 读取当前用户

```bash
curl -sS -b cookies.txt http://127.0.0.1:8000/api/v1/auth/me
```

响应示例：

```json
{
  "data": {
    "id": 1,
    "username": "admin",
    "permissions": [
      "file:delete:all",
      "file:read:all",
      "file:upload",
      "system:user:list"
    ]
  },
  "request_id": "请求追踪 ID"
}
```

### 8.3 写操作规则

所有 Cookie 认证的写操作必须同时满足：

- 请求头 `Origin` 在 `CSRF_ORIGINS` 中。
- 请求头 `X-CSRF-Token` 与会话绑定的 CSRF token 一致。
- 携带有效的 `sf_session` Cookie。

登录本身要求可信 `Origin`，但不需要 CSRF token。退出、会话轮换、文件上传和文件删除都需要 `Origin` 与 `X-CSRF-Token`。

### 8.4 轮换会话

轮换会吊销旧会话并签发新 Cookie 和新 CSRF token：

```bash
curl -sS -b cookies.txt -c cookies.txt \
  -X POST \
  -H 'Origin: http://127.0.0.1:8000' \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  http://127.0.0.1:8000/api/v1/auth/rotate \
  | tee rotate.json

CSRF_TOKEN=$(jq -r '.data.csrf_token' rotate.json)
```

轮换后旧 CSRF token 立即失效，后续写操作必须使用新值。

### 8.5 退出

```bash
curl -sS -b cookies.txt -c cookies.txt \
  -X POST \
  -H 'Origin: http://127.0.0.1:8000' \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  http://127.0.0.1:8000/api/v1/auth/logout
```

成功后当前服务端会话被吊销，Cookie 被清除。登录失败触发限流时返回 HTTP 429，并带有 `Retry-After` 响应头。

## 9. IAM 用户与菜单

### 9.1 权限前提

用户列表要求 `system:user:list` 权限。内置 `framework_admin` 角色包含该权限。V1 和 V2 都只返回当前主体数据范围内的用户。

### 9.2 V1 固定数组契约

```bash
curl -sS -b cookies.txt http://127.0.0.1:8000/api/v1/iam/users
```

响应示例：

```json
{
  "data": [
    {"id": 1, "username": "admin"}
  ],
  "request_id": "请求追踪 ID"
}
```

V1 固定返回数组，最多 100 条，不提供分页参数。`/api/v1/iam/users/legacy` 是兼容别名，响应形状相同，并带有 `Deprecation`、`Link` 和 `Warning` 响应头。

### 9.3 V2 固定分页契约

```bash
curl -sS -b cookies.txt \
  'http://127.0.0.1:8000/api/v2/iam/users?page=1&page_size=20'
```

响应示例：

```json
{
  "data": {
    "items": [
      {"id": 1, "username": "admin"}
    ],
    "total": 1,
    "page": 1,
    "page_size": 20
  },
  "request_id": "请求追踪 ID"
}
```

分页约束：`page >= 1`，`page_size` 为 `1..200`。V1 数组与 V2 分页是两个独立契约；不要在同一路径根据请求头或查询参数切换响应形状。

### 9.4 可见菜单

```bash
curl -sS -b cookies.txt http://127.0.0.1:8000/api/v1/iam/menus
```

菜单会按当前用户的权限过滤。菜单不是安全边界，实际接口仍必须执行服务端权限校验。

## 10. 文件接口

### 10.1 权限和数据范围

- 上传要求 `file:upload`。
- 列表和读取允许文件所有者访问；其他用户需要 `file:read:all`。
- 删除允许文件所有者访问；其他用户需要 `file:delete:all`。
- `framework_admin` 默认包含全部内置文件权限。
- 无权访问已存在文件时，接口返回 404 而非 403，以避免泄露文件是否存在。

### 10.2 支持的文件类型

当前支持 `.pdf`、`.png`、`.jpg`、`.jpeg`、`.txt`、`.csv` 和 `.xlsx`。服务端按文件结构和扩展名校验，不只信任客户端 `Content-Type`：

- `.txt`、`.csv` 必须是 UTF-8 文本且不能含 NUL 字节。
- PDF、PNG、JPEG 会检查基础结构。
- XLSX 会检查 OOXML 结构，并拒绝宏、外部引用、可疑嵌入内容等情况。

这些校验不能替代恶意文件扫描。`FILE_MALWARE_SCAN_ENABLED=true` 时，上传会调用本地 clamd；扫描器不可用会拒绝上传并返回 503。

### 10.3 上传

```bash
curl -sS -b cookies.txt \
  -H 'Origin: http://127.0.0.1:8000' \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -F 'file=@./example.pdf' \
  http://127.0.0.1:8000/api/v1/files \
  | tee upload.json
```

成功状态为 `201`：

```json
{
  "data": {
    "id": 1,
    "name": "example.pdf",
    "size": 12345,
    "sha256": "文件内容 SHA-256"
  },
  "request_id": "请求追踪 ID"
}
```

文件内容超过 `FILE_MAX_BYTES` 或整个请求超过 `MAX_REQUEST_BYTES` 会返回 413。空文件、非法文件名、扩展名不支持、内容与格式不符或文本不是 UTF-8 会返回 400。

### 10.4 列表和元数据

```bash
curl -sS -b cookies.txt \
  'http://127.0.0.1:8000/api/v1/files?page=1&page_size=20'
```

响应中的 `data` 为分页对象，字段包括 `items`、`total`、`page` 和 `page_size`。每个条目包含 `id`、`name`、`size`、`sha256` 和 `content_type`。

```bash
curl -sS -b cookies.txt \
  http://127.0.0.1:8000/api/v1/files/1/metadata
```

### 10.5 下载、ETag 与 Range

```bash
curl -sS -b cookies.txt \
  -D download.headers \
  -o downloaded.bin \
  http://127.0.0.1:8000/api/v1/files/1
```

下载响应的重要行为：

- 成功返回 `200`，内容类型为 `application/octet-stream`，以附件方式下载。
- `ETag` 来自文件 SHA-256，例如 `"<sha256>"`。
- `If-None-Match` 命中时返回 `304`，不返回正文。
- 单段 `Range: bytes=start-end` 返回 `206` 和 `Content-Range`。
- `If-Range` 只接受强 ETag；不匹配时忽略 Range 并返回完整内容。
- 非法或不可满足的 Range 返回 `416`，错误响应中带有 `COMMON.RANGE_NOT_SATISFIABLE`。

分段下载示例：

```bash
curl -sS -b cookies.txt \
  -H 'Range: bytes=0-1023' \
  -D range.headers \
  -o first-1kb.bin \
  http://127.0.0.1:8000/api/v1/files/1
```

条件请求示例：

```bash
curl -sS -b cookies.txt \
  -H 'If-None-Match: "请替换为文件的 SHA-256"' \
  -o /dev/null \
  -w '%{http_code}\n' \
  http://127.0.0.1:8000/api/v1/files/1
```

### 10.6 删除

```bash
curl -sS -b cookies.txt \
  -X DELETE \
  -H 'Origin: http://127.0.0.1:8000' \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  http://127.0.0.1:8000/api/v1/files/1
```

成功响应：

```json
{
  "data": {"deleted": true},
  "request_id": "请求追踪 ID"
}
```

删除会先在同一业务事务中删除元数据并写入持久化清理 intent。若物理文件暂时无法删除，API 仍可成功，实际对象由显式运维清理流程重试。系统不会自动创建定时清理任务或独立 Worker。

### 10.7 显式文件清理

执行清理的环境必须与 API 服务使用同一 PostgreSQL 和同一私有 `FILE_STORAGE_ROOT`。先只读扫描超过宽限期的孤儿对象：

```bash
python -m scripts.reconcile_files scan-orphans --grace-seconds 3600
```

确认结果后写入持久化清理 intent：

```bash
python -m scripts.reconcile_files scan-orphans --grace-seconds 3600 --apply
```

显式领取并重试清理：

```bash
python -m scripts.reconcile_files retry-cleanup --limit 100 --lease-seconds 300
```

`--apply` 只写清理 intent，不会依赖目录遍历直接删除任意文件。物理删除仍会经过 PostgreSQL lease claim、live-record recheck 和存储状态复核。

## 11. 健康检查

```bash
curl -sS http://127.0.0.1:8000/health/live
curl -sS http://127.0.0.1:8000/health/ready
```

正常响应：

```json
{"status":"alive"}
{"status":"ready"}
```

- `/health/live` 只表示进程能响应，不检查数据库。
- `/health/ready` 执行 PostgreSQL `SELECT 1`，成功返回 200，数据库不可用返回 503 和 `SYSTEM.DATABASE_UNAVAILABLE`。
- readiness 不检查迁移是否已执行到 head，也不检查业务表结构；启动后接口报缺表时，应执行 `python -m alembic current` 核对迁移。

## 12. 响应格式和错误处理

成功响应统一为：

```json
{
  "data": {},
  "request_id": "请求追踪 ID"
}
```

错误响应统一为：

```json
{
  "code": "AUTH.UNAUTHORIZED",
  "message": "本地化错误消息",
  "request_id": "请求追踪 ID",
  "details": []
}
```

客户端应依据稳定的 `code` 做分支判断，不要依赖可本地化的 `message`。`details` 通常包含字段名和原因，例如分页参数校验失败时的 `page` 或 `page_size`。

常见问题：

| 现象 | 常见原因 | 处理方式 |
|---|---|---|
| 登录返回 403 | `COOKIE_AUTH_ENABLED=false`，或 `Origin` 不在 `CSRF_ORIGINS` | 开启 Cookie 认证，逐字核对协议、主机、端口 |
| 读取接口返回 401 | Cookie 缺失、过期、已轮换、已退出，或账号被禁用 | 重新登录并确认 `-b cookies.txt` |
| 写操作返回 403 | 缺少 `Origin`、缺少/过期的 `X-CSRF-Token` | 从最新登录或轮换响应重新提取 token |
| 文件返回 404 | 文件不存在，或当前用户既不是所有者也没有全局读取/删除权限 | 使用所有者账号，或补充相应权限 |
| 登录返回 429 | 登录失败次数触发限流 | 按 `Retry-After` 等待后重试 |
| 上传返回 400 | 文件名非法、扩展名不支持、内容与格式不符、文本不是 UTF-8 | 使用支持的类型并检查文件内容 |
| 请求返回 413 | 请求体或文件超过大小上限 | 调整文件，或按容量策略修改配置 |
| 请求返回 422 | 路径、查询参数或 JSON 结构不符合契约 | 查看 `details` 中的字段和原因 |
| 返回 503 | PostgreSQL 不可用，或启用扫描时 clamd 不可用 | 检查依赖服务；readiness 只验证 PostgreSQL |
| 出现 `Invalid host header` | 请求的 Host 不在 `TRUSTED_HOSTS` | 使用允许的主机名访问，或更新配置并重启 |

排查时优先保留错误响应中的 `request_id`，并在服务端日志中查找同一 `request_id`。

## 13. 开发与验证命令

基础测试（未配置 `TEST_DATABASE_URL` 时，真实 PostgreSQL 用例会按设计 skip）：

```bash
python -m pytest -q
```

使用专用、可销毁的 PostgreSQL 测试库执行真实数据库集成测试：

```bash
TEST_DATABASE_URL='postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/python_framework_test' \
  python -m pytest -q
```

不要将 `TEST_DATABASE_URL` 指向开发库或生产库。测试库应预先迁移到 head；迁移生命周期测试还需要测试角色具备创建临时数据库的权限，否则相关用例会 skip。

静态质量门禁：

```bash
python -m ruff format --check .
python -m ruff check .
python -m mypy app scripts migrations tests
python -m bandit -r app scripts migrations
python -m pip_audit
python -m compileall -q app scripts migrations tests
```

没有执行的检查应明确标记为 `NOT_RUN`，不能用其他测试通过来推断它已通过。

## 14. 安全与交付边界

- 不提交 `.env`、管理员密码、Cookie、CSRF token、私钥或生产连接串。
- 不把 `FILE_STORAGE_ROOT` 设置为符号链接，也不允许通过路径穿越访问根目录之外的文件。
- 不要把上传校验当作恶意文件扫描；生产环境的 clamd 服务可用性由部署运维流程负责，代码开发验证不执行真实扫描。
- 不要绕过分页、数据范围和权限检查直接查询数据库来构造 API 响应。
- 不要增加自动文件清理、定时任务或独立 Worker；只使用显式运维 CLI。
- 数据库业务写入和审计必须共享 service-owned transaction。
- ORM 字段变更必须同时提供追加迁移和真实 PostgreSQL 验证证据。

以下四项永久不纳入代码开发、PR、CI 或发布前代码门禁的验证条件：

- 生产库备份、恢复及真实数据迁移演练。
- 目标环境负载、容量、重启和故障恢复验证。
- 真实 ClamAV/clamd 恶意文件端到端扫描。
- 生产密钥配置与安全审批。

这些事项由生产部署、运维或安全流程处理，不应据此把代码开发状态标记为 `BLOCKED`，也不应将其记作代码门禁的 `NOT_RUN`。`invalidate_user_authorization()` 保留但不作为验收项；历史登录限流 bucket 核对也不是当前阻断项。

## 15. 快速检查清单

- `.env` 中 `DATABASE_URL` 使用 `postgresql+asyncpg://`。
- 本地使用 Auth、IAM、Files 时 `COOKIE_AUTH_ENABLED=true`。
- `CSRF_ORIGINS` 是 `CORS_ORIGINS` 的子集，且访问地址逐字匹配。
- `TRUSTED_HOSTS` 包含浏览器实际使用的主机名或 IP。
- 已执行 `python -m scripts.init_database --admin-user admin`，或对已有库执行迁移与 `--seed-only`。
- `python -m alembic current` 显示 `1_quality_remediation`。
- `/health/live` 与 `/health/ready` 均返回 200。
- 登录后保存了 Cookie，并从最新响应取得了 CSRF token。
- 上传文件属于支持的类型，大小未超过请求和文件上限。
