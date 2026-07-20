# 芯鉴知微实现状态

最后更新：2026-07-20（Phase 6）

## 总体状态

- 当前阶段：Phase 6 学生端、聚合 API 和诊断反馈闭环已完成实现与验收。
- 下一阶段：Phase 7 尚未开始。
- Git：Phase 5 已提交为 `67650d023c07f7abcf252649f6973ab21e288eea feat: complete phase 5 fault tree guidance`；Phase 6 变更尚未提交。
- 运行状态：原 PostgreSQL、backend、frontend 长期容器持续 healthy，Phase 6 验收没有停止或替换它们。

## Phase 6 实现情况

- [x] 临时学生入口使用设备 ID/令牌验证，明确不等同于正式学生账号。
- [x] 凭据只在浏览器 `sessionStorage` 保存，刷新可恢复当前标签页会话，退出时清除。
- [x] 聚合 API 返回设备状态、最近 100 条日志、最近 500 条读数、最新诊断、对应提示与最新反馈。
- [x] 当前实验任务明确返回 `configured=false`，没有创建虚构账号、班级或任务。
- [x] 页面覆盖加载、空、错误、正常和异常状态，并提供手动及 15 秒自动刷新。
- [x] ECharts 根据通用指标字段动态生成趋势线，不绑定具体开发板、传感器或生产字段。
- [x] 诊断卡展示规则命中、证据、原因排序、置信级别和分层提示，并明确示例规则边界。
- [x] “已解决、仍未解决、请求教师协助”反馈写入 PostgreSQL，并继承诊断的测试数据标记。

## 数据库迁移

- 新增迁移 `20260720_0004_phase6_student_feedback.py`。
- 新增 `diagnosis_feedback` 表及设备/创建时间联合索引。
- 已在现有 PostgreSQL 执行；`alembic current` 返回 `20260720_0004 (head)`。
- `alembic check` 返回 `No new upgrade operations detected.`。

## 验证结果

| 验证项 | 命令/方式 | 结果 |
| --- | --- | --- |
| 后端 Ruff/格式 | `ruff check app tests`、`ruff format --check app tests migrations` | 通过 |
| 后端测试 | `pytest` | 34 passed |
| 模拟器回归 | Ruff、格式、`pytest -W error` | 8 passed |
| 前端静态检查 | ESLint、Prettier、Vue TypeScript | 通过 |
| 前端单元测试 | Vitest | 5 passed |
| 前端生产构建 | `npm run build` | 0.6.0 构建通过；仅有大分块优化提示 |
| 浏览器测试 | Playwright + 本机无头 Chrome | 3 passed：无数据/刷新、正常、异常/反馈；无控制台错误 |
| Compose 镜像 | `docker compose build backend frontend` | 0.6.0 后端与前端镜像构建通过 |
| PostgreSQL 迁移 | 一次性 0.6.0 后端容器 | `20260720_0004 (head)` |
| 真实数据库 API | 随机临时凭据 + TestClient + PostgreSQL | 会话/仪表盘 200，采集/诊断/提示/反馈 201，错误凭据 401 |
| 数据真实性标记 | 聚合响应断言 | 日志、读数、诊断、提示和反馈全部为测试数据 |
| 长期容器 | `docker compose ps` | 三个服务持续 healthy，未停止或替换 |

## 本地验收数据

Phase 6 创建了两组随机后缀、名称明确为 `Phase 6 acceptance test` 的临时设备，每组各包含一条测试心跳、日志、读数、诊断、提示和反馈。其中第一组因验收脚本对规则命中数量作了错误预期而在最终断言处停止，但此前各项 API 写入已经成功；第二组完成闭环验收。所有记录均标记为测试数据，随机设备令牌只存在于一次性进程内，未输出或写入仓库。

## 已知边界与风险

1. 正式学生账号、班级、实验任务和角色授权尚未建立；当前设备凭据登录只是 Phase 6 临时边界。
2. `sessionStorage` 仍受同源脚本访问，正式账号阶段应改为安全会话机制并完成 XSS、CSRF 和权限审计。
3. 当前诊断完全依赖数据库中的采集记录、YAML 示例规则和占位故障树，没有真实硬件数据、知识库或 AI 模型支持。
4. 生产构建的学生仪表盘分块约 532 kB，构建通过但超过 Vite 默认 500 kB 提示线；后续可继续拆分图表依赖。
5. 新镜像已构建，但为遵守“不停止当前 Docker 容器”，长期 backend/frontend 未滚动到 0.6.0。
6. 新版 FastAPI TestClient 发出上游弃用警告，不影响结果；依赖升级阶段应跟踪其替代方案。

## 下一阶段

Phase 7 将实现教师端。当前已按阶段门禁停止，不进入 Phase 7，也不自动提交 Phase 6；等待用户明确指示。
