# 部署与运行操作指南

适用于仓库 [compose.yaml](../compose.yaml)。本文维护启动、迁移、备份与探针操作；当前部署及验收状态见 [实现状态](implementation-status.md)。

## 1. 首次本地运行

准备 Docker/Compose。只在没有 `.env` 时复制示例，按 `.env.example` 替换数据库密码并保持 `DATABASE_URL` 与数据库服务配置一致；已有环境不要覆盖配置。

```bash
cp .env.example .env
# 在本机编辑 .env，保持 AI_ENABLED=false
# 确认所选数据库是本次要启动的环境后再执行：
docker compose up -d --build
docker compose ps
```

**后端默认启动命令会先执行 `alembic upgrade head`，然后启动服务。**因此 Compose 启动/重建不是只读检查，连接已有数据库前要确认目标与备份。单纯测试应使用 [隔离验收入口](evaluation.md)，不要直接启动现有业务环境。

| 默认入口 | 用途 |
| --- | --- |
| `http://localhost:8080` | 前端，由 Nginx 代理 `/api` 到后端 |
| `http://localhost:8000/api/v1/health` | 应用存活、版本与运行环境；不检查数据库 |
| `http://localhost:8000/health/ready` | 数据库连通性检查 |
| `http://localhost:8000/docs` | OpenAPI |
| PostgreSQL | 仅 Compose 内部网络，没有默认宿主机端口映射 |

依赖安装、镜像构建可能需要网络；依赖就绪后的基础运行不要求公网或 AI Key。无 Key 时保持 `AI_ENABLED=false`，使用确定性诊断。

## 2. 数据库与工作流恢复

Compose 将业务数据库保存在 `postgres_data` 命名卷，重建容器不等于删除数据。不要用删除卷来处理升级失败。pgvector 镜像满足不可修改的历史迁移，不表示当前诊断使用向量检索。

默认 `DIAGNOSIS_CHECKPOINT_BACKEND=memory` 只适合开发，服务重启会丢失内存中的工作流 Checkpoint。业务表持久化不等于图恢复能力已经持久化。

需要跨重启恢复时，在目标部署配置明确指定：

```text
DIAGNOSIS_CHECKPOINT_BACKEND=postgres
DIAGNOSIS_CHECKPOINT_DSN=postgresql://USER:PASSWORD@postgres:5432/DATABASE
DIAGNOSIS_CHECKPOINT_SETUP=false
```

上面是占位连接串。Checkpoint 表由独立设置命令管理，不属于业务 Alembic 版本链。数据库启动后、启动业务后端前执行显式部署步骤：

```bash
docker compose up -d postgres
docker compose run --rm backend python -m app.cli.setup_diagnosis_checkpoints
```

确认数据库就绪后再执行设置命令；同一命令可重复运行。多 worker 场景不要让每个服务启动时自动执行 setup。完成后仍须实际验证重启恢复、反馈幂等及失败窗口；配置存在不构成恢复验收。

业务迁移核查命令（对已明确选定的环境）：

```bash
docker compose exec -T backend alembic current
docker compose exec -T backend alembic heads
docker compose exec -T backend alembic check
```

Head 从代码和目标库分别读取，不在本说明维护易过期的重复版本号。升级兼容必须先在隔离库验证，不能只看当前模型无差异。

## 3. 局域网试运行

设备、学生电脑和教师电脑访问运行 Compose 的服务器局域网地址；设备 API URL 不能填写学生电脑自己的 `localhost`。当前 Compose 暴露 8080 和 8000 端口，应按实际入口配置防火墙。需要浏览器跨域直连后端时，`API_CORS_ORIGINS` 必须包含实际来源；同源前端 API 优先走 Nginx。

试运行核对 Wi-Fi 互访、账号和班级授权、设备令牌、实验会话/资料包状态与备份。演示身份操作见 [合成演示手册](demo-runbook.md)。公网中断与实验室局域网中断是两种情况：无公网仍可运行本地规则；设备到服务器断开后不能继续实时上传。

## 4. 备份、恢复与保留

在仓库根目录、明确当前 Compose 项目后运行：

```bash
scripts/backup_database.sh /explicit/existing-directory/backup.dump
scripts/restore_drill.sh /explicit/path/backup.dump
docker compose exec -T backend python -m app.cli.retention_dry_run --days 30
```

