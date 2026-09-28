# 芯鉴知微

**让嵌入式实验中的问题有据可查，让学生知道下一步该检查什么。**

面向高校嵌入式与物联网实验课程，收集开发板状态、日志和读数，提供规则诊断、排查指导、学生反馈与教师处置。后端使用 FastAPI/PostgreSQL，前端使用 Vue 3，LangGraph 编排固定诊断流程。

目前具备 V2 软件框架，正在准备实物验证。DHT11 资料包是 **`2.0.5` 测试草稿**，ESP32 固件已编译，尚未完成硬件和课堂验收。

## 能做什么

| 使用者 | 主要任务 |
| --- | --- |
| 学生 | 查看设备数据和异常说明，按分级提示排查；用新上传数据重新检查，反馈结果或请求教师帮助。 |
| 教师 | 查看授权课堂的异常和求助，处理工单，审核诊断与案例。 |
| 维护者 | 维护版本化实验资料包、规则与来源，核对软件实现和待确认事实。 |

设备上传 → 规则识别异常 → 故障树给出有限候选与步骤 → 学生排查/教师介入 → 经事实确认和审核后沉淀案例。

| 当前范围 | 说明 |
| --- | --- |
| 实验资料 | DHT11 温湿度 `2.0.5` 与 GPIO LED `2.0.3`，均为测试草稿。包内保存硬件配置、规则、故障树、知识、步骤和测试样例，运行绑定发布快照。 |
| AI 辅助 | 默认关闭；开启后辅助候选排序与中文解释，失败时保留确定性诊断。当前不使用 RAG、向量检索或自由规划 Agent。 |
| 已知边界 | “仍未解决”继续原指导；“重新检查”分析已上传数据，不控制硬件采样。资料包更新不会改写历史判断。 |

**证据、异常和根因分开。** 读取失败不能证明接线错误；LED 的 HIGH 命令不能证明实际发光；没有报错也不能证明硬件正常。证据不足时保留“未知/需要验证”。示例 GPIO、阈值和测试案例不能直接当正式接线、课程标准或教师经验。

当前版本、软件限制和测试证据见[实现状态](docs/implementation-status.md)；硬件、教师资料及真实效果缺口见[真实性看板](docs/project-truth-status.md)。

## 第一次体验

已有部署时，向维护者获取地址及测试身份，先查看“就绪状态”。本机启动需 Docker 与 Docker Compose，配置说明见[部署手册](docs/deployment.md)。首次配置：

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
```

已有 `.env` 时保留现有配置。默认入口：[首页](http://localhost:8080)、[学生登录](http://localhost:8080/login)、[教师登录](http://localhost:8080/teacher/login)、[就绪状态](http://localhost:8080/readiness)、[开发接口文档](http://localhost:8000/docs)。

创建合成测试身份与演示数据：

```bash
docker compose exec backend python -m app.cli.seed_demo --prefix demo-local-
```

使用终端输出的设备 ID/令牌和教师用户名/密码，凭据只显示一次。已有同名前缀时按[演示手册](docs/demo-runbook.md)处理。演示数据不是实物诊断结果，也不会自动发布新资料包。

## 开发与下一步

- 开发前读[开发入口](AGENTS.md)和[开发准则](docs/development-guidelines.md)，按[文档索引](docs/README.md)定位模块契约。
- 开发验证入口为 `scripts/verify.sh`，需要 Python 3.10+ 及对应依赖；可用 `BACKEND_PYTHON=/path/to/python scripts/verify.sh` 指定环境。命令和覆盖范围见[测试与评测](docs/evaluation.md)。
- 下一步优先补齐实物和课程证据：核对候选器件、接线和程序，按[硬件验证计划](docs/hardware-validation-plan.md)做正常—单因素故障—恢复对照，由教师确认教学动作和验收判据。
