# 内部测试实验准备与合成演练

日期：2026-09-29。对象：维护者在自己管理的隔离测试环境准备一次实验。入口为`app.cli.prepare_internal_experiment`；首个配置使用DHT11。硬件、学生与教师真实验收仍单独记录。

## 1. 环境与管理员

使用已迁移到当前Head的专用PostgreSQL和项目Python环境。不能选正在使用的业务库；CLI必须同时提供`APP_ENV=test`、`--test-database`与`--dsn-env`，不自动回退到DATABASE_URL。这几项表达操作者明确选择，不能自动证明某个连接串一定不是业务库，仍须核对目标。

在本地环境变量`INTERNAL_LAB_DSN`中设置专用库连接串，`INTERNAL_LAB_API`设为连接该库的测试后端地址。启动和迁移方法沿用[部署说明](../deployment.md)。仅准备测试环境时，可以从backend目录执行：

```bash
APP_ENV=test DATABASE_URL="$INTERNAL_LAB_DSN" python -m alembic upgrade head
APP_ENV=test DATABASE_URL="$INTERNAL_LAB_DSN" python -m app.cli.create_test_user \
  --username lab-operator --display-name '内部测试管理员' --role admin --test-account
APP_ENV=test DATABASE_URL="$INTERNAL_LAB_DSN" AI_ENABLED=false \
  python -m uvicorn app.main:app --host 127.0.0.1 --port 18080
```

以上前提是所选端口空闲、连接串已核对、依赖齐全；不能用示例地址冒充已经启动成功。管理员密码由现有CLI交互输入，账号已存在则使用已有凭据，不覆盖。另一个终端继续后续步骤，设置`INTERNAL_LAB_API=http://127.0.0.1:18080`仅当确实使用上述地址。

通过`POST /api/v1/auth/session`以该测试管理员登录。可在测试后端`/docs`调用，取得access_token后在自己的终端用隐藏输入保存：

```bash
read -rs INTERNAL_LAB_ADMIN_TOKEN
export INTERNAL_LAB_ADMIN_TOKEN
```

不把令牌粘贴到Git、报告或共享日志。工具使用令牌解析实际登录身份，并在等锁后复核有效期、撤销状态和管理权限；不能只提供某个管理员的用户名冒充登录。

## 2. 明确导入及测试发布

先在仓库根目录生成严格请求体。下面的JSON只有包内容与测试标记，没有账号凭据：

```bash
PYTHONPATH=backend python - <<'PY'
import json
from pathlib import Path
from app.experiment_packages.loader import load_experiment_package, package_documents
bundle, _ = load_experiment_package(Path('backend/experiment_packages/dht11_temperature_humidity'))
Path('/tmp/internal-lab-package-import.json').write_text(json.dumps({
    'documents': package_documents(bundle), 'is_test_data': True,
}, ensure_ascii=False))
PY
```

在测试后端`/docs`以该管理员Bearer身份执行：

1. `POST /api/v1/experiments/packages/validate`，请求体为上面JSON；核对valid与package_hash。
2. `POST /api/v1/experiments/packages/import`，使用相同请求体；保存服务端返回的版本UUID、内容版本与hash。同版本已存在时读取并核对已有快照，不能覆盖。
3. 分别调用`POST /api/v1/experiments/package-versions/{版本UUID}/status`，请求体依次为`{"status":"pending"}`、`{"status":"approved"}`、`{"status":"published"}`。每步核对结果；已位于后续状态则按当前状态核对，不盲目重复迁移。

这些动作仅用于本次隔离测试库，管理员的实际软件自审与操作会保留审计。测试版本仍含pending硬件/课程/教师来源；数据库published状态不等于真实教师审核、硬件合格或正式知识发布。初始化工具不会自动执行上述流程。

将返回的版本UUID、hash保存为`INTERNAL_LAB_VERSION_ID`、`INTERNAL_LAB_PACKAGE_HASH`，不要把内容版本号2.x.x当UUID。只接受当前、未撤回的已发布测试版本；包被替代、撤回或hash不匹配时先核对，不自动追随最新版本。

## 3. 预览、执行、恢复

从仓库根目录运行，使用项目Python环境：

