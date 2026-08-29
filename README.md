# 华住会 自动签到（设备端自动化）

在 Linux 服务器上定时完成华住会 App 每日签到。通过 `adb` 驱动一个**已登录华住会**的安卓设备/模拟器，冷启动 App → 进入签到页 → 点击签到 → 截图存档验证。

## 为什么是"设备端自动化"而不是纯 HTTP 脚本

华住会 App 做了较强加固，纯 Python 复刻请求这条路基本走不通：

- 核心接口 `appgw.huazhu.com` 做了**证书 pinning**，普通抓包（mitmproxy/Fiddler）无法解密；
- App 有**主动反 Frida**（注入即崩溃），也有 tongdun 风控 / 设备指纹；
- 签到请求的签名在**原生层**，很可能**绑定设备指纹**，纯脚本即便抓到一次也难以稳定复现，且 App 每次更新易失效。

设备端自动化让真 App 自己发请求，**免疫 pinning / 反调试 / 签名变更**，登录态由 App 自己维持（华住会通常很久不掉登录），是这类加固 App 最稳的自动化方式。

---

## 一、前置条件

1. 一个安卓环境（真机 / redroid 容器 / 云手机），已安装华住会并**登录好账号**。
2. 该安卓可通过 `adb` 连接（USB 或网络）。
3. 运行方（你的电脑或服务器）已安装 `adb`（源码方式），或用 Docker（镜像内已带 adb）。

### 安卓目标怎么选（可靠性从高到低）

| 方案 | 说明 | 备注 |
|------|------|------|
| **A. 真机（推荐）** | 一台常开的安卓手机，`adb tcpip 5555` 后通过局域网连接 | 兼容性最好，不触发反模拟器 |
| **B. redroid 容器** | 在 Linux 服务器上用 Docker 跑安卓（`redroid/redroid`） | 纯服务器方案；**可能被反模拟器/风控拦**，需实测 |
| **C. 云手机** | 各厂商云手机，开放 adb | 稳定但通常收费 |

> 真机联网 adb 一次性设置：手机连 USB 执行 `adb tcpip 5555`，记下手机 IP（如 `192.168.1.50`），之后服务器 `adb connect 192.168.1.50:5555` 即可。手机重启后端口可能需重设。

### ⚠️ 首次登录怎么做（服务器只有命令行）

**登录是一次性的**：脚本只点签到，不负责登录。华住会用「手机号 + 短信验证码（可能带滑块验证）」登录，需要人工操作一次。之后 App 长期保持登录（通常数月不掉），cron 全自动。

关键点：**必须在"最终跑签到的那台安卓"上直接登录**，因为华住有设备指纹风控，跨设备迁移登录态（拷 `/data/data`）大概率失效或触发风控。三种方式：

1. **真机登录（推荐，最省心）**：拿真手机像平时一样打开华住会登录好，再 `adb tcpip 5555` 接入服务器局域网。服务器只发点击，无需在服务器上登录。手机放家里常开即可。

2. **redroid + scrcpy 远程登录**：服务器无屏幕，但可从你自己的电脑把 redroid 画面投出来操作一次：
   ```bash
   # 在你的电脑上(需装 scrcpy 与 adb):
   adb connect <服务器IP>:5555          # 连到服务器上的 redroid
   adb install huazhu.apk               # 装华住会(自备 apk)
   scrcpy                               # 弹出 redroid 画面, 用鼠标操作登录
   #  → 输手机号 → 你本人手机收短信验证码 → 过滑块 → 登录成功后关掉 scrcpy
   ```
   之后服务器上的 cron 全自动，无需再看屏幕。

3. **本机先跑通再迁移**：先用你现在这台电脑 + 手机（已验证可用）长期跑；等熟悉了再迁到服务器。

> 掉登录时（少见）：重复上面的一次性登录即可。建议把「签到失败连续 N 次」做个告警（看 `artifacts/` 截图或退出码）。

---

## 二、坐标校准（首次必做）

签到靠**坐标点击**（该页是 React Native 无限动画页，`uiautomator` 无法 dump，故用坐标）。不同分辨率坐标不同，先校准一次：

```bash
python checkin.py --calibrate
```

会在 `artifacts/` 生成 `cal_home.png`（首页）和 `cal_signin.png`（签到页）。用看图工具读出：

- **`TILE_XY`** = `cal_home.png` 里"签到 · 福利领取"磁贴的中心像素坐标；
- **`BUTTON_XY`** = `cal_signin.png` 里红色"签到"大按钮的中心像素坐标。

把这两个值填入 `config.env` 或环境变量。填了绝对坐标最准；不填则回退到按比例（`TILE_FRAC`/`BUTTON_FRAC`）换算，跨分辨率但不一定精准。

> 成功判定：脚本采样"签到"按钮区域颜色——饱和红=未签、浅粉=已签，据此判断，不依赖 OCR。

---

## 三、源码方式运行

