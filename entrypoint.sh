#!/bin/sh
# 容器入口: 纯 HTTP 签到, 无需 adb/安卓。默认常驻按 RUN_AT 定时。
set -e
export TZ="${TZ:-Asia/Shanghai}"
MODE="${MODE:---loop}"
echo "[entrypoint] python checkin.py $MODE (TZ=$TZ RUN_AT=${RUN_AT:-09:05})"
exec python /app/checkin.py "$MODE"
