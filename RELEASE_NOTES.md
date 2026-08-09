# JJYB_AI_VideoAutoCut v3.3.0

发布日期：2026-08-09

## 本次更新

- 全量同步新版 JJYB_AI 智剪源码到原公开源码仓库。
- 完善原创解说、智能混剪、AI 配音、声音复刻、AI 封面和剪映草稿导出说明。
- 重构 GitHub README 首屏，加入全部品牌介绍图和 QQ 群二维码。
- 强化敏感配置、数据库、日志、模型权重、用户素材和生成文件的忽略规则。
- 新增 `scripts/build_release.ps1`，用于生成可复现的源码 Release 压缩包。

## 下载与安装

1. 下载 `JJYB_AI_VideoAutoCut-v3.3.0-source.zip`。
2. 解压后安装 Python 3.10-3.13。
3. 执行 `py -3 -m pip install -r requirements.txt`。
4. 安装 FFmpeg，并确保 `ffmpeg` 与 `ffprobe` 已加入 PATH。
5. 双击 `启动应用.bat`，或执行 `py -3 frontend\app.py`。

## 注意事项

- Release 源码包不包含 API Key、数据库、日志、用户素材、生成视频和大型模型权重。
- IndexTTS2、TransNetV2、ImageMagick 等可选资源需要按照 README 单独准备。
- 使用声音复刻功能前，必须获得参考音频权利人的明确授权。
- 本软件仅授权个人学习、研究和自行使用；未经作者事先书面授权，不得商用、收费分发、提供收费服务或集成到商业产品。
- 下载、安装或使用本软件即表示同意仓库根目录 `LICENSE` 中的许可条款。

## 社区

QQ 交流群：`279549628`
