# ESP32 + DHT11 首轮实物施工方案

方案日期：2026-09-29。用途：硬件具备后的内部实验实施设计，尚未执行接线、烧录、部署或实物验收。用户已授权自主确定常见器材和内部技术目标；后续已授权并实施固件修复；本次交付状态见[修复报告](../../output/audits/dht11-firmware-fix-20260929/report.md)。部署、烧录及实物验收仍待执行。

## 1. 本轮目标与真实起点

完成一条可复查的实物链路：传感器采集 → 串口记录 → 平台入库 → 异常识别 → 恢复复查 → 断网缓存与重连 → 形成实验记录和下一版资料包。

当前交付基线为资料包 `2.0.11`、固件 `0.2.5`、设备协议 `1.0`。Git HEAD 为 `6eba82127910bbef4e63f7d890db5b74c37cf915`，存在大量未提交和新增文件；只复制这个提交不能得到当前交付内容。当前包哈希为 `629920faabf5897beffa5700e2daf8643c4feafe831b1d1a4808cf70233fc044`，实施前以实际锁定版本重新计算。

用户报告硬件条件已完善；具体实物身份、接线、功能仍待开工核对。旧内部指南 v3 中“尚未采购”是编写时状态，当前可用条件以[真实性看板](../project-truth-status.md)和本轮记录为准。该指南作为当前包已登记的来源保留；本方案负责执行顺序，当前包和固件已按本轮修复追加版本，既有验收规则保持不变。

| 阶段 | 产出 | 进入下一阶段的条件 |
| --- | --- | --- |
| S0 软件开工准备，对应 T0 | 修复后的固件、可核验的源码快照、构建和来源检查记录 | 下述采样调度缺陷修复并回归，锁定真实施工版本 |
| S1 实物核对与串口采集，对应 T1 | 照片、接线表、供电记录、连续原始串口日志 | 身份匹配、首次 priming 正确、后续真实采样可追溯 |
| S2 隔离平台接入，对应 T2 | 固定测试包、学生/设备/会话、真实入库记录 | 身份及包一致，心跳、温湿度/错误与回执逐项对应 |
| S3 先导测量与包修订 | 有依据的内部读数时效配置、新版固定包 | 参数有测量记录支持；独立验证样本与调参样本分开 |
| S4 DATA 异常与恢复，对应 T3 | 三轮独立 A→B→A 对照和新诊断 | 异常可识别、证据不足保留 unknown、恢复使用新证据 |
| S5 缓存与重连，对应 T4 | 原批次重投、暂停/恢复与重启保留记录 | 原身份不变、不重复入库、恢复重新 priming、间隔满足配置 |
| S6 收尾 | 一份实物报告、问题清单、资料包修订清单 | 每项注明通过/失败/未执行，附证据位置 |

本轮验收对象为内部功能与证据链。测量精度、课程效果、真实 AI Provider 和正式部署另列结果。仍使用 `is_test_data=true`，同时在记录中标明“真实板卡采集/受控故障”，不把测试标记误解为一定使用模拟数据。

## 2. 确定的器材与电脑安排

| 物品 | 本轮选定 | 用途 |
| --- | --- | --- |
| 开发板 | ESP32-DevKitC V4，ESP32-WROOM-32E 模组，1 块 | 与已设计固件和引脚资料对应 |
| 传感器 | Aosong DHT11 四针裸器件，1 个；可另备同型号正常件 | 首轮采集；备用件不预先认定为已验证正常 |
| 上拉电阻 | 4.7kΩ，1 个 | DATA 上拉至 3.3V |
| 连接 | 面包板、短杜邦线、匹配板卡接口的 USB 数据线 | 首轮采用短距离布线 |
| 基础测量 | 万用表 | 断电检查阻值/连通，上电核对 VDD-GND 电压 |
| 时序测量 | 逻辑分析仪可用于独立核对 DATA 触发间隔 | 没有波形时，只报告固件记录所能支持的时间结论 |
| 网络 | 可由维护者控制的 2.4GHz 实验 Wi-Fi，设备与平台互访 | 正常上传及独立断网试验 |

实物到手后按板卡、模组和器件标识核对。三针模块、ESP32-C3/S3 或其他板卡不能直接套用本方案；出现差异时只暂停相关接线和烧录，先做适配核对。

电脑采用两个角色，可以由同一台电脑承担：

