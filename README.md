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
- **AI 文案生成**：通过已配置的视觉/文本模型分析画面并生成解说文稿，支持 **12 种叙述风格**（默认、口语化、高能合辑、萌讲八道、直播带货、新闻联播、引导式、吐槽式、深度解析、慢节奏、影视解说、短剧漫剪）。
- **三处解说风格联动**：
  - **风格预设仪表板**：12种视频类型一键套用（影视解说/动漫解说/短剧漫剪/综艺娱乐/体育高光/综合通用/纪录片/科技数码/美食种草/旅行教育/自定义），自动同步文稿风格、情感基调、解说类型、钩子类型和写作人格。
  - **文稿风格配置**：12种文稿风格（正式/幽默/激情/悬疑/情感/平和/纪录片/中二热血/爽点密集/感官细节/叙事白描/钩子反转）+ 4种情感基调 + 12种解说类型 + 10种开头钩子手动选择。
  - **写作人格面板**：12种写作人格 + 4种叙事视角（第三人称/第一人称/内心独白/客观）+ 5档语速 + 4档情感浓度。
- **分段配音**：将文稿拆分为语音段，支持 Edge TTS、Azure、gTTS、火山引擎、IndexTTS2 克隆等多种 TTS 引擎。
- **拟人化同步**：`PuppetSyncEngine` 逐段匹配镜头与配音，支持直连、慢放、末帧定格、截取高光、短语音合并五种策略。
- **原片原声穿插**：支持按成片比例或按段落间隔穿插原片原声，可控制音量比例。
- **目标时长**：支持设置目标时长，同步引擎根据目标时长调整片段选取和速度。
- **文案质检**：六维评分诊断（吸引力、节奏、信息量、情感、流畅度、原创性）。
- **断点恢复**：长任务支持断点保存与恢复，流式生成实时反馈进度。
- **剪映草稿导出**：一键导出剪映原生草稿（含视频轨、配音轨、BGM轨、字幕轨），剪映专业版可直接扫描打开。

### 2. 智能混剪

两种混剪模式，适配不同创作场景：

- **普通模式**：先批量分镜，再按画面评分选择高光镜头；可根据配音时长做逐段音画匹配。
- **音乐卡点模式**：使用 `librosa` 分析 BGM 节拍和能量，支持密集（dense）、适中（medium）、稀疏（sparse）三种卡点密度；高潮段可适度慢放。
- **目标时长**：混剪支持目标时长设置，节拍引擎根据目标时长计算最大节拍数。
- 两种模式均支持输出视频及导出剪映草稿包。
- 支持 Edge TTS、Azure、gTTS、火山引擎、IndexTTS2 克隆等多种 TTS 引擎。

### 3. AI 配音与声音复刻

- **常规配音**：Edge TTS、gTTS、pyttsx3、Azure TTS、火山引擎 TTS、可选 Coqui TTS。
- **声音复刻**：
  - **IndexTTS2 本地 worker**：独立 Python 3.10 环境，本地运行，隐私安全。
  - **云端服务**：Fish Audio、MiniMax、火山引擎、Azure Custom Voice。
- **批量生成**：支持批量文案配音，逐行生成并展示结果。
- **下载到指定目录**：可将生成的音频复制到用户指定的文件夹。
- 使用克隆语音前必须取得参考音频权利人的明确授权；接口要求 `consent=true`。

### 4. AI 封面生成

- **多模型支持**：DALL-E 3、通义万相、文心一格、腾讯混元、智谱 CogView、豆包生图、MiniMax、SiliconFlow、OpenRouter，以及自定义 OpenAI 兼容图像生成网关。
- **自定义网关**：支持任意 OpenAI 兼容的图像生成 API（如 OneAPI、NewAPI、本地 SD WebUI 等），API Key 独立于文本/视觉模型配置。
- **风格与尺寸**：支持多种尺寸模板和风格标签，可自定义生成参数。
- **本地模板兜底**：云端模型不可用时自动切换本地模板生成，并明确提示原因。
- **封面管理**：封面历史记录、预览、删除。

### 5. 视频编辑器

