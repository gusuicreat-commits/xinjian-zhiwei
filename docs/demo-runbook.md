# 合成演示与重置手册（P11）

## 强制边界

演示数据统一使用 `demo-` 前缀和 `is_test_data=true`。脚本不会导入真实学生、真实设备、
正式知识或生产参数。Seed 输出的随机测试凭据只在终端显示一次，不写入仓库。

## Seed

```bash
docker compose exec backend python -m app.cli.seed_demo --prefix demo-local-
```

若前缀已存在，脚本失败，不覆盖。请将一次性输出仅保存在本地临时安全位置。

- `student_page_device_id` 与 `student_page_device_token`：用于前端 `/login`。
- `teacher_page_username` 与 `teacher_page_password`：用于前端 `/teacher/login`。
- `rbac_student_username` 与 `rbac_student_password`：用于课堂范围 Bearer API；当前设备
  中心学生页面不使用这组账号。

设备令牌与密码只显示一次，数据库只保存哈希，无法反向找回。

## 场景

使用 seed 输出的测试设备凭据配置模拟器，然后依次执行：

```bash
xinjian-simulator run normal --iterations 1
xinjian-simulator run read-failure --iterations 1
xinjian-simulator run offline --iterations 2
xinjian-simulator run out-of-range --iterations 1
xinjian-simulator run recovery --iterations 2
```

AI 禁用演示保持 `AI_ENABLED=false`，学生端应继续显示确定性解释，不应显示 AI 成功。
每次运行产生 `testRunId` 和本地报告，可用 `xinjian-simulator cleanup <UUID>` 定向清理。

## Readiness

- API：`GET /api/v1/readiness/status`
- 页面：`/readiness`

状态只允许 `ready`、`blocked`、`not_required`、`test_only`。真实硬件、正式知识、正式
课堂数据或生产部署缺失时必须保持 `blocked`，不得为了演示改成 ready。

## Reset

```bash
docker compose exec backend python -m app.cli.reset_demo \
  --prefix demo-local- \
  --confirm demo-local-
```

重置仅匹配同一前缀且明确测试标记的用户、课程和 synthetic-demo 设备，并依赖外键级联
清理其绑定数据。脚本不会删除数据库卷、非测试对象或其他前缀。执行前仍应先备份。
