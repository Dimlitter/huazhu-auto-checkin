# 华住会 自动签到（设备端自动化 · 全 Docker）

[![build-and-publish](https://github.com/Dimlitter/huazhu-auto-checkin/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/Dimlitter/huazhu-auto-checkin/actions/workflows/docker-publish.yml)

在 **Linux 服务器上用 Docker 一站式运行**：`docker compose` 同时拉起「安卓环境(redroid) + 签到调度」，**无需任何手机**。通过 `adb` 驱动容器内已登录的华住会 App，冷启动 → 进入签到页 → 点击签到 → 截图验证 → 可选微信推送。

> 完成一次性引导（放 APK、登录一次、校准坐标）后，日常只需 `docker compose up -d`，全自动无人值守。

## 为什么是"设备端自动化"而不是纯 HTTP 脚本

华住会 App 加固较强，纯 Python 复刻请求基本走不通：核心接口 `appgw.huazhu.com` 有**证书 pinning**；App 有**主动反 Frida**；签到请求签名在**原生层**且很可能**绑定设备指纹**（tongdun 风控）。让真 App 自己发请求可**免疫 pinning / 反调试 / 签名变更**，登录态由 App 长期维持，是这类加固 App 最稳的自动化方式。

---

## ⚠️ 三个必读前提

1. **宿主内核需支持 binder**：redroid 靠宿主 Linux 内核跑安卓。KVM/独立服务器一般可以；**OpenVZ、部分廉价 VPS、内核无 binder 的机器跑不了**。见下方「宿主机准备」自检。
2. **需一次性登录**：华住用「手机号+短信验证码」，App 需要已登录账号。**日常签到全自动**，但**首次要人工输一次验证码**——不用手机连服务器，用 `scrcpy` 从你电脑远程操作一次即可。
3. **反模拟器风险**：华住带 tongdun 风控，**可能识别 redroid 为模拟器而拒绝登录/签到**。本项目无法预先替你实测 redroid；若被拦，见「反检测」一节尝试带 Magisk 的镜像与伪装（不保证成功）。

> 若你有一台可常开的真机，`方案B` 用真机更省心、兼容性最好。

---

## 一、宿主机准备（redroid 依赖）

```bash
# 1) 检查/加载 binder 内核模块
ls /dev/binder* 2>/dev/null && echo "binder OK" || sudo modprobe binder_linux devices="binder,hwbinder,vndbinder"
# 老内核可能还需 ashmem(新内核用 memfd, 无此模块可忽略)
sudo modprobe ashmem_linux 2>/dev/null || true

# 2) 开机自动加载(持久化)
echo 'binder_linux' | sudo tee /etc/modules-load.d/binder.conf
echo 'options binder_linux devices=binder,hwbinder,vndbinder' | sudo tee /etc/modprobe.d/binder.conf

# 3) 需已安装 docker + docker compose 插件
docker version && docker compose version
```

找不到 `binder_linux` 模块（`find /lib/modules -name 'binder*'` 为空）说明当前内核不支持，redroid 无法运行——请换支持 binder 的内核/机器，或改用 `方案B` 真机。

**架构匹配（重要）**：redroid 镜像要同时匹配「宿主架构」和「APK 架构」。华住 APK 多为 **arm**：
- **arm64 服务器**：用 `redroid/redroid:13.0.0_64only`（compose 默认）。
- **x86_64 服务器**：需带 **arm 指令翻译** 的 redroid 镜像（如 `...-ndk_translation` 或社区 translation 镜像），否则 arm 的华住装不上/闪退。请据此修改 `docker-compose.yml` 里 redroid 的 `image`。

---

## 二、一次性引导（约 10 分钟，仅一次）

### 1. 放入华住会 APK
把安装包放到 `apk/huazhu.apk`（版权原因仓库不附带，自行获取 arm64 包）。见 [apk/README.md](apk/README.md)。

### 2. 拉起两个容器
```bash
git clone git@github.com:Dimlitter/huazhu-auto-checkin.git
cd huazhu-auto-checkin
docker compose up -d          # 起 redroid + checkin; 首次会自动装 APK
docker compose logs -f checkin  # 看到"安卓已启动完成/华住会已安装"
```

### 3. 一次性登录（用 scrcpy 远程操作，无需手机连服务器）
redroid 的 adb 端口 5555 已映射到服务器。**不建议把 5555 暴露公网**，用 SSH 隧道从你自己的电脑连：

```bash
# 在你本地电脑(需装 adb + scrcpy):
ssh -L 5555:localhost:5555 user@<服务器IP>     # 开隧道, 保持此终端
# 另开一个终端:
adb connect localhost:5555
scrcpy -s localhost:5555                        # 弹出 redroid 画面
#  → 打开华住会 → 输手机号 → 你本人手机收短信验证码 → 过滑块 → 登录成功
```
登录一次后 App 长期保持登录，关掉 scrcpy 即可。

### 4. 校准坐标（redroid 分辨率固定，一次即可）
```bash
docker compose run --rm -e MODE=--calibrate checkin
# 查看 ./artifacts/cal_home.png 与 cal_signin.png,
# 读出"签到磁贴"和"签到按钮"中心像素坐标, 填入 docker-compose.yml:
#   TILE_XY: "x,y"      BUTTON_XY: "x,y"
docker compose up -d          # 用新坐标重启
```

### 使用预构建镜像（免本地 build，可选）

GitHub Actions 已把 checkin 镜像发布到 GHCR（多架构 amd64/arm64）。把 `docker-compose.yml` 里 `checkin` 服务的 `build: .` 换成：
```yaml
    image: ghcr.io/dimlitter/huazhu-auto-checkin:latest
```
即可直接拉取，无需本地构建。（首次可能需在 GitHub 仓库 Packages 里把该镜像设为 Public，或 `docker login ghcr.io` 后拉取。）

### 5.（可选）微信推送
在 [pushplus.plus](https://www.pushplus.plus) 用微信登录拿 token，填到 `docker-compose.yml` 的 `PUSHPLUS_TOKEN`，`docker compose up -d` 生效。

---

## 三、日常运行

引导完成后，日常什么都不用管；重启服务器或更新后只需：
```bash
docker compose up -d          # 常驻, 每天 RUN_AT(默认 09:05) 自动签到
docker compose logs -f checkin
docker compose run --rm -e MODE=--once checkin   # 手动立即签到一次
```
签到截图落在 `./artifacts/after_signin.png`，成功/失败会按 `NOTIFY_ON` 推送微信。

### 反检测（若 redroid 被华住识别为模拟器）
- 换带 **Magisk** 的 redroid 社区镜像，装 Shamiko 隐藏 root；
- 用 `resetprop` 伪装 `ro.product.*` / `ro.build.fingerprint` 为真机型号；
- 关闭开发者选项相关标志。
> 这些为经验性缓解，不保证过风控；实测不通建议改用 `方案B` 真机。

---

## 方案B：连接真机 / 外部安卓（备选，最稳）

不想跑 redroid，或被风控拦，可用一台常开真机：
```bash
# 真机(USB 连一次)执行, 开启网络 adb:
adb tcpip 5555            # 记下手机 IP, 如 192.168.1.50
```
然后在 `docker-compose.yml` 里**删掉 redroid 服务**、把 `checkin` 的 `ADB_HOST` 改为手机地址（如 `192.168.1.50:5555`），`network_mode: host` 便于连局域网，再 `docker compose up -d`。真机已登录，无需 scrcpy/APK 步骤，只需 `--calibrate` 校准坐标。

也可源码直接跑（需本机装 adb）：
```bash
cp config.env.example config.env   # 填 ADB_HOST / 坐标 / PUSHPLUS_TOKEN
python checkin.py --once           # 或 --loop
```

---

## 配置项一览

| 变量 | 说明 | 默认 |
|------|------|------|
| `ADB_HOST` | 安卓 adb 地址；容器内连 redroid 用 `redroid:5555` | `redroid:5555` |
| `ADB_SERIAL` | 指定设备序列号（与 ADB_HOST 二选一） | 空 |
| `ADB_PATH` | adb 路径 | `adb` |
| `USE_SU` | 模拟点击是否走 root（redroid 一般 0；MIUI 真机填 1） | 空(=0) |
| `RUN_AT` | `--loop` 每天执行时间 `HH:MM` | `09:05` |
| `TILE_XY` / `BUTTON_XY` | 绝对坐标 `x,y`（校准得到，最准） | 空 |
| `TILE_FRAC` / `BUTTON_FRAC` | 比例坐标 `fx,fy`（未填绝对坐标时用） | `0.14,0.81` / `0.50,0.83` |
| `PUSHPLUS_TOKEN` | PushPlus token，填了即启用微信推送 | 空 |
| `PUSHPLUS_TOPIC` | PushPlus 群组编码（可选） | 空 |
| `NOTIFY_ON` | 推送时机：`all` / `fail` / `success` | `all` |
| `CONTINUE_XY` | 代理提示"继续使用"坐标（一般不用） | 空 |
| `KEEP_ANIM` | `1` 时不改设备动画缩放 | 空 |
| `DEBUG` | `1` 输出更多日志 | 空 |

> 成功判定：脚本采样"签到"按钮区域颜色——饱和红=未签、浅粉=已签，不依赖 OCR，不受 RN 动画影响。

---

## 命令

```bash
python checkin.py --once        # 执行一次(退出码 0=成功/已签,1=不确定,2=页面异常,3=异常)
python checkin.py --loop        # 常驻定时
python checkin.py --calibrate   # 保存首页/签到页截图到 artifacts/ 供读坐标
python checkin.py --shot        # 仅截当前屏
```

## 注意事项

- **保持登录**：脚本只签到不登录；掉登录（少见）时重做一次性登录即可。建议开 PushPlus 推送，失败会提醒。
- **安全**：不要把 redroid 的 5555 暴露公网，用 SSH 隧道登录。
- **坐标漂移**：运营 Banner 变动可能让磁贴位移；签到失败先重跑 `--calibrate`。
- **合规**：仅用于自动化**你本人账号**的日常签到。

## 文件说明

| 文件 | 作用 |
|------|------|
| `checkin.py` | 主程序（`--once`/`--loop`/`--calibrate`/`--shot`） |
| `docker-compose.yml` | redroid + checkin 编排 |
| `Dockerfile` / `entrypoint.sh` | 调度容器镜像与入口 |
| `config.env.example` | 源码运行的配置模板 |
| `apk/` | 放华住会 APK（首次自动安装） |
| `artifacts/` | 运行时截图/存档输出 |

## 许可证

本项目基于 [GNU GPL v3.0](LICENSE) 开源。

## 免责声明

仅供学习交流与**自动化你本人账号**的日常签到使用。请遵守华住会用户协议与相关法律法规，使用本项目产生的任何后果由使用者自行承担。
