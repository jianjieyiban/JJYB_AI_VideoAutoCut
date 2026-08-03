# 架构与运行机制

## 1. 定位与边界

JJYB_AI智剪是本地桌面优先的 AI 视频创作工具。`frontend/app.py` 提供 Flask 服务和 PyWebView 窗口；所有项目、素材与输出默认保存在本机。

本仓库不承诺特定云端模型、外部 TTS 或剪映私有工程兼容性。可用能力由实际安装的依赖、配置的服务凭据和本地资源决定。

## 2. 目录职责

```text
JJYB_AI智剪/
├── frontend/                 Flask 应用入口、模板与静态资源
│   ├── app.py                Flask、SocketIO 与桌面窗口入口
│   ├── templates/            业务页面与设置页面
│   └── static/               公共脚本、Layui 与静态资源
├── backend/
│   ├── api/                  Flask Blueprint 路由（23 个模块）
│   ├── engine/               音视频、分镜、同步、字幕和模型引擎（24 个模块）
│   ├── services/             面向功能流程的业务编排（9 个模块）
│   ├── prompts/              解说风格、文案质检与提示词
│   ├── database/             SQLite DatabaseManager
│   ├── config/               后端路径与 AI 配置模型
│   ├── core/                 全局状态管理
│   ├── workers/              独立 Python 3.10 IndexTTS2 worker
│   ├── utils/                路径、草稿包、日志等工具
│   └── assets/               字体、音频与图片资源
├── config/                   本地应用配置（config.yaml、censor_words.json、ai_config.json）
├── resource/                 TransNetV2 权重与 ImageMagick 资源
├── models/index-tts/         IndexTTS2 源码与运行配置（独立环境）
├── uploads/                  运行时上传文件
├── output/                   成片、草稿包和其他输出
│   └── covers/               AI 生成的封面图片
├── temp/                     可再生处理临时文件
├── logs/                     运行日志
├── 开发文档/                 面向维护者的技术文档
├── scripts/                  开发调试脚本
├── requirements.txt          主程序 Python 依赖
├── 启动应用.bat              Windows 启动脚本
└── README.md                 项目说明
```

## 3. 启动链路

1. `启动应用.bat` 或 `py -3 frontend/app.py` 启动应用。
2. `frontend/app.py` 初始化 Flask、SocketIO、数据库管理器、业务服务和 API 路由。
3. PyWebView 可用时创建桌面窗口；HTTP 服务默认监听本地端口。
4. 页面以 `fetch` 调用 `/api/*` 接口，长任务可通过 SocketIO 或任务状态接口反馈进度。

启动前可运行：

```powershell
py -3 scripts/check_system.py
```

该命令用于检查环境，不会自动修复依赖、FFmpeg 或模型配置。

## 4. 前端页面

| 模板 | 页面 | 路径 | 职责 |
|---|---|---|---|
| `index.html` | 视频编辑器 | `/` | 时间线、基础编辑、播放控制、滤镜转场特效、AI工具 |
| `commentary.html` | 原创解说 | `/commentary` | 分镜、文稿、配音、拟人化同步、精选复刻、草稿包导出 |
| `remix.html` | 智能混剪 | `/remix` | 普通模式、音乐卡点模式、草稿包导出 |
| `voiceover.html` | AI 配音 | `/voiceover` | 常规 TTS、声音复刻、批量生成、下载 |
| `ai_features.html` | AI 功能 | `/ai_features` | AI 配音、字幕生成、智能剪辑快捷入口 |
| `materials.html` | 素材库 | `/materials` | 素材上传、分类、预览与管理 |
| `projects.html` | 项目管理 | `/projects` | 项目查询、模板创建与维护 |
| `settings.html` | 系统设置 | `/settings` | API、模型与外部引擎配置 |
| `home.html` | 首页 | `/home` | 功能导航与状态概览 |
| `mode_select.html` | 模式选择 | `/mode` | 创作模式选择入口 |

## 5. 后端分层

### API 层

`backend/api/` 接收 HTTP 请求、进行参数校验并调用服务层。核心蓝图包括：

- `commentary_api.py` - 原创解说基础路由
- `commentary_routes_enhanced.py` - 原创解说增强路由
- `remix_api.py` - 智能混剪
- `voiceover_api.py` - AI 配音
- `local_voice_clone_api.py` - 本地声音复刻
- `advanced_routes.py` - 高级功能（文案质检、AI去重、精选复刻、断点恢复等）
- `jianying_draft_api.py` - 剪映草稿导出
- `material_routes.py` - 素材管理
- `project_api.py` - 项目管理
- `upload_routes.py` - 文件上传
- `settings_api.py` - 系统设置
- `video_api.py` - 视频编辑
- `subtitle_api.py` - 字幕生成
- `effects_api.py` - 滤镜与特效
- `cleanup_api.py` - 清理操作
- `task_api.py` - 任务管理
- `auto_clip_routes.py` - 智能剪辑
- `ai_api.py` - AI 接口
- `config_routes.py` - 配置管理
- `hardware_capability_api.py` - 硬件能力
- `notification_api.py` - 通知管理
- `export_api.py` - 导出管理
- `test_api.py` - 测试连接

### 服务层