- **烧录电脑 A**：macOS、Windows 或 Linux，负责源码、PlatformIO、USB 串口和日志。
- **平台电脑 B**：运行 Docker Compose、后端、前端和专用数据库。与 A 可不同；ESP32 使用 B 的局域网地址。

实施时先填“操作系统、项目目录、平台 IP、串口”四项现场参数。Wi-Fi、账号和设备令牌在本机私下输入，不要求通过聊天传递。两台电脑分别构建时都使用 S0 锁定的同一源码快照及包；不从旧提交另行拼装。

## 3. S0：先完成软件开工准备

### 3.1 调度缺陷与修复状态

修复前固件0.2.4的 `main.cpp` 中，`loop()` 先取 `now`，然后处理可能阻塞的 HTTP 重试；重试成功解除缓存阻塞后，用旧时间设置采样起点，下一轮可能过早再次采样。

设计阶段在自动清理的临时副本中，用实际生产 `main.cpp`、`pending_store.cpp` 和主机 I/O 替身复现；项目文件及硬件未改动：

| 输入 | 实际传感器函数调用时刻 | 判断 |
| --- | --- | --- |
| 重试成功回执无延迟 | 11000ms，仅一次 | 对照 |
| 重试成功回执延迟 4000ms | 15000ms、15005ms | 相邻 5ms，小于项目要求 3000ms |

所测 `main.cpp` SHA-256：`a3628945e095c0e53c8a8f06ed697b5bb45a11e3579b452bb5d19d2ef789bee7`。以上为主机调度反例，不是 GPIO 实测；实施时重新保存可执行反例和日志。

固件0.2.5已按以下要求完成实现与主机回归；软件门禁和构建的本次结果以修复报告为准，不能据此认定实物通过。

