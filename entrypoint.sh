#!/bin/sh
# 容器入口: 启动 adb, 连接目标设备, 运行签到(默认常驻定时)
set -e
export TZ="${TZ:-Asia/Shanghai}"

adb start-server >/dev/null 2>&1 || true

if [ -n "$ADB_HOST" ]; then
  echo "[entrypoint] adb connect $ADB_HOST"
  adb connect "$ADB_HOST" || true
fi

echo "[entrypoint] adb devices:"
adb devices || true

# MODE: --loop(默认, 每天定时) / --once(执行一次) / --calibrate
MODE="${MODE:---loop}"
echo "[entrypoint] python checkin.py $MODE"
exec python /app/checkin.py "$MODE"
