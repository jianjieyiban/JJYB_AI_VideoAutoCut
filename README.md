# JJYB_AI智剪

<p align="center">
  <strong>本地运行的 AI 视频创作工具 · 闭源私有部署</strong>
</p>

<p align="center">
  原创解说 · 智能混剪 · AI 配音 · 声音复刻 · AI 封面生成 · 精选视频复刻 · 剪映草稿导出
</p>

<p align="center">
  <a href="#快速开始">快速开始</a> ·
  <a href="#核心功能">核心功能</a> ·
  <a href="#项目结构">项目结构</a> ·
  <a href="#配置说明">配置说明</a> ·
  <a href="#常见问题">常见问题</a>
</p>

---

## 项目简介

JJYB_AI智剪是一款本地桌面优先的 AI 视频创作工具，提供原创解说、智能混剪、AI 配音、声音复刻、AI 封面生成与精选视频复刻能力。前端基于 Flask + PyWebView，视频渲染依赖 FFmpeg，项目数据保存在本地 SQLite。

**最新版本**：v3.1.0（2026-08-01）

> **重要声明**：本工具仅处理用户拥有合法权利的文本、视频、音乐与参考音频。使用声音复刻功能前必须取得参考音频权利人的明确授权。云端模型、外部 TTS 和本地声音复刻是否可用，取决于对应 API 配置、运行环境及模型权重是否就绪。

---

## 核心功能

### 1. 原创解说（完整工作流）

完整的"视频→分析→文稿→配音→同步→导出"工作流：

- **智能镜头分割**：`SmartShotSegmenter` 优先尝试 TransNetV2 深度分镜；不可用时以 OpenCV 画面差异与直方图检测为降级方案，不设帧数上限。
- **AI 文案生成**：通过已配置的视觉/文本模型分析画面并生成解说文稿，支持 **12 种叙述风格**。
- **三处解说风格联动**：风格预设仪表板、文稿风格配置、写作人格面板。
- **分段配音**：支持 Edge TTS、Azure、gTTS、火山引擎、IndexTTS2 克隆等多种 TTS 引擎。
- **拟人化同步**：`PuppetSyncEngine` 逐段匹配镜头与配音，支持直连、慢放、末帧定格、截取高光、短语音合并五种策略。
- **原片原声穿插**：支持按成片比例或按段落间隔穿插原片原声。
- **目标时长**：支持设置目标时长，同步引擎根据目标时长调整片段选取和速度。
- **文案质检**：六维评分诊断（吸引力、节奏、信息量、情感、流畅度、原创性）。
- **断点恢复**：长任务支持断点保存与恢复，流式生成实时反馈进度。
- **剪映草稿导出**：一键导出剪映原生草稿（含视频轨、配音轨、BGM轨、字幕轨）。

### 2. 智能混剪

两种混剪模式：普通模式与音乐卡点模式（支持 dense/medium/sparse 三种卡点密度）。

### 3. AI 配音与声音复刻

- **常规配音**：Edge TTS、gTTS、pyttsx3、Azure TTS、火山引擎 TTS、Coqui TTS（可选）。
- **声音复刻**：IndexTTS2 本地 worker、Fish Audio、MiniMax、火山引擎、Azure Custom Voice。

### 4. AI 封面生成

多模型支持：DALL-E 3、通义万相、文心一格、腾讯混元、智谱 CogView、豆包生图、MiniMax、SiliconFlow、OpenRouter，以及自定义 OpenAI 兼容图像生成网关。

### 5. 视频编辑器 / 6. 素材库管理 / 7. 项目管理

多轨道编辑、素材上传分类、项目创建管理等完整能力。

---

## 技术栈