- **时间线编辑**：多轨道编辑，支持视频、音频、字幕轨道。
- **播放控制**：播放/暂停、停止、速度调节（0.5x-2x）、静音、音量调节。
- **滤镜效果**：grayscale、sepia、blur、invert、vintage 等多种滤镜。
- **转场特效**：fade、slide、zoom、wipe、dissolve 转场效果。
- **AI 工具**：AI 配音、自动字幕、智能剪辑、画质增强、画面分析。

### 6. 素材库管理

- 素材上传、分类（视频/音频/图片/文字）、预览、搜索、排序。
- 支持拖拽上传和文件选择。
- 收藏功能（基于 localStorage）。
- 素材添加到项目、下载、删除。

### 7. 项目管理

- 项目创建、查看、编辑、删除。
- 模板创建（视频编辑、AI剪辑、AI配音、混剪）。
- 批量操作（全选、批量删除）。
- 筛选与搜索（按类型、状态、名称）。
- 活动时间线记录。

---

## 技术栈

| 类别 | 技术 |
|---|---|
| **桌面与 Web** | Flask、Flask-SocketIO、PyWebView、HTML/JavaScript/Layui |
| **数据存储** | SQLite（`backend/database/db_manager.py`） |
| **视频处理** | FFmpeg/ffprobe、OpenCV、MoviePy、ImageMagick |
| **音频处理** | librosa、SoundFile、Pydub |
| **TTS 引擎** | Edge TTS、gTTS、pyttsx3、Azure TTS、火山引擎、Coqui TTS（可选） |
| **声音复刻** | IndexTTS2（本地）、Fish Audio、MiniMax、火山引擎、Azure Custom Voice |
| **视觉与 AI** | 可配置云端模型适配器、PyTorch、YOLO、faster-whisper |
| **ASR 识别** | faster-whisper、Whisper（可选）、FunASR（可选） |
| **图像生成** | DALL-E 3、通义万相、文心一格、腾讯混元、智谱 CogView、豆包生图、SiliconFlow、自定义 OpenAI 兼容网关 |
| **云端文本模型** | OpenAI、Claude、Gemini、Kimi、讯飞星火、通义千问、文心一言、ChatGLM、DeepSeek、OpenRouter、SiliconFlow、豆包 |

---

## 环境要求

- **操作系统**：Windows 10/11
- **Python**：主程序推荐 Python 3.10–3.13
- **FFmpeg**：必须已安装并可从命令行调用（`ffmpeg -version` 和 `ffprobe -version` 均可正常输出）
- **ImageMagick**（可选）：用于封面合成等图像处理，已内置在 `resource/imageMagick/` 目录
- **可选**：NVIDIA CUDA 环境，用于部分深度学习任务加速（分镜、YOLO、Whisper）
- **IndexTTS2**：单独使用 Python 3.10 环境，依赖见 `models/index-tts/pyproject.toml`

---

## 快速开始

### 方式一：Release 包（推荐）

