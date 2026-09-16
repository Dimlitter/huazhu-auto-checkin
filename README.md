# 华住会 自动签到（纯 HTTP）

[![build-and-publish](https://github.com/Dimlitter/huazhu-auto-checkin/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/Dimlitter/huazhu-auto-checkin/actions/workflows/docker-publish.yml)

直接请求华住会签到接口完成每日签到。**纯 HTTP、无需 App / 手机 / 模拟器**，任意 Linux 服务器（哪怕最小的 VPS）都能跑。只需一个 `userToken`。

## 特点

- ☁️ 任意服务器可跑，无需 redroid / binder / adb / 安卓环境
- 🪶 仅 Python 标准库，无第三方依赖，镜像极小
- 🔔 PushPlus 微信推送（成功/失败/token 过期即时提醒）
- 👥 支持多账号
- 🔁 支持服务器滑动续期时自动保存新 token
- ⏱️ 定时触发后随机延迟错峰，并对 429/5xx/网络异常自动延时重试
- 🐉 适配青龙面板（QingLong）：读面板变量、对接其统一通知

## 原理（抓包实证）

华住会签到的鉴权就是一个 cookie `userToken`（`Domain=.huazhu.com`），**没有签名、没有设备绑定**：

| 用途 | 请求 |
|------|------|
| 签到 | `GET https://appgw.huazhu.com/game/sign_in?date=<unix秒>` |
| 状态 | `GET https://appgw.huazhu.com/game/sign_header` |

返回 `code`：`200`=签到成功，`5004`=今日已签，其它=失败（通常是 token 过期）。

> 注：`appgw` 的证书 pinning 只在**原生 App 内部**校验；独立脚本直接请求完全不受影响。

---

## 一、如何获取 userToken（关键，只需一次）

`userToken` 是你华住会账号的登录令牌，藏在 App/小程序发出的请求 Cookie 里。抓一次即可：

**方法（手机抓包，通用）**
1. 手机装抓包工具：安卓用 **Reqable / HttpCanary / 小黄鸟**，iOS 用 **Stream / Thor / Reqable**。
2. 打开 **华住会 App**（或微信「华住会」小程序）→ 进「签到」页。
3. 在抓包记录里找任意发往 `*.huazhu.com` 的请求，查看其 **请求头 Cookie**，找到：
   ```
   userToken=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx123456789
   ```
   复制 `userToken=` 后面那串（到分号前）就是你要的值。

> 若你有 root 手机 + mitmproxy 经验，也可代理抓包，从 `hweb-*.huazhu.com` 等未 pinning 的请求里取 `userToken`。

把这串填到 `HZ_TOKEN`（源码用 `config.env`，Docker 用 compose 环境变量）。

---

## 二、token 有效期与「续期」（重要，务必了解）

**能不能永久全自动？—— 不能，但实际几乎不用管。** 诚实说明：

- ⛔ **无法做到完全无人续期**：token 的源头是华住的「手机号+短信验证码」登录，重新登录绕不开短信，机器无法自动收码。这是所有同类方案的共同上限。
- ✅ **但它很长命**：这是「App 持久登录」令牌（华住 App 你登录一次能几个月不掉），通常**数周到数月**有效，期间脚本天天自动签到。（实测：同一 token 连续每天签到 2 周以上仍有效。）
- ✅ **滑动续期（自动保存）**：若华住在响应里下发新 token，脚本会自动存回 `HZ_TOKEN_FILE`，只要天天在用就一直续着。（当前抓包未见其下发，此为防御性能力，未来若开启则零成本自动生效。）
- ✅ **过期即时告警**：token 一旦失效，脚本立刻 PushPlus 推「token 已过期请更新」，你花 1 分钟重新抓一次即可，绝不会悄无声息漏签。

结论：**偶尔（可能数月一次）手动更新一下 token**，其余时间全自动。

> 关于偶发 **429（限流）**：某些日子华住服务器繁忙会返回 429 导致签到失败，通常次日自动恢复。脚本已内置 **随机错峰延迟 + 自动延时重试**（见 `RANDOM_DELAY` / `RETRY_TIMES` / `RETRY_DELAY`）来缓解，一般无需干预。

---

## 三、部署

脚本很轻（单文件、纯标准库），**优先源码运行**；用青龙的直接加进去；Docker 属于杀鸡用牛刀，按需。

### 方式 A：源码直接运行（推荐）

```bash
git clone git@github.com:Dimlitter/huazhu-auto-checkin.git
cd huazhu-auto-checkin
cp config.env.example config.env     # 填 HZ_TOKEN 等
python3 checkin.py --once            # 执行一次(退出码 0=成功/已签,1=失败,2=未配置)
python3 checkin.py --loop            # 常驻自带定时, 每天 RUN_AT 执行
```

仅需 Python 3，无第三方依赖、无需 `pip install`。常驻方式二选一：

- **自带定时(简单)**：`nohup python3 checkin.py --loop &`，或写个 systemd service 守护。
- **交给系统 cron(省资源, 用 --once)**：`crontab -e` 加一行
  ```
  5 9 * * * cd /path/to/huazhu-auto-checkin && python3 checkin.py --once >> data/checkin.log 2>&1
  ```

### 方式 B：青龙面板（QingLong）

脚本已适配青龙：读面板环境变量、对接青龙统一通知、cron 驱动跑一次。

1. **拉脚本**（二选一）
   - 订阅（推荐）：青龙「订阅管理」新建，仓库 `https://github.com/Dimlitter/huazhu-auto-checkin.git`，白名单 `checkin.py`；脚本顶部已带 `cron: 5 9 * * *`，可自动建任务。
   - 手动：「脚本管理」上传 `checkin.py` → 「定时任务」新建，命令 `task checkin.py`，cron 自定（如 `5 9 * * *`）。
2. **配环境变量**（青龙「环境变量」）：`HZ_TOKEN`（必填，多账号用 `&` 分隔）；可选 `RANDOM_DELAY` / `RETRY_TIMES` 等。
3. **通知**：无需填 `PUSHPLUS_TOKEN`——脚本自动走**青龙统一通知**（在青龙「通知设置」里配 PushPlus / Telegram 等即可）。
4. 青龙下 `--once` 会自动按 `RANDOM_DELAY` 随机错峰（默认 30 分钟内）；不想让任务挂这么久，设 `RANDOM_DELAY=0` 并靠 cron 分散即可。

### 方式 C：Docker（可选）

```bash
git clone git@github.com:Dimlitter/huazhu-auto-checkin.git
cd huazhu-auto-checkin
# 编辑 docker-compose.yml, 填入 HZ_TOKEN(可选填 PUSHPLUS_TOKEN)
docker compose up -d --build
docker compose logs -f
```

免本地构建：把 compose 里 `build: .` 换成 `image: ghcr.io/dimlitter/huazhu-auto-checkin:latest`。手动签到一次：`docker compose run --rm -e MODE=--once huazhu-checkin`。

---

## 配置项

| 变量 | 说明 | 默认 |
|------|------|------|
| `HZ_TOKEN` | **必填**，userToken 值；多账号用 `&` 或换行分隔 | — |
| `HZ_TOKEN_FILE` | 可选，token 持久化文件；设置后优先读它，并自动保存续发 token | 空 |
| `RUN_AT` | `--loop` 每天签到时间 `HH:MM` | `09:05` |
| `RANDOM_DELAY` | 触发后随机延迟 0~此值(秒)再签到，错峰避免 429；`0` 关闭 | `1800` |
| `RETRY_TIMES` | 遇 429/5xx/网络异常的额外重试次数 | `3` |
| `RETRY_DELAY` | 重试基础间隔(秒)，按次线性递增（并遵守 `Retry-After`） | `60` |
| `PUSHPLUS_TOKEN` | PushPlus token，填了即启用微信推送 | 空 |
| `PUSHPLUS_TOPIC` | PushPlus 群组编码（可选） | 空 |
| `NOTIFY_ON` | 推送时机 `all` / `fail` / `success` | `all` |
| `DEBUG` | `1` 输出更多日志 | 空 |

## 命令

```bash
python checkin.py            # = --once, 执行一次
python checkin.py --loop     # 常驻定时
```

## 注意事项

- **保管好 userToken**：它等同于你账号的登录凭证，别泄露、别提交到公开仓库（本项目 `config.env`、`data/` 已在 .gitignore）。
- **合规**：仅用于自动化**你本人账号**的日常签到，请遵守华住会用户协议与相关法律法规。

## 许可证

本项目基于 [GNU GPL v3.0](LICENSE) 开源。

## 免责声明

仅供学习交流与自动化你本人账号的日常签到使用，使用本项目产生的任何后果由使用者自行承担。
