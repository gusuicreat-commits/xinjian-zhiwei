# Agent 开源复用与框架选型评估

日期：2026-10-07。状态：源码与官方文档评估完成，尚未安装候选依赖、运行第三方代码或进行真实模型性能对照。

## 1 结论

**当前项目优先复用已有 LangGraph 和官方工具循环示例；PydanticAI 为 Python 备选；Pi 保留为条件候选。现有证据不足以认定 Pi 最优，也不足以证明换框架会提升诊断正确率。**

有可直接作为依赖使用的基础组件、有改造价值的模板，也有接近嵌入式场景的资料和测试项目。本次样本中没有核实到能直接替代芯鉴知微、同时满足课程权限、证据版本、预算回执和教师确认合同的完整成品。这是有限检索结论，不代表 GitHub 上不存在其他项目。

前一方案把 Pi 桥接和通用任务运行设施设计得过早。修订后先完成复用清单与最小 LangGraph 原型，出现明确能力缺口才投入第二框架；不用为了比较而先完整建设多个运行时。

按当前[产品背景与PRD](product-background-prd.md)，本次取证能力服务于 FR-04至FR-06：利用实际设备内部运行证据辅助分析、解释与验证。先判断既有信号能否区分问题，再判断是否需要动态查询；不能把查文档次数或聊天自然度当成产品价值。查询组件也不替代 FR-01/FR-02 的真实观测和采集能力。最终效果同时分开核对新增信息的收益与同一证据下规则加AI的额外收益。

## 2 核查范围与方法

通过 GitHub 官方 API 核对 15 个仓库的归属、归档状态、最近推送、许可证元数据和主分支提交；下载 README，并进一步阅读重点模板、调用/预算源码、示例和许可证。OpenAI Agents SDK 另查官方文档。检索词包含 embedded fault diagnosis llm、iot diagnosis agent、langgraph human in the loop、fault diagnosis agent、IoT anomaly；严格检索无结果后扩大关键词。

深入核对：LangGraph、react-agent、PydanticAI；Pi 沿用前轮已读官方核心/SDK/持久化文档并更新仓库状态；其他框架用于范围筛选。没有把 README 功能声明当成产品已验收，也没有依据 star 数决定选型。最近推送只说明存在活动，不证明发布质量、维护响应或无漏洞。

本项目已锁定 `langgraph==1.2.11`、`langgraph-prebuilt==1.1.0`、`langgraph-checkpoint-postgres==3.1.2`、`pydantic==2.13.4`；见[依赖锁](../backend/requirements.lock)。[诊断图](../backend/app/ai/diagnosis_graph.py)已有 interrupt，[恢复服务](../backend/app/services/diagnosis_workflow.py)已有 Command 和 thread 身份校验，不能将这些重新列为从零建设的能力。

## 3 哪些现成项目值得复用

### 3.1 第一优先级是 LangGraph 官方组件与模板

