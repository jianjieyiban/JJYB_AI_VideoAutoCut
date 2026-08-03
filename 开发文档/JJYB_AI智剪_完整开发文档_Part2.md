# AI、分镜与渲染引擎

## 1. 智能镜头分割

实现文件：`backend/engine/smart_shot_segmenter.py`。

`SmartShotSegmenter` 以一个分割画面作为一个可编辑镜头，不设置人为的分析帧上限。处理顺序：

1. 尝试加载可用的 TransNetV2 实现和项目权重 `resource/models/transnetv2-weights/`。
2. 若深度分镜运行环境不可用，明确使用 OpenCV 方案，不伪称使用了 TransNetV2。
3. OpenCV 方案通过画面内容差异与颜色直方图相似度共同判断边界。
4. 合并过短镜头，计算运动、亮度和色彩评分，并可导出关键帧缩略图。

核心接口：

```text
POST /api/commentary/smart-segment
POST /api/remix/smart-segment
```

常见字段包括 `video_path` / `video_paths`、`threshold`、`min_scene_len_sec`、`use_transnetv2`、`max_shots`。`max_shots` 为 `null` 时表示不做数量限制。

## 2. 拟人化音画字幕同步

实现文件：`backend/engine/puppet_sync_engine.py`。

`PuppetSyncEngine` 以"一个主要画面匹配一段配音"为目标，按照实际镜头和音频时长决定策略：

| 策略 | 使用情形 |
|---|---|
| `direct` | 镜头与音频时长接近 |
| `slow_down` | 镜头较短且在允许变速范围内 |
| `freeze` | 仅靠慢放仍不足时，慢放后以末帧定格补足 |
| `cut_highlight` | 镜头较长时截取关键中段 |
| `merge` | 极短配音与相邻段合并，共用一个画面 |

当前常量：极短配音阈值约 1.2 秒；变速限制为 0.25x 至 2.0x。渲染使用 FFmpeg 的 `setpts`、帧提取和拼接能力。

接口：

```text
POST /api/commentary/generate-voices
POST /api/commentary/puppet-sync
```

`generate-voices` 将文稿拆成语音段；`puppet-sync` 接收视频、镜头列表、语音段和可选 BGM/字幕路径，返回时间线及可选渲染结果。

### 目标时长

原创解说和混剪均支持目标时长设置：

- **原创解说**：`target_duration_seconds` 传入 `PuppetSyncEngine`，同步引擎根据目标时长调整片段选取和速度；生成后做实际时长与目标时长的对比校验。前端通过 `updateCommentaryDurationUI` 设置 `window.commentaryTargetSeconds`，传递给 `/api/commentary/create` 和 `/api/commentary/process`。

- **混剪**：`target_duration` 传入 `BeatRemixEngine`，节拍引擎根据目标时长计算最大节拍数。前端通过 `updateRemixDurationUI` 设置目标时长，传递给 `/api/remix/generate`、`/api/remix/general-mode`、`/api/remix/music-beat` 等端点。

## 3. 原创解说流程

实现文件：`backend/services/commentary_service.py`、`backend/services/commentary_service_enhanced.py` 与 `backend/api/commentary_api.py`、`backend/api/commentary_routes_enhanced.py`。

推荐流程：

1. 上传或选择视频。
2. 执行智能镜头分割，建立后续拟人化同步使用的镜头池。
3. 通过已配置云端视觉模型获取画面理解，并生成或人工编辑解说文稿。
4. 生成逐段配音；最终成片前必须确认每一段都有有效音频文件和真实时长。
5. 可选设置原片原声穿插策略。系统先以配音时长匹配解说镜头，再从未分配给解说的镜头中按比例或间隔插入原声，解说和原声不会重叠。
6. 执行拟人化同步成片，生成统一的画面、配音、原声和字幕时间线。
7. 基于该时间线渲染成片或导出草稿包/多格式时间线。

“快速自动成片”仅用于基础三同步预览，不应用拟人化逐段时间线和原声穿插策略，不能替代第 6 步的最终精剪。

### TTS 引擎支持

原创解说支持以下 TTS 引擎：

- Edge TTS（默认，多种中文音色）
- Azure TTS（已配置凭据时）
- gTTS（Google 翻译 TTS）
- 火山引擎 TTS（已配置凭据时）
- IndexTTS2 本地克隆（已就绪时）

引擎名称归一化：`indextts2`/`IndexTTS`/`index-tts2` → `indextts2`；`volcano`/`volcano-tts` → `volcano`；`azure-tts` → `azure`。

### 高级功能

原创解说界面集成的 JJYB-ZJ 高级功能：

