# 测试报告放在哪里、怎么看

本项目将简明结果与排错附件分开：测试照常执行全部检查，精简的是保存和展示方式。报告长度不代表测试覆盖率。

## 固定位置

| 内容 | 位置 | 是否进入 Git |
| --- | --- | --- |
| 报告约定、运行命令 | 本文 | 是 |
| 本机流程摘要（给人看） | `output/workflow-evaluation/local-latest.md` | 否 |
| 简明机器结果、源码和输入指纹 | 同目录 `local-latest.json` | 否 |
| 失败用例的完整排错附件 | 同目录 `local-latest.details.json.gz`，按需生成 | 否 |
| CI 流程结果 | 同目录 `ci-postgres.*`；摘要同步到 Actions Job Summary | 否；上传 Actions artifact |
| 浏览器原生报告、失败截图 | `frontend/playwright-report/`、`frontend/test-results/` | 否；上传 Actions artifact |
| 以前的详细审计记录 | `output/audits/`、`output/workflow-evaluation/` 既有文件 | 否；原地保留 |

自动报告不再放进 `docs/`，也不新建散落的日期文件夹。根 README 通过本文找到固定摘要入口。浏览器报告沿用 Playwright 的已有目录，不为统一外观搬动工具目录。

## 如何运行

完整本机门禁仍用 `scripts/verify.sh`，需要有效的 `BACKEND_PYTHON`、模拟器环境和专用 `XINJIAN_EVAL_POSTGRES_DSN`。流程部分也可单独运行：

```sh
PYTHONPATH=backend python -m app.cli.run_workflow_evaluation \
  --postgres --output output/workflow-evaluation/local-latest.json
```

- 默认生成 Markdown 摘要和简明 JSON。通过用例只保留结果、检查数量等信息。
- 失败/执行错误用例完整内容保存到独立 gzip JSON，包含快照、预期/实际值、事件等，不改变任何判定。
- `--details all` 为所有已执行场景保存完整记录；仅用于需要详细取证的运行。
- `--details none` 不保存完整附件，失败项名称仍保留在摘要及简明 JSON。
- 缺数据库返回受阻、退出 2；场景未执行返回未完成、退出 2；失败退出 1；全部软件检查通过退出 0。压缩报告不改变退出码。
- 新 JSON 增加 `report_format=workflow-summary-v1`；`cases` 中不再包含完整快照及检查值。需要这些数据的消费者须读取附件（通过场景需显式 `--details all`），不能继续假定简明文件是原始快照。

## 保留与清理

本机常规执行复用固定文件名，覆盖上次自动摘要与结果；本次没有附件时删除该文件名对应的旧附件，避免误读上次失败。其他历史文件不自动删除。

需要保留某次取证时，可以通过 `--output output/workflow-evaluation/<明确名称>.json --details all` 命名保存；由负责人决定何时删除。旧审计记录本轮不移动、不删除，历史文档链接继续有效。这是刻意保留，不是已经实施了历史自动清理。

CI 摘要放 Job Summary，文件作为 artifact 保留 **14 天**，不提交源码库。这个期限是本项目选择，不是官方规定。Job Summary 中附件需从该次运行的 artifact 下载，不能把本机相对链接当在线地址。

## 依据与边界

- [Playwright Reporters](https://playwright.dev/docs/test-reporters)：支持简洁终端结果与完整 JSON 同时输出，详细失败信息与成功信息采用不同详略程度。
- [GitHub Actions artifacts](https://docs.github.com/en/actions/tutorials/store-and-share-data)：测试结果等作为运行产物保存，并支持 `retention-days`。
- [GitHub Job Summary](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands#adding-a-job-summary)：通过 `GITHUB_STEP_SUMMARY` 展示 Markdown 摘要。

源码和输入指纹仍保留。语义审阅、硬件验证未执行时必须如实标记，不因为软件流程通过而变成通过。当前摘要只汇报这次流程评测，不自动借用历史前端或全量测试数量。
