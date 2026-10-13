# JJYB_AI_VideoAutoCut v3.3.2

发布日期：2026-10-13

## 本次更新（对标剪映"粗剪"算法，修复用户反馈的剪辑质量问题）

针对用户反馈的"音画不齐、杂乱无章、片头片尾剪进成片、前后不衔接、大量重复片段"五大问题，全面重构混剪与原创解说的粗剪核心：

- **片头片尾智能剔除**（新增 `backend/utils/intro_outro_detector.py`）：
  - 黑场检测（ffmpeg blackdetect）+ 低信息画面检测（抽帧灰度方差）+ 固定比例保护（默认首尾各 5%，0.8s~8s 自适应）。
  - 多素材片头/片尾模板检测：同系列视频的重复片头模板通过感知哈希识别并整段剔除。
  - 混剪三大模式（高光/普通/音乐卡点）与原创解说的分镜规划全部接入。
- **片段内容去重**（新增 `backend/utils/frame_dedup.py`）：
  - 每个候选镜头在片段中点抽帧计算 64bit dHash，海明距离 ≤10 判定为相似画面。
  - 相似镜头保留精彩度评分最高者，并从候选池自动补位（顶替原位置，不打乱已排定的叙事顺序）。
- **音画同步修复**（`backend/engine/puppet_sync_engine.py`）：
  - 逐段实测校准：每个视频片段渲染后用 ffprobe 实测时长，音频段按实测时长生成（原为计划时长，编码误差逐段累积导致越到片尾音画错位越大）。
  - 最终合成的期望总时长同样以实测值为准。
- README / RELEASE_NOTES 文档更新至 v3.3.2。

## 下载与安装

1. 下载 `JJYB_AI_VideoAutoCut-v3.3.2-source.zip`。
2. 解压后安装 Python 3.10-3.13。
3. 执行 `py -3 -m pip install -r requirements.txt`。
4. 安装 FFmpeg，并确保 `ffmpeg` 与 `ffprobe` 已加入 PATH。
5. 双击 `启动应用.bat`，或执行 `py -3 frontend\app.py`。

## 注意事项

- Release 源码包不包含 API Key、数据库、日志、用户素材、生成视频和大型模型权重。
- `config/ai_config.json`、`app.json`、`manifest.json`、`.anna/`、`executas/`、`jjyb_wsl/` 等私有配置文件已被 `.gitignore` 排除，不会进入开源仓库。
- 使用声音复刻功能前，必须获得参考音频权利人的明确授权。
- 本软件仅授权个人学习、研究和自行使用；未经作者事先书面授权，不得商用、收费分发、提供收费服务或集成到商业产品。
- 下载、安装或使用本软件即表示同意仓库根目录 `LICENSE` 中的许可条款。

## 社区

QQ 交流群：`279549628`