- **解说风格**：12 种叙述风格（电影解说、纪录片、知识科普等）
- **文案质检**：六维评分诊断（吸引力、节奏、信息量、情感、流畅度、原创性）
- **AI 提纯文案**：自动去除非解说词内容
- **覆盖审计**：检查文案与视频的时间覆盖情况
- **AI 智能去重**：检测并去除重复内容
- **智能穿插原片**：自动插入原片素材
- **精选视频复刻**：从爆款视频提取文案并改写为原创
- **断点恢复**：流式生成与断点管理
- **多格式导出**：支持多种时间线格式

模型调用失败、视频无法解码、FFmpeg 不可用时会返回错误；系统不会用虚构的视觉分析或文案覆盖失败状态。

## 4. 智能混剪

实现文件：`backend/services/remix_service.py`、`backend/engine/beat_remix_engine.py` 与 `backend/api/remix_api.py`。

### 普通模式

`POST /api/remix/general-mode`

- 批量智能分镜。
- 按镜头评分选择高光镜头。
- 有配音时使用拟人化同步引擎安排逐段时长；允许按流程需要复用镜头池。
- 可选渲染并返回时间线、片段数和输出路径。

### 音乐卡点模式

`POST /api/remix/music-beat`

- 对 BGM 使用 `librosa` 提取节拍、强拍、能量和音乐分段。
- `dense` 使用全部节拍；`medium` 以每两拍取点；`sparse` 主要使用强拍。
- 每个卡点匹配一个高光或名场面；对高潮区可使用约 0.7x 慢放。
- 按节拍间隔裁剪或慢放镜头，尽量避免相邻镜头重复并保持连贯。

该模式的卡点效果取决于 BGM 的节拍可检测性和可用镜头数量，不能保证对任何素材都生成同等质量结果。

### TTS 引擎支持

混剪界面支持与原创解说相同的 TTS 引擎（Edge TTS、Azure、gTTS、火山引擎、IndexTTS2 克隆）。选择 IndexTTS2 时会显示参考音频上传和授权确认面板。

## 5. TTS 与声音复刻

### 常规 TTS

实现：`backend/engine/tts_engine.py`、`backend/engine/tts_provider.py`、`backend/services/voiceover_service.py`。

可用引擎由环境与设置决定：

- Edge TTS
- gTTS
- pyttsx3（离线）
- Azure TTS（已配置凭据时）
- 火山引擎 TTS（已配置凭据时）
- Coqui TTS（可选安装）

常规配音通过 `/api/voiceover/generate` 或 `/api/voiceover/generate-and-download` 调用。服务会记录请求引擎、实际使用引擎和回退状态。

### 本地 IndexTTS2 声音复刻

实现：`backend/services/local_voice_clone_service.py`、`backend/workers/index_tts_worker.py`、`backend/api/local_voice_clone_api.py`。

- worker 必须由 Python 3.10 运行；可通过 `INDEXTTS_PYTHON` 指定解释器。
- 参考音频必须位于项目 `uploads/` 目录中。
- 运行前会检测 Python、模型目录、权重和依赖；未就绪时返回实际原因。
- 依赖以 `models/index-tts/pyproject.toml` 为准，不应与主程序环境混装。

接口：

```text
GET  /api/local-voice-clone/health      检查引擎状态
POST /api/local-voice-clone/generate    生成克隆语音
```

### 统一克隆语音入口

`VoiceoverService` 还可列出并调用以下配置型引擎：IndexTTS2、Fish Audio、MiniMax、火山引擎、Azure Custom Voice。

```text
GET  /api/voiceover/clone-engines
POST /api/voiceover/clone-generate
POST /api/voiceover/clone-generate-and-download
POST /api/voiceover/download-to-folder
```

云端克隆服务是否可用以 `/clone-engines` 返回的 `ready` 状态为准。调用任何克隆接口均须传 `consent=true`，确认已取得参考音频权利人授权。

## 6. 精选视频复刻

实现文件：`backend/engine/curated_remake_engine.py`、`backend/api/advanced_routes.py`。

精选视频复刻功能允许用户导入爆款解说视频和原片素材，通过 ASR 提取爆款文案，AI 改写为原创文案，再进行场景匹配，最终生成原创作品。

### 工作流程

1. **提取文案**：从爆款视频提取音频，使用 ASR（Whisper/FunASR/faster-whisper）识别解说文案。
2. **AI 改写**：通过 LLM 将爆款文案改写为原创文案，计算相似度和原创度评分。
3. **场景匹配**：将改写后的文案与原片素材进行场景匹配，支持多原片匹配和存疑高亮标记。

接口：

```text
POST /api/advanced/curated-remake/extract-script    提取爆款文案
POST /api/advanced/curated-remake/rewrite-script    AI改写文案
POST /api/advanced/curated-remake/match             场景匹配
POST /api/advanced/curated-remake/export-suspect    导出存疑清单
```

