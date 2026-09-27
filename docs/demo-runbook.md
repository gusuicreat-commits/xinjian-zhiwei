# 合成演示与定向重置

核对日期：2026-09-27。本文用于隔离的本地演示环境。演示会创建、上传或删除测试记录，不是只读检查；不应用于正式学生数据。

## 1. 创建测试身份

先按 [部署说明](deployment.md) 启动明确选定的环境，再运行：

```bash
docker compose exec backend python -m app.cli.seed_demo --prefix demo-local-
```

前缀必须以 `demo-` 开头且不超过 30 字符；同名演示设备已存在时失败，不覆盖。脚本创建测试用户、课程、班级、作业、设备绑定与活动实验会话；**不导入或发布实验包，不生成真实知识，也不完成真实硬件验证**。

随机凭据只在终端显示一次，数据库保存哈希；无法从哈希找回。不要把输出提交 Git 或写进公开截图。

| 输出字段 | 当前用途 |
| --- | --- |
| `rbac_student_username` / `rbac_student_password` | `/login` 默认“学生账号”入口；验证身份后选择授权实验/会话 |
| `student_page_device_id` / `student_page_device_token` | `/login` 的“测试设备演示”入口，以及模拟器上传认证 |
| `teacher_page_username` / `teacher_page_password` | `/teacher/login` 教师入口 |
| `experiment_session_id` | 已创建的测试会话标识；保留作核对，不随意换绑旧数据 |

CLI 的末尾兼容提示仍称学生账号仅供 API 使用，该提示滞后于当前登录页；字段值用途以上表和实际页面为准。学生账号存在不等于实验包已发布或课堂资料就绪。

## 2. 上传合成场景

按 [模拟器说明](../simulator/README.md) 安装并配置测试设备凭据。默认场景使用通用测试指标，未自动匹配 DHT11 的字段、规则和阈值；上传成功不能直接解释为 DHT11 故障或恢复已验证。

```bash
xinjian-simulator list
xinjian-simulator validate
xinjian-simulator run normal --iterations 1
xinjian-simulator run read-failure --iterations 1
xinjian-simulator run out-of-range --iterations 1
xinjian-simulator run recovery --iterations 2
```

这些命令只上报数据，不能代替学生明确触发诊断、反馈或教师处置。`read-failure` 一次只有一条失败日志，不承诺达到任一包的阈值；`recovery` 只是合成时间线，是否满足恢复判据由实际资料包与服务器证据判断。

离线场景应单独运行，期间停止其他心跳来源：

```bash
xinjian-simulator run offline --iterations 2
```

该命令先上报一轮，再跳过一轮；默认约 5 秒就结束，不会自动等待后端离线阈值。命令退出后保持不上报，等待实际 `DEVICE_OFFLINE_AFTER_SECONDS` 再查看。不要紧接着运行 normal/recovery 后仍声称离线已出现；超过两轮会循环场景并再次发送心跳。

AI 禁用演示保持 `AI_ENABLED=false`，学生端应显示确定性结果；切换标签页和刷新不应被当作重新诊断。完整的有断言流程使用 [评测入口](evaluation.md)，不能仅凭演示画面判定通过。

## 3. 查看记录与就绪边界

成功运行版本化场景后，在启动模拟器的工作目录生成 `.simulator-runs/<UUID>.json`，记录测试批次、场景版本和哈希。保持同一工作目录查看：

```bash
xinjian-simulator report <test-run-uuid>
```

`replay` 会按当前场景与配置创建一次新运行，不是重发原批次；详见模拟器说明。

业务就绪 API 为 `GET /api/v1/readiness/status`，页面为 `/readiness`。`ready`、`blocked`、`not_required`、`test_only` 反映具体项目，不能把某一项 ready 当作生产验收。该接口含静态待办与简单计数，不会替你实测硬件、调用 Provider 或验证部署；当前事实还需 [真实性看板](project-truth-status.md) 和对应证据。

## 4. 清理指定测试范围

只清理某次模拟器上报，可在原报告工作目录、使用原设备配置执行：

```bash
xinjian-simulator cleanup <test-run-uuid>
```

清理范围由当前认证设备和 `testRunId` 限定，不能用它清理正式数据或替代历史纠错。更换设备配置会改变请求作用的设备，执行前核对原运行报告。

需要删除整组演示身份及其绑定记录时：

```bash
docker compose exec backend python -m app.cli.reset_demo \
  --prefix demo-local- --confirm demo-local-
```

该命令按前缀、synthetic-demo 设备类型和用户/课程测试标志删除相应对象及关联记录，不删除数据卷或其他前缀。它还清理匹配前缀的角色/权限；因此前缀必须专用于这组演示，不能与其他对象共用。清理前确认所选 Compose 环境与备份，操作后按实际输出核对数量；不要把 Reset 当作运行失败时的通用修复办法。
