FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

# 仅需时区数据; 脚本只用 Python 标准库, 无第三方依赖, 也不需要 adb。
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && ln -fs /usr/share/zoneinfo/$TZ /etc/localtime \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY checkin.py entrypoint.sh /app/
RUN chmod +x /app/entrypoint.sh && mkdir -p /app/data

VOLUME ["/app/data"]
ENTRYPOINT ["/app/entrypoint.sh"]
