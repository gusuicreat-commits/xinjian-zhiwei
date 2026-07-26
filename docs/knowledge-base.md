# Phase 8 通用知识库框架

## 当前状态

Phase 8 已建立来源可追溯、Provider 无关的知识库后端框架，但当前没有导入任何正式知识资料，也没有选择 Embedding Provider。框架存在不等于系统已经拥有专业知识。

当前能力：

- 登记资料来源、版本、URI、授权范围、许可证、扩展元数据和测试标记。
- 导入已经提取出的 UTF-8 文本，进行规范化、确定性切分和内容哈希去重。
- 保存文档、知识块、审核历史及向量记录。
- 临时审阅令牌边界下仍要求整理人、技术审核人和正式批准人三种角色分离；状态同步到全部知识块。
- 只有审核通过的知识块可以写入向量并参与检索。
- PostgreSQL 使用 pgvector 的 `vector` 类型；SQLite 测试使用兼容 JSON 类型。
- 检索结果返回来源、版本、URI、文档、定位信息和测试数据标记。

当前明确未完成：

- 没有 PDF、DOCX、HTML 或扫描件解析器；当前接口只接收外部适配器提取后的 `text/*` 文本。
- 没有真实知识来源、正式审核教师、授权资料、Embedding 或 pgvector 数据记录。
- 没有确定 Embedding Provider、模型和向量维度；DeepSeek 对话模型的确定不等同于选择云端 Embedding。
- 没有文本问题自动转向量的外部模型调用，也没有 AI 生成诊断。
- 临时 `X-Review-Token` 不能证明真实教师身份，正式账号与审核责任人模型仍待建立。

## 数据模型

| 表 | 用途 |
| --- | --- |
| `knowledge_sources` | 来源标识、类型、标题、URI、版本、许可证、授权范围和测试标记 |
| `knowledge_documents` | 文档哈希、解析器版本、存储 URI、审核状态和来源关联 |
| `knowledge_chunks` | 确定性文本分块、字符范围、定位元数据和审核状态 |
| `knowledge_embeddings` | Provider、模型、维度、向量、测试标记和知识块关联 |
| `knowledge_reviews` | 每次状态流转的审核角色、审核人引用、决定、备注和时间 |

向量列不固定维度，以避免在 Provider 未确定前写死模型参数。每次写入和查询仍会校验 Provider、模型与维度一致；确定生产模型后再评估是否增加指定维度的 HNSW/IVFFlat 索引。

## 导入和审核流程

1. 通过 `POST /api/v1/knowledge/sources` 登记来源。
2. 原始 PDF、DOCX、扫描件或网页由来源适配器提取为文本。
3. 通过 `POST /api/v1/knowledge/sources/{source_id}/documents/text` 导入文本。
4. 系统按配置切分，并以 `source_id + content_hash` 保证幂等。
5. 整理人将 `draft` 提交为 `pending`，技术审核人转为 `technical_reviewed`，正式批准人才能转为 `approved`。
6. 状态全集为 `draft`、`pending`、`technical_reviewed`、`approved`、`rejected`、`withdrawn` 和 `superseded`；不同状态只允许经过预定义转移。
7. 只有记录了 `authorization_scope` 的来源才能批准；正式来源还必须有类型、URI、版本、整理人和适用硬件。
8. 官方硬件资料必须有页码/章节定位；已验证案例必须记录最终修复动作和根因置信度。
9. 确认 Embedding Provider 后，由适配器生成向量并写入文档的 embeddings 接口。
10. 通过 `/api/v1/knowledge/search` 检索时只返回 `approved` 且模型维度匹配的知识块。

Provider 未配置时，写入非测试向量会返回 503；只有 `is_test_data=true` 的测试向量可用于框架测试。检索默认排除所有测试来源、测试文档和测试向量。

## 配置

```dotenv
KNOWLEDGE_CHUNK_SIZE_CHARS=1200
KNOWLEDGE_CHUNK_OVERLAP_CHARS=150
KNOWLEDGE_MAX_DOCUMENT_CHARS=500000
KNOWLEDGE_EMBEDDING_PROVIDER=
KNOWLEDGE_EMBEDDING_MODEL=
KNOWLEDGE_EMBEDDING_DIMENSIONS=
```

切分参数是开发默认值，不是课程或硬件阈值。修改后，新导入文档会使用新参数；已有文档不会被静默重切分。

## 原始文件放置与 Git 边界

- 本地开发原始资料建议放在 `data/knowledge/raw/`。
- 解析中间结果建议放在 `data/knowledge/processed/`。
- 两个目录均已加入 `.gitignore`，避免把内部课程资料、版权文档或大文件意外提交。
- 生产环境应将原文件放入经授权的对象存储，数据库只保存 `storage_uri`、哈希、来源信息、文本块、审核记录和向量。
- 只有项目方明确允许再分发的小型自有测试资料才可以进入 Git，并必须标记为测试数据。

## 资料门禁

正式导入前必须至少确认：资料所有者、允许用途、可否保存全文、可否用于 Embedding/外部模型、版本、来源 URI、适用硬件、整理人、技术审核人、正式批准人和失效/替换方式。官方资料还需页码/章节定位，案例还需最终修复动作与根因置信度。博客、论坛、AI 生成文本和无法追溯的文件不得直接批准为正式知识。
