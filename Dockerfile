FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

# 安装 adb 与时区数据 (脚本仅用标准库, 无需 pip 依赖)
RUN apt-get update \
    && apt-get install -y --no-install-recommends android-tools-adb tzdata \
    && ln -fs /usr/share/zoneinfo/$TZ /etc/localtime \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY checkin.py entrypoint.sh /app/
RUN chmod +x /app/entrypoint.sh

# 截图/存档输出目录
RUN mkdir -p /app/artifacts
VOLUME ["/app/artifacts"]

ENTRYPOINT ["/app/entrypoint.sh"]
