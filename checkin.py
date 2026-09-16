#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2026  Dimlitter
# Licensed under the GNU General Public License v3.0 (see LICENSE).
"""
华住会 自动签到 (纯 HTTP)
==================================================
直接请求华住会签到接口完成每日签到, 无需 App / 手机 / 模拟器, 任意 Linux 服务器可跑。

原理(抓包实证):
  鉴权 = 一个 cookie `userToken`(Domain=.huazhu.com), 无签名/无设备绑定。
  签到   GET https://appgw.huazhu.com/game/sign_in?date=<unix秒>
  状态   GET https://appgw.huazhu.com/game/sign_header
  返回 code: 200=签到成功, 5004=今日已签, 其它=失败(常见为 token 过期需更新)。

用法:
  python checkin.py           # 执行一次
  python checkin.py --once
  python checkin.py --loop     # 常驻, 每天 RUN_AT 定时执行

配置(环境变量, 或同目录 config.env):
  HZ_TOKEN        必填。userToken 值; 多账号用 & 或换行分隔。
  RUN_AT          --loop 每天执行时间 HH:MM (默认 09:05)
  RANDOM_DELAY    --loop 触发后随机延迟秒数上限, 错峰避免 429 (默认 1800=30分钟)
  RETRY_TIMES     遇 429/5xx/网络异常的额外重试次数 (默认 3)
  RETRY_DELAY     重试基础间隔秒数, 按次线性递增 (默认 60)
  PUSHPLUS_TOKEN  PushPlus 微信推送 token (可选)
  PUSHPLUS_TOPIC  PushPlus 群组编码 (可选)
  NOTIFY_ON       推送时机 all/fail/success (默认 all)
  DEBUG           1 输出更多日志
"""
import os, sys, re, json, time, random, datetime
import urllib.request, urllib.error

_HERE = os.path.dirname(os.path.abspath(__file__))
_cfg = os.path.join(_HERE, "config.env")
if os.path.exists(_cfg):
    for _line in open(_cfg, encoding="utf-8"):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

def _int_env(name, default):
    try:
        return int(str(os.environ.get(name, default)).strip())
    except Exception:
        return default


API = "https://appgw.huazhu.com"
RUN_AT = os.environ.get("RUN_AT", "09:05").strip()
DEBUG = os.environ.get("DEBUG", "") == "1"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "").strip()
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "").strip()
NOTIFY_ON = os.environ.get("NOTIFY_ON", "all").strip()
# 遇到 429/5xx/网络抖动时的延时重试
RETRY_TIMES = _int_env("RETRY_TIMES", 3)      # 额外重试次数
RETRY_DELAY = _int_env("RETRY_DELAY", 60)     # 重试基础间隔(秒), 按次线性递增
# --loop 定时触发后, 随机延迟 0~此值(秒)再签到, 错峰避免 429; 默认 30 分钟
RANDOM_DELAY = _int_env("RANDOM_DELAY", 1800)
_RETRY_CODES = (429, 500, 502, 503, 504)

UA = "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/114 Mobile Safari/537.36"