| 类别 | 技术 |
|---|---|
| **桌面与 Web** | Flask、Flask-SocketIO、PyWebView、HTML/JavaScript/Layui |
| **数据存储** | SQLite |
| **视频处理** | FFmpeg/ffprobe、OpenCV、MoviePy、ImageMagick |
| **音频处理** | librosa、SoundFile、Pydub |
| **TTS 引擎** | Edge TTS、gTTS、pyttsx3、Azure TTS、火山引擎、Coqui TTS |
| **声音复刻** | IndexTTS2（本地）、Fish Audio、MiniMax、火山引擎、Azure Custom Voice |
| **视觉与 AI** | 可配置云端模型适配器、PyTorch、YOLO、faster-whisper |
| **ASR 识别** | faster-whisper、Whisper（可选）、FunASR（可选） |
| **图像生成** | DALL-E 3、通义万相、文心一格、腾讯混元、智谱 CogView、豆包生图、SiliconFlow、自定义 OpenAI 兼容网关 |
| **云端文本模型** | OpenAI、Claude、Gemini、Kimi、讯飞星火、通义千问、文心一言、ChatGLM、DeepSeek、OpenRouter、SiliconFlow、豆包 |

---

## 环境要求

- **操作系统**：Windows 10/11
- **Python**：主程序推荐 Python 3.10–3.13
- **FFmpeg**：必须已安装并可从命令行调用
- **ImageMagick**（可选）：已内置在 `resource/imageMagick/` 目录
- **可选**：NVIDIA CUDA 环境
- **IndexTTS2**：单独使用 Python 3.10 环境

---

## 快速开始

### 方式一：Release 包（推荐）

