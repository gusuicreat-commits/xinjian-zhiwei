# 芯鉴知微实现状态

最后更新：2026-07-21（Phase 8 通用知识库框架）

## 总体状态

- 当前阶段：Phase 8 通用知识库框架已完成实现；正式资料、审核教师和 Embedding Provider 尚未提供。
- 下一阶段：先导入并审核真实知识资料；在此之前不开始 Phase 9 AI 结构化诊断。
- Git：Phase 7 已提交为 `9a92026 第七轮`；Phase 8 变更尚未提交。
- 运行状态：长期 Docker 容器未停止或替换；Phase 8 迁移与 API 验收不要求停止现有容器。

## Phase 8 通用框架实现情况

- [x] 建立 `knowledge_sources`、`knowledge_documents`、`knowledge_chunks`、`knowledge_embeddings` 和 `knowledge_reviews`。
- [x] 提供来源登记、幂等文本导入、审核、测试/正式向量门禁、状态和向量检索 API。
- [x] 文本切分大小、重叠和文档上限通过环境变量配置。
- [x] 向量类型兼容 PostgreSQL pgvector 与 SQLite 测试，不绑定 Provider、模型或固定维度。
- [x] 只有记录授权范围并审核通过的知识块才能写入向量和被检索。
- [x] 测试数据从来源、文档到向量保持标记，检索默认排除测试内容。
- [x] 教师端知识卡片改为读取实际知识状态和记录数量。
- [x] 原始知识文件目录加入 `.gitignore`，README 明确禁止提交未授权资料。

## 数据库迁移

- 新增迁移 `20260721_0005_phase8_knowledge_framework.py`。
- PostgreSQL 继续使用已安装的 `vector` 扩展；向量列暂不固定维度，也不在模型未确定前创建近似索引。
- 知识表为空时只表示框架就绪，不表示系统拥有知识数据。

## 验证结果

| 验证项 | 命令/方式 | 结果 |
| --- | --- | --- |
| 后端静态检查 | `ruff check app tests` | 通过 |
| 后端测试 | `pytest` | 42 passed；含空库、授权门禁、幂等导入、审核、测试向量与来源引用 |
| 前端静态检查 | Prettier、ESLint、Vue TypeScript | 通过 |
| 前端单元测试 | `vitest run` | 7 passed |
| 前端生产构建 | `npm run build` | 0.8.0 构建通过；仅有 ECharts 分块大小提示 |
| 模拟器回归 | Ruff、`pytest` | 8 passed |
| PostgreSQL 迁移 | 一次性 0.8.0 后端容器 | `20260721_0005 (head)`；`alembic check` 无待生成操作 |
| pgvector 实测 | PostgreSQL 事务内写入三维测试向量并执行余弦检索 | 1 条结果，相似度 > 0.999；事务已回滚 |
| 知识数据计数 | PostgreSQL 五张知识表 | 全部 0 条；没有自动导入资料或留下测试向量 |
| 后端镜像 | `docker compose build backend` | 0.8.0 最终镜像构建通过 |
| 浏览器桌面布局 | 内置浏览器，1680×940 | 四列统计和四列分析布局；无水平溢出 |
| 浏览器移动布局 | 内置浏览器，390×844 | 两列统计、单列分析和底部三项导航；无水平溢出 |
| 浏览器交互 | 上下滚动、三项菜单定位与高亮、搜索、折叠/展开、刷新、退出边界 | 核心交互可用；长页面可上下滑动，菜单与区块同步，搜索可将异常表过滤为 0 条 |
| 视觉对照 | 参考图与最终浏览器截图同屏比较 | 无未解决 P0/P1/P2；数据稀疏差异属于禁止伪造数据的产品约束 |
| 长期容器 | 未执行停止、重建或替换 | 保持原运行状态 |

## 视觉证据

- 源图：`docs/design-qa/phase7-teacher-ui/reference.png`
- 最终桌面：`docs/design-qa/phase7-teacher-ui/dashboard-viewport.png`
- 菜单审查前后：`docs/design-qa/phase7-teacher-ui/menu-audit-before.png`、`docs/design-qa/phase7-teacher-ui/menu-audit-after.png`
- 移动端：`docs/design-qa/phase7-teacher-ui/dashboard-mobile.png`
- 同屏对照：`docs/design-qa/phase7-teacher-ui/full-comparison.jpg`
- QA 报告：项目根目录 `design-qa.md`

## 已知边界与风险

1. 目前只能识别异常设备，不能证明异常属于某位学生；正式学生、教师、班级、实验任务和角色授权尚未建立。
2. 实验完成率和班级进度没有可计算数据，教师端显示“未配置”，不使用参考图中的示例百分比。
3. 知识表和 API 已建立，但当前没有正式来源、文档、知识块、Embedding 或 pgvector 向量记录。
4. 当前诊断仍只依赖数据库采集记录、YAML 示例规则和占位故障树；知识检索尚未接入诊断，也没有 AI 模型支持。
5. 临时教师令牌保存在浏览器 `sessionStorage`，正式账号阶段必须替换为服务端会话与角色权限。
6. ECharts 公共渲染分块约 517 kB，构建通过但超过 Vite 默认提示线，后续可继续按图表类型拆分。

## 下一阶段

等待项目方提供可授权资料、来源版本、审核教师和 Embedding 使用决策。资料确认前不导入正式内容、不开始 Phase 9，也不自动提交 Phase 8。