def log(*a):
    print("[%s]" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def dbg(*a):
    if DEBUG:
        log("DEBUG", *a)


# 可选: token 持久化文件。设置后优先从此文件读取, 并在服务器下发新 token 时自动覆盖(滑动续期)。
TOKEN_FILE = os.environ.get("HZ_TOKEN_FILE", "").strip()


def tokens():
    if TOKEN_FILE and os.path.exists(TOKEN_FILE):
        raw = open(TOKEN_FILE, encoding="utf-8").read().strip()
        if raw:
            dbg("从 HZ_TOKEN_FILE 读取 token")
            return [t.strip() for t in re.split(r"[&\n\r]+", raw) if t.strip()]
    raw = os.environ.get("HZ_TOKEN", "").strip()
    return [t.strip() for t in re.split(r"[&\n\r]+", raw) if t.strip()]


def _save_token(new_token):
    """滑动续期: 单账号且配置了 HZ_TOKEN_FILE 时, 把服务器下发的新 token 存回。"""
    if not TOKEN_FILE:
        return
    try:
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(new_token)
        log("检测到服务器续发新 token, 已自动保存(滑动续期)。")
    except Exception as e:
        dbg("save token err", repr(e))


def _refreshed_token(resp, used):
    """从响应 Set-Cookie 中提取新的 userToken(若与当前不同)。"""
    try:
        for sc in resp.headers.get_all("Set-Cookie") or []:
            m = re.search(r"userToken=([^;]+)", sc)
            if m and m.group(1) and m.group(1) != used:
                return m.group(1)
    except Exception:
        pass
    return None


def _retry_after(e):
    """从 429/503 响应的 Retry-After 头取等待秒数(仅支持纯秒数写法)。"""
    try:
        ra = (e.headers.get("Retry-After") or "").strip()
        if ra.isdigit():
            return int(ra)
    except Exception:
        pass
    return None


def _get(path, token):
    """GET 请求; 遇 429/5xx/网络异常按 RETRY_TIMES 延时重试。"""
    req = urllib.request.Request(API + path, headers={
        "Cookie": "userToken=" + token,
        "User-Agent": UA,
        "Referer": "https://cdn.huazhu.com/hzapp-signinfe/",
        "Origin": "https://cdn.huazhu.com",
        "Accept": "application/json, text/plain, */*",
    })
    last = None
    for attempt in range(RETRY_TIMES + 1):
        try:
            r = urllib.request.urlopen(req, timeout=25)
            body = r.read().decode("utf-8", "replace")
            return r.status, body, _refreshed_token(r, token)
        except urllib.error.HTTPError as e:
            last = e
            if e.code in _RETRY_CODES and attempt < RETRY_TIMES:
                wait = _retry_after(e) or RETRY_DELAY * (attempt + 1)
                log("请求 %s 返回 %s, %d 秒后重试(第 %d/%d 次)" % (path, e.code, wait, attempt + 1, RETRY_TIMES))
                time.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
            if attempt < RETRY_TIMES:
                wait = RETRY_DELAY * (attempt + 1)
                log("请求 %s 网络异常(%r), %d 秒后重试(第 %d/%d 次)" % (path, e, wait, attempt + 1, RETRY_TIMES))
                time.sleep(wait)
                continue
            raise
    if last:
        raise last


def sign_one(token, idx):
    """对单个 token 签到; 返回 (ok, 摘要文本, 续发token或None)。"""
    tag = "账号%d" % idx
    try:
        st, body, fresh = _get("/game/sign_in?date=%d" % int(time.time()), token)
        d = json.loads(body)
        code = d.get("code")
        msg = d.get("message", "")
        dbg(tag, "sign_in code=", code, "msg=", msg)
        if code == 200:
            log("[OK] %s 签到成功。%s" % (tag, _status(token)))
            return True, "%s 签到成功。%s" % (tag, _status(token)), fresh
        if code == 5004:
            log("[OK] %s 今日已签到。%s" % (tag, _status(token)))
            return True, "%s 今日已签到。%s" % (tag, _status(token)), fresh
        # 其它: 常见为 token 失效
        log("[FAIL] %s 签到失败: code=%s %s" % (tag, code, msg))
        return False, "%s 签到失败(code=%s): %s" % (tag, code, msg or "可能 token 已过期, 请更新 HZ_TOKEN"), fresh
    except urllib.error.HTTPError as e:
        log("[FAIL] %s HTTP %s" % (tag, e.code))
        if e.code == 429:
            hint = "(限流/服务器繁忙, 重试后仍失败; 通常次日自动恢复, 可调大 RANDOM_DELAY 错峰)"
        elif e.code in (401, 403):
            hint = "(鉴权失败, 可能 token 已过期, 请更新 HZ_TOKEN)"
        else:
            hint = ""
        return False, "%s 请求失败 HTTP %s %s" % (tag, e.code, hint), None
    except Exception as e:
        log("[FAIL] %s 异常: %r" % (tag, e))
        return False, "%s 异常: %r" % (tag, e), None


def _status(token):
    """取积分/连签天数做摘要, 失败不影响主流程。"""
    try:
        st, body, _f = _get("/game/sign_header", token)
        c = json.loads(body).get("content", {})
        return "积分%s 今年累计签到%s天" % (c.get("memberPoint"), c.get("yearSignInCount"))
    except Exception:
        return ""


def notify(ok, content):
    if not PUSHPLUS_TOKEN:
        return
    if (NOTIFY_ON == "fail" and ok) or (NOTIFY_ON == "success" and not ok):
        return
    title = "华住会签到 " + ("成功" if ok else "需关注")
    payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "txt"}
    if PUSHPLUS_TOPIC:
        payload["topic"] = PUSHPLUS_TOPIC
    try:
        req = urllib.request.Request("https://www.pushplus.plus/send",
                                     data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=20)
        dbg("pushplus sent")
    except Exception as e:
        dbg("pushplus err", repr(e))


def run_once():
    toks = tokens()
    if not toks:
        log("未配置 HZ_TOKEN"); notify(False, "未配置 HZ_TOKEN"); return 2
    results, all_ok = [], True
    single = len(toks) == 1
    for i, t in enumerate(toks, 1):
        ok, summary, fresh = sign_one(t, i)
        results.append(summary)
        all_ok = all_ok and ok
        if fresh and single:
            _save_token(fresh)   # 滑动续期: 单账号时保存服务器续发的新 token
        if not single:
            time.sleep(2)
    notify(all_ok, "\n".join(results))
    return 0 if all_ok else 1


def loop():
    log("常驻模式: 每天 %s 触发 (随机延迟 0~%d 秒错峰)" % (RUN_AT, RANDOM_DELAY))
    last = None
    while True:
        now = datetime.datetime.now()
        if now.strftime("%H:%M") == RUN_AT and last != now.date():
            last = now.date()  # 先占位, 避免随机延迟期间重复触发
            delay = random.randint(0, RANDOM_DELAY) if RANDOM_DELAY > 0 else 0
            if delay:
                log("随机延迟 %d 秒(约 %.1f 分钟)后签到" % (delay, delay / 60.0))
                time.sleep(delay)
            try:
                log("触发签到, rc=%d" % run_once())
            except Exception as e:
                log("异常:", repr(e)); notify(False, "签到异常: %r" % e)
        time.sleep(20)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--once"
    if mode == "--loop":
        loop()
    else:
        sys.exit(run_once())


if __name__ == "__main__":
    main()
