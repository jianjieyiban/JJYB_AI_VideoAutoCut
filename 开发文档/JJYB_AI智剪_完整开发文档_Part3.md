# 服务、API 与发布准备

## 1. 业务服务

| 服务 | 文件 | 责任 |
|---|---|---|
| 原创解说 | `backend/services/commentary_service.py` | 画面分析、文稿、分镜、配音、同步、草稿包 |
| 原创解说增强 | `backend/services/commentary_service_enhanced.py` | 高级配置、时间轴优化、视频输出参数 |
| 混剪 | `backend/services/remix_service.py` | 分镜、高光、普通/音乐卡点混剪、草稿包 |
| AI 配音 | `backend/services/voiceover_service.py` | 常规 TTS、克隆语音、输出下载 |
| 本地复刻 | `backend/services/local_voice_clone_service.py` | IndexTTS2 环境检测与 worker 调用 |
| 任务 | `backend/services/task_service.py` | 任务状态和进度 |
| 硬件 | `backend/services/hardware_capability_service.py` | 本地硬件能力信息 |
| 断点恢复 | `backend/services/checkpoint_service.py` | 断点恢复与流式生成 |
| AI 封面生成 | `backend/api/cover_api.py` | 多模型封面生成、本地模板兜底、封面管理 |

项目和素材的持久化由 `backend/database/db_manager.py` 的 SQLite `DatabaseManager` 负责。当前仓库不是 SQLAlchemy/Redis/PostgreSQL 架构；这些内容不应作为现状描述。

## 2. API 响应约定

主要 API 返回 JSON：

```json
{
  "code": 0,
  "msg": "操作成功",
  "data": {}
}
```

`code` 非 0 表示请求失败；客户端应显示 `msg` 并停止后续依赖操作。文件路径、供应商原始异常和密钥不应直接暴露给终端用户。

## 3. 关键 API 清单

### 原创解说

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/commentary/create` | 创建解说任务 |
| POST | `/api/commentary/analyze` | 视觉分析视频 |
| POST | `/api/commentary/generate-script` | 生成解说文稿 |
| POST | `/api/commentary/generate-voiceover` | 生成完整配音 |
| POST | `/api/commentary/generate-voices` | 生成分段配音 |
| POST | `/api/commentary/sync` | 音画字幕同步 |
| POST | `/api/commentary/puppet-sync` | 拟人化音画字幕同步与可选渲染 |
| POST | `/api/commentary/process` | 处理视频 |
| GET | `/api/commentary/result/<task_id>` | 获取任务结果 |
| POST | `/api/commentary/optimize-script` | AI 优化文稿 |
| POST | `/api/commentary/smart-segment` | 智能分镜与镜头评分 |
| GET | `/api/commentary/detect-jianying-draft-dir` | 检测草稿输出目录 |
| POST | `/api/commentary/export-jianying-draft` | 导出通用草稿包 |
| POST | `/api/commentary/auto-clip` | 智能剪辑 |
| POST | `/api/commentary/add-voiceover` | 添加配音 |
| POST | `/api/commentary/generate-subtitles` | 生成字幕 |

### 智能混剪

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/remix/create` | 创建混剪任务 |
| POST | `/api/remix/analyze` | 分析视频 |
| POST | `/api/remix/highlights` | 提取高光片段 |
| POST | `/api/remix/create-plan` | 创建混剪计划 |
| POST | `/api/remix/process` | 处理混剪 |
| POST | `/api/remix/generate` | 生成混剪视频 |
| GET | `/api/remix/progress/<task_id>` | 获取进度 |
| POST | `/api/remix/smart-segment` | 批量智能分镜 |
| POST | `/api/remix/general-mode` | 普通高光/配音混剪 |
| POST | `/api/remix/music-beat` | 音乐卡点混剪 |
| GET | `/api/remix/detect-jianying-draft-dir` | 检测草稿目录 |
| POST | `/api/remix/export-jianying-draft` | 导出通用草稿包 |

### AI 配音与声音复刻

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/voiceover/voices` | 获取常规音色 |
| GET | `/api/voiceover/engines` | 获取 TTS 引擎列表 |
| POST | `/api/voiceover/create` | 创建配音任务 |
| POST | `/api/voiceover/generate` | 生成常规配音 |
| POST | `/api/voiceover/batch-generate` | 批量生成常规配音 |
| POST | `/api/voiceover/preview` | 预览音色 |
| POST | `/api/voiceover/merge` | 合并配音文件 |
| GET | `/api/voiceover/clone-engines` | 获取克隆引擎就绪状态 |
| POST | `/api/voiceover/clone-generate` | 生成克隆配音 |
| POST | `/api/voiceover/download-to-folder` | 将已有配音复制到指定目录 |
| POST | `/api/voiceover/generate-and-download` | 生成常规配音并保存到指定目录 |
| POST | `/api/voiceover/clone-generate-and-download` | 克隆配音并保存到指定目录 |
| DELETE | `/api/voiceover/delete` | 删除配音文件 |

### 本地声音复刻

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/local-voice-clone/health` | 检查 IndexTTS2 引擎状态 |
| POST | `/api/local-voice-clone/generate` | 生成克隆语音 |