```bash
# 1. 准备配置
cp config.env.example config.env
# 编辑 config.env: 填 ADB_HOST / TILE_XY / BUTTON_XY 等

# 2. 执行一次（测试）
python checkin.py --once      # 退出码 0=成功/已签, 1=不确定, 2=页面异常

# 3. 常驻定时（每天 RUN_AT 执行）
python checkin.py --loop
```

配合 systemd / nohup / screen 常驻即可。仅用 Python 标准库，无需 `pip install`（但系统要有 `adb`）。

---

## 四、Docker 方式运行（推荐用于服务器）

镜像内置 adb，容器负责"定时 + 连接设备 + 点签到"。安卓设备本身在容器外（真机/redroid/云手机）。

```bash
# 1. 编辑 docker-compose.yml: 改 ADB_HOST 为你的设备地址; 填 TILE_XY/BUTTON_XY
# 2. 构建并后台运行
docker compose up -d --build

# 3. 看日志
docker compose logs -f

# 4. 手动触发一次（可选）
docker compose run --rm -e MODE=--once huazhu-checkin
```

- `network_mode: host`：便于容器连接局域网内手机或同机 redroid 的 adb 端口。
- `./artifacts` 已挂载到宿主，签到截图 `after_signin.png` 会落到这里，可随时核对。
- 时区 `TZ=Asia/Shanghai`，`RUN_AT` 用本地时间。

### 想全部在一台服务器（含安卓）？加 redroid

在同一台 Linux 上再跑一个 redroid 安卓容器，`ADB_HOST` 指向它（如 `127.0.0.1:5555`）。示例（需要宿主内核支持，且**华住可能检测模拟器，需实测**）：

```bash
docker run -itd --rm --name redroid --privileged \
  -p 5555:5555 redroid/redroid:13.0.0_64only \
  androidboot.redroid_gpu_mode=guest
# 然后 adb connect 127.0.0.1:5555，装入华住会 apk 并登录，再校准坐标
```

---

## 五、配置项一览

| 变量 | 说明 | 默认 |
|------|------|------|
| `ADB_PATH` | adb 路径 | `adb` |
| `ADB_HOST` | 设备网络地址 `ip:port`，设置后先 `adb connect` | 空 |
| `ADB_SERIAL` | 指定设备序列号（与 ADB_HOST 二选一） | 空 |
| `USE_SU` | 模拟点击是否走 root（MIUI 等填 `1`） | 空(=0) |
| `RUN_AT` | `--loop` 每天执行时间 `HH:MM` | `09:05` |
| `TILE_XY` / `BUTTON_XY` | 绝对坐标 `x,y`（校准得到） | 空 |
| `TILE_FRAC` / `BUTTON_FRAC` | 比例坐标 `fx,fy`（未填绝对坐标时用） | `0.14,0.81` / `0.50,0.83` |
| `CONTINUE_XY` | 代理提示"继续使用"坐标（一般不用） | 空 |
| `PUSHPLUS_TOKEN` | PushPlus token，填了即启用微信推送 | 空 |
| `PUSHPLUS_TOPIC` | PushPlus 群组编码（一对多推送用，可选） | 空 |
| `NOTIFY_ON` | 推送时机：`all` / `fail` / `success` | `all` |
| `KEEP_ANIM` | `1` 时不改设备动画缩放 | 空 |
| `DEBUG` | `1` 输出更多日志 | 空 |

### 推送通知（PushPlus）

在 [pushplus.plus](https://www.pushplus.plus) 用微信登录拿到 token，填入 `PUSHPLUS_TOKEN` 即可。每次签到结果（成功 / 已签 / 失败 / 异常）会推送到微信。`NOTIFY_ON=fail` 可只在失败时提醒。

---

## 六、注意事项

- **保持登录**：脚本只做签到，不负责登录。设备上华住会需先登录好；偶尔掉登录需手动重登。
- **屏幕/锁屏**：设备尽量设为常亮或无密码锁屏（脚本会尝试唤醒+划开简单锁屏，但过不了密码锁）。
- **MIUI/部分定制系统**：模拟点击可能被拦，需 root 并设 `USE_SU=1`（真机方案 A 若用 MIUI 需注意）。
- **坐标漂移**：首页磁贴位置会随运营 Banner 变化；若某天签到失败，重跑 `--calibrate` 校准即可。
- **合规**：仅用于自动化你**本人账号**的日常签到，请勿滥用。

---

## 文件说明

| 文件 | 作用 |
|------|------|
| `checkin.py` | 主程序（`--once` / `--loop` / `--calibrate` / `--shot`） |
| `config.env.example` | 配置模板（复制为 `config.env`） |
| `Dockerfile` / `docker-compose.yml` / `entrypoint.sh` | Docker 部署 |
| `artifacts/` | 运行时截图/存档输出 |

## 许可证

本项目基于 [GNU GPL v3.0](LICENSE) 开源。

## 免责声明

本项目仅供学习交流与**自动化你本人账号**的日常签到使用。请遵守华住会用户协议与相关法律法规，因使用本项目产生的任何后果由使用者自行承担。