1. 从 [GitHub Releases](https://github.com/jianjieyiban/JJYB-AI-ZhiJian/releases) 下载最新版本的 `JJYB_AI智剪-vX.X.X.zip`。
2. 解压到任意目录。
3. 安装 Python 依赖：`py -3 -m pip install -r requirements.txt`。
4. 安装 [FFmpeg](https://ffmpeg.org/download.html) 并加入 PATH。
5. 双击 `启动应用.bat` 启动。

### 方式二：从源码构建

```powershell
# 1. 克隆仓库
git clone https://github.com/jianjieyiban/JJYB-AI-ZhiJian.git
cd JJYB-AI-ZhiJian

# 2. 安装主程序依赖
py -3 -m pip install -r requirements.txt

# 3. 检查环境
py -3 scripts/check_system.py
```

### 安装 FFmpeg

FFmpeg 是视频渲染、时长探测和音画同步的必需系统依赖：

1. 从 [FFmpeg 官网](https://ffmpeg.org/download.html) 下载。
2. 解压到任意目录（如 `C:\ffmpeg`）。
3. 将 `C:\ffmpeg\bin` 添加到系统环境变量 `PATH`。
4. 验证：

```powershell
ffmpeg -version
ffprobe -version
```

### 启动

双击 `启动应用.bat`，或在项目根目录执行：

```powershell
py -3 frontend\app.py
```

应用会尝试打开 PyWebView 桌面窗口。服务可用时也可访问 `http://127.0.0.1:5000`。

退出时关闭窗口，或在启动终端按 `Ctrl + C`。

### 首次配置

1. 打开 **系统设置**：`/settings`。
2. 填写至少一个文本模型的 API Key、Base URL 与模型名（推荐使用"自定义 OpenAI 兼容"）。
3. 原创解说如需云端视觉分析，还需配置相应视觉模型（独立于文本模型）。
4. 如需 AI 封面生成，在图片生成卡片中配置图像生成模型的 API（独立于文本/视觉模型）。
5. 点击页面的"测试连接"，只在真实连通后再开始任务。
6. 需要云端声音复刻时，填写 Fish Audio、MiniMax、火山引擎或 Azure 的对应凭据。
7. 未配置的引擎会显示为未就绪，不影响其他功能使用。

> **模型配置隔离说明**：文本模型（LLM）、视觉模型（VLM）和图像生成模型的 API 配置完全独立，互不干扰。设置页面上有三个独立的配置卡片，请确保在正确的卡片中填写对应模型的 API Key。

---

## 常用流程

### 原创解说

1. 进入 `/commentary` 并选择视频。
2. **选择解说风格预设**（第1处）：点击风格卡片一键套用全套参数。
3. **调整文稿风格**（第2处）：可修改文稿风格、情感基调、解说类型、开头钩子。
4. 使用"智能镜头分割"生成镜头列表。
5. 生成或输入解说文稿，并生成配音段。
6. **微调写作人格**（第3处）：选择写作人格、叙事视角、语速、情感浓度。
7. 使用"拟人化同步"让镜头、配音和字幕逐段对齐。
8. 导出成片，或点击"导出剪映草稿"。

同步规则会按实际时长选择直连、慢放、定格、截取高光或短语音合并。智能分析失败时会明确报错，不会伪造分析结果。

### 精选视频复刻

1. 在原创解说界面展开"精选视频复刻"面板。
2. 导入爆款解说视频，点击"提取爆款文案"（ASR 识别）。
3. 配置改写参数，点击"AI 改写"生成原创文案。
4. 查看相似度和原创度评分，确认文案满足原创要求。
5. 进行场景匹配，导出存疑清单（如有）。
6. 使用改写后的文案继续原创解说流程。

### 智能混剪

1. 进入 `/remix`，每行输入一个视频路径或使用已有上传素材。
2. 选择模式：
   - **普通模式**：根据镜头评分与配音进行混剪。
   - **音乐卡点模式**：提供 BGM，选择 dense / medium / sparse 卡点密度，可启用高潮慢放。
3. 先执行智能分镜，再开始混剪。
4. 预览输出或导出草稿包。

### AI 配音与声音复刻

1. 进入 `/voiceover`，普通 TTS 可直接选择音色并生成。
2. 声音复刻区先刷新引擎状态，仅已就绪的引擎可选择。
3. 提供参考音频路径、文本和目标下载目录。
4. 勾选"我已获得参考音频权利人的授权"，再生成。

参考音频必须由你拥有或已获得明确授权；本地 IndexTTS2 参考音频需要位于 `uploads/` 目录内。

### AI 封面生成

1. 在原创解说界面的高级功能工作台中选择"AI 生图"标签。
2. 选择图像生成厂商（推荐"自定义 OpenAI 兼容"）。
3. 输入提示词，选择尺寸和风格。
4. 点击生成，等待云端模型返回（通常需要 60-120 秒）。
5. 系统会明确提示是否使用了云端模型或本地模板兜底。

---

## 配置说明

### 三类独立模型配置

项目支持三类独立的模型配置，互不干扰：

#### 文本模型（LLM）

用于文案生成、脚本优化、文案质检等文本任务。支持 14 种渠道：

| 渠道 | 默认模型 |
|---|---|
| custom_openai（推荐） | 用户自定义 |
| openai | gpt-5 |
| anthropic | claude-sonnet-5 |
| gemini | gemini-2.5-flash |
| kimi | kimi-k2.6 |
| spark | spark-v4 |
| qwen | qwen3-max |
| ernie | 用户自定义 |
| chatglm | glm-4.6 |
| deepseek | deepseek-chat |
| openrouter | qwen/qwen3-235b-a22b-instruct |
| siliconflow | Qwen/Qwen3-235B-A22B-Instruct |
| doubao | doubao-seed-1-6-250615 |

#### 视觉模型（VLM）

用于视频画面分析、场景识别。支持 8 种渠道：custom_vision（推荐）、gpt4v、claude_vision、gemini、qwen_vl、baidu、tencent、spark_vision。

#### 图像生成模型

用于 AI 封面生成。支持 10 种渠道：custom_openai（推荐）、openai、qwen、baidu、tencent、chatglm、doubao、minimax、siliconflow、openrouter。

> **重要**：三类模型的 API Key、Base URL 和模型名完全独立配置，不会互相干扰。请在设置页面的对应卡片中填写。

### 配置 IndexTTS2 本地声音复刻（可选）

本地 IndexTTS2 声音复刻使用独立 Python 3.10 worker：

1. 安装 Python 3.10。
2. 按 `models/index-tts/pyproject.toml` 安装依赖。
3. 下载模型权重到 `models/index-tts/checkpoints/` 目录。
4. 可选：设置环境变量 `INDEXTTS_PYTHON` 指向 Python 3.10 解释器路径。

---

## 项目结构

```text
JJYB_AI智剪/
├── frontend/                 Flask 应用入口、模板与静态资源
│   ├── app.py                Flask、SocketIO 与桌面窗口入口
│   ├── templates/            业务页面与设置页面
│   │   ├── base.html         基础模板
│   │   ├── index.html        视频编辑器
│   │   ├── commentary.html   原创解说（含三处风格联动+高级功能工作台）
│   │   ├── remix.html        智能混剪
│   │   ├── voiceover.html    AI 配音
│   │   ├── settings.html     系统设置
│   │   ├── materials.html    素材库
│   │   ├── projects.html     项目管理
│   │   └── ...               其他页面
│   └── static/               公共脚本、Layui 与静态资源
├── backend/
│   ├── api/                  Flask Blueprint 路由模块
│   │   ├── commentary_api.py           原创解说路由
│   │   ├── commentary_routes_enhanced.py 原创解说增强路由
│   │   ├── remix_api.py                混剪路由
│   │   ├── voiceover_api.py            配音路由
│   │   ├── cover_api.py                AI 封面生成路由
│   │   ├── advanced_routes.py          高级功能路由
│   │   ├── settings_api.py             设置路由
│   │   └── ...                         其他路由
│   ├── engine/               音视频、分镜、同步、字幕和模型引擎
│   │   ├── smart_shot_segmenter.py    智能镜头分割
│   │   ├── puppet_sync_engine.py      拟人化同步引擎
│   │   ├── beat_remix_engine.py       音乐卡点混剪引擎
│   │   ├── script_generator.py        脚本生成
│   │   ├── tts_engine.py              TTS 引擎
│   │   ├── video_composer.py          视频合成
│   │   ├── sync_engine.py             三同步引擎
│   │   └── ...                        其他引擎
│   ├── services/             面向功能流程的业务编排
│   │   ├── commentary_service.py          解说服务
│   │   ├── commentary_service_enhanced.py 解说增强服务（全流程编排）
│   │   ├── remix_service.py               混剪服务
│   │   ├── voiceover_service.py           配音服务
│   │   └── ...                             其他服务
│   ├── prompts/              解说风格、文案质检与提示词
│   │   ├── narration_styles.py    12 种解说写作风格定义
│   │   ├── narration_prompts.py   解说提示词（含10种钩子+7种模式指引）
│   │   └── script_doctor.py       文案质检六维评分提示词
│   ├── database/             SQLite DatabaseManager
│   ├── config/               AI 配置模型
│   ├── utils/                路径、草稿包、日志等工具
│   ├── workers/              独立 Python 3.10 IndexTTS2 worker
│   └── assets/               字体、音频与图片资源
├── config/                   本地应用配置
│   ├── config.yaml           应用配置文件
│   ├── censor_words.json     违禁词库
│   └── ai_config.json        AI 模型配置（运行时生成，含 API Key，不提交）
├── resource/                 TransNetV2 权重与 ImageMagick 资源
├── models/index-tts/         IndexTTS2 源码与运行配置（独立环境）
├── uploads/                  运行时上传文件
├── output/                   成片、草稿包和其他输出
├── 开发文档/                 面向维护者的技术文档
├── scripts/                  开发调试脚本
│   ├── check_system.py       环境检查脚本
│   └── start_flask.py        Flask 启动脚本
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

| 方法 | 路径 | 功能 |
|---|---|---|
| POST | `/api/remix/smart-segment` | 批量分镜 |
| POST | `/api/remix/general-mode` | 普通混剪 |
| POST | `/api/remix/music-beat` | 音乐卡点混剪 |
| GET | `/api/remix/progress/<task_id>` | 查询混剪进度 |
| POST | `/api/remix/export-jianying-draft` | 导出草稿包 |

### AI 配音

| 方法 | 路径 | 功能 |
|---|---|---|
| GET | `/api/voiceover/voices` | 获取音色列表 |
| POST | `/api/voiceover/generate` | 生成配音 |
| POST | `/api/voiceover/batch-generate` | 批量生成 |
| GET | `/api/voiceover/clone-engines` | 获取克隆引擎状态 |
| POST | `/api/voiceover/clone-generate` | 生成克隆配音 |

### AI 封面生成

| 方法 | 路径 | 功能 |
|---|---|---|
| POST | `/api/cover/generate` | 生成封面 |
| GET | `/api/cover/history` | 获取封面历史 |

### 高级功能

| 方法 | 路径 | 功能 |
|---|---|---|
| GET | `/api/advanced/narration-styles` | 获取解说风格列表 |
| POST | `/api/advanced/script-purify` | AI 提纯文案 |
| POST | `/api/advanced/highlight-extract` | 高光提取 |
| POST | `/api/advanced/script-doctor/diagnose` | 文案质检 |
| POST | `/api/advanced/curated-remake/extract-script` | 提取爆款文案 |
| POST | `/api/advanced/curated-remake/rewrite-script` | AI 改写文案 |
| POST | `/api/advanced/export/multi-format` | 多格式导出 |

### 系统设置

| 方法 | 路径 | 功能 |
|---|---|---|
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

**症状**：渲染、时长探测或音画同步失败。

**处理**：安装 FFmpeg 并将其目录加入 `PATH`，重新打开终端后执行 `ffmpeg -version` 验证。

### 模型/API 不能调用

- 检查 `/settings` 中的 Key、Base URL、模型名称。
- 确保在正确的配置卡片中填写（文本模型、视觉模型、图像模型三个独立卡片）。
- 使用"测试连接"确认服务端真实可达。
- 查看 `logs/app.log`，不要把日志中的敏感信息公开。

### 配音段提示未完成

- 检查 TTS 引擎是否正常（Edge TTS 需要网络）。
- 确认配音段的 `status` 字段是否为 `ready`。
- 查看浏览器控制台是否有 `refreshPsReadyCheck` 的详细日志。

### 拟人化同步失败

- 确认已完成智能镜头分割。
- 确认已生成至少一段配音。
- 检查 `logs/app.log` 中 `puppet_sync_commentary` 的日志。
- 后端已对 shots/voices 格式做兼容处理，如仍失败请检查输入数据。

### 剪映草稿导出失败

- 确认已完成拟人化同步（timeline 非空）。
- 后端会自动从项目 workbench 回填 timeline/audio_paths。
- 检查剪映草稿目录是否可写。

### 本地声音复刻未就绪

- 确认已安装 Python 3.10。
- 确认 `INDEXTTS_PYTHON`（如已设置）指向 Python 3.10。
- 确认 `models/index-tts/checkpoints/` 模型权重齐全。
- 在 AI 配音页面刷新克隆引擎状态。

### 视频无法解码

- 检查视频文件完整性。
- 确认视频编码格式为常见格式（H.264、H.265、VP9 等）。
- 查看 OpenCV/FFmpeg 日志获取详细错误信息。

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
