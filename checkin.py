#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2026  Dimlitter
# Licensed under the GNU General Public License v3.0 (see LICENSE).
"""
华住会 自动签到 (设备端自动化)
==================================================
通过 adb 驱动一个"已登录华住会"的安卓设备/模拟器完成每日签到。
不做任何逆向/抓包, 因此免疫证书 pinning 与反调试, App 更新也不易失效。

原理: 冷启动 App -> 首页点"签到"磁贴 -> 签到页点"签到"按钮 -> 截图存档。
页面跳转用窗口焦点(dumpsys window)确认, 不依赖 uiautomator(RN 动画页无法 dump)。

常用命令:
    python checkin.py --once        # 执行一次签到
    python checkin.py --loop        # 常驻, 每天 RUN_AT 定时执行
    python checkin.py --calibrate   # 保存首页/签到页截图到 ./artifacts, 用于读取坐标
    python checkin.py --shot        # 仅截当前屏到 ./artifacts/now.png

配置: 同目录 config.env (KEY=VALUE) 或环境变量(环境变量优先)。见 config.env.example。
"""
import os, sys, re, time, json, subprocess, datetime
import urllib.request
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---- 读取同目录 config.env 作为默认值(不覆盖真实环境变量) ----
_HERE = os.path.dirname(os.path.abspath(__file__))
_cfg = os.path.join(_HERE, "config.env")
if os.path.exists(_cfg):
    for _line in open(_cfg, encoding="utf-8"):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

PKG = "com.htinns"
HOME_ACT = "com.huazhu.main.RnMainActivity"
SIGNIN_ACT = "RNContainer"  # 签到页 Activity 关键字

ADB = os.environ.get("ADB_PATH", "adb")
ADB_HOST = os.environ.get("ADB_HOST", "").strip()
ADB_SERIAL = os.environ.get("ADB_SERIAL", "").strip()
USE_SU = os.environ.get("USE_SU", "") == "1"      # MIUI 等需 root 才能模拟点击
RUN_AT = os.environ.get("RUN_AT", "09:05").strip()
KEEP_ANIM = os.environ.get("KEEP_ANIM", "") == "1"
DEBUG = os.environ.get("DEBUG", "") == "1"
# 坐标: 绝对 "x,y" 优先; 否则用比例 "fx,fy"(0~1) * 屏幕尺寸
TILE_XY = os.environ.get("TILE_XY", "").strip()
BUTTON_XY = os.environ.get("BUTTON_XY", "").strip()
TILE_FRAC = os.environ.get("TILE_FRAC", "0.14,0.81").strip()
BUTTON_FRAC = os.environ.get("BUTTON_FRAC", "0.50,0.83").strip()
CONTINUE_XY = os.environ.get("CONTINUE_XY", "").strip()  # 代理弹窗"继续使用"(可选)
ART = os.path.join(_HERE, "artifacts")


def log(*a):
    print("[%s]" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def dbg(*a):
    if DEBUG:
        log("DEBUG", *a)


# ---- PushPlus 推送 ----
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "").strip()
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "").strip()      # 可选: 群组编码
NOTIFY_ON = os.environ.get("NOTIFY_ON", "all").strip()            # all / fail / success


