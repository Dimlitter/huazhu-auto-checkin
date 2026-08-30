#!/bin/sh
# 容器入口: 等待安卓就绪 -> 连接 -> 安装 APK -> 运行签到
set -e
export TZ="${TZ:-Asia/Shanghai}"
ADB_HOST="${ADB_HOST:-redroid:5555}"

adb start-server >/dev/null 2>&1 || true

echo "[entrypoint] 等待安卓就绪 @ $ADB_HOST ..."
booted=0
i=0
while [ "$i" -lt 60 ]; do
  adb connect "$ADB_HOST" >/dev/null 2>&1 || true
  state=$(adb -s "$ADB_HOST" get-state 2>/dev/null || true)
  if [ "$state" = "device" ]; then
    boot=$(adb -s "$ADB_HOST" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r\n')
    if [ "$boot" = "1" ]; then booted=1; echo "[entrypoint] 安卓已启动完成"; break; fi
  fi
  i=$((i + 1)); sleep 3
done
[ "$booted" = "1" ] || echo "[entrypoint] 警告: 等待安卓超时, 仍尝试继续"

# 首次自动安装华住会 APK (放在 ./apk/*.apk)
if ! adb -s "$ADB_HOST" shell pm list packages 2>/dev/null | grep -q "com.htinns"; then
  APK=$(ls /app/apk/*.apk 2>/dev/null | head -1)
  if [ -n "$APK" ]; then
    echo "[entrypoint] 安装华住会: $APK"
    adb -s "$ADB_HOST" install -r -g "$APK" || echo "[entrypoint] 安装失败(可忽略, 稍后手动装)"
  else
    echo "[entrypoint] 未安装华住会, 且 /app/apk 无 APK。请放入 huazhu.apk 后重启本容器。"
  fi
else
  echo "[entrypoint] 华住会已安装"
fi

echo "[entrypoint] 当前设备:"; adb devices

MODE="${MODE:---loop}"
echo "[entrypoint] 运行 checkin.py $MODE"
exec python /app/checkin.py "$MODE"
