# JJYB_AI_VideoAutoCut v3.3.1

发布日期：2026-10-12

## 本次更新

- **新增中英双语界面（i18n）**：
  - 全站 200+ 界面文案支持简体中文与 English 一键切换。
  - 语言设置通过 localStorage 持久化，重启后自动恢复。
  - 默认中文显示与原版完全一致，切换英文不影响任何功能。
  - 覆盖范围：导航栏、设置页、编辑器右侧面板（剪辑属性/色彩校正/特效/导出设置）、快捷工具、通知中心、快捷导航等。
- 修复 `base.html` 的 HTML `lang` 属性（en-US → zh-CN）与模板尾部多余反引号语法问题。
- 编辑器工具栏、视频预览区、剪辑检查器补充翻译标记。
- 设置页快捷导航、编辑器布局设置、外观保存按钮补充翻译标记。
- 新增 `backend/utils/ffmpeg_utils.py` 工具模块。

## 下载与安装

1. 下载 `JJYB_AI_VideoAutoCut-v3.3.1-source.zip`。
2. 解压后安装 Python 3.10-3.13。
3. 执行 `py -3 -m pip install -r requirements.txt`。
4. 安装 FFmpeg，并确保 `ffmpeg` 与 `ffprobe` 已加入 PATH。
5. 双击 `启动应用.bat`，或执行 `py -3 frontend\app.py`。

## 注意事项

- Release 源码包不包含 API Key、数据库、日志、用户素材、生成视频和大型模型权重。
- `config/ai_config.json`、`app.json`、`manifest.json`、`.anna/`、`executas/` 等私有配置文件已被 `.gitignore` 排除，不会进入开源仓库。
- IndexTTS2、TransNetV2、ImageMagick 等可选资源需要按照 README 单独准备。
- 使用声音复刻功能前，必须获得参考音频权利人的明确授权。
- 本软件仅授权个人学习、研究和自行使用；未经作者事先书面授权，不得商用、收费分发、提供收费服务或集成到商业产品。
- 下载、安装或使用本软件即表示同意仓库根目录 `LICENSE` 中的许可条款。

## 社区

QQ 交流群：`279549628`
