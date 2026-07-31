# Phase 7 教师端 Design QA

## Comparison target

- source visual truth path: `docs/design-qa/phase7-teacher-ui/reference.png`
- implementation URL: `http://127.0.0.1:5173/teacher`
- implementation screenshot path: `docs/design-qa/phase7-teacher-ui/dashboard-viewport.png`
- navigation audit screenshots: `docs/design-qa/phase7-teacher-ui/menu-audit-before.png` and `docs/design-qa/phase7-teacher-ui/menu-audit-after.png`
- mobile screenshot path: `docs/design-qa/phase7-teacher-ui/dashboard-mobile.png`
- viewport: desktop 1680×940；mobile 390×844
- state: 当时通过临时审阅令牌进入教师端；当前教师端已改为正式 Bearer 测试账号。该次 SQLite 验收含 1 台明确标记的测试设备、测试日志与规则诊断，没有真实硬件数据

## Comparison evidence

- full-view comparison: `docs/design-qa/phase7-teacher-ui/full-comparison.jpg`
- focused top/navigation/KPI/chart comparison: `docs/design-qa/phase7-teacher-ui/top-comparison.jpg`
- focused table/log/intervention/knowledge comparison: `docs/design-qa/phase7-teacher-ui/detail-comparison.jpg`
- 两侧已统一为 1680×940、相同深色教师总览状态后同屏检查。

## Findings

- 无未解决 P0/P1/P2。
- 字体与排版：实现使用项目既有 Inter、苹方、微软雅黑系统栈，保持源图的紧凑层级；标题、数字、说明和表格小字有明确权重差。动态长设备 ID 和错误码使用截断或可滚动容器，没有溢出。
- 间距与布局：桌面保留顶部栏、左侧导航、四个 KPI、四个分析区和三列详情区；最终页面高度 956px，接近源图单屏密度。390px 下 KPI 为两列、分析区为单列、导航转为底部三项，没有水平溢出。
- 颜色与视觉令牌：深海军蓝画布、蓝色描边和高亮、青绿在线、橙色警告、红色异常、紫色完成率状态与源图一致；空状态保持低对比但可读。
- 图像与图标：源图没有必须复用的照片或产品图。实现使用统一 Element Plus 图标库表达芯片、设备、告警、用户和导航，不使用 emoji、手绘 SVG、CSS 图形或虚构教师头像。
- 文案与内容：静态中文文案可独立理解；实现没有复制源图中的虚构教师名、学生名、设备数和完成率。缺失业务模型明确显示“未配置”，测试记录明确标记为“测试/模拟”。
- 交互与状态：左侧导航仅保留“数据总览、设备分析、异常处置”三个当前可用模块，顺序与页面自上而下的内容一致；点击会定位到对应区块，页面滚动时当前项同步高亮。知识审核仍是 Phase 8 禁用卡片，不再冒充主导航功能。另验证了搜索过滤、侧栏折叠/展开、刷新、临时教师会话登录和禁用的知识审核入口；接口失败有可恢复错误页，空数据使用明确空状态。
- 响应式与可访问性：桌面与移动端 `scrollWidth === clientWidth`；核心按钮有可访问名称，图表有 `role=img` 与中文标签，禁用入口保持 disabled 语义。

## Comparison history

1. 首次同屏比较发现 P2：右侧介入空状态继承了通用 220px 空容器高度，导致详情行被拉高，页面密度明显低于源图。
2. 修复：为 `.intervention-panel .el-empty` 设置 128px 专用高度，保持空状态可读，同时收紧详情行。
3. 修复后证据：重新捕获 `dashboard-viewport.png` 并重建三个 comparison 文件；页面高度从 1121px 降至 956px，桌面主体与源图恢复接近的一屏密度，未产生裁切或重叠。
4. 导航审查发现原八项菜单包含重复锚点、未实现功能和固定首项高亮，菜单文案及顺序与页面内容不一致。
5. 修复：收敛为三个真实页面区块，加入锚点定位、滚动同步、`aria-current` 和键盘焦点样式；前后截图分别为 `menu-audit-before.png` 与 `menu-audit-after.png`。

## Open questions

- 源图中的班级进度、学生异常名单、教师姓名和知识案例均无仓库数据支持。当前差异属于数据真实性约束；待项目方提供账号/班级/任务模型及知识来源后再实现对应真实状态。

## Primary interactions tested

- 使用当前测试教师用户名、密码登录并进入 `/teacher`。
- 搜索不存在的错误码后，异常表从 1 条过滤为 0 条；清空后恢复。
- 侧栏从 206px 折叠到 76px，再正常展开。
- 手动刷新成功；30 秒自动刷新逻辑保持启用。
- 内容超过视口时，桌面页面可从顶部向下滚动并返回；根滚动容器没有被固定高度裁切。
- 三个导航入口分别定位到总览、设备分析和异常处置；到达底部时异常处置保持高亮，返回顶部后数据总览恢复高亮。
- 390×844 下显示两列 KPI、单列内容和底部三项导航。
- 浏览器控制台 error：0。

## Follow-up polish

- P3：真实班级/任务数据接入后，可在现有“未配置”卡位置启用 ECharts 实验进度图，并补充表格分页；在数据模型出现前不应以演示数据填充。

final result: passed