- 备份使用 `pg_dump -Fc --snapshot`，需要 Python 3.10+、Docker 与当前 Compose postgres 服务。父目录须存在，拒绝覆盖 dump 或同名 `.manifest.json`；普通失败清理本次不完整 dump，强制终止留下的无清单文件不算完成备份。
- 恢复演练在同一个 PostgreSQL 实例创建临时数据库，退出时删除该临时库，不替换业务库、不删除数据卷。
- dump 与清单来自同一 `REPEATABLE READ` 导出快照，覆盖全部非系统表的全行 SHA-256、条数、列类型和关系约束。恢复先验 dump 摘要再比清单，源库后续写入不会造成误报。清单不含记录原文，仍须与 dump 一起受控保存；备份窗口避免 DDL，恢复后人工核验业务可用性及所需角色权限。
- `retention_dry_run` 只报告候选数量，`deleted=0`；不实施删除策略。

正式备份存储位置、加密、保留周期、恢复目标和负责人仍需部署方确定。业务库与独立 Checkpoint 库若分开，当前脚本仅证明指定数据库；须暂停相关业务写入并分别备份两个库，再按同一停写窗口联合恢复，单库通过不能称跨库一致；仅复制容器文件不是数据库备份。

### 记忆停用与维护

部署新代码前迁移到仓库当前Head；本轮没有替运行库执行迁移。治理表应与业务库一起备份，另外独立保存最新停用登记。以下命令使用显式选择的 `DATABASE_URL`，从backend目录执行；先在隔离副本验证。

```bash
python -m app.cli.memory_maintenance clear-stopped-caches --actor-user-id <current-admin-uuid>
python -m app.cli.memory_maintenance export-stops --actor-user-id <current-admin-uuid> --file /safe/new-memory-stops.json
# 仅在隔离恢复库，迁移到当前Head后执行；不要连正在提供服务的库。
python -m app.cli.memory_maintenance replay-stops --actor-user-id <current-admin-uuid> --file /safe/latest-memory-stops.json --isolated-restore
```

缓存维护每批最多100个待处理停用事件，可重复运行，不删除事实或Checkpoint。导出拒绝覆盖已有文件，只包含必要来源标识；文件哈希校验完整性，不证明文件来自可信操作者或已经最新。恢复重放会重新停用精确来源并使解释缓存到期；对象、内容或操作人无法核验时失败，不猜测对应关系。重放不自动授权上线，仍需核对Checkpoint和实际读取路径；跨存储保留/删除策略、第三方及离线副本尚未确认，不能宣称所有副本已清除。

教师“资料与审核”提供影响复核；管理员可预览并执行固定的过期缓存计划。权限变化、计划变化或部分失败须重新读取当前结果；普通保留数据没有通用破坏性删除入口。

## 5. AI 配置边界