```bash
APP_ENV=test PYTHONPATH=backend python -m app.cli.prepare_internal_experiment plan \
  --test-database --dsn-env INTERNAL_LAB_DSN --actor-token-env INTERNAL_LAB_ADMIN_TOKEN \
  --prefix lab-dht11-first --device-kind synthetic \
  --package-version-id "$INTERNAL_LAB_VERSION_ID" --package-hash "$INTERNAL_LAB_PACKAGE_HASH"
```

`state=absent`表示命名空间未被使用，可查看将创建的名称；`state=ready`表示已有可复用且关系完整的对象。plan/status只读，不生成凭据或会话。

将同一命令中的`plan`改为`apply`执行。首次会隐藏输入并确认学生密码、教师密码、设备令牌（均12—512字符）。自动化时可用`--student-password-env`、`--teacher-password-env`和`--device-token-env`指定受控环境变量名，不能把明文密码写入命令参数。

成功结果包含课程、班级、学生、教师、任务、设备ID以及device_key、固定包身份，不包含密码或令牌。可重定向结果为本地操作记录；写盘失败或终端断开后，使用同参数`status`或重复`apply`恢复。成功提交过的同一配置不再要求密码，不重置凭据，不重复创建对象。

对象和审计在一个事务提交；前缀锁与包状态锁后重新核验身份。同前缀换包、正式对象混入、无回执的残缺对象或绑定改变会拒绝，不自动“修复”历史。需要换版本时使用新前缀准备新任务，已有会话继续保留原版本。

这里创建的账号名为`lab-dht11-first-student`和`lab-dht11-first-teacher`。教师账号只是软件测试角色，不能填写成某位教师本人。默认synthetic设备只接合成输入；到货后使用不同前缀与`--device-kind hardware`准备实物内部测试身份，不能将先前合成数据当作板卡履历。

## 4. 由学生开始会话

打开连接同一测试后端的学生页面，输入刚创建的学生账号和密码，点击“验证学生账号”，选择任务、设备后“开始所选实验”。初始化工具不创建活动会话。

API对应流程：`GET /api/v1/student/assignments`确认可用对象，`POST /api/v1/student/experiment-sessions`提交request_id（UUID）、device_id（device_key）和experiment_assignment_id（任务UUID）。保存响应中的会话ID及experiment_version_id，核对固定包。

学生读取与操作使用Bearer账号令牌，并传`X-Device-ID`与`X-Experiment-Session-ID`；不要把设备令牌当学生密码。设备上传另外使用`X-Device-ID`、`X-Device-Token`和`X-Experiment-Session-ID`。具体字段以[设备协议](../device-protocol.md)和[API契约](../api-design.md)为准。

## 5. 演练与验收记录

无硬件时先做明确的合成演练，不连接设备或执行烧录。测试入口：

```bash
PYTHONPATH=backend python -m pytest backend/tests/test_internal_experiment_cli.py \
  backend/tests/test_internal_experiment_preparation.py \
  backend/tests/test_internal_experiment_preparation_postgres.py \
  backend/tests/test_internal_experiment_drill.py
```

真实PostgreSQL用例需要`XINJIAN_EVAL_POSTGRES_DSN`，使用专用库中的随机schema并在结束后清理；缺DSN会跳过部分测试，不能将跳过写成完成。设置`XINJIAN_INTERNAL_DRILL_REPORT`可将成功演练的脱敏过程写到指定JSON。完整检查和浏览器入口见[评测指南](../evaluation.md)。

演练覆盖：空数据、有效字段、累计读取失败、重复批次、错误设备/会话、资料快照、反馈、旧数据/缺测、新数据重新检查和结束会话。有效数值不会自动校准未知的时效参数；无异常不等于已确认正常，累计失败不等于唯一根因。AI关闭时审计仍可记录skipped，核对attempt_count为0，不能把审计行数当模型调用次数。

本轮实际软件结果见[验收记录](../../output/audits/dht11-readiness-20260929/report.md)。这份命令说明不是硬件/课堂通过证据。完成后清理自己的临时导入文件和凭据环境变量；一次性测试库可销毁，持续内部测试环境保留原记录与版本。