### 高级功能

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/advanced/script-doctor/diagnose` | 文案质检诊断 |
| POST | `/api/advanced/script-doctor/optimize` | 生成优化方案 |
| GET | `/api/advanced/script-doctor/dimensions` | 获取评分维度 |
| POST | `/api/advanced/script-purify` | AI 提纯文案 |
| POST | `/api/advanced/coverage-audit` | 覆盖审计 |
| POST | `/api/advanced/ai-dedup` | AI 智能去重 |
| POST | `/api/advanced/smart-interlude` | 智能穿插原片 |
| POST | `/api/advanced/audio-align` | 音画强制对齐 |
| POST | `/api/advanced/curated-remake/extract-script` | 提取爆款文案 |
| POST | `/api/advanced/curated-remake/rewrite-script` | AI 改写文案 |
| POST | `/api/advanced/curated-remake/match` | 场景匹配 |
| POST | `/api/advanced/curated-remake/export-suspect` | 导出存疑清单 |
| POST | `/api/advanced/checkpoint/create` | 创建断点 |
| GET | `/api/advanced/checkpoint/list` | 查看断点列表 |
| POST | `/api/advanced/checkpoint/recover` | 恢复断点 |
| DELETE | `/api/advanced/checkpoint/delete` | 删除断点 |
| POST | `/api/advanced/stream-generate` | 流式生成 |

### AI 封面生成

| 方法 | 路径 | 功能 |
|---|---|---|
| POST | /api/cover/generate | 生成封面 |
| GET | /api/cover/history | 获取封面历史 |
| GET | /api/cover/config | 获取封面配置 |
| POST | /api/cover/delete | 删除封面 |
| GET | /api/cover/sizes | 获取尺寸列表 |

### 模型配置

| 方法 | 路径 | 功能 |
|---|---|---|
| GET | /api/config/image | 获取图片模型配置 |
| POST | /api/config/image | 保存图片模型配置 |
| POST | /api/config/test-image | 测试图片模型连接 |
| GET | /api/config/vision | 获取视觉模型配置 |
| POST | /api/config/test-vision | 测试视觉模型连接 |
| GET | /api/config/llm | 获取文本模型配置 |
| POST | /api/config/test-llm | 测试文本模型连接 |

### 项目与素材管理

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/projects` | 获取项目列表 |
| POST | `/api/projects` | 创建项目 |
| GET | `/api/projects/<id>` | 获取项目详情 |
| PUT | `/api/projects/<id>` | 更新项目 |
| DELETE | `/api/projects/<id>` | 删除项目 |
| POST | `/api/projects/batch-delete` | 批量删除项目 |
| GET | `/api/project/stats` | 项目统计 |
| GET | `/api/projects/<id>/tracks` | 获取项目轨道 |
| PUT | `/api/projects/<id>/tracks` | 更新项目轨道 |
| GET | `/api/materials` | 获取素材列表 |
| POST | `/api/materials` | 添加素材到项目 |
| POST | `/api/upload/material` | 上传素材 |
| GET | `/api/material/download/<id>` | 下载素材 |
| DELETE | `/api/material/delete/<id>` | 删除素材 |
| GET | `/api/activity/timeline` | 活动时间线 |
| DELETE | `/api/activity/<id>` | 删除活动 |

### 系统设置

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/settings` | 获取所有设置 |
| POST | `/api/settings` | 保存设置 |
| GET/POST | `/api/settings/api-config` | 获取/保存 API 配置 |
| POST | `/api/settings/test-api` | 测试 API 连接 |
| POST | `/api/settings/upstream-models` | 从上游获取模型列表 |
| POST | `/api/settings/azure-tts-preview` | Azure TTS 试听 |
| POST | `/api/settings/volcano-voice-clone-test` | 火山引擎测试 |
| POST | `/api/settings/volcano-voice-clone-preview` | 火山引擎试听 |
| POST | `/api/settings/reset` | 重置设置 |
| POST | `/api/settings/clear-cache` | 清空缓存 |

### 视频编辑

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/video/info` | 获取视频信息 |
| POST | `/api/video/cut` | 视频剪切 |
| POST | `/api/video/merge` | 视频合并 |
| POST | `/api/effects/apply` | 应用特效/转场 |
| POST | `/api/subtitle/generate` | 生成字幕 |
| POST | `/api/subtitle/enhance` | 增强字幕 |
| POST | `/api/ai/smart-clip` | 智能剪辑 |
| POST | `/api/ai/smart-clip/plan` | 智能剪辑方案 |
| POST | `/api/ai/smart-clip/analyze-scenes` | 分析场景 |
| POST | `/api/export/video` | 导出视频 |

### 其他接口

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET | `/api/system/metrics` | 系统指标 |
| GET | `/api/status-bar` | 状态栏数据 |
| POST | `/api/asr/batch-upload-transcribe` | 批量转录 |
| POST | `/api/upload/video` | 上传视频 |
| POST | `/api/upload/audio` | 上传音频 |
| POST | `/api/upload/image` | 上传图片 |

