# 放置华住会 APK

把华住会安卓安装包放到本目录并命名为 `huazhu.apk`（或任意 `*.apk`），
容器首次启动会自动 `adb install` 到 redroid。

- 出于版权原因，本仓库**不附带** APK，请自行从官方渠道/应用商店获取。
- 建议使用 arm64 架构的安装包（redroid 默认镜像为 arm 翻译/或对应架构）。
- 更新 App：替换此处 APK 后 `docker compose restart checkin` 会自动覆盖安装。