| 来源 | 已核实的可用部分 | 在本项目的使用方式 |
| --- | --- | --- |
| [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) | StateGraph、条件边、ToolNode、interrupt/Command、checkpoint 生态 | 继续依赖现有包；编排、工具分发和暂停恢复优先用现成机制 |
| [langchain-ai/react-agent](https://github.com/langchain-ai/react-agent) | `src/react_agent/graph.py` 的模型→工具→模型循环及终止分支 | 作为小范围参考/改造模板，替换模型调用、工具与终止合同，不整仓覆盖项目 |
| [官方人工中断文档](https://docs.langchain.com/oss/python/langgraph/interrupts) | 结构化中断、恢复及节点重执行语义 | 扩展现有恢复路径；问答身份、权限和业务回执仍使用项目服务 |

已经查看模板的实际 `graph.py`、`tools.py` 和 `pyproject.toml`，有四处必须改造：

1. 默认工具是 Tavily 通用搜索，不是受权课程查询；替换为已有证据、固定包和已审核案例服务。
2. `call_model` 直接 `.ainvoke()`，会绕开本项目治理；改接现有治理入口，不能复制第二套预算。
3. 无 tool_calls 即结束、步数耗尽返回通用文字，不满足本项目“材料满足/仍未知/资源终止”区分；接入任务完成合同。
4. 模板要求 Python >=3.11，且带多个 Provider 和 Tavily 依赖；项目声明 Python >=3.10。不得整份复制其依赖或因模板静默提高运行要求，选取与已锁版本兼容的结构即可。

源码依据：[模型和循环](https://github.com/langchain-ai/react-agent/blob/f5520937686b06d7139a165e71af1b86e291b866/src/react_agent/graph.py)、[示例工具](https://github.com/langchain-ai/react-agent/blob/f5520937686b06d7139a165e71af1b86e291b866/src/react_agent/tools.py)、[依赖要求](https://github.com/langchain-ai/react-agent/blob/f5520937686b06d7139a165e71af1b86e291b866/pyproject.toml)。模板是 MIT；复制代码保留相应版权和许可说明，记录上游提交及本地改造。

ToolNode 是工具分发组件，不是权限系统。若它在当前锁定版本中的并发/错误包装行为不符合任务合同，应通过官方配置及业务工具包装层适配，保留授权失败的终止语义；不要因为引入现成组件而放宽检查。只有少量 JSON 动作时也可直接用现有服务函数，避免为使用 ToolNode 强行增加消息转换层。

### 3.2 PydanticAI 有直接相关的现成能力

[pydantic/pydantic-ai](https://github.com/pydantic/pydantic-ai) 提供类型化工具、依赖注入、结构化输出和延迟工具结果。官方还有 [FastAPI 聊天示例](https://pydantic.dev/docs/ai/examples/conversational-agents/chat-app/)、[Deferred Tools](https://pydantic.dev/docs/ai/tools-toolsets/deferred-tools/) 和 [Moonshot/Kimi 适配](https://pydantic.dev/docs/ai/models/moonshotai/)。

可复用点：把服务器持有的任务服务通过依赖注入交给工具；用结构化输出传递动作；等待人工答复时结束当前运行，之后按工具请求身份提交结果。示例银行客服通过依赖传递对象身份的模式可借鉴，但它不是本项目的班级/历史权限实现。

改造成本包括：接入持久化外发治理、输出投影、错误和重试政策、现有 LangGraph 外层状态与 PydanticAI 内层运行之间的职责划分。只有在能显著减少所需适配代码时才新增它；不同时建立两套通用工作流。

其源码 `UsageLimits` 明确区分请求数预检和响应后的 token 核算，默认请求上限是 50。部分预先计数取决于 Provider 支持，不能把它直接当成当前 Kimi 的持久化人民币硬预算，也不能照搬默认 50 次调用。源码依据：[usage.py](https://github.com/pydantic/pydantic-ai/blob/402a2eddbafc5445472f9c4f951431652ffb204d/pydantic_ai_slim/pydantic_ai/usage.py)。

官方 Kimi 示例使用的模型名不是本项目既定 `kimi-k2.6`；只采纳接口适配依据，不随示例换模型。版本、tool-calling、thinking、错误/usage和账单行为仍需项目小样本验证。

### 3.3 嵌入式领域确有可参考的资料与测试

[iot-agent/iot-skillsbench](https://github.com/iot-agent/iot-skillsbench) 是嵌入式编程和硬件在环评测项目，仓库采用 Apache-2.0。已查看 `skills-human-expert/dht11.md` 和 `scripts/auto_test.py`；具有与本项目相关的 DHT11 资料、硬件任务及编译/烧录/观察流程。

适合借鉴任务组织、硬件验证记录及资料清单，不能直接当成学生诊断平台。脚本包含生成代码、编译、烧录和人工成功/失败输入；它不等于独立自动测量，也不应被产品 Agent 直接调用。其 DHT11 简短资料没有自动证明适用于本项目具体器件、接线与厂家版本，仍需按资料包流程核对一手来源与实物。

[davidfertube/anomaly-agent](https://github.com/davidfertube/anomaly-agent) 以燃气轮机传感器异常检测和模型解释为核心，可参考异常展示。领域、输入与确认链条差异大，不推荐改造成项目主干。README 声称 MIT，但本次文件树未发现独立许可证文件且 API 未识别许可证；在核实授权前不复制代码。这一限制只针对当前证据，不推断作者没有许可意图。

### 3.4 可下载但当前不值得接入的组件

| 项目 | 原因 |
| --- | --- |
| [agent-chat-ui](https://github.com/langchain-ai/agent-chat-ui) | Next.js/React，面向 LangGraph Server；现有 Vue + FastAPI 可复用，整套引入会增加前端栈。可借鉴进度和人工交互设计 |
| [langgraph-bigtool](https://github.com/langchain-ai/langgraph-bigtool) | 面向大量工具的检索与发现；当前仅少量明确业务工具，没有相应需求 |
| [deepagents](https://github.com/langchain-ai/deepagents) | 提供文件系统、子代理、上下文管理等完整能力；当前受限取证不需要这套默认能力，可以保留作未来开发/资料助手候选 |
| [Dify](https://github.com/langgenius/dify) | 可运行的应用平台，适合独立快速演示；整合会新增工作流、账号/知识与运维边界，并非给已有后端添加一个小循环 |

Dify 的 LICENSE 是带附加条件的 Apache 2.0 修改版，涉及多租户服务及前端标识，不能直接列为普通 Apache-2.0；具体使用方式应按[原文](https://github.com/langgenius/dify/blob/b369e875feabac591a9b74a7debca9bc56bbe982/LICENSE)核对。此处只说明选型差别，不对项目未来使用作法律结论。

## 4 框架适配比较

下表是基于项目结构和公开接口的工程判断，不是性能排行榜。所有候选都需要应用提供课程授权、证据语义、持久化预算与未知结果处理。

| 候选 | 可利用优势 | 对本项目的主要成本或局限 | 建议 |
| --- | --- | --- | --- |
| LangGraph | 已有依赖、状态图、PostgreSQL checkpoint及恢复路径；可组合受限循环 | 原生机制不替代业务幂等；工具权限和完成条件仍要接项目服务 | 首选，先验证最小增量 |
| PydanticAI | Python、类型化依赖/输出、延迟工具结果、Kimi适配 | 增加新的模型运行层；要校准其重试、用量、消息与现有治理 | 第一备选，先做有限适配比较 |
| Pi Agent核心 | 可组合工具循环、事件、自定义模型流；适合定制 Agent 运行器 | Python↔Node、取消/错误/状态协议、隔离和模型桥接；仍需完整业务约束 | 条件候选，当前不优先 |
| OpenAI Agents SDK | 现成循环、工具、结构化结果、人工审核和运行状态 | 保留 Kimi 时需核对兼容模型路径；现有预算和输出合同需要适配，不能把 guardrail 当授权 | 可用备选，本轮无充分理由新增 |
| Microsoft Agent Framework | Python/.NET、工作流、中间件、checkpoint及人工介入 | 已有 LangGraph 能覆盖当前主要编排需求，迁移收益尚未证实 | 未来跨语言/企业集成时再考虑 |
| Agno | Python、工具/会话，AgentOS 提供应用运行与接口能力 | 只用库可行，但整套 AgentOS 与现有后端和持久化职责重叠 | 不优先整套引入 |
| CrewAI | 同时提供 Agents/Crews 和受控 Flows | 目前没有多角色协作需求；Flows 也需要重新适配现有治理 | 非首选，不能仅因多 Agent 宣称效果更好 |
| smolagents | 小型工具/代码 Agent，支持多模型；也可用 ToolCallingAgent | 代码执行不是当前教学取证需求；即使用工具模式仍增加运行层 | 离线研究候选，不引入 CodeAgent 默认路线 |

补充状态：AutoGen 官方 README 已标维护模式，并指向 Microsoft Agent Framework；新接入不推荐从 AutoGen 开始。GitHub 元数据把其许可证识别为 CC-BY-4.0，但源码另有 MIT `LICENSE-CODE`，不能把文档许可证套到全部代码。

来源：[MAF](https://github.com/microsoft/agent-framework)、[Agno](https://github.com/agno-agi/agno)、[CrewAI](https://github.com/crewAIInc/crewAI)、[smolagents](https://github.com/huggingface/smolagents)、[AutoGen](https://github.com/microsoft/autogen)、[OpenAI SDK模型](https://developers.openai.com/api/docs/guides/agents/models)、[人工审核及Guardrails](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals)。上述 README 描述未转化为本项目的运行通过结论。

## 5 明确哪些不重造 哪些仍要写

| 能力 | 复用位置 | 项目只补什么 |
| --- | --- | --- |
| 图调度与条件分支 | 已安装 LangGraph | 取证任务的少量节点与结束条件 |
| 暂停/恢复和 checkpoint | 现有 interrupt/Command 及 Postgres saver | 问题/答复身份、授权重验、幂等回执与合法新修订 |
| 工具 Schema与分发 | Pydantic、合适时的 ToolNode | 对业务服务的薄包装和资格检查 |
| 模型 HTTP、超时与错误 | 现有 clients + governance | 仅在确需原生工具调用时扩展明确缺少的消息合同 |
| 预算、尝试与未知结果 | 现有 AI 操作/预留记录 | 新阶段归因及统一上限，禁止第二套扣账 |
| 证据/包/知识检索 | 现有领域服务 | 将必要查询暴露为有界工具，不自建向量库 |
| 学生页面和反馈恢复 | Vue与现有 API 基础设施 | 一道许可问题的展示与提交，不引入第二前端 |
| 评测及报告 | 现有 rubric、pytest、隔离 PostgreSQL 和报告约定 | 动作过程反例与配对样本，不另起通用评测平台 |

现成框架不能提供“本班教师何时失去权限”“哪些观察在本实验获准”“哪个版本来源可以交付”等项目语义。这些是业务实现。它们应复用已有共同服务，而非复制到每个框架适配器。

LangGraph 官方明确指出 interrupt 恢复可能重执行节点，中断前副作用必须幂等。因此复用 checkpoint 可以减少运行基础设施代码，但不能删除业务回执。反过来，也不能因为需要业务回执，就重新开发通用 checkpoint、调度器或会话树。[中断语义依据](https://docs.langchain.com/oss/python/langgraph/interrupts#side-effects-called-before-interrupt-must-be-idempotent)

## 6 对原方案的具体修订

1. 先做 **A现有流程 / B0最小LangGraph受控查询**。B0可以沿用当前受管 JSON 动作选择，使用既有模型客户端和任务合同；明确标记为 JSON 选择器，不冒充原生 function calling。
2. 先复用官方组件/模板及本地 query-task-v2 反例，不从零编写通用 Agent 循环。将本机历史原型按审核后的最小范围迁入版本控制，不复制审计目录作生产模块。
3. B0满足任务且有稳定收益时，优先沿现有栈完善；没有收益时先排查材料与任务设计，不能靠换框架掩盖问题。
4. 出现明确、可复现的接口/维护缺口后，比较 **B1原生工具调用 / D PydanticAI**。只做同一任务的最小适配，不同时建设第二套状态库。
5. **C Pi** 仅在其扩展或运行能力对应明确需求时加入。B1/C/D 保持等价能力与治理；B0与原生工具组之间的差异不得单独归因于框架。
6. 推迟 Node IPC、Pi专用隔离、通用租约/fencing及新增任务表的施工；先证明现有服务无法满足哪些要求。必要的问题/答复业务字段仍要设计，但不预设建设通用平台。
7. 保留原方案的安全、语义、预算和异常时序判据；减少候选数量，不减少必要反例。只运行已激活组的完整配对批次，不预支全部四组费用。

实施时先形成一张组件采用清单：上游名称/版本/许可、具体复用接口或文件、最小改造、已有规则入口、验证实例。依赖优先锁版本正常引入；小模板可保留许可后改造；不复制整个框架源码长期自维护。

## 7 维护证据与检查限制

2026-10-07查询到最新正式发布：LangGraph `1.2.14`、PydanticAI `v2.54.0`、Pi `v1.0.4`。这些是查询时点的发布状态，**不构成升级建议**。本轮功能深入核对主要来自下列主分支快照；采用前还要在选定发布 tag 重验，不能假定主分支功能全部进入发行包。

| 仓库 | 阅读快照 | 最近推送日期 | 许可核查 |
| --- | --- | --- | --- |
| langgraph | `708aaa4ebc1cba2621aa6113050eb519a5a1bfdb` | 2026-10-07 | MIT 元数据 |
| react-agent | `f5520937686b06d7139a165e71af1b86e291b866` | 2026-10-01 | MIT 元数据及项目声明 |
| pydantic-ai | `402a2eddbafc5445472f9c4f951431652ffb204d` | 2026-10-07 | MIT 元数据 |
| pi | `b30a6dd779340f7bc2f3ffa60f4c0a5f914ba9ae` | 2026-10-07 | MIT 元数据；功能细读另见原方案固定快照 |
| iot-skillsbench | `426cdbb9c9b1fcee1e8d76aacb0d475b19da1a50` | 2026-07-09 | Apache-2.0 元数据及LICENSE入口 |
| anomaly-agent | `963f64c24cd0a65bb7aa31986e93de86c8581a8a` | 2026-08-23 | README声称MIT，独立许可待核实 |
| dify | `b369e875feabac591a9b74a7debca9bc56bbe982` | 2026-10-07 | 已读附加条件原文 |
| autogen | `027ecf0a379bcc1d09956d46d12d44a3ad9cee14` | 2026-04-15 | 已读维护说明及MIT代码许可 |

候选主干与模板的源码下载只用于静态检查，没有安装、导入执行、烧录或使用真实凭据。尚未完成依赖解析、完整许可证/安全审计、Kimi2.6适配回归和效果基准，故不声称任何候选“下载后已能在本项目直接运行”。

最终建议：**先复用 LangGraph 完成最小增量，PydanticAI用于有目标的备选比较，Pi不再作为默认必须落地的第三组。** 后续执行范围与停止判据见[修订后的方案](pi-controlled-query-plan-20261007.md)。
