# Knowledge Ingestion Pipeline MVP

一个可复用、结构优先的知识库资料导入流水线。它把 PDF、DOCX、XLSX、Markdown
和 TXT 转成可追溯的 Chunk，使用本地 `Qwen3-Embedding-0.6B` 生成向量，并写入独立的
PostgreSQL + pgvector，最后通过 CLI 做 cosine similarity Top-K 检索。

本目录是完全自包含的独立子项目：它有自己的 Python 依赖、环境变量、Docker Compose、
数据库端口和数据卷。当前阶段不导入、调用或修改上层原项目的代码、配置、迁移和数据库。

## MVP 流程

```text
PDF / DOCX / XLSX / MD / TXT
  -> 格式专用 Parser（PDFium 优先，pypdf fallback）
  -> 统一 Document(content, metadata)
  -> 保守文本清洗
  -> 章节/段落/句子优先 Chunk
  -> 稳定 ID + 来源 Metadata
  -> 本地 Qwen3-Embedding-0.6B
  -> PostgreSQL + pgvector
  -> cosine Top-K 检索
```

## 环境要求

- Python 3.9+（推荐 3.11 或 3.12）
- Docker Desktop 或其他可运行 Docker Compose 的环境
- 首次从 Hugging Face 加载模型时需要网络，约需下载模型权重并预留缓存空间
- Apple Silicon 会自动优先选择 MPS；MPS 不可用时回退 CPU。也可显式设置
  `KIP_EMBEDDING_DEVICE=mps` 或 `KIP_EMBEDDING_DEVICE=cpu`

当前机器检查结果（2026-08-16）：arm64 Apple Silicon；Docker/Compose CLI 已安装；系统
Python 为 3.9.6；检查时 Docker daemon 的 socket 不可访问，因此真实 pgvector 集成测试需在
Docker Desktop 启动后执行。

## 安装

所有命令都在本目录执行：

```bash
cd knowledge-ingestion-pipeline
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

示例配置把 Hugging Face 缓存设为本项目的 `.cache/huggingface`，该目录不会提交到 Git。

如果只运行不下载模型的快速单元测试，可安装较轻的测试依赖：

```bash
python -m pip install -r requirements-test.txt
```

## 启动独立 PostgreSQL + pgvector

```bash
docker compose up -d
docker compose ps
```

服务只映射到宿主机 `55432`，使用独立容器 `knowledge-ingestion-postgres` 和独立数据卷
`knowledge_ingestion_pgdata`。应用首次导入时自动创建 `vector` 扩展、`documents` 与
`chunks` 表及向量索引。

## 本地模型

默认配置直接使用 Hugging Face 模型 ID：

```dotenv
KIP_EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B
KIP_EMBEDDING_MODEL_PATH=
KIP_EMBEDDING_DEVICE=auto
KIP_EMBEDDING_BATCH_SIZE=16
KIP_EMBEDDING_DIMENSION=1024
```

首次导入/查询会由 `sentence-transformers` 下载并缓存在本机。若需要离线或固定版本，先把
模型快照下载到任意本地目录，再把 `KIP_EMBEDDING_MODEL_PATH` 设置为该目录；业务代码无需修改。
模型逻辑只存在于 `app/embeddings/`，Parser、Chunker 和 Storage 不依赖模型实现。

## 导入资料

把资料放入 `documents/`，然后执行：

```bash
python -m app.ingest ./documents
```

也可传入单个文件。目录会递归扫描，忽略不支持的扩展名。命令输出文件、成功、失败、Chunk、
Embedding、重复、需 OCR 文件及错误列表。单文件失败会被捕获，不会中断整批。

Parser 或切分配置升级后，可显式重新处理已有文件。新内容完成解析和向量化后，旧文档与 Chunk
才会在同一个数据库事务中被替换：

```bash
python -m app.ingest ./documents/manual.pdf --force
```

文件内容 SHA-256 是稳定文档 ID；同一内容再次导入会在生成向量前被识别并跳过。Chunk ID
由文档 ID、结构 Metadata 与 Chunk 内容哈希共同生成。每个 Chunk 均保留来源；PDF 保留页码和
推断章节，DOCX 保留标题/段落/表格类型，XLSX 保留工作表、行号和列名。

PDF 默认用 PDFium 提取，并对每页做文本质量评分；PDFium 异常或低质量时自动尝试 pypdf，选择
质量更高的结果。Metadata 会记录 `extraction_method`、`text_quality_score` 和
`font_mapping_missing`。扫描型、几乎无文本或原生文本质量不合格的页面会记录
`ocr_required=true` 并出现在导入报告中。MVP 不会静默丢弃或编造 OCR 文本。

## 语义查询

```bash
python -m app.query "ESP32 I2C传感器无法响应" --top-k 5
```

输出相似度、原文、来源、页码/章节（若存在）和 Chunk ID。本项目不调用 LLM，也不生成诊断答案。

## 配置

全部配置均来自 `.env`/环境变量，示例见 `.env.example`：数据库 URL、模型名称或路径、device、
batch size、向量维度、Chunk 大小/overlap、Top-K、PDF 主引擎和文本质量阈值均可调整。若更换为不同
维度的模型，应同步修改 `KIP_EMBEDDING_DIMENSION`，并对新的空数据库初始化表结构。

## 测试

快速测试不加载真实模型，也不需要数据库：

```bash
pytest -m "not integration and not model"
ruff check app tests
```

Docker 启动后运行 pgvector 集成测试（测试使用 1024 维替身向量并清理自己的记录）：

```bash
TEST_DATABASE_URL=postgresql://knowledge:knowledge@localhost:55432/knowledge_ingestion \
  pytest -m integration
```

真实模型测试会下载/加载 Qwen 模型，默认跳过：

```bash
RUN_REAL_MODEL_TEST=1 pytest -m model
```

测试覆盖 TXT/MD、PDF 文本与 OCR 标记、DOCX、XLSX 结构记录、Metadata/稳定 Chunk ID、
批次失败隔离、重复导入幂等、EmbeddingProvider 契约，以及可选的 pgvector cosine 检索与真实模型。

## 当前边界

支持：PDFium/pypdf 多引擎 PDF、DOCX、XLSX、Markdown、UTF-8 TXT；结构优先切分；本地向量；幂等导入；
来源追踪；cosine Top-K。

暂不支持：OCR、旧版 `.doc`/`.xls`、图片/音视频、PDF 复杂版面与跨页表格还原、密码文件、远程对象
存储、后台任务、权限、多租户、混合检索、重排、LLM/RAG 答案生成。PDF 章节为保守启发式推断，
不会自动改写或补充原始知识。

## 后续对接方式（本阶段未实现）

- **FastAPI**：在 API 层注入 `IngestionPipeline` 和 `PostgresVectorStore`，将 CLI 参数换成上传文件/
  查询请求；核心模块无需改写。
- **LangChain**：为 `EmbeddingProvider` 和 `PostgresVectorStore` 写薄适配器，保持当前数据库 schema
  与来源 Metadata 为事实源。
- **原项目**：优先通过独立 HTTP 服务或任务队列调用；若后续决定作为 Python 包接入，也只依赖本
  项目的公开接口。接入前应单独评审数据库、鉴权、任务状态和迁移策略。