修复按[Bug 流程](../development-guidelines.md#fix-bugs)进行：先固化延迟回执反例，再以真实采样前的单调时间维护最小间隔；覆盖正常循环、重试成功、缓存解除和重新 priming。分别检查整板断电与仅复位ESP32而传感器仍供电：后一种情况下也必须满足请求间隔，因此启动首次请求的等待须覆盖3秒项目下限，不能只沿用1秒器件上电稳定等待。修复后固件、来源指纹、资料包版本、包清单及当前文档一起更新，不能只改一个哈希。

另有 HTTPS 文案/实现差异：修复前允许本地 HTTP 的开关为 1 时，HTTPS 空 CA 分支也可能调用 `setInsecure()`。首轮固定使用隔离 HTTP；0.2.5已改为HTTPS缺CA拒绝、HTTP开关只控制HTTP，并验证无效配置不消耗预算和已确认缓存仍可清理。

### 3.2 锁定可重现交付

1. 核对工作区差异，保存提交号及本次源文件指纹，包含新增源文件；保留无关改动。
2. 配置持久 PlatformIO Core 6.1.19 环境，核对锁定的 Espressif32 7.0.1、Arduino 框架和 ArduinoJson 7.4.2。不要依赖上一轮 `/private/tmp` 虚拟环境永久存在。
3. 先构建不含 `secrets.h` 的本地采集版。已有凭据文件先私有保存并核对，不覆盖或丢弃。
4. 运行固件主机反例、协议、包结构、已登记来源内容哈希和版本清单检查。此次涉及固件调度和传输修复，交付候选版本按[完整门禁](../evaluation.md#2-完整本机门禁)验证；使用与实物运行库分开的测试数据库。
5. 保存修复后的实际版本和产物；本方案不预先把计划的新版本写成已完成。

以下命令使用已安装的 `pio`；也可用其完整路径或同一虚拟环境下的 `python -m platformio`：

~~~text
pio --version
pio pkg list -d firmware/esp32_dht11
pio run -d firmware/esp32_dht11 -e esp32dev
pio run -d firmware/esp32_dht11 -e esp32dev -t buildfs
~~~

归档 `firmware.bin`、`littlefs.bin`、`partitions.bin` 及构建日志。核对实际分区表；当前 4MB 默认布局的文件系统偏移为 `0x290000`、大小 `0x160000`，这些值不能跨布局照抄。镜像应为 LittleFS，解包文件集合及内容与 `data/README.txt` 一致。

SHA-256 命令：macOS 用 `shasum -a 256 文件`；Linux 用 `sha256sum 文件`；PowerShell 用 `Get-FileHash 文件 -Algorithm SHA256`。当次生成的镜像哈希可以与历史构建不同，需结合实际内容核验。

## 4. S1：接线、首次烧录、串口采集

### 4.1 先核对板卡，再断电接线

先仅连接开发板 USB，插拔对照 `pio device list` 的变化，登记实际串口；Windows 常见为 COM，macOS/Linux 使用各自列出的设备路径。若没有串口，先查数据线、接口和实际 USB-UART 芯片驱动。

拔掉 USB 及其他电源。按奥松对应手册图示确定脚号，不凭照片左右方向猜：

| DHT11 脚号 | 接线 |
| --- | --- |
| 1 / VDD | ESP32 的 3V3 |
| 2 / DATA | ESP32 的 IO4/GPIO4，同时经 4.7kΩ 接 3V3 |
| 3 / NC | 不连接 |
| 4 / GND | ESP32 的 GND |

~~~text
3V3 ─────────────── DHT11 pin 1
 │
 └──[4.7kΩ]──┬───── DHT11 pin 2
GPIO4 ───────┘
GND ─────────────── DHT11 pin 4
                     pin 3 留空
~~~

GPIO4 是标注的功能名称，不是“排针第 4 根”。核对面包板分段电源轨与公共地，保存照片和实际阻值。首轮只由 USB 给开发板供电；上电后记录传感器 VDD-GND 实测电压，与所选手册允许范围核对。

### 4.2 烧录本地采集版

先关闭占用串口的监视器，替换真实端口：

~~~text
pio run -d firmware/esp32_dht11 -e esp32dev -t upload --upload-port <实际串口>
pio device monitor -d firmware/esp32_dht11 --port <实际串口> --baud 115200 --filter direct --filter log2file
~~~

当前 PlatformIO 的日志写入固件项目 `logs/device-monitor-*.log`，结束后复制到本次运行证据目录。记录烧录日志、启动版本、GPIO、test_data 和 bootId；需要复位捕获开机行时记录复位时刻。

采集预期：

1. 首个有效帧只作 priming，不作为温湿度发布。
2. 后续有效帧出现温湿度；读数对应前一次转换。
3. 完整保留失败和成功序列，不仅截成功的一行。
4. 检查实际触发间隔；当前配置为 3 秒，网络阻塞和暂停会拉长间隔，不应缩短到项目下限以下。

有效读数中的 `conversion_triggered_uptime_ms` 对应前一次成功触发，首次 priming 可从下一有效读数追溯。失败记录只有读取完成时间；完整物理触发间隔需逻辑分析仪补证，不能把读取完成时间或收包时间当作触发时刻。

首轮观察量采用现有硬件计划建议的至少 30 个完整有效温湿度采样，保存这段时间内所有失败。它是内部先导样本量，不是准确率或课程合格标准。不能稳定取得基线时先定位，再另开运行记录，失败材料保留。

### 4.3 首次初始化 LittleFS

仅对确认没有待保留数据的新设备，核对镜像、分区、端口后执行一次：

~~~text
pio run -d firmware/esp32_dht11 -e esp32dev -t uploadfs --upload-port <实际串口>
~~~

`uploadfs` 会替换文件系统内容。普通固件更新不重复执行；挂载失败时保存错误现场。首次命令成功后，仍需在配置上传身份的固件上验证挂载、保存和读取。项目使用 `LittleFS.begin(false)`，不自动格式化。

## 5. S2：建立独立平台和真实硬件身份

### 5.1 固定隔离入口

平台电脑使用现有 `compose.yaml`，实施时创建专用 `.env.hardware-lab` 与 `compose.hardware-lab.override.yaml`。本节为待落地配置模板，本轮未创建或启动该环境。

采用 Compose ≥2.24.4，以 `!override` 真正替换端口，避免普通列表合并保留旧端口。覆盖文件：

~~~yaml
services:
  backend:
    ports: !override
      - "18080:8000"
    environment:
      APP_ENV: test
      AI_ENABLED: "false"
      AI_LOCAL_ENABLED: "false"
      AI_CLOUD_ENABLED: "false"
      DIAGNOSIS_CHECKPOINT_BACKEND: postgres
      DIAGNOSIS_CHECKPOINT_SETUP: "false"
  frontend:
    ports: !override
      - "18081:80"
~~~

专用环境文件固定 `POSTGRES_DB=xj_dht11_hw`、`POSTGRES_USER=xj_dht11_lab`，并设置本机生成的 `POSTGRES_PASSWORD`；`DATABASE_URL` 使用同一项目内的 `postgres:5432/xj_dht11_hw`，SQLAlchemy 格式为 `postgresql+psycopg://...`；`DIAGNOSIS_CHECKPOINT_DSN` 用同库同用户的 `postgresql://...`。URI 中密码特殊字符须正确编码。不复制现有业务 DSN；同名实验实例已存在时先核对归属和记录，不能重置卷。

`--env-file` 不会压过宿主终端已导出的同名变量。先在本次实验专用终端清除以下变量，再使用专用文件；仅影响该终端，不修改系统或其他项目设置。Bash/zsh/Git Bash：

~~~sh
unset POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD DATABASE_URL DIAGNOSIS_CHECKPOINT_DSN
~~~

PowerShell：

~~~powershell
'POSTGRES_DB','POSTGRES_USER','POSTGRES_PASSWORD','DATABASE_URL','DIAGNOSIS_CHECKPOINT_DSN' | ForEach-Object { Remove-Item "Env:$_" -ErrorAction SilentlyContinue }
~~~

以下 `lab` 是固定选择器的简写，在 Bash/zsh/Git Bash 定义：

~~~sh
lab() {
  docker compose -p xinjian-hardware-lab --env-file .env.hardware-lab \
    -f compose.yaml -f compose.hardware-lab.override.yaml "$@"
}
~~~

PowerShell 对应定义：

~~~powershell
function lab {
  docker compose -p xinjian-hardware-lab --env-file .env.hardware-lab -f compose.yaml -f compose.hardware-lab.override.yaml @args
}
~~~

在仓库根目录依次执行：

~~~text
lab config -q
lab build backend frontend
~~~

启动数据库和迁移前，检查最终容器中的两个连接地址，不打印密码。先进入不启动依赖的临时容器：

~~~text
lab run --rm --no-deps backend sh
~~~

在容器 shell 内执行，只有断言通过才继续；`exit` 返回宿主终端：

~~~sh
python -c 'import os; from urllib.parse import urlsplit; targets=[urlsplit(os.environ[k]) for k in ("DATABASE_URL","DIAGNOSIS_CHECKPOINT_DSN")]; assert all(t.hostname=="postgres" and t.port==5432 and t.path=="/xj_dht11_hw" and t.username=="xj_dht11_lab" for t in targets), "isolated database target mismatch"; print("isolated database targets verified")'
exit
~~~

该检查失败时核对专用环境文件和最终配置，不进行迁移。回到宿主后执行 `lab up -d postgres`、`lab ps`，确认数据库 healthy 再继续：

~~~text
lab run --rm backend alembic upgrade head
lab run --rm backend python -m app.cli.setup_diagnosis_checkpoints
lab up -d backend frontend
lab ps
lab exec backend alembic current
lab exec backend alembic heads
lab exec backend alembic check
~~~

后端启动也会执行迁移，所以所有命令必须保留隔离选择器。检查 `http://<平台IP>:18080/health/ready` 和 `http://<平台IP>:18081/login`。前端同源代理后端，避免 Vite 开发模式连到已有 8000 端口。若端口占用，修改覆盖文件并统一更新本次地址表，不关闭无关服务。

设备 URL 使用 `http://<平台IP>:18081/api/v1/device/ingest`。即使 USB 接在平台电脑上，ESP32 也不能填写 `localhost`。实验网须允许设备与该端口互访；只调整明确的实验访问规则，不改代理设置。检查设备时间同步；当前固件使用 NTP，未同步的 `server_fallback` 记录可以入库，但不满足自动确认恢复的时间证据要求。

### 5.2 导入和内部测试发布

使用[内部测试准备说明](internal-lab-preparation.md)的已有入口，顺序不能省略：

1. `lab exec backend python -m app.cli.create_test_user --username lab-operator --display-name 内部测试管理员 --role admin --test-account`；密码隐藏输入。
2. 在测试后端 `/docs` 调用 `POST /api/v1/auth/session`，用管理员账号取得 Bearer token。
3. 从 S0 已审阅源码生成包导入 JSON（`package_documents(bundle)`，`is_test_data=true`）；构建容器的包与这份源码必须一致。跨电脑可统一执行下面的容器生成方法。
4. 管理员依次 validate、import，核对内容版本、服务端版本 UUID 和包 hash。
5. 导入初始状态为 draft；依现有版本 status 接口依次提交 pending → approved → published，保存真实的软件自审依据及返回记录。这里的发布只是隔离内部测试可用状态，不清除硬件/教师/课程待确认项。

同版本已存在时读取并比对，不能覆盖；版本号、版本 UUID 和包 hash 分别保存。不能借用 `seed_demo` 的旧合成任务作为本次实物履历。

宿主执行 `lab exec backend sh` 后，在容器内生成无账号凭据的导入文件：

~~~sh
python - <<'PY'
import json
from pathlib import Path
from app.experiment_packages.loader import load_experiment_package, package_documents
bundle, _ = load_experiment_package(Path('/app/experiment_packages/dht11_temperature_humidity'))
Path('/tmp/internal-lab-package-import.json').write_text(json.dumps({
    'documents': package_documents(bundle), 'is_test_data': True,
}, ensure_ascii=False), encoding='utf-8')
PY
exit
~~~

返回宿主后 `lab cp backend:/tmp/internal-lab-package-import.json <本次记录目录>/package-import.json`，将该 JSON 用于 validate/import。不要在容器中照抄宿主的 `backend/experiment_packages` 相对路径。每次记录用新路径，不覆盖上一轮文件。

### 5.3 创建实物任务，然后由学生开会话

先执行 `lab exec backend sh` 进入容器 TTY，再在 Linux 容器 shell 中执行下面命令，避免不同宿主终端的引号处理差异。它隐藏输入管理员 token，再进入继承 token 的临时 shell；不把 token 写进命令、日志或 Git：

~~~text
python -c 'import getpass, os; os.environ["INTERNAL_LAB_ADMIN_TOKEN"] = getpass.getpass("Admin bearer token: "); os.execl("/bin/sh", "sh")'
~~~

在该 shell 内运行：

~~~sh
python -m app.cli.prepare_internal_experiment plan \
  --test-database --dsn-env DATABASE_URL \
  --actor-token-env INTERNAL_LAB_ADMIN_TOKEN \
  --prefix lab-dht11-hardware-01 --device-kind hardware \
  --package-version-id <服务端版本UUID> --package-hash <已核对的包hash>
~~~

预览正确后，将 `plan` 改为 `apply`；工具交互输入学生、教师测试角色密码和设备令牌。随后改为 `status` 核对实际对象。`--dsn-env DATABASE_URL` 是明确选择本容器专用库，工具不会隐式回退；同前缀换版本或关系冲突应拒绝，不能强行接管。完成后退出 shell。

学生在 `http://<平台IP>:18081/login` 登录 `lab-dht11-hardware-01-student`，验证账号、选择任务和设备、开始实验，保存返回的活动会话 UUID 和固定包版本。初始化 CLI 本身不创建会话。

**固件使用 `device_key`，不是数据库设备行 UUID。** 在被忽略的 `firmware/esp32_dht11/include/secrets.h` 本机填写：

~~~text
XJ_WIFI_SSID / XJ_WIFI_PASSWORD：实验 Wi-Fi
XJ_API_BASE_URL：http://<平台IP>:18081/api/v1/device/ingest
XJ_DEVICE_ID：初始化回执中的 device_key
XJ_DEVICE_TOKEN：刚设置并私有保存的设备令牌
XJ_EXPERIMENT_SESSION_ID：学生开始实验得到的会话 UUID
XJ_ALLOW_INSECURE_HTTP：1，仅限本次隔离 HTTP
~~~

该文件实际 C 语法按 `firmware/esp32_dht11/include/secrets.example.h` 填写。保持 `XJ_IS_TEST_DATA=1`，重新 build/upload 程序，另记配置后固件 hash，不重刷 LittleFS。含凭据的源码和二进制私有保存，公开报告只保留版本和指纹。

### 5.4 接入通过条件

同一个 requestId 同时能定位串口批次、有效服务端回执和入库记录；核对温度、湿度、心跳/错误、设备、会话、包、bootId、sequenceNo 及时间来源。实际数据库中的日志/读数 ID 与诊断生成的 Evidence UUID 分别留存，不能编造 UUID。

只有串口 JSON、网页可打开或设备在线，都不足以证明这条链路完成。固件成功行只包含请求 ID 和记录数，完整回执及幂等需要后端记录支持。

## 6. S3：先测量，再补全自动恢复所需参数

当前 `2.0.11` 温度、湿度的 `maximum_age_seconds=null`；代码因此把 `data_fresh/data_periodic` 判为 unknown，无法满足正常状态和自动确认恢复。这是当前明确缺口，不以“再多采几条”或修改页面颜色解决。

安排两批数据：

1. **先导数据**：正常条件下三次独立启动，每次至少 30 个完整有效采样，保留全部失败、实际周期、转换到接收延迟、时间质量和网络条件。
2. **独立验收数据**：参数冻结后新开任务/会话，再采三组；不得用选择阈值的同一批记录宣称验收通过。

内部时效阈值采用可审查的制定方法：以测得的有效读数年龄和相邻观测间隔最大值为依据，加一个项目周期的余量，并至少覆盖三个配置周期。读数年龄按每次实际诊断时刻减当时最新观测的设备时间计算，不能用事后整理时刻计算；转换到接收延迟单列。相邻间隔按同一连续运行段计算，不把两次启动间的人工停机拼成正常周期，原始停机记录仍保留。设 P 为 3 秒，候选 L 为 `max(3P, ceil(max(观测年龄最大值, 相邻间隔最大值) + P))`，单位秒。这是本项目首轮先导方法，不是厂商性能指标；无数据时不填具体 L，异常长延迟先定位。若 L 已接近或超过当前 90 秒在线监测时限，应重新审查网络/任务目标，不直接放宽到能通过。

测量结果、方法和适用环境进入来源记录后，再修订资料包的新鲜度配置，追加包版本并校验。先通过离线/软件的正常、缺测、旧数据、失败与恢复反例及来源审阅，再在隔离库发布新版本，用新前缀、新任务和新会话开展独立实物验收。旧固定会话和诊断不回填。

切换时按“处理完原会话未决批次 → 停止原设备上传 → 正常结束原 active 会话并保存回执 → 新任务/新会话 → 重编译身份配置”执行，不能用 `uploadfs` 清队列。结束可用学生页面或 `POST /api/v1/student/experiment-sessions/{id}/end`，请求包含新 `request_id`、当前 `expected_version`（version_no）及实际 `reason=completed/cancelled`。只有经实际验证的对应事实才更新状态，不能把所有 `pending_hardware` 一次性清空。

## 7. S4：正常—DATA 断开—恢复

沿用现有 A→B→A 硬件计划，做三次独立重复。每次独立保存原始数据：

1. **A 基线**：接线正确，确认真实新读数入库，记录正常诊断或其具体限制。
2. **B 单因素**：断电，只断开传感器 DATA 信号连接，供电和其他线保持原配置；记录断开位置、照片、时刻后再上电。不得以短路或过压制造异常。
3. 保存完整失败序列，确认窗口累计至少 5 次 `sensor.read_failed` 时命中当前规则；“累计”不能写成“连续”。断线真值来自人工操作记录，系统只有读取失败时仍应保留有限候选/unknown。
4. **A 恢复**：断电恢复 DATA，重新上电；首个有效帧 priming 后继续取得新读数及回执。
5. 用新请求基于最新诊断重新检查。观察物理读取恢复、平台入库恢复、系统确认恢复三个结果；任一未满足都如实记录。

本次将诊断回看窗口明确设为 **90 秒内部调试窗口**，整个对照组保持一致。当前接口默认是 3600 秒，网页按钮不会自动改成 90 秒；因此本组用测试后端 `/docs` 的学生身份调用：

~~~text
POST /api/v1/diagnosis-workflows/devices/<device_key>
Authorization: Bearer <学生令牌>
X-Device-ID: <device_key>
X-Experiment-Session-ID: <会话UUID>
~~~

首次请求体：

~~~json
{"request_id":"<新操作UUID>","lookback_seconds":90}
~~~

恢复复查请求体：

~~~json
{"request_id":"<新操作UUID>","baseline_id":"<最新诊断结果UUID>","lookback_seconds":90}
~~~

同一次请求遇到超时/503，保留原 request_id 和请求体查询/恢复，不另造操作；409 先读最新状态核对 baseline。UI 用于查看结果，若另用网页默认窗口创建诊断，应另记窗口并重新取得最新 baseline。

旧失败仍在回看窗口内时继续报异常可能是正确行为。恢复后持续采样，让旧失败退出固定窗口，再核对正常所需的间隔、新鲜度和有效字段；保存实际输入时间窗，不能删旧数据凑恢复。自动恢复还要求同作用域、晚于旧诊断的新证据和 `device_reported` 时间质量。NTP 未同步时保留 unknown 并处理时间来源。

## 8. S5：断网缓存、重连和重启保留

当前缓存只能容纳一批。缓存被占用就暂停新采样；Wi-Fi 未连接不消耗 HTTP 次数，Wi-Fi 在线但服务器失败会消耗每批最多 3 次的持久预算。次数耗尽后暂停并保留数据，网络恢复或重启都不会重置。没有已实现的通用人工“清队列再试”入口。

### 8.1 先做 Wi-Fi 失联和恢复

1. 先保证正常基线、服务端可用和无未决批次；记录会话及最后已确认请求。
2. 仅控制专用实验 Wi-Fi 使设备失联，平台服务继续运行；不动日常代理或共享网络。
3. 观察下一批生成、缓存占用和采样暂停。记录真实批次类型，它可能含读数，也可能是 priming 心跳；不能把心跳批次写成温湿度补传。
4. 恢复实验 Wi-Fi，核对是否在该板卡/框架上自动重连。若不重连，记录失败，不能以另一次重启结果替代这次自动重连结论。
5. 原 requestId/session/bootId/sequenceNo 应保持，后端记录不重复；解除缓存后先重新 priming，再恢复正常间隔采样。

当前固件不保证打印独立的“缓存已占用/挂载成功”提示；用批次停止增长、串口 alive 持续、后续原请求确认及独立闪存取证交叉核对，不能把没有报错单独视为已落盘。

此测试不使用“长时间关服务器再开”代替 Wi-Fi 失联。若已耗尽发送预算，停止本轮、保留现场与请求记录，按故障流程处理，不格式化文件系统。

### 8.2 再做独立的重启保留试验

当前固件无专用 pending 文件导出命令。需要验证持久文件内容时，实施前先在空白实验设备验证以下只读取证方法：

1. 记录实际 `partitions.bin` 解析出的文件系统偏移和大小。
2. 关闭串口监视器，利用 PlatformIO 已解析版本的 esptool 在下载模式读取该分区；读取会中断/重启运行，因此另记为独立试验，不能混入“不重启自动恢复”组。
3. 确认转储字节数等于分区大小，原始转储先计算哈希并保存，复制一份后用同版本 mklittlefs 解包到新目录。`pending.json` 是封装记录：先核对 sessionId、requestId、recordCount、attempts、acknowledged，再把 `body` 字符串解析为批次 JSON，核对两层 requestId 相同、recordCount 等于 records 数量，以及原 bootId、sequenceNo 和实际记录。保留原始文件，不重新序列化覆盖；解包后重新核对原始转储未变。

命令模板（占位路径、偏移、大小必须由本次环境确定）：

~~~text
<PIO环境Python> <tool-esptoolpy/esptool.py> --chip esp32 --port <串口> --after no_reset read_flash <实际偏移> <实际大小> <新文件系统转储.bin>
<tool-mklittlefs/mklittlefs> -b 4096 -p 256 -s <实际大小十进制> -u <新的解包目录> <转储副本.bin>
~~~

块/页参数对应当前项目构建配置；实施前核对构建器实际参数。`--after no_reset` 让读取完成后保持下载模式，由操作者记录后明确恢复运行，避免默认自动复位导致状态变化。操作限定只读 `read_flash`，不用 erase/write 命令替代。私有保管请求载荷和设备身份。

正式试验在确认一批已落盘后保持网络断开，断电重启；比较 `retained request=... attempts=...`、文件证据、恢复网络后的原请求入库及新 bootId 下的新采样。回执丢失幂等、短写、挂载损坏、确认落盘窗口等属于下一轮有明确注入工具的专项测试，分别标未执行，不能由本轮结果一并判通过。

## 9. 记录、故障处理和验收归档

每次运行使用独立 run_id，结构沿用[硬件计划](../hardware-validation-plan.md#3-记录格式与证据层级)：

~~~text
hardware-validation/dht11_temperature_humidity/<run_id>/
  run-record.md
  identity-and-wiring/
  build/
  serial/
  platform/
  flash-snapshots/
  checksums.sha256
~~~

可以将此结构放在私有实验盘或被忽略的本地审计目录；原始凭据、含凭据固件、数据库附件不加入公开 Git。记录至少包含：操作者、时间、硬件身份、接线版本、源码/包/固件身份、串口与平台地址、唯一改变项、采集来源、诊断窗口、requestId、会话、真实记录/Evidence ID、结果和未解释现象。未执行填“未执行/null”，不用 0 或伪造标识补空。

| 现象 | 先核对 | 本轮处理 |
| --- | --- | --- |
| 没串口/无法烧录 | USB 数据线、实际端口、串口占用、板卡下载模式 | 保留报错，逐项排除 |
| 串口持续读取失败 | 器件身份、3V3/GND、GPIO4、上拉、错误阶段 | 断电核对并复测；不直接判传感器损坏 |
| HTTP 401/403 | device_key、设备 token、活动会话及授权 | 核对原身份；不改成演示接口绕过 |
| HTTP 409 | requestId/序号、会话、包、baseline 的具体冲突 | 读取当前状态，保留冻结请求 |
| 入库了却仍 unknown | 读数时效配置、时间质量、旧失败窗口、实际间隔 | 按 S3/S4 分别处理 |
| storage unavailable/预算耗尽 | 原始串口、分区、pending 及尝试记录 | 保存现场，不自动格式化或重置预算 |

先完成一轮完整功能链，再做重复对照；每阶段出现失败先停该阶段并按 Bug 流程定位，已完成证据保留。单人可承担实施、记录和内部软件自审，按实际操作者署名，不填写虚构教师。

最终报告逐项列 T0—T4 的通过/失败/未执行与证据位置。之后把实物身份、可复现步骤、错误表现、恢复材料追加为新来源，按既有七阶段资料包流程修订；不能用一次接线成功把全部故障原因或课堂效果标为已验证。

## 10. 下一轮实施顺序与文档检查

第一步执行 S0 的调度修复与相称回归，同时建立受控源码/产物清单；随后 S1 本地采集可以先完成，不必等平台搭建。平台 S2 可与实物准备独立推进。S3 的真实测量和新包完成后，再开展 S4/S5 验收。

施工所需账号、IP、串口和仪表值在现场登记，不作为本方案目前必须由用户补齐的输入。没有实际执行记录时，阶段状态保持待执行。

每次收尾固定核对：先审阅变更，再更新受影响的来源指纹、包版本和包清单，最后运行检查。只写本方案及状态导航不改变已登记包内容，因此本轮不升级包、不改来源哈希；已登记指南/固件变更则必须走版本链。检查失败不能靠无审阅地重算哈希消除。

## 11. 核对依据与本轮验证范围

- 项目实现：[固件](../../firmware/esp32_dht11/src/main.cpp)、[配置](../../firmware/esp32_dht11/include/firmware_config.h)、[运行健康判断](../../backend/app/diagnosis/runtime_health.py)、[恢复证据](../../backend/app/services/recovery_evidence.py)、[设备协议](../device-protocol.md)、[内部初始化](internal-lab-preparation.md)。
- 官方接线依据：[ESP32-DevKitC V4 指南](https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32/esp32-devkitc/user_guide.html)、[奥松 DHT11 V1.3 手册](https://www.aosong.com/userfiles/files/media/DHT11-V1_3%E8%AF%B4%E6%98%8E%E4%B9%A6%EF%BC%88%E8%AF%A6%E7%BB%86%E7%89%88%EF%BC%89.pdf)。本次乐鑫页面可读取，奥松在线请求超时；DHT11 采用项目已留存且有哈希的 V1.3 原件，不替换来源。
- 工具依据：[PlatformIO Espressif32](https://docs.platformio.org/en/latest/platforms/espressif32.html)、[Compose 合并与覆盖规则](https://docs.docker.com/reference/compose-file/merge/)；本轮官方页面复核用于操作设计，不改项目锁定依赖。
- 本轮只完成源码/文档核对、隔离主机反例、方案和文档一致性检查；未运行完整软件门禁、未部署、未烧录、未读取实物。历史软件通过记录仍按其原版本和日期保留。

本轮文档检查：11处本地链接/锚点通过，版本清单及20项可用来源身份核验通过；硬件、教师、课程3项来源仍待取得。用临时非敏感环境值运行 `docker compose config`，确认上述覆盖模板只暴露18080/18081、数据卷按独立项目命名、AI关闭、测试环境及数据库/Checkpoint目标一致；未启动容器，临时文件已清理。同版本mklittlefs对临时合成pending文件的建镜像、解包和双层JSON核对通过，不能替代实物取证。