克隆接口的必填安全条件为 `consent: true`。调用端也应校验参考音频路径和目标输出目录。

## 4. 常见错误处理

| 情况 | 建议处理 |
|---|---|
| API Key/Base URL 无效 | 在 `/settings` 测试连接并修正配置 |
| 视频无法解码 | 检查视频完整性、编码格式和 OpenCV/FFmpeg 日志 |
| FFmpeg 不存在 | 安装 FFmpeg/ffprobe 并加入 PATH |
| TransNetV2 不可用 | 使用 OpenCV 分镜；接口/日志应真实标示所用方案 |
| 本地声音复刻未就绪 | 按状态提示配置 Python 3.10、模型权重和依赖 |
| 目标目录无写权限 | 选择用户有写权限的输出目录 |
| 草稿目录未识别 | 使用自动回退目录或手动指定目录 |
| IndexTTS2 引擎不可用 | 检查 Python 3.10 环境、模型权重和依赖 |
| 模型不支持视觉输入 | 配置专用视觉模型或更换支持视觉的模型 |

## 5. 本地验证

### 代码检查

```powershell
py -3 scripts/check_system.py
py -3 -m py_compile backend\api\commentary_api.py
py -3 -m py_compile backend\api\remix_api.py
py -3 -m py_compile backend\api\voiceover_api.py
py -3 -m py_compile backend\api\advanced_routes.py
py -3 -m py_compile backend\services\commentary_service.py
py -3 -m py_compile backend\engine\tts_engine.py
```

### 功能冒烟测试

1. 打开设置页，测试至少一个模型服务连接。
2. 对小视频执行一次智能分镜，确认返回镜头列表。
3. 用短文本生成常规配音，试听并测试下载到指定目录。
4. 使用两段以上视频测试普通混剪；提供 BGM 测试音乐卡点模式。
5. 仅对拥有授权的参考音频测试声音复刻。
6. 分别测试原创解说和混剪的草稿包导出，并检查 ZIP 中的 `timeline.json` 与 `instructions.json`。
7. 测试精选视频复刻的文案提取和 AI 改写功能。
8. 测试文案质检的六维评分诊断。

## 6. GitHub 开源发布准备

### 不提交的本地数据

根 `.gitignore` 应至少忽略：

- `config/ai_config.json` 等含密钥的本地配置；
- `database/*.db`；
- `logs/`、`uploads/`、`output/`、`temp/` 的运行时内容；
- `__pycache__/`、`*.py[cod]`、Jupyter `.ipynb_checkpoints/`；
- 大型本地模型权重、下载缓存和个人素材。

如果希望保留目录结构，使用 `.gitkeep`，不要上传真实数据。

### 许可证和第三方内容

发布前必须确认：

1. 根目录 `LICENSE` 的许可证由项目权利人确定。
2. `models/index-tts/` 保留其上游许可证、声明和依赖要求。
3. `resource/` 中 ImageMagick、TransNetV2 权重的再分发许可符合计划。
4. 内置字体、音乐、YOLO 权重、示例图片和视频均有公开再分发权。
5. 不把 API Key、个人信息、用户素材、日志或数据库提交到仓库。

### 建议发布步骤

```powershell
# 检查变更和未跟踪内容
git status

# 运行环境与编译检查
py -3 scripts/check_system.py
py -3 -m py_compile backend\api\commentary_api.py backend\api\remix_api.py backend\api\voiceover_api.py backend\api\advanced_routes.py

# 清理缓存和临时文件
Get-ChildItem -Path . -Recurse -Force -Directory | Where-Object { $_.Name -eq '__pycache__' -and $_.FullName -notlike '*models\index-tts*' } | Remove-Item -Recurse -Force
```

之后人工核对 `git status`，只暂存源码、文档、必要资源和经过许可确认的文件。不要使用无差别的 `git add .` 将本地配置、数据库或大模型误提交。

## 7. 后续维护

新增功能时应同步更新：

1. 根 `README.md` 的功能、限制与快速开始；
2. 本目录中对应引擎/API 章节；
3. `requirements.txt` 的主程序直接依赖；
4. `.gitignore` 的运行时数据与敏感信息规则。

## 模型配置隔离

项目支持三类独立的模型配置，互不干扰：

- **文本模型 (LLMConfig)**：用于文案生成、脚本优化、文案质检等文本任务。支持 14 种渠道。
- **视觉模型 (VisionConfig)**：用于视频画面分析、场景识别。支持 8 种渠道。
- **图像生成 (ImageGenConfig)**：用于 AI 封面生成。支持 10 种渠道。

三类模型的 API Key、Base URL 和模型名完全独立存储和读取，不会互相覆盖或回退。后端 `_looks_like_masked_value` 防止掩码值（如 `********`）覆盖真实 Key。

设置页面有三个独立的配置卡片，分别对应三类模型。图片模型的"从上游获取模型"只读取 ImageGenConfig，不会回退到文本或视觉模型配置。

返回：[开发文档索引](文档索引.md)。
