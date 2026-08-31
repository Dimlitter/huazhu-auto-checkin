# 华住会 自动签到（纯 HTTP）

[![build-and-publish](https://github.com/Dimlitter/huazhu-auto-checkin/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/Dimlitter/huazhu-auto-checkin/actions/workflows/docker-publish.yml)

直接请求华住会签到接口完成每日签到。**纯 HTTP、无需 App / 手机 / 模拟器**，任意 Linux 服务器（哪怕最小的 VPS）都能跑。只需一个 `userToken`。

## 特点

- ☁️ 任意服务器可跑，无需 redroid / binder / adb / 安卓环境
- 🪶 仅 Python 标准库，无第三方依赖，镜像极小
- 🔔 PushPlus 微信推送（成功/失败/token 过期即时提醒）
- 👥 支持多账号
- 🔁 支持服务器滑动续期时自动保存新 token

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
- ✅ **但它很长命**：这是「App 持久登录」令牌（华住 App 你登录一次能几个月不掉），通常**数周到数月**有效，期间脚本天天自动签到。
- ✅ **滑动续期（自动保存）**：若华住在响应里下发新 token，脚本会自动存回 `HZ_TOKEN_FILE`，只要天天在用就一直续着。（当前抓包未见其下发，此为防御性能力，未来若开启则零成本自动生效。）
- ✅ **过期即时告警**：token 一旦失效，脚本立刻 PushPlus 推「token 已过期请更新」，你花 1 分钟重新抓一次即可，绝不会悄无声息漏签。

结论：**偶尔（可能数月一次）手动更新一下 token**，其余时间全自动。

---

## 三、部署

### 方式 A：Docker（推荐）

```bash
git clone git@github.com:Dimlitter/huazhu-auto-checkin.git
cd huazhu-auto-checkin
# 编辑 docker-compose.yml, 填入 HZ_TOKEN(可选填 PUSHPLUS_TOKEN)
docker compose up -d --build
docker compose logs -f
```

免本地构建：把 compose 里 `build: .` 换成 `image: ghcr.io/dimlitter/huazhu-auto-checkin:latest`。

手动签到一次：
```bash
docker compose run --rm -e MODE=--once huazhu-checkin
```

### 方式 B：源码直接运行

```bash
cp config.env.example config.env    # 填 HZ_TOKEN 等
python checkin.py --once            # 执行一次(退出码 0=成功/已签,1=失败,2=未配置)
python checkin.py --loop            # 常驻, 每天 RUN_AT 定时
```

仅需 Python 3，无需 `pip install`。可配合 systemd / crontab / nohup 常驻。

---

## 配置项

| 变量 | 说明 | 默认 |
|------|------|------|
| `HZ_TOKEN` | **必填**，userToken 值；多账号用 `&` 或换行分隔 | — |
| `HZ_TOKEN_FILE` | 可选，token 持久化文件；设置后优先读它，并自动保存续发 token | 空 |
| `RUN_AT` | `--loop` 每天签到时间 `HH:MM` | `09:05` |
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