- `CommentaryService`：原创解说流程、分镜、文稿配音、同步与草稿包。
- `CommentaryServiceEnhanced`：原创解说增强能力（高级配置、时间轴优化等）。
- `RemixService`：普通混剪、音乐卡点混剪、镜头池和草稿包。
- `VoiceoverService`：常规 TTS、云端/外部声音复刻、下载到指定目录。
- `LocalVoiceCloneService`：本地 IndexTTS2 worker 的环境检测与调用。
- `TaskService`：任务状态与进度协作。
- `HardwareCapabilityService`：本地硬件能力信息。
- `CheckpointService`：断点恢复与流式生成。

### 引擎层

- `smart_shot_segmenter.py`：智能镜头边界检测与镜头评分。
- `puppet_sync_engine.py`：逐段镜头、配音、字幕同步与 FFmpeg 渲染。
- `beat_remix_engine.py`：BGM 节拍、能量与分段分析。
- `scene_detector.py`、`scene_scorer.py`：场景检测与评分。
- `curated_remake_engine.py`：精选视频复刻（文案提取、AI改写、场景匹配）。
- `ai_dedup_engine.py`：AI 智能去重。
- `sync_engine.py`：音画同步与节拍检测。
- `tts_engine.py`、`tts_provider.py`：语音合成引擎。
- `asr_engine.py`：语音识别（Whisper、FunASR、faster-whisper）。
- `subtitle_generator.py`：字幕生成。
- `vision_analyzer.py`：视觉分析。
- `video_processor.py`、`video_composer.py`、`video_clipper.py`：视频处理。
- `audio_processor.py`、`audio_normalizer.py`：音频处理。
- `multi_format_exporter.py`：多格式时间线导出。
- `multi_model_adapter.py`：多模型适配器。
- `script_generator.py`：文案生成。
- `video_analyzer.py`：视频分析。
- `auto_clip_controller.py`：智能剪辑控制器。

## 6. 数据与运行目录

项目数据由 SQLite 的 `DatabaseManager` 管理，数据库默认位于 `database/jjyb_ai.db`。项目配置可保存统一时间线 `config.tracks`，供编辑器与草稿包导出复用。

运行目录说明：

| 目录 | 用途 | 清理原则 |
|---|---|---|
| `uploads/` | 用户上传素材、参考音频 | 仅在确认不再被项目引用后清理 |
| `temp/` | 分段、关键帧与临时渲染 | 可安全清理可再生中间文件 |
| `output/` | 成片、预览、草稿包 | 先归档或下载用户成果再清理 |
| `logs/` | 运行日志 | 发布前清理内容，保留 `.gitkeep` |

## 7. 配置

主要配置位置：

- `config/config.yaml`：应用运行配置。
- `config/ai_config.json`：模型与 API 配置；不得提交真实 Key。
- `backend/config/ai_config.py`：配置对象与默认字段。
- `backend/config/paths.py`：路径常量定义。
- `/settings`：可视化配置入口。

外部 API 采用"Key + Base URL + 模型名"方式配置，支持官方服务或兼容协议的中转服务。调用前应使用设置页的连接测试验证实际可达性。

自定义 OpenAI 兼容服务支持文本模型与视觉模型独立配置（`custom_openai_model` / `custom_openai_vision_model`），共用同一组 Key 与 Base URL。若模型支持多模态输入，两个字段可填写相同模型 ID；也可分别指定不同模型以适配网关能力差异。运行时视觉分析优先取 `custom_openai_vision_model`，未设置时回退到 `custom_openai_model`。

### 模型配置隔离

项目支持三类独立的模型配置，互不干扰，分别对应 `backend/config/ai_config.py` 中的三个配置类：

| 类型 | 配置类 | 用途 | 独立字段 |
|---|---|---|---|
| 文本模型 (LLM) | `LLMConfig` | 文案生成、脚本优化、文案质检 | `custom_openai_api_key` / `base_url` / `model` |
| 视觉模型 (VLM) | `VisionConfig` | 视频画面分析、场景识别 | `custom_openai_api_key` / `base_url` / `vision_model` |
| 图像生成 | `ImageGenConfig` | AI 封面生成 | `custom_openai_api_key` / `base_url` / `model` |

三类模型的 API Key、Base URL 和模型名完全独立存储和读取，不会互相覆盖或回退。设置页面有三个独立的配置卡片，分别对应三类模型，便于针对不同任务使用不同的服务商或网关。

支持的云端模型服务商：

- OpenAI（含兼容协议中转）
- Anthropic Claude
- Google Gemini
- 月之暗面 Kimi
- 讯飞星火
- 通义千问
- 百度文心一言
- 智谱 ChatGLM
- DeepSeek
- OpenRouter
- SiliconFlow
- 豆包

## 8. 安全与真实结果策略

- 分镜、视觉分析、配音和渲染失败时，应返回明确错误，而不是生成虚构结果。
- 声音复刻需要权利人授权，API 要求显式确认 `consent=true`。
- 不应把 API Key、上传素材、数据库、日志或导出内容提交到公开仓库。
- FFmpeg 命令处理外部文件时必须保留路径校验与输出目录约束。
- 系统设置中的 API Key 通过本地配置文件存储，提交前必须检查并清除敏感信息。

## 9. 全局状态管理

`backend/core/global_state.py` 提供全局状态管理，统一管理：

- 多模型管理器（MultiModelManager）
- 数据库管理器（DatabaseManager）
- 任务服务（TaskService）
- 配置管理器（ConfigManager）
- SocketIO 实例

各 API 蓝图通过 `get_global_state()` 获取共享实例，避免循环导入和重复初始化。

下一篇：[AI、分镜与渲染引擎](JJYB_AI智剪_完整开发文档_Part2.md)。
