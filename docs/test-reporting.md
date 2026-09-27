# 测试报告约定

核对日期：2026-09-27。本文只维护报告位置、格式、退出码和保留方式。运行依赖与命令见 [测试与评测](evaluation.md)，历史结果不能替代本次执行。

## 位置与生成范围

| 内容 | 位置 | 生成条件与 Git 边界 |
| --- | --- | --- |
| 本机流程摘要 | `output/workflow-evaluation/local-latest.md` | `verify.sh` 流程步骤或同名 CLI 输出；Git 忽略 |
| 简明机器结果、源码和输入指纹 | 同目录 `local-latest.json` | 同上；不是整个 verify 的聚合报告 |
| 完整排错附件 | 同目录 `local-latest.details.json.gz` | 按 details 策略生成；Git 忽略 |
| CI 流程结果 | 同目录 `ci-postgres.*` | Markdown 写入 Job Summary，目录上传 artifact |
| 浏览器结果 | `frontend/playwright-report/`、`frontend/test-results/` | CI 上传这两个目录；Mock E2E 本机默认仅 list 输出，真实联调生成 HTML/JSON，失败按配置保存截图 |
| 专项取证 | `output/audits/` 与 `output/workflow-evaluation/` 中明确命名的结果 | 按需保存，Git 忽略；并非每次 verify 都自动生成 |

自动运行报告不新增到 `docs/`。指南、要求映射和有独特决策价值的历史记录可以保留在文档目录，但必须标明用途和日期；不能把一次报告复制成第二份持续规则。

## 完整流程报告

在仓库根目录，使用已安装后端依赖的 Python，并配置隔离测试 `XINJIAN_EVAL_POSTGRES_DSN`：

```bash
PYTHONPATH=backend python -m app.cli.run_workflow_evaluation \
  --postgres --output output/workflow-evaluation/local-latest.json
```

`--output` 必填且以 `.json` 结尾；工具同时生成同名 Markdown。`verify.sh` 使用上述固定名称，也可通过 `WORKFLOW_EVALUATION_REPORT` 指定其他 JSON 路径。

| 参数 | 保存内容 |
| --- | --- |
| `--details failures`（默认） | 简明结果，加失败/执行错误场景的完整 gzip 附件 |
| `--details all` | 简明结果，加全部已执行场景的完整附件，适用于保留专项取证 |
| `--details none` | 仅简明结果；失败项名称仍保留 |

简明格式标记为 `report_format=workflow-summary-v1`。`cases` 保存场景状态、检查数量及失败项，不包含全部快照/预期/实际值；这些内容从附件读取。通过场景的完整材料必须显式使用 `--details all`。

| 退出码 | 完整流程含义 |
| --- | --- |
| 0 | 全部流程场景的软件检查通过 |
| 1 | 断言失败或执行错误 |
| 2 | 数据库环境受阻，或场景未完成 |

这套退出码不能套用到合成诊断 CLI：后者退出 0 只代表 `code_checks_passed=true`，语义未审阅时总体仍为 `incomplete`。不能把报告中的 software passed 写成语义、硬件或课堂通过。

## 保留与敏感信息

- 同一路径的新运行覆盖上次摘要与 JSON；本次没有附件时会删除该路径对应的旧附件，避免串读。需保留失败基线时使用独立文件名，不依赖 `latest`。
- 其他历史文件不自动删除。历史链接用于溯源，文件缺失时应标记证据不可取得，不能用旧文字补作通过。
- CI 的流程与浏览器 artifact 保留 14 天；这是项目配置，不代表本机清理策略。Job Summary 中本机相对链接不是在线附件地址，应从该次 Actions artifact 下载。
- 摘要只描述本次流程评测。后端、前端、固件、迁移等结果分别附实际命令、环境、源码状态与退出码；不得借用历史数量拼成“全量通过”。失败后未执行的后续步骤应写未执行。
- 详细附件可能包含合成请求、快照和页面内容。保留测试边界，分享前核对凭据和个人信息；历史只读清单只保留记录 ID、固定原因与数量，不导出私密正文。

## 已有专项证据入口

这些是对应历史任务的本机取证位置，不是当前门禁结果，也不是所有检出副本都必然拥有的文件：

- 第二轮修复：`output/audits/remediation-r2-latest.md`、`r2-history-inventory.json`、`remediation-r2-evidence.zip`。
- 新旧入口一致性修复：`output/audits/legacy-boundary-remediation-latest/`；报告区分原始全链路失败日志、修正后联调/离线审核结果和最终定向复测，不合并重复测试数量。
- 七项软件修复：`output/audits/software-remediation-latest/`，保存修复前失败、最终门禁、JUnit 与源码指纹；系统 Chrome 退出失败与配套 Chromium 成功分别保留。

## 格式实现与参考

实际写入规则见 [reporting.py](../backend/app/evaluation/reporting.py)；上传范围见 [CI](../.github/workflows/ci.yml)；浏览器格式见 [Mock 配置](../frontend/playwright.config.ts) 与 [真实联调配置](../frontend/playwright.integration.config.ts)。

外部设计参考：[Playwright Reporters](https://playwright.dev/docs/test-reporters)、[GitHub artifacts](https://docs.github.com/en/actions/tutorials/store-and-share-data)、[Job Summary](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands#adding-a-job-summary)。实际项目行为以上述仓库配置为准。