非敏感默认配置在 [.env.example](../.env.example) 与 Compose。真实 Key 从服务器密钥管理或不提交 Git 的环境配置注入；启用模型、更换 Provider 或采用示例模型前，按 [模型与外发约束](development-guidelines.md#model-core) 验证可用性、字段、预算与降级。

`/health/dependencies` 的 AI 状态仅检查启用和密钥配置，不实际调用 Provider；结构化知识状态也不等于正式资料审核通过。`/api/v1/readiness/status` 是业务就绪提示，不能代替运行探针、硬件验收或生产验收。

## 6. 运行检查与正式部署边界

以下命令检查已启动环境，不执行迁移：

```bash
docker compose ps
docker compose logs --tail=200 backend
docker compose logs --tail=200 frontend
curl --fail http://127.0.0.1:8000/health/live
curl --fail http://127.0.0.1:8000/health/ready
curl --fail -I http://127.0.0.1:8080/student
```

页面能打开和存活探针成功不足以验收。还应按 [测试与评测](evaluation.md) 核对目标范围的登录、上传、诊断、反馈、教师处置、无 Key 降级及恢复。

正式部署还需落实 HTTPS、网络访问、账号/设备凭据生命周期、持久化 Checkpoint、备份恢复、监控告警、隐私和数据保留责任，以及真实硬件与课程验收。仓库具备入口不表示部署方已完成这些事项。

## 登录准入迁移（2026-09-30）

共享登录准入由0036追加 `login_attempts` 表；当前源码Head为 `20261002_0038`，还包含来源授权和持久AI操作。部署新版登录接口前需在选定目标库执行并核对迁移，不能仅重启旧结构的服务。本轮修复只在隔离测试库执行，未迁移业务库。多worker必须连接同一PostgreSQL并使用一致的限流配置；代理链应仅信任受控代理。短时预留失败会在窗口后释放，不能通过重启绕过限流。

回撤可以保留这张短期表；若执行降级，存在未过期预留时迁移会拒绝，先停新登录并等待窗口结束。降级不会修改诊断、会话或实验历史。API文档使用FastAPI默认CDN，目标网络须能访问；离线查看OpenAPI JSON不依赖该CDN。


### 2026-09-30 容器就绪探针

后端Compose健康检查使用`/api/v1/health/ready`，含数据库连通性；`/api/v1/health`继续仅表示进程存活。`depends_on: service_healthy`只约束启动顺序，不能据此声称运行中数据库故障会自动重启后端或停止前端。断库/恢复证据见本轮共享校验修复报告。

### 环境与修复版本部署

`APP_ENV` 仅接受 development/test/staging/production（忽略大小写与两端空白，prod为production别名）；未知值拒绝启动。启用工作流的staging/production必须配置PostgreSQL checkpoint，不能用拼写或别名落入内存模式。

Python Settings维护AI_PROMPT_VERSION默认值；Compose仅转交明确覆盖，不注入另一个默认。显式覆盖须与实际Prompt及指纹一起留档。0037–0038只在隔离库完成升级验证，业务部署另行执行。旧知识来源需管理员逐来源授权；旧待审核文档需真实整理人重新提交后由另一批准人审核。回退时关闭AI/受影响入口并保留新表，不能删除未知费用或权限历史。

### 知识文件导入资源边界（2026-10-02）

文件导入目前要求 Linux 服务：解析器在独立 Python 子进程运行，在导入解析库前设置虚拟内存、CPU 和输出文件限制；父进程按墙钟期限终止并回收子进程。macOS/Windows 或资源限制无法设置时返回 `503 KNOWLEDGE_PARSER_UNAVAILABLE`，不会退回无限制的进程内解析。本机仍可使用受字符数限制的文本导入，文件导入请使用 Linux 容器。

默认预算为原文件 10 MiB、文档 500,000 字符、PDF 200 页、单解析进程 256 MiB 虚拟内存、5 秒 CPU、10 秒墙钟、同服务主机 2 个解析槽。并发槽耗尽返回 `503 KNOWLEDGE_PARSER_BUSY`；超资源预算返回 413，坏格式返回 422。TXT/Markdown/CSV/DOCX/PDF 均经过同一进程边界，DOCX 仍有展开 XML 大小限制。CPU/内存等值是软件保护预算，不是已验证的课堂容量。

配置项为 `KNOWLEDGE_PARSER_MEMORY_BYTES`、`KNOWLEDGE_PARSER_CPU_SECONDS`、`KNOWLEDGE_PARSER_WALL_SECONDS`、`KNOWLEDGE_PARSER_MAX_PAGES`、`KNOWLEDGE_PARSER_CONCURRENCY`。本轮正常样本探针为 20 页 PDF、8,043 文件字节、640 字符、约 30 MiB RSS；上限附近文本和恶意资源消耗另在隔离 Linux 测试中验证。

应用在 JSON 解析前限制导入请求的实际字节数，文件请求预算为 `4 × ceil(KNOWLEDGE_MAX_FILE_BYTES / 3) + KNOWLEDGE_REQUEST_METADATA_BYTES`，文本请求预算为 `12 × KNOWLEDGE_MAX_DOCUMENT_CHARS + KNOWLEDGE_REQUEST_METADATA_BYTES`（覆盖 JSON 转义）。上传总时限为 30 秒；导入路径关闭 Nginx 请求缓冲，使后端期限从接收上传时开始，代理另设30秒空闲期限。不支持压缩请求体。默认元数据预算为 65,536 字节。超限、断连或解析失败不会创建半份文档。

Compose 将文件、文档及元数据三项预算通过同一 YAML anchor 传给后端与前端。Nginx 启动脚本据此生成两个导入路径的上限，不改变其他 API 路径。单独启动前端镜像必须显式设置 `KNOWLEDGE_MAX_FILE_BYTES`、`KNOWLEDGE_MAX_DOCUMENT_CHARS`、`KNOWLEDGE_REQUEST_METADATA_BYTES` 三项，并与后端配置一致；缺值启动失败。修改环境后须重建/重启相关服务使生成配置生效。
