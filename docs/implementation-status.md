# 芯鉴知微实现状态

最后更新：2026-07-20（Phase 5）

## 总体状态

- 当前阶段：Phase 5 实现、测试、镜像构建和实际 PostgreSQL 提示升级验收完成。
- 下一阶段：Phase 6 尚未开始。
- Git：Phase 4 已提交为 `e7759b158a3d2cd5e2ef4bf6b06f95dfeca69ee1 feat: complete phase 4 rule diagnosis`；Phase 5 变更尚未提交。
- 运行状态：原 PostgreSQL、backend、frontend 长期容器保持运行；Phase 5 的 0.5.0 新镜像通过一次性容器验收。

## Phase 5 实现情况

- [x] YAML 保存 DHT11 读取失败、LED 不亮、按键无反应三棵课程示例故障树。
- [x] 三棵树均标记 `placeholder`，不将板卡型号、引脚、传感器字段或生产参数写入 Python。
- [x] 通用事实解析器根据 Phase 4 错误类型或配置事件码匹配证据。
- [x] 同一异常输出三个可能原因，按证据权重和原因 ID 确定性排序。
- [x] 无专属证据时最高仅 20 分低置信；原因专属证据可提升排序和置信度。
- [x] 没有任何证据的原因不输出，不生成无依据的高置信结论。
- [x] Level 1–4 阈值和提示文本由 YAML 配置，按失败次数或持续时间升级。
- [x] 保存树版本/哈希、首次发现时间、失败次数、持续时间、原因、证据、提示和测试标记。
- [x] 同一诊断/故障树幂等，连续窗口外重新计数。
- [x] Level 4 进入临时令牌保护的介入列表；未配置审阅令牌时默认关闭。

## 数据库迁移

- 新增 `20260720_0003_phase5_guidance_history.py`。
- 新增 `guidance_history` 表、唯一约束及设备历史和介入查询索引。
- 已在现有 PostgreSQL 执行，`alembic current` 返回 `20260720_0003 (head)`。
- `alembic check` 返回 `No new upgrade operations detected.`。

## 验证结果

| 验证项 | 命令/方式 | 结果 |
| --- | --- | --- |
| 后端 Ruff/格式 | `ruff check app tests`、`ruff format --check app tests` | 通过 |
| 后端测试 | `pytest` | 30 passed |
| 模拟器回归 | Ruff、格式、`pytest -W error` | 8 passed |
| 前端回归 | ESLint、Prettier、Vitest、类型检查、构建 | 2 tests passed，构建通过 |
| Compose 镜像 | `docker compose build backend frontend` | 0.5.0 镜像构建通过 |
| PostgreSQL 迁移 | 一次性 Phase 5 后端容器 | `20260720_0003 (head)` |
| 迁移一致性 | `alembic check` | 无待生成操作 |
| 提示升级 | 实际 API + PostgreSQL，连续 10 次测试异常 | `1,1,2,2,2,3,3,3,3,4` |
| 原因与置信约束 | 实际 API | 每次 3 个有证据低置信候选 |
| 历史幂等 | 重复调用第 10 个诊断 | 历史仍为 10 条，失败次数仍为 10 |
| 教师介入查询 | 临时随机审阅凭据 | Level 4 测试设备可见 |
| 测试数据标记 | PostgreSQL `bool_and(is_test_data)` | true |
| 长期容器 | `docker compose ps` | 三个服务持续 healthy，未停止或替换 |

## 本地验收数据

Phase 5 创建了一个随机后缀、名称明确标记为 acceptance test 的临时设备，一条测试错误日志、十条诊断结果和十条提示历史。所有提示历史均为测试数据，不代表真实硬件、课程或生产结论；设备与审阅随机令牌未写入仓库。

## 已知问题与风险

1. 三棵树是项目计划指定但尚未经课程方确认的示例模板，必须在真实实验与硬件确定后审核 YAML。
2. LED 和按键根事件码当前只是可配置接口约定，尚无真实设备字段映射。
3. 教师账号和角色尚未建立；`REVIEW_ACCESS_TOKEN` 是默认关闭的临时审阅边界，后续必须替换。
4. 当前原因评分为透明的加权证据，不包含 Phase 8 知识检索或 Phase 9 AI 推理。
5. 新镜像已构建，但为保持长期容器不中断，当前 backend/frontend 未替换；下次获准更新运行环境时再滚动到 0.5.0。
6. 容器内新版 FastAPI 的 TestClient 发出上游弃用警告，不影响本阶段结果；依赖升级阶段应跟踪其替代方案。

## 下一阶段

Phase 6 将实现学生端页面和真实后端接口展示。用户再次明确输入“继续下一阶段”前，不进入 Phase 6。