def notify(ok, msg):
    if not PUSHPLUS_TOKEN:
        return
    if (NOTIFY_ON == "fail" and ok) or (NOTIFY_ON == "success" and not ok):
        return
    title = "华住会签到 " + ("成功" if ok else "需关注")
    content = "%s\n设备: %s\n时间: %s" % (
        msg, ADB_SERIAL or ADB_HOST or "?",
        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "txt"}
    if PUSHPLUS_TOPIC:
        payload["topic"] = PUSHPLUS_TOPIC
    try:
        req = urllib.request.Request(
            "https://www.pushplus.plus/send",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        r = urllib.request.urlopen(req, timeout=20)
        dbg("pushplus:", r.status)
    except Exception as e:
        dbg("pushplus err:", repr(e))


def _base():
    cmd = [ADB]
    s = ADB_SERIAL or ADB_HOST
    if s:
        cmd += ["-s", s]
    return cmd


def adb(*args, timeout=60, binary=False):
    dbg("adb", " ".join(str(x) for x in args)[:160])
    if binary:
        return subprocess.run(_base() + list(args), capture_output=True, timeout=timeout)
    return subprocess.run(_base() + list(args), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def sh(cmdline, timeout=60):
    return adb("shell", cmdline, timeout=timeout)


def su_sh(cmdline, timeout=60):
    """需要 root 的 shell(如模拟点击)。USE_SU=1 时用 su 包裹。"""
    if USE_SU:
        return sh("su -c '%s'" % cmdline.replace("'", "'\\''"), timeout=timeout)
    return sh(cmdline, timeout=timeout)


def connect():
    if ADB_HOST:
        log("adb connect", ADB_HOST)
        adb("connect", ADB_HOST, timeout=30)
        time.sleep(1)
    r = adb("get-state", timeout=15)
    state = (r.stdout or r.stderr).strip()
    if "device" not in state:
        raise RuntimeError("设备不在线: %r (检查 ADB_HOST/ADB_SERIAL / adb devices)" % state)
    log("已连接:", sh("getprop ro.product.model").stdout.strip() or "?", "| ", state)


def screen_size():
    out = sh("wm size").stdout
    m = re.search(r"(\d+)x(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else (1080, 1920)


def resolve_xy(name, absval, fracval):
    if absval:
        x, y = absval.split(",")
        return int(x), int(y)
    w, h = screen_size()
    fx, fy = fracval.split(",")
    return int(float(fx) * w), int(float(fy) * h)


def wake_unlock():
    if "Asleep" in sh("dumpsys power | grep -m1 mWakefulness=").stdout or \
       "Dozing" in sh("dumpsys power | grep -m1 mWakefulness=").stdout:
        su_sh("input keyevent KEYCODE_WAKEUP"); time.sleep(1)
    su_sh("input keyevent 82"); time.sleep(0.5)  # 划开简单锁屏


def set_anim(scale):
    if KEEP_ANIM:
        return
    for k in ("window_animation_scale", "transition_animation_scale", "animator_duration_scale"):
        sh("settings put global %s %s" % (k, scale))


def focus():
    return sh("dumpsys window | grep -m1 mCurrentFocus").stdout.strip()


def wait_focus(keyword, timeout=25):
    for _ in range(timeout):
        if keyword in focus():
            return True
        time.sleep(1)
    return False


def tap(x, y):
    su_sh("input tap %d %d" % (x, y)); time.sleep(1.5)


def screenshot(path):
    r = adb("exec-out", "screencap", "-p", timeout=30, binary=True)
    if r.stdout:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(r.stdout)
        return True
    return False


def raw_frame():
    """原始帧(RGBA), 用于按钮像素判定。screencap 无 -p 输出: 头部+w*h*4。"""
    r = adb("exec-out", "screencap", timeout=30, binary=True)
    return r.stdout or b""


def _pixel(raw, w, h, x, y):
    off = len(raw) - w * h * 4          # 头部长度随版本不同, 用总长反推
    if off < 0 or off > 256:
        return None
    i = off + (y * w + x) * 4
    if 0 <= i and i + 3 <= len(raw):
        return raw[i], raw[i + 1], raw[i + 2]
    return None


def button_signed(raw, w, h, cx, cy):
    """采样按钮中心区域平均色; 返回 True=已签到(浅粉低饱和), False=未签(饱和红), None=未知。"""
    pts = []
    for dx in (-40, 0, 40):
        for dy in (-15, 0, 15):
            p = _pixel(raw, w, h, cx + dx, cy + dy)
            if p:
                pts.append(p)
    if not pts:
        return None
    r = sum(p[0] for p in pts) / len(pts)
    g = sum(p[1] for p in pts) / len(pts)
    b = sum(p[2] for p in pts) / len(pts)
    mx, mn = max(r, g, b), min(r, g, b)
    sat = (mx - mn) / mx if mx else 0
    dbg("按钮 rgb=(%.0f,%.0f,%.0f) sat=%.2f" % (r, g, b, sat))
    return sat < 0.45  # 低饱和=已签到粉色


def launch_app():
    sh("am force-stop %s" % PKG); time.sleep(1)
    sh("am start -n %s/%s" % (PKG, HOME_ACT))
    ok = wait_focus(HOME_ACT, 20)
    time.sleep(3 if ok else 1)  # 让首页数据/磁贴加载
    return ok


def do_checkin():
    connect()
    wake_unlock()
    set_anim("0")
    try:
        if not launch_app():
            log("警告: 首页焦点未确认, 当前:", focus())

        # 可选: 处理代理风险弹窗(仅当设备走了代理才会出现; 服务器场景一般没有)
        if CONTINUE_XY:
            x, y = map(int, CONTINUE_XY.split(","))
            tap(x, y)

        # 第一步: 首页点"签到"磁贴 -> 进入签到页
        tx, ty = resolve_xy("tile", TILE_XY, TILE_FRAC)
        log("点击首页签到入口 @(%d,%d)" % (tx, ty))
        tap(tx, ty)
        if not wait_focus(SIGNIN_ACT, 15):
            log("未跳转到签到页, 当前:", focus())
            screenshot(os.path.join(ART, "no_signin_page.png"))
            notify(False, "未能进入签到页(可能未登录/入口坐标偏移/App 异常)")
            return 2
        time.sleep(3)  # 签到页加载

        w, h = screen_size()
        bx, by = resolve_xy("button", BUTTON_XY, BUTTON_FRAC)

        # 点击前判断: 若按钮已是"已签到"态, 说明今日已签, 幂等返回
        before = button_signed(raw_frame(), w, h, bx, by)
        if before is True:
            screenshot(os.path.join(ART, "after_signin.png"))
            log("[OK] 今日已签到(无需重复)。截图: artifacts/after_signin.png")
            notify(True, "今日已签到(无需重复)")
            return 0

        # 第二步: 点"签到"按钮
        log("点击签到按钮 @(%d,%d)" % (bx, by))
        tap(bx, by)
        time.sleep(2.5)

        # 第三步: 再次判断按钮态 + 存档
        screenshot(os.path.join(ART, "after_signin.png"))
        after = button_signed(raw_frame(), w, h, bx, by)
        if after is True:
            log("[OK] 签到成功。截图: artifacts/after_signin.png")
            notify(True, "签到成功")
            return 0
        if after is None:
            log("[WARN] 无法读取按钮状态(坐标/分辨率需校准)。截图: artifacts/after_signin.png")
            notify(False, "已点击签到, 但无法读取按钮状态, 请检查坐标/分辨率")
        else:
            log("[WARN] 点击后按钮仍为未签到态, 可能按钮坐标偏移, 请校准。截图: artifacts/after_signin.png")
            notify(False, "已点击签到, 但按钮仍为未签到态, 疑似坐标偏移, 请重新校准")
        return 1
    finally:
        set_anim("1")


def calibrate():
    connect()
    wake_unlock(); set_anim("0")
    w, h = screen_size()
    log("屏幕尺寸: %dx%d" % (w, h))
    launch_app()
    screenshot(os.path.join(ART, "cal_home.png"))
    log("已保存首页截图 -> artifacts/cal_home.png (读取'签到福利领取'磁贴中心坐标填 TILE_XY)")
    tx, ty = resolve_xy("tile", TILE_XY, TILE_FRAC)
    tap(tx, ty); wait_focus(SIGNIN_ACT, 12); time.sleep(3)
    screenshot(os.path.join(ART, "cal_signin.png"))
    log("已保存签到页截图 -> artifacts/cal_signin.png (读取红色'签到'按钮中心坐标填 BUTTON_XY)")
    set_anim("1")


def loop():
    log("常驻模式: 每天 %s 执行" % RUN_AT)
    last = None
    while True:
        now = datetime.datetime.now()
        if now.strftime("%H:%M") == RUN_AT and last != now.date():
            last = now.date()
            try:
                log("触发签到, rc=%d" % do_checkin())
            except Exception as e:
                log("签到异常:", repr(e))
                notify(False, "签到异常: " + repr(e))
        time.sleep(20)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--once"
    if mode == "--loop":
        loop()
    elif mode == "--calibrate":
        calibrate()
    elif mode == "--shot":
        connect(); screenshot(os.path.join(ART, "now.png")); log("已保存 artifacts/now.png")
    else:
        try:
            sys.exit(do_checkin())
        except SystemExit:
            raise
        except Exception as e:
            log("签到异常:", repr(e))
            notify(False, "签到异常: " + repr(e))
            sys.exit(3)


if __name__ == "__main__":
    main()