1. 从 [GitHub Releases](https://github.com/jianjieyiban/JJYB-AI-ZhiJian/releases) 下载最新版本。
2. 解压到任意目录。
3. 安装 Python 依赖：`py -3 -m pip install -r requirements.txt`。
4. 安装 FFmpeg 并加入 PATH。
5. 双击 `启动应用.bat` 启动。

### 方式二：从源码构建

```powershell
git clone https://github.com/jianjieyiban/JJYB-AI-ZhiJian.git
cd JJYB-AI-ZhiJian
py -3 -m pip install -r requirements.txt
py -3 scripts/check_system.py
```

### 启动

双击 `启动应用.bat`，或执行 `py -3 frontend\app.py`。

应用会尝试打开 PyWebView 桌面窗口。服务可用时也可访问 `http://127.0.0.1:5000`。

### 首次配置

1. 打开 **系统设置**：`/settings`。
2. 填写至少一个文本模型的 API Key、Base URL 与模型名。
3. 原创解说如需云端视觉分析，还需配置相应视觉模型。
4. 如需 AI 封面生成，在图片生成卡片中配置图像生成模型的 API。
5. 点击"测试连接"，只在真实连通后再开始任务。

> **模型配置隔离说明**：文本模型（LLM）、视觉模型（VLM）和图像生成模型的 API 配置完全独立，互不干扰。

---

## 项目结构

```text
JJYB_AI智剪/
├── frontend/                 Flask 应用入口、模板与静态资源
│   ├── app.py                Flask、SocketIO 与桌面窗口入口
│   ├── templates/            业务页面与设置页面
│   └── static/               公共脚本、Layui 与静态资源
├── backend/
│   ├── api/                  Flask Blueprint 路由模块
│   ├── engine/               音视频、分镜、同步、字幕和模型引擎
│   ├── services/             面向功能流程的业务编排
│   ├── prompts/              解说风格、文案质检与提示词
│   ├── database/             SQLite DatabaseManager
│   ├── config/               AI 配置模型
│   ├── utils/                路径、草稿包、日志等工具
│   ├── workers/              独立 Python 3.10 IndexTTS2 worker
│   └── assets/               字体、音频与图片资源
├── config/                   本地应用配置
├── resource/                 TransNetV2 权重与 ImageMagick 资源
├── models/index-tts/         IndexTTS2 源码与运行配置
├── uploads/                  运行时上传文件
├── output/                   成片、草稿包和其他输出
├── 开发文档/                 面向维护者的技术文档
├── scripts/                  开发调试脚本
├── requirements.txt          主程序 Python 依赖
├── 启动应用.bat              Windows 启动脚本
└── README.md                 项目说明
```

---

## 主要页面

| 页面 | 地址 | 用途 |
|---|---|---|
| 视频编辑器 | `/` | 项目时间线与基础编辑 |
| 原创解说 | `/commentary` | 分镜、文案、配音、拟人化同步、精选复刻、高级功能工作台 |
| 智能混剪 | `/remix` | 普通混剪与音乐卡点混剪 |
| AI 配音 | `/voiceover` | 常规 TTS、声音复刻、下载到指定目录 |
| AI 功能 | `/ai_features` | AI 配音、字幕生成、智能剪辑快捷入口 |
| 素材库 | `/materials` | 素材上传、分类、预览与管理 |
| 项目管理 | `/projects` | 项目查看与管理 |
| 系统设置 | `/settings` | API、模型与运行配置 |

---

## 关键 API

### 原创解说

| 方法 | 路径 | 功能 |
|---|---|---|
| POST | `/api/commentary/smart-segment` | 智能分镜 |
| POST | `/api/commentary/generate-script` | AI 生成解说文稿 |
| POST | `/api/commentary/optimize-script` | AI 优化文稿 |
| POST | `/api/commentary/generate-voices` | 生成分段配音 |
| POST | `/api/commentary/puppet-sync` | 拟人化同步 |
| POST | `/api/commentary/process` | 一键处理解说全流程 |
| GET | `/api/commentary/result/<project_id>` | 获取解说结果 |
| POST | `/api/commentary/export-jianying-draft` | 导出剪映草稿 |

### 智能混剪

| POST | `/api/remix/smart-segment` | 批量分镜 |
| POST | `/api/remix/general-mode` | 普通混剪 |
| POST | `/api/remix/music-beat` | 音乐卡点混剪 |
| GET | `/api/remix/progress/<task_id>` | 查询混剪进度 |
| POST | `/api/remix/export-jianying-draft` | 导出草稿包 |

### AI 配音

| GET | `/api/voiceover/voices` | 获取音色列表 |
| POST | `/api/voiceover/generate` | 生成配音 |
| POST | `/api/voiceover/batch-generate` | 批量生成 |
| GET | `/api/voiceover/clone-engines` | 获取克隆引擎状态 |
| POST | `/api/voiceover/clone-generate` | 生成克隆配音 |

### AI 封面生成

| POST | `/api/cover/generate` | 生成封面 |
| GET | `/api/cover/history` | 获取封面历史 |

### 高级功能

| GET | `/api/advanced/narration-styles` | 获取解说风格列表 |
| POST | `/api/advanced/script-purify` | AI 提纯文案 |
| POST | `/api/advanced/highlight-extract` | 高光提取 |
| POST | `/api/advanced/script-doctor/diagnose` | 文案质检 |
| POST | `/api/advanced/curated-remake/extract-script` | 提取爆款文案 |
| POST | `/api/advanced/curated-remake/rewrite-script` | AI 改写文案 |
| POST | `/api/advanced/export/multi-format` | 多格式导出 |

### 系统设置

| GET/POST | `/api/settings` | 获取/保存设置 |
| GET/POST | `/api/settings/api-config` | API 配置 |
| POST | `/api/settings/test-api` | 测试 API 连接 |

---

## 草稿包说明

"导出剪映草稿"会生成剪映原生草稿目录结构：

- 检测到剪映草稿目录时，直接写入原生格式，剪映专业版可自动扫描打开。
- 未检测到时，回退到 `output/jianying_drafts/` 目录，生成通用草稿包。

草稿包含以下轨道：
- **视频轨**：按配音段选取的镜头片段
- **配音轨**：TTS 生成的语音段
- **BGM 轨**：背景音乐（可选）
- **字幕轨**：逐段字幕文本

---

## 运行数据位置

| 路径 | 内容 | 说明 |
|---|---|---|
| `config/ai_config.json` | AI 模型配置（含 API Key） | 不提交，运行时生成 |
| `database/jjyb_ai.db` | 项目与素材记录 | 不提交 |
| `uploads/` | 上传视频、音频、参考音频 | 不提交 |
| `output/` | 成片、草稿包、预览、封面 | 不提交 |
| `temp/` | 可再生中间文件 | 可随时清理 |
| `logs/` | 本地运行日志 | 不提交 |

---

## 开发与验证

```powershell
# 环境检查
py -3 scripts/check_system.py

# 语法检查
py -3 -c "import ast; ast.parse(open('backend/services/commentary_service_enhanced.py', encoding='utf-8').read()); print('OK')"
```

提交前建议验证以下关键流程：

1. 原创解说（分镜→文稿→配音→同步→导出）
2. 普通混剪
3. 音乐卡点混剪
4. 常规配音
5. 克隆配音
6. 剪映草稿导出
7. 精选视频复刻
8. 文案质检
9. AI 封面生成
10. 断点恢复

---

## 文档

- [开发文档索引](开发文档/文档索引.md)
- [架构与运行机制](开发文档/JJYB_AI智剪_完整开发文档.md)
- [AI、分镜与渲染引擎](开发文档/JJYB_AI智剪_完整开发文档_Part2.md)
- [服务、API 与发布准备](开发文档/JJYB_AI智剪_完整开发文档_Part3.md)

---

## 常见问题

### FFmpeg 不可用
安装 FFmpeg 并将其目录加入 `PATH`，重新打开终端后执行 `ffmpeg -version` 验证。

### 模型/API 不能调用
- 检查 `/settings` 中的 Key、Base URL、模型名称。
- 确保在正确的配置卡片中填写（文本模型、视觉模型、图像模型三个独立卡片）。
- 使用"测试连接"确认服务端真实可达。

### 配音段提示未完成
- 检查 TTS 引擎是否正常（Edge TTS 需要网络）。
- 确认配音段的 `status` 字段是否为 `ready`。

### 拟人化同步失败
- 确认已完成智能镜头分割。
- 确认已生成至少一段配音。
- 检查 `logs/app.log` 中 `puppet_sync_commentary` 的日志。

### 剪映草稿导出失败
- 确认已完成拟人化同步（timeline 非空）。
- 后端会自动从项目 workbench 回填 timeline/audio_paths。

### 本地声音复刻未就绪
- 确认已安装 Python 3.10。
- 确认 `INDEXTTS_PYTHON` 指向 Python 3.10。
- 确认 `models/index-tts/checkpoints/` 模型权重齐全。

### 视频无法解码
- 检查视频文件完整性。
- 确认视频编码格式为常见格式（H.264、H.265、VP9 等）。

---

## 免责声明

- 本工具仅供个人合法使用，使用者需遵守当地法律法规。
- 使用声音复刻功能前必须取得参考音频权利人的明确授权。
- 请只对拥有合法权利的文本、视频、音乐与参考音频进行处理。
- 生成内容的版权归属由使用者自行判断和承担。
- 开发者不对使用本工具产生的任何法律责任负责。

---

## 版本历史

| 版本 | 日期 | 主要更新 |
|---|---|---|
| v3.1.0 | 2026-08-01 | 三处解说风格联动、10种钩子选择、配音段容错、音画同步兜底、剪映草稿导出修复 |
| v3.0.0 | 2026-07-31 | 全面重构原创解说流程、新增拟人化同步引擎、原片原声穿插 |
| v2.0 | 2026-07 | 新增 AI 封面生成、精选视频复刻、声音复刻 |
| v1.0 | 2026-06 | 初始版本：原创解说、智能混剪、AI 配音 |
