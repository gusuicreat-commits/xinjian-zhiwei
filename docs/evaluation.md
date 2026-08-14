# 合成诊断与检索评测（P3）

## 评测边界

本评测的全部输入都是仓库内合成数据，只验证当前示例规则、边界语义、冲突排序、生产同源
混合检索路径和禁止性陈述门禁。它不是设备说明书、行业标准、课程真值或真实故障样本，
不能据此声明真实硬件诊断准确率、误报率、漏报率、专业知识有效性或生产就绪。

## 数据集

- `backend/evaluation/golden_cases.json`：30 个合成诊断用例，覆盖正常、读取失败、离线、
  数值越界、边界值、未知事件、多规则冲突和优先级；同时声明示例原因与必须包含的排查
  步骤片段。
- `backend/evaluation/retrieval_cases.json`：25 个合成文档、54 个带有明确
  `expected_document_ids` 和 `expected_chunk_ids` 的人工标注查询。评测在
  隔离的内存数据库中装载这些知识块，直接调用生产同源的
  `hybrid_retrieve`（词法 + 确定性测试向量 + RRF）。确定性哈希向量
  只是无网络的代码验收 fixture，不是语义 Embedding 模型。
  语料包含 6 条多相关知识块查询、独立自然语言改写以及共享高频词的
  负例干扰块；不再依赖扩展到全语料的候选集或唯一大写标签。
- `backend/evaluation/forbidden_claims.json`：6 个禁止性陈述模式。

三个数据集都带 `is_test_data` 或明确合成依据。默认运行只写入内存
SQLite，不写入 PostgreSQL。

## 指标与门禁

- 诊断 exact match、Top-1/Top-3 原因命中和必含步骤：阈值 100%，因为规则与模板是
  确定性的；
- 无证据高置信输出必须为 0；
- 合成混合检索主门禁：Recall@5 不低于 80%；同时报告 MRR@5、
  Hit Rate@5、Top-1/Top-3 命中率和逐条 miss 列表；
- 候选与融合上限使用生产默认值：词法 Top-10、向量 Top-10、融合 Top-5；
- 两次同设备、同实验、同错误的诊断必须聚合为一个 Episode；
- 输出诊断平均响应时间、AI Provider 调用次数和缓存命中次数。本评测不调用 AI，
  因此后两项预期均为 0；
- 禁止性陈述：必须 0 命中；
- 任一门禁失败，CLI 返回非零退出码，测试失败。

运行：

```bash
cd backend
python -m app.cli.run_synthetic_evaluation
pytest tests/test_synthetic_evaluation.py
```

默认评测使用 SQLite，会覆盖同一个 `hybrid_retrieve` 入口及 SQLite 词法、
向量和 RRF 分支，但不会执行 PostgreSQL FTS/pgvector SQL。可用专用的、
可丢弃的 PostgreSQL 数据库补跑集成验收：

```bash
TEST_RAG_POSTGRES_DSN=postgresql+psycopg://.../rag_eval_ci \
  pytest tests/test_synthetic_evaluation.py::test_optional_postgres_hybrid_retrieval_acceptance
```

为防止误操作业务库，该 DSN 的数据库名必须以 `test`、`tmp` 或
`rag_eval` 开头，且 public schema 不得已有任何表。专用库需预先启用
pgvector 扩展。集成评测会在该空库中建表并于结束时清理，不得指向
共享、已迁移或生产库。未配置 `TEST_RAG_POSTGRES_DSN` 时，该用例明确 skip。

2026-08-13 更严格的 SQLite 基线为诊断 30/30、原因 Top-1/Top-3 与必含
步骤均 100%、无证据高置信输出 0；合成混合检索 50/54 完全找齐，
Top-1 87.04%、Top-3 90.74%、Recall@5 93.83%、MRR@5 89.72%、
Hit Rate@5 94.44%、4 条 miss，通过 Recall@5 ≥ 80% 门禁；其中一条为
多相关块的部分召回，因而 Recall@5 与 Hit Rate@5 不再等价。禁止性陈述必须
0/6 命中，Episode 必须 2→1 聚合，AI/缓存调用为 0/0。平均响应时间
不作为跨机器固定性能承诺。机器可读摘要位于
`docs/evaluation-baseline.json`。这些结果只证明代码与提交的合成预期一致。

## 仍待真实资料

真实评测仍需要：硬件/传感器型号与说明书、正式实验模板和阈值、带真值的正常/故障
数据、确认根因和修复结果、正式知识语料与审核结论，以及由项目方确认的误报/漏报/
覆盖率目标。未提供前不得将合成基线替换成专业结论。