## 7. 文案质检与 AI 去重

### 文案质检

实现文件：`backend/prompts/script_doctor.py`、`backend/api/advanced_routes.py`。

六维评分诊断：

- 吸引力（Hook）
- 节奏（Rhythm）
- 信息量（Information）
- 情感（Emotion）
- 流畅度（Fluency）
- 原创性（Originality）

接口：

```text
POST /api/advanced/script-doctor/diagnose      诊断文案
POST /api/advanced/script-doctor/optimize      生成优化方案
GET  /api/advanced/script-doctor/dimensions    获取评分维度
```

### AI 智能去重

实现文件：`backend/engine/ai_dedup_engine.py`、`backend/api/advanced_routes.py`。

检测并去除视频中的重复内容，支持多种去重策略。

### AI 提纯文案

实现文件：`backend/prompts/narration_styles.py`、`backend/api/advanced_routes.py`。

自动去除文案中的非解说词内容，保留核心解说文本。

## 8. 字幕与草稿包

### 字幕

实现文件：`backend/engine/subtitle_generator.py`。

字幕引擎和配音时间线可用于生成 SRT 或渲染到视频。不同 ASR 后端（faster-whisper、可选 Whisper/FunASR）的可用性取决于安装的包与模型。

### 草稿包

实现：`backend/utils/jianying_detector.py`、`backend/engine/multi_format_exporter.py` 和相关服务/路由。

接口：

```text
GET  /api/commentary/detect-jianying-draft-dir
POST /api/commentary/export-jianying-draft
GET  /api/remix/detect-jianying-draft-dir
POST /api/remix/export-jianying-draft
```

工具会尝试检测常见的 Windows/macOS 剪映目录并测试写权限，找不到时使用 `output/jianying_drafts/`。导出内容通常包括：

```text
assets/              复制的视频、音频与 BGM
manifest.json        草稿包元数据
timeline.json        通用时间线
instructions.json    导入与使用说明
subtitles.srt        可选字幕
*.zip                打包文件
```

这是通用时间线草稿包，不是剪映私有工程格式，不能保证剪映专业版直接打开。

### 多格式导出

实现文件：`backend/engine/multi_format_exporter.py`。

支持导出多种时间线格式，便于在不同编辑器中使用。

## 9. 断点恢复与流式生成

实现文件：`backend/services/checkpoint_service.py`、`backend/api/advanced_routes.py`。

- 长任务支持断点恢复，避免因中断导致的工作丢失。
- 流式生成可实时返回进度，便于前端展示。
- 支持创建、查看、恢复和删除断点。

## 10. 外部依赖

- FFmpeg/ffprobe：渲染、探测、变速、定格和合并的必需系统依赖。
- PyTorch：YOLO、TransNetV2 可用实现和部分本地模型的运行基础。
- `librosa`：音乐卡点和音频特征分析。
- OpenCV：视频解码、镜头退化检测与画面评分。
- ImageMagick：图片处理（位于 `resource/imageMagick/`）。

## AI 封面生成

实现文件：`backend/api/cover_api.py`、`backend/config/ai_config.py`（`ImageGenConfig`）。

AI 封面生成支持多种文生图服务，API 配置独立于文本模型和视觉模型。

### 支持的厂商

| 厂商 | 配置前缀 | 默认模型 |
|---|---|---|
| custom_openai（推荐） | custom_openai_ | 用户自定义 |
| openai | openai_ | dall-e-3 |
| qwen | qwen_ | wanx-v1 |
| baidu | baidu_ | wanxiang-v1 |
| tencent | tencent_ | hunyuan-image |
| chatglm | chatglm_ | cogview-4-plus |
| doubao | doubao_ | seedream-4 |
| minimax | minimax_ | speech-2.0 |
| siliconflow | siliconflow_ | FLUX.1-schnell |
| openrouter | openrouter_ | dall-e-3 |

### 核心接口

```text
POST /api/cover/generate          生成封面
GET  /api/cover/history           获取封面历史
GET  /api/cover/config            获取封面配置
POST /api/cover/delete            删除封面
GET  /api/cover/file/<path>       获取封面文件
GET  /api/cover/sizes             获取尺寸列表
```

### 兜底机制

云端模型不可用时（缺 API Key、请求超时、上游错误），自动切换本地模板生成（PIL 渐变 + 水印），并在响应中明确标注 `actually_used_provider: local_fallback` 和 `fallback_reason`，前端会显示橙色提示。

### 超时设置

- 连接超时：15 秒
- 读取超时：max(180, 90*n) 秒（n 为生成数量）
- 单张图片生成通常需要 60-120 秒

返回索引：[开发文档索引](文档索引.md)。下一篇：[服务、API 与发布准备](JJYB_AI智剪_完整开发文档_Part3.md)。
